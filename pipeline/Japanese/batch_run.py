#!/usr/bin/env python3
"""Batch-run the learner pipeline over the Tatoeba-Rework Japanese master file.

Two-pass design with ONE shared JMdict index (and one shared fugashi tagger):

  pass 1: build_chunks on every sentence, collect every JMdict lookup key
  index:  jmdict_lookup(all keys) — ONE 10 MB XML parse for the whole corpus
  pass 2: build_chunks again + attach_glosses(chunks, idx=shared)

Memory stays O(vocabulary), not O(corpus): chunks are not kept between passes.

Zero-error policy: every sentence must come through pass 2 without an
exception AND with a schema-complete chunk list. Exceptions are caught per
sentence, never fatal; they are reported with full tracebacks at the end.

Usage:
  python3 batch_run.py --sample 5000                 # stratified sample
  python3 batch_run.py --sample 5000 --torture       # + edge-case torture set
  python3 batch_run.py --all --out cards.jsonl       # full corpus, cards JSONL
"""
import argparse
import bz2
import json
import resource
import time
import traceback
from collections import Counter

import learner_pipeline as lp

MASTER = 'Japanese/tatoeba_all_pairs_sorted.json.bz2'
REQ_KEYS = ('surface', 'reading', 'type', 'dictionaryForm', 'conjugation',
            'grammarPoint', 'breakdown', 'gloss', 'common')

TORTURE = [
    '', ' ', '　', '。', '！', '？？？', '……。', '😅😅', '123', 'ABC',
    'test sentence', 'a。b。c。', '「」', 'ーーー', '漢字', 'あ' * 500,
    '今日は2026年10月2日です。', 'iPhone15を買いました🎉',
    'ünïcödéと日本語の混合', '⭐︎⭐︎⭐︎', 'クリスマスイブにサンタが来た。',
]


def load_sentences(path):
    """Unique Japanese sentences in rank order (all translations share a rank)."""
    d = json.load(bz2.open(path))
    seen, out = set(), []
    for p in d['pairs']:
        if p['ja_id'] not in seen:
            seen.add(p['ja_id'])
            out.append((p['ja_id'], p['ja']))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--master', default=MASTER)
    ap.add_argument('--sample', type=int, default=0, help='stratified sample size')
    ap.add_argument('--all', action='store_true', help='process every sentence')
    ap.add_argument('--out', default=None, help='write cards JSONL here')
    ap.add_argument('--torture', action='store_true', help='prepend edge cases')
    args = ap.parse_args()

    t_load0 = time.time()
    all_s = sents = load_sentences(args.master)
    t_load = time.time() - t_load0
    total_corpus = len(all_s)
    if args.all:
        pass
    elif args.sample:
        step = max(1, len(all_s) // args.sample)
        sents = all_s[::step] + all_s[-5:]      # stratified + extreme tail
    if args.torture:
        sents = [(-i, t) for i, t in enumerate(TORTURE)] + sents

    print(f'corpus: {total_corpus:,} unique sentences · processing {len(sents):,}'
          + (' (stratified sample)' if not args.all and args.sample else ''))

    # ---------- pass 1: segment everything, collect lookup keys ----------
    t0 = time.time()
    keys, err1 = set(), []
    for n_done, (sid, ja) in enumerate(sents, 1):
        try:
            _, chunks = lp.build_chunks(ja)
            keys.update(k for k in lp.chunks_lookup_keys(chunks) if k)
        except Exception:
            err1.append((sid, ja, traceback.format_exc()))
        if n_done % 5000 == 0:
            print(f'  pass 1: {n_done:,}/{len(sents):,} ({n_done/(time.time()-t0):,.0f}/s)', flush=True)
    t1 = time.time()

    # ---------- one shared JMdict index for the whole run ----------
    idx = lp.jmdict_lookup(sorted(keys))
    t2 = time.time()

    # ---------- pass 2: attach glosses, verify schema ----------
    err2, schema_err, miss_counter = [], [], Counter()
    hits_t = look_t = 0
    morph_t = chunk_t = 0
    max_ms, max_sent = 0.0, ''
    out_f = open(args.out, 'w', encoding='utf-8') if args.out else None
    try:
        for n_done, (sid, ja) in enumerate(sents, 1):
            ts = time.time()
            try:
                toks, chunks = lp.build_chunks(ja)
                h, l = lp.attach_glosses(chunks, idx=idx)
                hits_t += h
                look_t += l
                morph_t += len(toks)
                chunk_t += len(chunks)
                for c in chunks:
                    missing = [k for k in REQ_KEYS if k not in c]
                    if missing:
                        schema_err.append((sid, c.get('surface'), missing))
                    if c['type'] != 'punctuation' and c['gloss'] is None:
                        miss_counter[c['surface']] += 1
                if out_f:
                    out_f.write(json.dumps(
                        {'ja_id': sid, 'sentence': ja, 'chunks': chunks},
                        ensure_ascii=False) + '\n')
            except Exception:
                err2.append((sid, ja, traceback.format_exc()))
            ms = (time.time() - ts) * 1000
            if ms > max_ms:
                max_ms, max_sent = ms, ja[:40]
            if n_done % 5000 == 0:
                print(f'  pass 2: {n_done:,}/{len(sents):,} ({n_done/(time.time()-t2):,.0f}/s)', flush=True)
    finally:
        if out_f:
            out_f.close()

    t3 = time.time()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024

    # ---------- report ----------
    n = len(sents)
    print(f'\n===== REPORT =====')
    print(f'pass 1 (segment + collect keys): {t1-t0:6.1f}s   ({n/(t1-t0):,.0f} sent/s)')
    print(f'JMdict index: {len(idx):,} forms from {len(keys):,} keys in {t2-t1:.1f}s')
    print(f'pass 2 (segment + gloss):        {t3-t2:6.1f}s   ({n/(t3-t2):,.0f} sent/s)')
    scale = total_corpus / n
    est = t_load + (t1-t0)*scale + (t2-t1) + (t3-t2)*scale
    print(f'master load: {t_load:.1f}s · total: {t3-t0:.1f}s for {n:,} sentences '
          f'({n/(t3-t0):,.0f}/s incl. one-time index build)')
    print(f'full-corpus estimate: ~{est/60:.0f} min '
          f'[load {t_load:.0f}s + pass1 {(t1-t0)*scale/60:.1f} min '
              f'+ index {t2-t1:.0f}s + pass2 {(t3-t2)*scale/60:.1f} min]')
    print(f'peak RSS: {rss:,} MB')
    print(f'morphemes {morph_t:,} -> chunks {chunk_t:,} · avg {morph_t/max(chunk_t,1):.2f} morph/chunk')
    if look_t:
        print(f'JMdict gloss coverage: {hits_t:,}/{look_t:,} ({100*hits_t/look_t:.1f}%)')
    print(f'\nerrors  pass1: {len(err1)} · pass2: {len(err2)} · schema: {len(schema_err)}')
    for sid, ja, tb in (err1 + err2)[:10]:
        print(f'\n--- ja_id {sid}: {ja[:60]!r}')
        print(tb)
    for row in schema_err[:10]:
        print('schema:', row)
    print(f'\ntop gloss misses: {miss_counter.most_common(15)}')
    if args.out:
        import os
        size = os.path.getsize(args.out)
        print(f'\nJSONL: {size:,} bytes for {n:,} sentences '
              f'({size/n:.0f} B/sent -> full corpus ~{size/n*total_corpus/1e6:.0f} MB)')


if __name__ == '__main__':
    main()
