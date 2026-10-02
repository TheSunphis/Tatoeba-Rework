#!/usr/bin/env python3
"""Run step 4 (the anchored LLM layer) with an Ollama model.

Single sentence (prints the enriched cards, optionally saves a deck for
build_site.py):

    python3 step4_run.py --sentence "今は、それについてコメントしたくない。" \\
        --model qwen2.5:7b --out deck.json

Batch over a pack file (enriched JSONL; --limit caps the sentence count):

    python3 step4_run.py --pack "Japanese/Pack 01/pack01_020.json" \\
        --limit 10 --model qwen2.5:7b --out enriched.jsonl

Requires a running Ollama server (`ollama serve`) with the model pulled.
Every model reply is validated by parse_response: a reply that tries to
resegment is rejected, never applied.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import learner_pipeline as lp


def enrich_sentence(llm, sentence, translations, idx):
    result = lp.process(sentence, idx=idx)
    prompt = lp.build_prompt(result, translations)
    reply = llm(prompt)
    lp.parse_response(result['chunks'], reply)   # ValueError if the model misbehaved
    return result, reply


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sentence', default=None)
    ap.add_argument('--pack', default=None, help='pack file (JSON) to read sentences from')
    ap.add_argument('--limit', type=int, default=10, help='max sentences from the pack')
    ap.add_argument('--model', default='qwen2.5:7b')
    ap.add_argument('--host', default='http://localhost:11434')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    if not args.sentence and not args.pack:
        ap.error('need --sentence or --pack')

    llm = lp.ollama_llm(model=args.model, host=args.host)
    t0 = time.time()

    if args.sentence:
        try:
            result, reply = enrich_sentence(llm, args.sentence, None, None)
        except ValueError as e:
            print(f'model reply rejected by validation: {e}', file=sys.stderr)
            sys.exit(2)
        for c in result['chunks']:
            if c['type'] == 'punctuation':
                continue
            print(f"  {c['surface']:<10} in this sentence : {c['contextualMeaning']}")
            print(f"  {'':<10} builds           : {c['literalContribution']}")
        if args.out:
            deck = {
                'meta': {
                    'source': 'step-4 via Ollama',
                    'translation': None,
                    'pipeline': f'UniDic -> merger -> JMdict -> step-4 Ollama ({args.model})',
                    'generated': time.strftime('%Y-%m-%d'),
                    'note': f'step-4 contextual layer · Ollama {args.model}',
                },
                'sentence': result['sentence'],
                'reading': ''.join(c['reading'] for c in result['chunks']),
                'stats': result['stats'],
                'chunks': result['chunks'],
            }
            json.dump(deck, open(args.out, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=2)
            print(f'\nsaved -> {args.out}')
        print(f'model reply: {len(reply)} chars · {time.time()-t0:.0f}s')
        return

    # ---- pack mode: batch enrichment with a shared JMdict index ----
    data = json.load(open(args.pack, encoding='utf-8'))
    sentences = data['sentences'][:args.limit]
    keys = set()
    for s in sentences:
        _, chunks = lp.build_chunks(s['ja'])
        keys.update(k for k in lp.chunks_lookup_keys(chunks) if k)
    idx = lp.jmdict_lookup(sorted(keys))
    print(f'{len(sentences)} sentences · shared index: {len(idx)} forms', flush=True)

    out_path = args.out or 'enriched.jsonl'
    ok = rejected = 0
    with open(out_path, 'w', encoding='utf-8') as out:
        for n, s in enumerate(sentences, 1):
            translations = [t['en'] for t in s.get('translations', [])]
            try:
                result, _ = enrich_sentence(llm, s['ja'], translations, idx)
                out.write(json.dumps(
                    {'ja_id': s['ja_id'], 'rank': s['rank'], 'sentence': s['ja'],
                     'translations': translations, 'chunks': result['chunks']},
                    ensure_ascii=False) + '\n')
                ok += 1
            except ValueError as e:
                rejected += 1
                print(f'  REJECTED rank {s["rank"]}: {e}', file=sys.stderr)
            except Exception as e:
                rejected += 1
                print(f'  ERROR rank {s["rank"]}: {e}', file=sys.stderr)
            print(f'  {n}/{len(sentences)} enriched={ok} rejected={rejected} '
                  f'({time.time()-t0:.0f}s)', flush=True)
    print(f'\ndone: {ok} enriched, {rejected} rejected -> {out_path}')


if __name__ == '__main__':
    main()
