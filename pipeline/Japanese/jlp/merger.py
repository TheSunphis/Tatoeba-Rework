"""Layer 2b — the chunk merger: UniDic morphemes -> learner-sized chunks.

Walks the token stream once. Structural decisions (punctuation, prefixes,
head token, compound verbs, te-form compounds, auxiliary runs, suffixes)
live here; GRAMMAR PATTERNS come from the rule registry in grammar.py.

Also decorates raw chunks into the public card shape (surface, reading,
type, dictionaryForm, conjugation, grammarPoint, breakdown). Keep the
decoration key order stable — serialized output depends on it.
"""
from . import grammar
from .tagger import get_tagger, tokens_of, kata_to_hira

COMPOUND_VERBS = {'続ける'}                       # 持ち + 続ける -> 持ち続ける
TE_COMPOUND_VERBS = {'いる', '居る', 'ある', '有る', 'おく', '置く', 'しまう',
                     'みる', '見る', 'いく', '行く', 'くる', '来る'}

AUX_LABEL = {
    'ます': 'polite', 'た': 'past', 'ない': 'negative', '無い': 'negative', 'ぬ': 'negative', 'ず': 'negative',
    'れる': 'passive/potential', 'られる': 'passive/potential',
    'せる': 'causative', 'させる': 'causative', 'たい': 'want to',
    'だ': 'copula', 'です': 'polite copula', 'そう': 'seems', 'よう': 'volitional',
}

POS1_TYPE = {
    '名詞': 'noun', '代名詞': 'pronoun', '動詞': 'verb', '形容詞': 'i-adjective',
    '形状詞': 'na-adjective', '副詞': 'adverb', '連体詞': 'pre-noun adjectival',
    '助詞': 'particle', '助動詞': 'auxiliary', '接続詞': 'conjunction',
    '感動詞': 'interjection', '接頭辞': 'prefix', '接尾辞': 'suffix',
}

CFORM_LABEL = {
    '連用形-一般': 'masu-stem (連用形)', 'タ系連用テ形': 'te-form',
    'タ系連用タ形': 'ta-form (past)', '未然形-一般': 'imperfective (未然形)',
    '意志推量形': 'volitional', '仮定形-一般': 'conditional',
    '基本形': None, '終止形-一般': None, '連体形-一般': None,
}


def aux_chain_label(aux_tokens):
    tags = []
    for t in aux_tokens:
        if t['lemma'] == 'ます' and ('意志' in t['cform'] or t['s'].startswith('ましょ')):
            tags.append('polite volitional ("let\'s")')
            continue
        lab = AUX_LABEL.get(t['lemma'], '')
        if lab and lab not in tags:
            tags.append(lab)
    return ', '.join(tags) if tags else None


def build_chunks(sent: str):
    toks = tokens_of(get_tagger(), sent)
    chunks = []
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if t['p1'] in ('記号', '補助記号'):
            chunks.append({'morphemes': [t], 'type': 'punctuation',
                           'grammarPoint': None, 'aux': [], 'te': None, 'compound': False})
            i += 1
            continue

        # prefix attaches to the next chunk
        prefix = []
        while i < n and toks[i]['p1'] == '接頭辞':
            prefix.append(toks[i])
            i += 1
        if i >= n:
            chunks.append({'morphemes': prefix, 'type': 'prefix', 'grammarPoint': None,
                           'aux': [], 'te': None, 'compound': False})
            break
        t = toks[i]

        # --- registered grammar patterns (〜なくてはならない, について, ...) ---
        for rule in grammar.PRE_RULES:
            m = rule(toks, i, n)
            if m:
                end, tmpl = m
                chunk = {'morphemes': toks[i:end]}
                chunk.update(tmpl)
                chunks.append(chunk)
                i = end
                break
        else:
            # --- head token ---
            morph = prefix + [t]
            head = t
            i += 1

            # compound verb: 持ち + 続ける -> 持ち続ける
            compound = False
            if head['p1'] == '動詞' and head['cform'].startswith('連用形') and \
               i < n and toks[i]['p1'] == '動詞' and toks[i]['lemma'] in COMPOUND_VERBS:
                morph.append(toks[i])
                compound = True
                i += 1

            # te-form + auxiliary verb: 食べて + いる
            te = None
            if head['p1'] == '動詞' and head['cform'].startswith('タ系連用テ形') and \
               i < n and toks[i]['p1'] == '動詞' and toks[i]['lemma'] in TE_COMPOUND_VERBS:
                te = toks[i]['lemma']
                morph.append(toks[i])
                i += 1

            # absorb the following auxiliary-verb run (ます, た, ない, です, だ, ...)
            aux = []
            while i < n and toks[i]['p1'] == '助動詞':
                aux.append(toks[i])
                morph.append(toks[i])
                i += 1

            # --- registered post-absorption rules (〜たくない, 形式名詞+copula) ---
            for rule in grammar.POST_RULES:
                i2 = rule(morph, aux, toks, i, n)
                if i2 is not None:
                    i = i2

            chunks.append({'morphemes': morph, 'type': None, 'grammarPoint': None,
                           'aux': aux, 'te': te, 'compound': compound})

            # suffixes attach to the chunk just built (私 + たち -> 私たち)
            while i < n and toks[i]['p1'] == '接尾辞':
                chunks[-1]['morphemes'].append(toks[i])
                i += 1

    # ---- decorate ----
    out = []
    for c in chunks:
        morphs = c['morphemes']
        head = next((m for m in morphs if m['p1'] not in ('接頭辞',)), morphs[0])
        surface = ''.join(m['s'] for m in morphs)
        reading = ''.join(kata_to_hira(m['kana']) for m in morphs)
        ctype = c['type'] or POS1_TYPE.get(head['p1'], head['p1'])
        if c['grammarPoint']:
            ctype = 'grammar point'
        conj = None if c['grammarPoint'] else (
            aux_chain_label(c['aux']) if c['aux'] else CFORM_LABEL.get(head['cform'], head['cform'] or None))
        if c['te']:
            conj = (f"〜て{c['te']} + {aux_chain_label(c['aux'])}" if c['aux'] else f"〜て{c['te']} (te-form + {c['te']})")
        # uninflected noun-ish chunks: the surface IS the dictionary form
        if c.get('dictform'):
            dictform = c['dictform']
        elif ctype in ('noun', 'pronoun') and not c['aux'] and not c['grammarPoint']:
            dictform = surface
        else:
            dictform = head['lemma']
        if c['compound']:                      # 持ち + 続ける -> 持ち続ける (dict form)
            dictform, conj = surface, None
        out.append({
            'surface': surface,
            'reading': reading,
            'type': ctype,
            'dictionaryForm': dictform,
            'conjugation': conj,
            'grammarPoint': c['grammarPoint'],
            'breakdown': [
                {'surface': m['s'], 'lemma': m['lemma'], 'pos': m['pos'], 'form': m['cform'] or None}
                for m in morphs
            ] if len(morphs) > 1 else None,
        })
    return toks, out
