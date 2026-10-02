# Tatoeba-Rework

Sentence-pack corpora rebuilt from the official [Tatoeba](https://tatoeba.org)
bulk exports, **ordered by everyday commonness** (rank 1 = most everyday
sentence in the corpus) — plus the learner analysis pipeline that turns those
sentences into interactive study material.

## Language packs

| Language pack | Sentences | Translation links | Files |
|---|---|---|---|
| **[Japanese/](Japanese/)** — Japanese → English | 232,778 | 280,520 | 10 packs / 932 files |

Each language pack is self-contained — see
**[Japanese/README.md](Japanese/README.md)** for the file schema, the
everyday-frequency ranking method, rebuild instructions, and the corpus build
scripts.

## Pipeline

**[pipeline/](pipeline/)** — the learner analysis layer (under active
development): one directory per language, same strict layering — morphology →
chunk merger → dictionary glosses → (roadmap) anchored LLM layer. See
**[pipeline/README.md](pipeline/README.md)**.

- **[pipeline/Japanese/](pipeline/Japanese/)** — UniDic → chunk merger →
  JMdict → interactive HTML explorers. Demos:
  [everyday sentence, rank 5,000](pipeline/Japanese/examples/everyday_sentence_explorer.html)
  · [corpus outlier, rank 232,778](pipeline/Japanese/examples/sentence_explorer.html)
