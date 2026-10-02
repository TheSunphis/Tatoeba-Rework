# Japanese Learner Pipeline

The Japanese pipeline of the [Tatoeba-Rework pipeline layer](../README.md) —
one directory per language, same strict layering everywhere.

Deterministic Japanese → learner-cards pipeline: a raw sentence goes in,
verified chunk cards and an interactive HTML explorer come out.

## Architecture (strict layering)

```
sentence
  │
  ▼
1. UniDic (via fugashi)        raw morphological truth: lemmas, POS, conjugation
  │
  ▼
2. rule-based chunk merger     learner-sized chunks: polite/past/negative/volitional
  │                            endings, 〜たい + negative, 〜てください,
  │                            〜なくてはならない / 〜なければならない,
  │                            について, 〜続ける, compound particles, …
  ▼
3. JMdict lookup               dictionary-form anchored glosses: dictForm-first
  │                            for inflected verbs, kanji-swap fallback for
  │                            UniDic lemma quirks, common-word preference
  │                            (news1/ichi1 + PRI codes), ent_seq dedupe
  ▼
4. (roadmap) LLM layer         runs LAST and only here: anchored on the verified
                               tokens above, writes contextualMeaning /
                               literalContribution. Never segments from scratch.
```

## Usage

```bash
# 1. cards JSON for one sentence
python3 pipeline/Japanese/learner_pipeline.py "今は、それについてコメントしたくない。" --out cards.json

# 2. self-contained interactive HTML explorer from the cards
python3 pipeline/Japanese/build_site.py cards.json explorer.html
```

Requirements: Python 3, `fugashi` + `unidic`
(`pip install fugashi unidic && python -m unidic download`), and the
English-only JMdict (`JMdict_e.gz` from <https://www.edrdg.org/pub/Nihongo/>)
at `/tmp/JMdict_e.gz`.

## Card schema (cards JSON)

Every chunk carries: `surface`, `reading`, `type`, `dictionaryForm`,
`conjugation`, `grammarPoint` (for pattern chunks like 〜について), `breakdown`
(the raw morphemes merged into the chunk), `gloss` (first-sense JMdict), and
`common` (JMdict news1/ichi1). `meta` + `stats` record the sentence, its
translations, morpheme/chunk counts, and the JMdict hit rate.

The explorer site (built by `build_site.py`) embeds the same JSON and offers
two views: **🎓 Learner** (merged chunks) and **🔧 Machine** (raw UniDic
morphemes), with clickable chips, a gloss/details panel, and per-chunk
breakdown tables.

## Examples

- `examples/everyday_sentence_explorer.html` — rank 5,000 (everyday
  conversational sentence): 12 morphemes → 8 chunks, JMdict 6/6
- `examples/sentence_explorer.html` — rank 232,778 (the 302-character corpus
  outlier, stress test): 197 morphemes → 151 chunks, JMdict 130/130

Both are single self-contained HTML files — open them anywhere; no server, no
network, no dependencies.

## Known limitations (deliberate)

- **First-sense glosses**: the pipeline picks JMdict's first sense; choosing
  the contextually right sense is explicitly the LLM layer's job (step 4).
- **Grammar patterns**: ~10 patterns today; idioms like 手にする are not yet
  merged.
- **JMdict location**: expects `/tmp/JMdict_e.gz`.

## Roadmap

1. step 4 — the anchored LLM contextual layer (the architecture above)
2. more grammar patterns and idiom merging
3. batch mode over the Japanese/ pack files
4. Anki deck export from cards JSON
