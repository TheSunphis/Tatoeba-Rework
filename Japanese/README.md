# Japanese — Tatoeba sentence packs

The Japanese language pack of [Tatoeba-Rework](../README.md).

Japanese–English sentence packs, **ordered by everyday commonness**, rebuilt from
the official [Tatoeba](https://tatoeba.org) bulk exports.

**232,778 unique Japanese sentences** with all **280,520 direct English
translation links**, furigana readings, and an everyday-frequency rank
(**rank 1 = most everyday**), packaged into 10 packs of 100 JSON files × 250
sentences.

## Why

Tatoeba's exports are unordered and contain outlier entries — famous speeches,
quotes, multi-sentence paragraphs. This rework scores every Japanese sentence
by how everyday its vocabulary is and sorts the whole corpus by that score, so
a learner can start at rank 1 with genuinely conversational sentences and work
down. The corpus' hardest outlier (a 302-character translated victory speech)
sits at rank 232,778 — the ranking quarantines it automatically.

## Layout

```
Tatoeba-Rework/
├── README.md         (repo index: language packs + pipeline)
├── pipeline/         (learner analysis layer — its own project, see ../pipeline/README.md)
└── Japanese/         (language pack — this directory)
    ├── README.md     (this file)
    ├── manifest.json (machine-readable index of every pack & file)
    ├── tatoeba_all_pairs_sorted.json.bz2  (master dataset the packs were split from)
    ├── Pack 01/  pack01_001.json … pack01_100.json   ranks 1–25,000       (most everyday)
    ├── Pack 02/ … Pack 09/                           ranks 25,001–225,000
    ├── Pack 10/  pack10_001.json … pack10_032.json   ranks 225,001–232,778 (partial)
    └── scripts/
        ├── tatoeba_bulk.py       (download + build pairs from Tatoeba exports)
        ├── sort_by_frequency.py  (everyday-commonness scoring & ranking)
        └── split_packs.py        (packaging into packs & manifest)
```

## File schema

Each pack file is self-describing:

```json
{
  "meta": { "pack": 1, "file": 1, "sentences": 250, "rank_range": [1, 250], "source": "...", "license": "..." },
  "sentences": [
    {
      "rank": 1,                          // 1 = most everyday/common
      "freq_score": 7.07,                 // higher = more everyday (see below)
      "ja_id": 11053934,                  // Tatoeba sentence id
      "ja": "いつしたい？",
      "ja_furigana": "いつしたい？",        // reading, format 漢字[漢|かん]; plain text if no kanji
      "translations": [                   // ALL direct English translations
        { "en_id": 6949897, "en": "When do you like to do that?" }
      ]
    }
  ]
}
```

All translations of one Japanese sentence live in the same file — a sentence
never spans two files.

## Totals

| | |
|---|---|
| Unique Japanese sentences | 232,778 |
| Translation pairs | 280,520 |
| Packs | 10 (last one partial) |
| Files | 932 (100 per pack; Pack 10 has 32) |
| Sentences per file | 250 (Pack 10's last file has 28) |

## Ranking

`freq_score` = mean zipf word frequency of content words (wordfreq `ja` data:
Twitter/subtitles/web; lemmas extracted with UniDic via fugashi) minus a
0.05-per-token length penalty. Higher = more everyday. All translations of the
same Japanese sentence share one rank.

## How it was built / how to rebuild

Built from the **official bulk exports** at <https://downloads.tatoeba.org/exports/>
(not the paged API):

```bash
# 1. download exports, build all ja→en pairs (one pair per translation link)
python3 scripts/tatoeba_bulk.py --all --out tatoeba_all_pairs.json

# 2. score & rank by everyday commonness
python3 scripts/sort_by_frequency.py --in tatoeba_all_pairs.json --out tatoeba_all_pairs_sorted.json

# 3. split into packs (100 files × 250 sentences per pack)
python3 scripts/split_packs.py --master tatoeba_all_pairs_sorted.json --out .
```

Options worth knowing:

- `tatoeba_bulk.py --single-sentence` — keep only entries that are a single
  sentence. **This build intentionally does NOT use it**: the 6,571
  multi-sentence entries (2.8%) are kept, since the ranking already pushes
  them toward the bottom (median rank ≈ 149,000) and many are legitimate
  quoted mini-dialogues (`「何したの？」「何も」`). Use the flag for a
  stricter rebuild.
- `--seed N` on `tatoeba_bulk.py` for reproducible sampling when not using
  `--all`.

## Intentionally kept

- **Every translation link**: a sentence with three direct English
  translations appears once in the packs with all three in `translations`
  (three pairs in the master file).
- **Redundancy**: normalized/punctuation variants and near-duplicate
  paraphrases are **not** deduplicated. They're legitimate corpus data.

## Learner pipeline

The analysis layer that turns these sentences into learner-facing chunk cards
and interactive explorers lives in its own top-level directory:
**[../pipeline/](../pipeline/)** — architecture, usage, and roadmap in
[its README](../pipeline/README.md).

Demos built from this corpus:

- [everyday_sentence_explorer.html](../pipeline/examples/everyday_sentence_explorer.html) — rank 5,000, a typical conversational sentence
- [sentence_explorer.html](../pipeline/examples/sentence_explorer.html) — rank 232,778, the corpus outlier (stress test)
## License & attribution

- **Sentences and translations**: © Tatoeba.org contributors, **CC BY 2.0 FR**
  (some CC0). This repo is a derivative re-packaging; original Tatoeba
  sentence ids (`ja_id`, `en_id`) are preserved in every record so the
  original contributions can be traced.
- **JMdict** (used by the examples pipeline): EDRDG/JMdict licence —
  <https://www.edrdg.org/pub/Nihongo/JMdict_e.gz>.
- **UniDic** and **wordfreq** are used for segmentation and frequency scoring
  in the build pipeline.

## Credits

- [Tatoeba.org](https://tatoeba.org) and its contributors — the entire dataset.
- Ranking build & learner pipeline: generated for
  [TheSunphis](https://github.com/TheSunphis), October 2026.
