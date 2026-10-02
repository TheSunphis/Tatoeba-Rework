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

**Module map** — the pipeline is the `jlp` package (one module per layer),
with `learner_pipeline.py` as a thin, backwards-compatible CLI shim
(`import learner_pipeline` still works; `batch_run.py` and `build_site.py`
are unchanged):

| module | layer | owns |
|---|---|---|
| `jlp/tagger.py` | 1 | shared fugashi tagger, raw token extraction, kata-hira conversion |
| `jlp/grammar.py` | 2 | **grammar pattern rule registry** — where new rules go |
| `jlp/merger.py` | 2 | chunk merger loop + card decoration |
| `jlp/lexicon.py` | 3a | JMdict index (path overridable via `JMDICT_E` env var) |
| `jlp/glosser.py` | 3b | entry choice: dict-form anchoring, kanji swap, POS preference |
| `jlp/cards.py` | driver | `process()`, batch key pre-pass, card schema + `validate_chunks()` |

### Adding a grammar rule

Rules are registered, not inlined — one small function in `jlp/grammar.py`
and the merger picks it up automatically:

```python
@pre                                    # tried before head-token handling
def toki_ni(toks, i, n):
    # 〜時に (when ...): 時 + に
    if toks[i]['lemma'] == '時' and i + 1 < n and toks[i+1]['s'] == 'に':
        return i + 2, {'type': 'grammar point',
                       'grammarPoint': '〜時に (when ...)',
                       'aux': [], 'te': None, 'compound': False}
    return None
```

`@post` rules instead extend the chunk being built after auxiliary
absorption (`absorb(morph, aux, toks, i, n) -> new_i | None`) — see the
`jlp/grammar.py` docstring for the full contract. After adding a rule,
guard it:

```bash
python3 tests.py        # from pipeline/Japanese/ — regression suite (~15 s)
```

## Step 4 — the anchored LLM contextual layer

`jlp/step4.py` implements the final layer. The LLM runs LAST, sees the
verified card deck, and may only add two fields per content chunk:

- `contextualMeaning` — what the chunk means in THIS sentence (fixes
  first-sense gloss ambiguity)
- `literalContribution` — how the chunk builds the English translation

Everything else is frozen, and **enforced by code**: the model must echo
each chunk surface exactly, in deck order. Any attempt to merge, split,
reorder, rewrite, add or drop chunks makes `parse_response` reject the
whole response — no partial application ever touches the deck.

Bring your own model — `llm` is any callable `(prompt: str) -> str`
(OpenAI/Anthropic SDK, a local server, even a human). No network code in
this package:

```python
from jlp import process, build_prompt, parse_response, enrich

result = process("今は、それについてコメントしたくない。", idx=idx)
prompt = build_prompt(result, translations=["I'd prefer not to comment on that now."])
reply = my_llm(prompt)                      # your callable
parse_response(result['chunks'], reply)     # validated, then applied
# or in one call: result = enrich(sentence, translations, idx=idx, llm=my_llm)
```

`build_site.py` renders both fields in the chunk details panel when
present. A complete example prompt: `examples/step4_prompt_everyday.txt`.

## Usage

```bash
# 1. cards JSON for one sentence
python3 pipeline/Japanese/learner_pipeline.py "今は、それについてコメントしたくない。" --out cards.json

# 2. self-contained interactive HTML explorer from the cards
python3 pipeline/Japanese/build_site.py cards.json explorer.html

# 3. regression suite (from pipeline/Japanese/)
python3 tests.py
```

Requirements: Python 3, `fugashi` + `unidic`
(`pip install fugashi unidic && python -m unidic download`), and the
English-only JMdict (`JMdict_e.gz` from <https://www.edrdg.org/pub/Nihongo/>)
at `/tmp/JMdict_e.gz`.

## Batch mode (full corpus)

`batch_run.py` processes the whole corpus with one shared tagger and ONE
shared JMdict index (two-pass: collect every lookup key → build the index
once → gloss everything):

```bash
# from the repo root
python3 pipeline/Japanese/batch_run.py --sample 5000 --torture   # stratified sample + edge cases
python3 pipeline/Japanese/batch_run.py --all --out cards.jsonl   # every sentence, cards JSONL
```

Measured on the full 232,778-sentence corpus (Oct 2026, 1 GB RAM sandbox):

| | |
|---|---|
| wall clock | **2.5 min** (load 5 s · pass 1 64 s · index 16 s · pass 2 72 s) |
| errors | **0 exceptions, 0 schema violations** (incl. a 21-case edge torture set) |
| morphemes → chunks | 2,668,044 → 2,298,261 (avg 1.16) |
| JMdict gloss coverage | 98.9% (misses are names/digits; gloss stays `null`) |
| peak RSS | 530 MB |
| cards JSONL | ~564 MB (2.4 KB/sentence) |

Zero-error policy: any failing sentence is caught per sentence (never fatal)
and reported with a full traceback; the runner also verifies the card schema
of every chunk. The 1.1% gloss misses are honest `null`s — proper nouns
(メアリー, トム…), digits, and clipped forms — not pipeline failures.

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

1. more grammar patterns and idiom merging (idioms like 手にする)
2. batch step-4 enrichment (rate/cost control over many sentences)
3. output format for full-corpus batch runs (compressed / per-pack enrichment)
4. Anki deck export from cards JSON
