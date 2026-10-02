"""Layer 1 — UniDic morphological truth (via fugashi).

Owns the shared tagger instance and raw token extraction. Everything
downstream (merger, glosser) consumes the token dicts produced here:

    {'s': surface, 'pos': full POS string, 'p1': first POS field,
     'lemma': cleaned lemma, 'cform': conjugation form, 'kana': reading}
"""
from fugashi import Tagger

# UniDic lemma display fixes (為る is a rare spelling of する)
DISPLAY_LEMMA = {'為る': 'する', '為す': 'する'}


def kata_to_hira(s: str) -> str:
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c for c in s)


def clean_lemma(l: str, surface: str) -> str:
    if not l or l == '*':
        return surface
    l = l.split('-')[0]
    return DISPLAY_LEMMA.get(l, l)


_TAGGER = None


def get_tagger():
    """Single shared fugashi tagger (loading UniDic per call is wasteful)."""
    global _TAGGER
    if _TAGGER is None:
        _TAGGER = Tagger()
    return _TAGGER


def tokens_of(tagger, sent):
    out = []
    for node in tagger(sent):
        pos = node.pos.split(',')
        out.append({
            's': node.surface,
            'pos': node.pos,
            'p1': pos[0] if pos else '',
            'lemma': clean_lemma(node.feature.lemma or '', node.surface),
            'cform': node.feature.cForm or '',
            'kana': getattr(node.feature, 'kana', None) or node.surface,
        })
    return out
