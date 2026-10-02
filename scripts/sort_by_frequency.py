#!/usr/bin/env python3
"""Reorder a Tatoeba pairs JSON file by how everyday/common each Japanese
sentence is.

Scoring (per unique Japanese sentence):
  - tokenize with UniDic (fugashi) and take each content word's lemma
    (nouns/verbs/adjectives/adjectives-nominal/adverbs/interjections;
    numbers excluded)
  - commonness of each word = zipf frequency from the wordfreq 'ja' data
    (built from Twitter, subtitles and the web), max over lemma/surface
  - freq_score = mean content-word zipf  -  0.05 * token_count
    (a mild length penalty: shorter sentences rank higher on ties)
  - higher freq_score = more everyday; rank 1 = most everyday. All English
    translations of the same Japanese sentence share its rank and score.

Usage:
    python sort_by_frequency.py                       # tatoeba_all_pairs.json -> _sorted
    python sort_by_frequency.py --in x.json --out y.json
"""

import argparse
import json
import math
import os
import time

from fugashi import Tagger
from wordfreq import get_frequency_dict

CONTENT_POS = ('名詞', '動詞', '形容詞', '形状詞', '副詞', '感動詞')
LEN_PENALTY = 0.05      # zipf points subtracted per token
NEUTRAL = 3.5           # fallback for sentences with no content words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='infile', default='tatoeba_all_pairs.json')
    ap.add_argument('--out', dest='outfile', default='tatoeba_all_pairs_sorted.json')
    ap.add_argument('--keep-unsorted', action='store_true',
                    help="don't delete the input file afterwards")
    args = ap.parse_args()

    t0 = time.time()
    data = json.load(open(args.infile, encoding='utf-8'))
    pairs = data['pairs']
    print(f"loaded {len(pairs)} pairs", flush=True)

    tagger = Tagger()
    freqs = get_frequency_dict('ja')

    def zipf(w: str) -> float:
        f = freqs.get(w, 0)
        return math.log10(f * 1e9) if f > 0 else 0.0

    # ---- score each unique Japanese sentence once ------------------------
    scores = {}                     # ja_id -> (freq_score, n_tokens)
    for k, p in enumerate(pairs):
        jid = p['ja_id']
        if jid in scores:
            continue
        content, ntok = [], 0
        for node in tagger(p['ja']):
            pos = node.pos
            if pos.startswith('記号') or pos.startswith('補助記号'):
                continue
            ntok += 1
            if pos.split(',')[0] in CONTENT_POS and '数詞' not in pos:
                w = node.feature.lemma
                if not w or w == '*':
                    w = node.surface
                if w.isdigit():
                    content.append(4.5)
                else:
                    z = max(zipf(w), zipf(node.surface))
                    content.append(z if z > 0 else 1.0)   # unknown word -> 1.0
        raw = sum(content) / len(content) if content else NEUTRAL
        scores[jid] = (raw - LEN_PENALTY * ntok, ntok)
        if k % 50000 == 0:
            print(f"  scored {k}/{len(pairs)} ...", flush=True)

    # ---- order unique sentences: score desc, then shorter, then id -------
    order = sorted(scores, key=lambda j: (-scores[j][0], scores[j][1], j))
    rank = {jid: i + 1 for i, jid in enumerate(order)}

    # ---- apply to pairs (translations of one sentence stay adjacent) -----
    pairs.sort(key=lambda p: (rank[p['ja_id']], p['en_id']))
    for p in pairs:
        p['rank'] = rank[p['ja_id']]
        p['freq_score'] = round(scores[p['ja_id']][0], 3)

    data['meta']['count'] = len(pairs)
    data['meta']['unique_ja_sentences'] = len(scores)
    data['meta']['sorting'] = {
        "order": "rank 1 = most everyday/common; all translations of the same Japanese sentence share a rank",
        "freq_score": ("mean zipf word frequency of content words (wordfreq 'ja' data: "
                       "Twitter/subtitles/web; UniDic lemmas via fugashi) "
                       f"minus {LEN_PENALTY} per token length penalty; higher = more everyday"),
    }

    with open(args.outfile, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    print(f"wrote {len(pairs)} pairs to {args.outfile} "
          f"({os.path.getsize(args.outfile)/1e6:.1f} MB, {time.time()-t0:.0f}s)")

    print("\nmost everyday (rank 1-10):")
    for p in [x for x in pairs if x['rank'] <= 10][:10]:
        print(f"  #{p['rank']:>6} {p['freq_score']:5.2f}  {p['ja']}  ->  {p['en'][:50]}")
    print("\nleast everyday (bottom 3):")
    for p in pairs[-3:]:
        print(f"  #{p['rank']:>6} {p['freq_score']:5.2f}  {p['ja'][:50]}")

    if not args.keep_unsorted:
        os.remove(args.infile)
        print(f"\nremoved unsorted {args.infile} "
              f"(regenerate anytime: python tatoeba_bulk.py --all)")


if __name__ == '__main__':
    main()
