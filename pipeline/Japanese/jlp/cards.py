"""Driver layer — a sentence in, a card deck out.

process() is the public entry point (single sentences or, with a shared
JMdict index from jmdict_lookup(), whole batches). chunks_lookup_keys()
supports batch pre-passes. CARD_KEYS + validate_chunks() define and verify
the card schema.
"""
from .glosser import alt_dict_form, attach_glosses
from .merger import build_chunks

# every decorated chunk must carry all of these keys (values may be None)
CARD_KEYS = ('surface', 'reading', 'type', 'dictionaryForm', 'conjugation',
             'grammarPoint', 'breakdown', 'gloss', 'common')


def chunks_lookup_keys(chunks):
    """All JMdict lookup keys a set of chunks will need (for batch pre-pass)."""
    keys = []
    for c in chunks:
        keys += [c['surface'], c['dictionaryForm'], c['reading'], alt_dict_form(c)]
    return keys


def validate_chunks(chunks):
    """Return a list of schema problems ([] means every card is complete)."""
    problems = []
    for c in chunks:
        for k in CARD_KEYS:
            if k not in c:
                problems.append((c.get('surface'), 'missing key: ' + k))
    return problems


def process(sentence: str, idx=None) -> dict:
    toks, chunks = build_chunks(sentence)
    hits, lookupable = attach_glosses(chunks, idx=idx)
    return {
        'sentence': sentence,
        'stats': {
            'rawMorphemes': len(toks),
            'learnerChunks': len(chunks),
            'multiMorphemeChunks': sum(1 for c in chunks if c['breakdown']),
            'jmdictHits': f'{hits}/{lookupable}',
        },
        'chunks': chunks,
    }
