#!/usr/bin/env python3
"""Build a JSON file of Japanese<->English sentence pairs from Tatoeba's
bulk exports at https://downloads.tatoeba.org/exports/

Instead of paging through the API, this uses the weekly per-language TSV
dumps (much friendlier for large volumes):
  per_language/jpn/jpn_sentences.tsv.bz2       id, lang, text
  per_language/jpn/jpn-eng_links.tsv.bz2       jpn_id, eng_id
  per_language/jpn/jpn_transcriptions.tsv.bz2  id, lang, script, user, furigana
  per_language/eng/eng_sentences.tsv.bz2       id, lang, text

Usage:
    python tatoeba_bulk.py                          # 1000 pairs -> tatoeba_1000_pairs.json
    python tatoeba_bulk.py --n 500 --out my.json    # 500 pairs
    python tatoeba_bulk.py --all                    # EVERY ja<->en pair (~280k)
"""

import argparse
import bz2
import json
import random
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "https://downloads.tatoeba.org/exports/per_language"
CACHE = Path("/tmp/tatoeba_bulk")   # downloads live outside the workspace on purpose

FILES = {
    "jpn_sentences": f"{BASE}/jpn/jpn_sentences.tsv.bz2",
    "jpn_links":     f"{BASE}/jpn/jpn-eng_links.tsv.bz2",
    "jpn_furigana":  f"{BASE}/jpn/jpn_transcriptions.tsv.bz2",
    "eng_sentences": f"{BASE}/eng/eng_sentences.tsv.bz2",
}


def download(name: str) -> Path:
    """Download a file into the cache dir (skipped if already there)."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{name}.tsv.bz2"
    if not path.exists():
        print(f"downloading {FILES[name]} ...", file=sys.stderr)
        urllib.request.urlretrieve(FILES[name], path)
    return path


def read_tsv(path: Path):
    """Yield rows (lists of tab-separated fields) from a .tsv.bz2 file."""
    with bz2.open(path, mode="rt", encoding="utf-8") as f:
        for line in f:
            yield line.rstrip("\n").split("\t")


SENT_END_MARKS = '。！？'


def is_single_sentence(text: str) -> bool:
    """True if the entry is a single sentence (at most one terminal mark,
    and it must be the last character)."""
    core = text.rstrip()
    total = sum(core.count(m) for m in SENT_END_MARKS)
    return total == 0 or (total == 1 and core[-1] in SENT_END_MARKS)


def build_pairs(n: int | None = 10, seed: int | None = None,
                single_sentence: bool = False) -> list[dict]:
    """Return sentence pairs. n=None returns ALL ja->en link pairs
    (a Japanese sentence with 3 English translations yields 3 pairs);
    otherwise n distinct Japanese sentences are sampled, one pair each."""
    if seed is not None:
        random.seed(seed)

    # 1. Japanese sentences: id -> text
    ja_text = {row[0]: row[2] for row in read_tsv(download("jpn_sentences"))}
    if single_sentence:
        ja_text = {sid: txt for sid, txt in ja_text.items() if is_single_sentence(txt)}

    # 2. all jpn->eng links (first column is always the jpn id)
    all_links = []
    links_by_ja = defaultdict(list)
    for row in read_tsv(download("jpn_links")):
        ja_id, en_id = row[0], row[1]
        if ja_id in ja_text:
            all_links.append((ja_id, en_id))
            links_by_ja[ja_id].append(en_id)

    if n is None:
        # every link is a pair
        chosen = all_links
    else:
        # sample n distinct Japanese sentences (oversample a little in case
        # some linked English ids no longer exist in the export)
        sampled_ids = random.sample(list(links_by_ja), min(len(links_by_ja), int(n * 1.1) + 10))
        chosen = [(ja_id, links_by_ja[ja_id][0]) for ja_id in sampled_ids]

    # 3. stream the English export once, keeping only the texts we need
    wanted = {en_id for _, en_id in chosen}
    en_text = {}
    for row in read_tsv(download("eng_sentences")):
        if row[0] in wanted:
            en_text[row[0]] = row[2]
            if len(en_text) == len(wanted):
                break

    # 4. furigana transcriptions (bonus)
    wanted_ja = {ja_id for ja_id, _ in chosen}
    furigana = {}
    for row in read_tsv(download("jpn_furigana")):
        if row[0] in wanted_ja:
            furigana[row[0]] = row[4]   # e.g. "ギター[弾|ひ]けるようになりたい。"

    # 5. assemble final pairs
    pairs, skipped = [], 0
    for ja_id, en_id in chosen:
        if en_id not in en_text:
            skipped += 1                # linked English sentence no longer exists
            continue
        pairs.append({
            "ja_id": int(ja_id),
            "en_id": int(en_id),
            "ja": ja_text[ja_id],
            "en": en_text[en_id],
            "ja_furigana": furigana.get(ja_id),
        })
        if n is not None and len(pairs) == n:
            break
    if skipped:
        print(f"skipped {skipped} links with missing English text", file=sys.stderr)
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--all", action="store_true", help="take every ja-en pair (~280k)")
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--seed", type=int, default=None, help="random seed for reproducibility")
    ap.add_argument("--single-sentence", action="store_true",
                    help="keep only entries that are a single sentence (drops multi-sentence paragraphs)")
    args = ap.parse_args()

    n = None if args.all else args.n
    out_path = args.out or ("tatoeba_all_pairs.json" if args.all else "tatoeba_1000_pairs.json")

    pairs = build_pairs(n, args.seed, args.single_sentence)
    if n is not None and len(pairs) < n:
        print(f"warning: only got {len(pairs)} pairs", file=sys.stderr)

    out = {
        "meta": {
            "source": "Tatoeba.org bulk exports",
            "url": "https://downloads.tatoeba.org/exports/",
            "license": "Sentences are CC BY 2.0 FR (some are CC0); attribution required",
            "fields": {
                "ja": "Japanese sentence", "en": "English translation",
                "ja_furigana": "furigana-annotated reading, format 漢字[漢|かん] (null if none available)",
                "ja_id / en_id": "Tatoeba sentence ids",
            },
            "count": len(pairs),
        },
        "pairs": pairs,
    }
    # pretty-print small files, keep big ones compact (the full set is ~60+ MB)
    if len(pairs) > 20000:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    else:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    have_furigana = sum(1 for p in pairs if p["ja_furigana"])
    print(f"wrote {len(pairs)} pairs to {out_path} ({have_furigana} with furigana)")
    for p in pairs[:5]:
        print(f"  {p['ja']}\n    -> {p['en']}")


if __name__ == "__main__":
    main()
