# Learner Pipeline

Deterministic sentence → learner-cards pipelines: a raw sentence goes in,
verified chunk cards and an interactive HTML explorer come out.

One directory per language, same strict layering everywhere:

| Language pipeline | Toolchain | Status |
|---|---|---|
| **[Japanese/](Japanese/)** | UniDic (fugashi) → chunk merger → JMdict | working — demos in [Japanese/examples/](Japanese/examples/) |

## Architecture (all languages)

```
sentence
  │
  ▼
1. morphological analysis    raw truth: lemmas, POS, conjugation
  │                          (language-specific segmenter/tagger)
  ▼
2. rule-based chunk merger   learner-sized chunks
  │                          (language-specific grammar patterns)
  ▼
3. dictionary lookup         dictionary-form anchored glosses
  │                          (language-specific lexicon, common-word preference)
  ▼
4. (roadmap) LLM layer       runs LAST and only here: anchored on the verified
                             tokens above, writes contextualMeaning /
                             literalContribution. Never segments from scratch.
```

Rules of the house — they apply to every language pipeline:

- the LLM never segments and never glosses from scratch
- the LLM never runs over the whole corpus — one sentence at a time, on demand
- the deterministic layers are the source of truth; the LLM only refines on
  top of verified tokens

## Adding a pipeline

Follow the pattern in [Japanese/](Japanese/): pick a segmenter and a lexicon
for the language, write its chunk-merger grammar patterns, and reuse
`build_site.py` from an existing pipeline — it renders any cards JSON in the
same schema (type colors are defined at the top of the file, per language).

## Roadmap

1. step 4 — the anchored LLM contextual layer (Japanese first)
2. more Japanese grammar patterns and idiom merging
3. batch mode over pack files
4. further language pipelines
