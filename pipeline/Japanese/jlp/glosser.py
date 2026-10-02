"""Layer 3b — gloss attachment.

Chooses the best JMdict entry per chunk: dictionary-form anchoring (dict form
first for inflected chunks), kanji-swap alternative for UniDic lemma quirks
(帰りました -> 返る -> 帰る), POS preference per chunk type, common-word
preference, ent_seq dedupe.
"""
from .lexicon import jmdict_lookup

# JMdict POS prefixes preferred for each learner chunk type
TYPE_POS_PREF = {
    'particle': ('prt',), 'pre-noun adjectival': ('pn',), 'pronoun': ('pn',),
    'verb': ('v', 'suru'), 'i-adjective': ('adj-i',), 'na-adjective': ('adj-na',), 'adverb': ('adv',),
}


def pick_entry(cands, ctype):
    """Choose the best JMdict candidate for a chunk (list is best-first)."""
    if not cands:
        return None
    pref = TYPE_POS_PREF.get(ctype)
    if pref:
        for e in cands:
            if any(any(p.startswith(x) for p in (e['pos'] or [])) for x in pref):
                return e
    return cands[0]


def alt_dict_form(c):
    """UniDic sometimes picks a homophonous lemma kanji (帰りました -> 返る);
    offer surface-kanji + lemma tail (帰る) as an alternative dictionary form."""
    if c['type'] in ('verb', 'grammar point') and len(c['dictionaryForm']) >= 2 and \
            c['surface'] and c['surface'][0] != c['dictionaryForm'][0] and \
            '\u4e00' <= c['surface'][0] <= '\u9fff':          # only swap in a real kanji
        return c['surface'][0] + c['dictionaryForm'][1:]
    return None


def attach_glosses(chunks, idx=None):
    for c in chunks:
        c['_alt'] = alt_dict_form(c)
    keys = [c[k] for c in chunks for k in ('surface', 'dictionaryForm', 'reading', '_alt')]
    if idx is None:
        idx = jmdict_lookup(keys)
    # a shared idx is used as-is: keys absent from it are simply unmatched,
    # exactly like a fresh per-sentence lookup (never re-parse per sentence)
    hits = lookupable = 0
    for c in chunks:
        c['gloss'] = None
        c['common'] = None
        if c['type'] == 'punctuation':
            continue
        lookupable += 1
        if c['_alt'] and c['_alt'] in idx:            # 返る -> 帰る
            c['dictionaryForm'] = c['_alt']
        # inflected chunks: dictionary form first (しました -> する, not a surface homophone)
        if c['type'] in ('verb', 'i-adjective', 'na-adjective', 'grammar point') or c['conjugation']:
            order = ('dictionaryForm', 'surface', 'reading')
        else:
            order = ('surface', 'dictionaryForm', 'reading')
        entry = None
        for k in order:
            if c[k] in idx:
                entry = pick_entry(idx[c[k]], c['type'])
                break
        if entry is None and c['dictionaryForm'].endswith('する'):    # 悲観する -> 悲観
            if c['dictionaryForm'][:-2] in idx:
                entry = pick_entry(idx[c['dictionaryForm'][:-2]], c['type'])
        if entry:
            c['gloss'] = '; '.join(g for g in entry['glosses'] if g)
            c['common'] = entry['common']
            hits += 1
    for c in chunks:
        c.pop('_alt', None)
    return hits, lookupable
