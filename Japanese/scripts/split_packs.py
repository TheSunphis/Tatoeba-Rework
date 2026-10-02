#!/usr/bin/env python3
"""Split the everyday-ranked Tatoeba pairs file into packs:

    <out>/
      Pack 01/ pack01_001.json ... pack01_100.json  <- ranks 1..25,000
      Pack 02/ ...
      ...
      Pack 10/ (partial: 32 files)
      manifest.json   (index of every pack & file)

Pack and file names are zero-padded so they sort in true numeric order.

Each file holds 250 UNIQUE Japanese sentences (all English translations of a
sentence stay together in that file). Ordering: rank 1 = most everyday.

Usage:
    python split_packs.py                       # defaults below
    python split_packs.py --master X.json --out . --per-file 250 --per-pack 100
"""

import argparse
import datetime
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--master', default='tatoeba_all_pairs_sorted.json')
    ap.add_argument('--out', default='Tatoeba')
    ap.add_argument('--per-file', type=int, default=250)
    ap.add_argument('--per-pack', type=int, default=100)
    args = ap.parse_args()

    data = json.load(open(args.master, encoding='utf-8'))
    pairs = data['pairs']

    # ---- group consecutive pairs (same Japanese sentence) ----------------
    sentences = []
    for p in pairs:
        if sentences and sentences[-1]['ja_id'] == p['ja_id']:
            sentences[-1]['translations'].append({'en_id': p['en_id'], 'en': p['en']})
        else:
            sentences.append({
                'rank': p['rank'],
                'freq_score': p['freq_score'],
                'ja_id': p['ja_id'],
                'ja': p['ja'],
                'ja_furigana': p.get('ja_furigana'),
                'translations': [{'en_id': p['en_id'], 'en': p['en']}],
            })
    assert len(sentences) == data['meta']['unique_ja_sentences'], \
        "sentence grouping mismatch -- master file not sorted by sentence?"
    print(f"{len(pairs)} pairs -> {len(sentences)} unique Japanese sentences")

    # ---- write pack files -------------------------------------------------
    src_repo = os.path.join(args.out, 'Source repository')
    os.makedirs(src_repo, exist_ok=True)

    chunks = [sentences[i:i + args.per_file]
              for i in range(0, len(sentences), args.per_file)]

    packs_meta, file_index = [], []
    for idx, chunk in enumerate(chunks):
        pack_no, file_no = idx // args.per_pack + 1, idx % args.per_pack + 1
        pack_dir = os.path.join(args.out, f'Pack {pack_no:02d}')
        os.makedirs(pack_dir, exist_ok=True)
        fname = f'pack{pack_no:02d}_{file_no:03d}.json'
        rank_range = [chunk[0]['rank'], chunk[-1]['rank']]

        out = {
            'meta': {
                'source': 'Tatoeba.org (https://downloads.tatoeba.org/exports/), export of 2026-09-26',
                'license': 'Sentences CC BY 2.0 FR (some CC0); attribution: Tatoeba.org contributors',
                'pack': pack_no,
                'file': file_no,
                'file_name': fname,
                'sentences': len(chunk),
                'rank_range': rank_range,
                'ordering': 'rank 1 = most everyday/common Japanese; see Source repository/README.md',
            },
            'sentences': chunk,
        }
        with open(os.path.join(pack_dir, fname), 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

        file_index.append({
            'file': f'Pack {pack_no}/{fname}',
            'sentences': len(chunk),
            'rank_range': rank_range,
            'freq_score_range': [chunk[-1]['freq_score'], chunk[0]['freq_score']],
        })
        if file_no == 1 or file_no == len(chunks) % args.per_pack and idx == len(chunks) - 1:
            pass  # (pack summaries computed below)

    # ---- pack summaries ---------------------------------------------------
    for pack_no in range(1, (len(chunks) - 1) // args.per_pack + 2):
        pack_files = [c for c in file_index if c['file'].startswith(f'Pack {pack_no:02d}/')]
        if not pack_files:
            break
        packs_meta.append({
            'pack': pack_no,
            'directory': f'Pack {pack_no}',
            'files': len(pack_files),
            'sentences': sum(c['sentences'] for c in pack_files),
            'rank_range': [pack_files[0]['rank_range'][0], pack_files[-1]['rank_range'][1]],
        })

    # ---- manifest ----------------------------------------------------------
    manifest = {
        'dataset': 'Tatoeba Japanese-English sentence packs, ordered by everyday commonness',
        'generated': datetime.date.today().isoformat(),
        'source': {
            'name': 'Tatoeba.org',
            'url': 'https://downloads.tatoeba.org/exports/',
            'export_date': '2026-09-26',
            'license': 'Sentences CC BY 2.0 FR (some CC0); attribution required',
        },
        'totals': {
            'unique_japanese_sentences': len(sentences),
            'translation_pairs': len(pairs),
            'packs': len(packs_meta),
            'files': len(chunks),
            'sentences_per_file': args.per_file,
            'files_per_pack': args.per_pack,
        },
        'ranking': data['meta'].get('sorting'),
        'packs': packs_meta,
        'files': file_index,
    }
    with open(os.path.join(src_repo, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    for pm in packs_meta:
        print(f"  {pm['directory']:<9} {pm['files']:3d} files  {pm['sentences']:6d} sentences  "
              f"ranks {pm['rank_range'][0]:,}-{pm['rank_range'][1]:,}")
    print(f"wrote {len(chunks)} files + manifest.json")


if __name__ == '__main__':
    main()
