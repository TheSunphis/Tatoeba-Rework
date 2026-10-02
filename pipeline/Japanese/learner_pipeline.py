#!/usr/bin/env python3
"""Learner pipeline for Japanese sentences — CLI entry point.

All logic lives in the jlp package (one module per layer; grammar rules are
a registry in jlp/grammar.py). This file keeps the historical single-file
interface working:

    import learner_pipeline as lp      # lp.process, lp.build_chunks, ...
    python3 learner_pipeline.py "ただいま帰りました"

Usage:
    python3 learner_pipeline.py "ただいま帰りました"            # print cards
    python3 learner_pipeline.py "sentence" --out cards.json
"""
import argparse
import json

from jlp import (CARD_KEYS, POST_RULES, PRE_RULES, alt_dict_form, attach_glosses,
                 build_chunks, build_prompt, chunks_lookup_keys, clean_lemma,
                 enrich, get_tagger, jmdict_lookup, kata_to_hira,
                 ollama_chat_payload, ollama_llm, parse_response,
                 pick_entry, post, pre, process, tokens_of, validate_chunks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sentence')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    result = process(args.sentence)
    s = result['stats']
    print(f"{s['rawMorphemes']} morphemes -> {s['learnerChunks']} chunks "
          f"({s['multiMorphemeChunks']} merged, JMdict {s['jmdictHits']})")
    for c in result['chunks']:
        if c['type'] == 'punctuation':
            continue
        extra = f" [{c['conjugation']}]" if c['conjugation'] else ''
        gp = f" {c['grammarPoint']}" if c['grammarPoint'] else ''
        gloss = f" = {c['gloss']}" if c['gloss'] else ''
        print(f"  {c['surface']:<12} ({c['type']}, {c['dictionaryForm']}){extra}{gp}{gloss}")
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nsaved -> {args.out}")


if __name__ == '__main__':
    main()
