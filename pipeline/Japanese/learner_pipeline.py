#!/usr/bin/env python3
"""Learner pipeline for Japanese sentences.

    raw sentence
        -> UniDic morphemes (fugashi)            [machine layer, exact]
        -> rule-based chunk merger               [learner layer: 帰り+まし+た -> 帰りました]
        -> JMdict gloss lookup                   [dictionary layer]

Output: learner "cards" -- one per learner-sized chunk with reading,
dictionary form, English gloss, conjugation label, and the raw morpheme
breakdown (which the later LLM layer can use to write explanations).

Usage:
    python learner_pipeline.py "ただいま帰りました"            # print cards
    python learner_pipeline.py "sentence" --out cards.json
"""

import argparse
import gzip
import io
import json
import re
import xml.etree.ElementTree as ET

from fugashi import Tagger

# ------------------------------------------------------------------ config

DISPLAY_LEMMA = {'為る': 'する', '為す': 'する'}
NARU = {'なる', '成る'}
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

# JMdict POS prefixes preferred for each learner chunk type
TYPE_POS_PREF = {
    'particle': ('prt',), 'pre-noun adjectival': ('pn',), 'pronoun': ('pn',),
    'verb': ('v', 'suru'), 'i-adjective': ('adj-i',), 'na-adjective': ('adj-na',), 'adverb': ('adv',),
}

# ------------------------------------------------------------------ helpers

def kata_to_hira(s: str) -> str:
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c for c in s)


def clean_lemma(l: str, surface: str) -> str:
    if not l or l == '*':
        return surface
    l = l.split('-')[0]
    return DISPLAY_LEMMA.get(l, l)


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


# ------------------------------------------------------------------ chunker

def match_must_pattern(toks, i):
    """V + なく + て + は + なり(なる) + aux*   or   V + なけれ + ば + なり + aux*
    -> end index of the 〜なくてはならない grammar chunk, else None."""
    if toks[i]['p1'] not in ('動詞', '名詞'):
        return None
    j = i + 1
    if j >= len(toks) or toks[j]['p1'] != '助動詞' or toks[j]['lemma'] != 'ない':
        return None
    j += 1                                    # past なく / なけれ
    if toks[j - 1]['s'].startswith('なく') and j < len(toks) and toks[j]['s'] == 'て':
        j += 1
        if j < len(toks) and toks[j]['s'] == 'は':
            j += 1
    elif toks[j - 1]['s'].startswith('なけれ') and j < len(toks) and toks[j]['s'] == 'ば':
        j += 1
    else:
        return None
    if j < len(toks) and toks[j]['p1'] == '動詞' and toks[j]['lemma'] in NARU:
        j += 1
    else:
        return None
    while j < len(toks) and toks[j]['p1'] == '助動詞':
        j += 1
    return j


_TAGGER = None


def get_tagger():
    """Single shared fugashi tagger (loading UniDic per call is wasteful)."""
    global _TAGGER
    if _TAGGER is None:
        _TAGGER = Tagger()
    return _TAGGER


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

        # --- grammar pattern: 〜なくてはならない ---
        j = match_must_pattern(toks, i)
        if j:
            chunks.append({'morphemes': toks[i:j], 'type': 'grammar point',
                           'grammarPoint': '〜なくてはならない / 〜なければならない (must, have to)',
                           'aux': [], 'te': None, 'compound': False})
            i = j
            continue

        # --- compound particle: に + つい(つく) + て -> について ---
        if t['p1'] == '助詞' and t['s'] == 'に' and i + 2 < n and \
           toks[i+1]['p1'] == '動詞' and toks[i+1]['lemma'] in ('つく', '付く') and \
           toks[i+2]['s'] == 'て':
            chunks.append({'morphemes': toks[i:i+3], 'type': 'grammar point',
                           'grammarPoint': '〜について (about, regarding)',
                           'aux': [], 'te': None, 'compound': False, 'dictform': 'について'})
            i += 3
            continue

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

        # negative of ~たい: したく + ない -> したくない
        if aux and any(t['lemma'] == 'たい' for t in aux) and i < n and \
           toks[i]['s'] == 'ない' and toks[i]['p1'] in ('助動詞', '形容詞'):
            aux.append(toks[i])
            morph.append(toks[i])
            i += 1

        # explanatory の + copula after a noun: ひとつ + な + の + だ
        if i < n and '形式名詞' in toks[i]['pos'] and i + 1 < n and \
           toks[i + 1]['p1'] == '助動詞' and toks[i + 1]['lemma'] in ('だ', 'です'):
            morph += [toks[i], toks[i + 1]]
            i += 2

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


# ------------------------------------------------------------------ JMdict

def jmdict_lookup(keys):
    """Parse JMdict_e.gz once, return {form: [best entries...]} for needed keys."""
    wanted = set()
    for k in keys:
        if k:
            wanted.add(k)
            wanted.add(kata_to_hira(k))
    COMMON = {'ichi1', 'news1', 'spec1', 'gai1', 'nf01', 'nf02'}
    matches = {}
    with gzip.open('/tmp/JMdict_e.gz', 'rb') as f:
        raw = f.read()
    # strip JMdict's DTD entities (&v1;, &prt;, ...) but keep the builtin XML
    # ones (&amp; &lt; ...) -- expat resolves those itself
    raw = re.sub(rb'&(?!amp;|lt;|gt;|quot;|apos;)(\w+);', rb'\1', raw)
    root = None
    for event, elem in ET.iterparse(io.BytesIO(raw), events=('start', 'end')):
        if event == 'start':
            root = root or elem
            continue
        if elem.tag != 'entry':
            continue
        kebs = [e.text for e in elem.findall('./k_ele/keb') if e.text]
        rebs = [e.text for e in elem.findall('./r_ele/reb') if e.text]
        pris = {e.text for e in elem.findall('./k_ele/ke_pri')} | {e.text for e in elem.findall('./r_ele/re_pri')}
        glosses = [g.text for g in elem.findall('./sense/gloss') if g.text][:2]
        poss = [p.text for p in elem.findall('./sense/pos')][:2]
        ent = {'glosses': glosses, 'pos': poss, 'common': bool(pris & COMMON),
               'npris': len(pris), 'nsenses': len(elem.findall('./sense')),
               'ent_seq': int(elem.findtext('./ent_seq') or 0)}
        for form in kebs + rebs + [kata_to_hira(r) for r in rebs]:
            if form in wanted:
                matches.setdefault(form, []).append(ent)
        elem.clear()
        root.clear()
    # best first: common (or very sense-rich, e.g. the する entry itself has no
    # priority tags), most senses, most priority tags, lowest id; always
    # keep particle entries so は/て/に never resolve to 羽/手/荷 homophones
    for form, cands in matches.items():
        cands.sort(key=lambda e: (not (e['common'] or e['nsenses'] >= 8),
                                  -e['nsenses'], -e['npris'], e['ent_seq']))
        seen, keep = set(), []
        for e in cands:                     # dedupe (rebs + hira(rebs) match twice)
            if e['ent_seq'] not in seen:
                seen.add(e['ent_seq'])
                keep.append(e)
        keep = keep[:10]
        keep += [e for e in keep[10:] if any('prt' in (p or '') for p in e['pos'])]
        matches[form] = keep
    return matches


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


def chunks_lookup_keys(chunks):
    """All JMdict lookup keys a set of chunks will need (for batch pre-pass)."""
    keys = []
    for c in chunks:
        keys += [c['surface'], c['dictionaryForm'], c['reading'], alt_dict_form(c)]
    return keys


# ------------------------------------------------------------------ driver

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sentence')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    result = process(args.sentence)
    s = result['stats']
    print(f"{s['rawMorphemes']} morphemes -> {s['learnerChunks']} chunks "
          f"({s['multiMorphemeChunks']} merged, JMdict {s['jmdictHits']})")
    for c in result['chunks']:
        if c['type'] == 'punctuation':
            continue
        extra = f" [{c['conjugation']}]" if c['conjugation'] else ''
        gp = f" {c['grammarPoint']}" if c['grammarPoint'] else ''
        gloss = f" = {c['gloss']}" if c['gloss'] else ''
        print(f"  {c['surface']:<12} ({c['type']}, {c['dictionaryForm']}){extra}{gp}{gloss}")
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nsaved -> {args.out}")


if __name__ == '__main__':
    main()
