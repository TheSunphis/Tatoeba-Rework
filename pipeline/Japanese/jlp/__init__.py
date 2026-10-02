"""jlp — the Japanese learner pipeline package.

One module per layer:

    tagger.py    UniDic morphemes (fugashi)       layer 1 — machine truth
    grammar.py   grammar pattern rule registry    layer 2 — where new rules go
    merger.py    chunk merger loop + decoration   layer 2
    lexicon.py   JMdict index                     layer 3a
    glosser.py   gloss attachment                 layer 3b
    cards.py     process() driver + card schema   public API
    step4.py     anchored LLM contextual layer     layer 4 — runs LAST, adds
                                                     contextualMeaning +
                                                     literalContribution only

Stable public API: process, build_chunks, attach_glosses,
chunks_lookup_keys, jmdict_lookup. The step-4 LLM layer will sit ON TOP of
these (anchored on verified tokens), never underneath them.
"""
from .tagger import get_tagger, tokens_of, kata_to_hira, clean_lemma
from .merger import build_chunks
from .grammar import pre, post, PRE_RULES, POST_RULES
from .lexicon import jmdict_lookup
from .glosser import attach_glosses, alt_dict_form, pick_entry, TYPE_POS_PREF
from .cards import process, chunks_lookup_keys, CARD_KEYS, validate_chunks
from .step4 import build_prompt, parse_response, enrich

__version__ = '2.1.0'
