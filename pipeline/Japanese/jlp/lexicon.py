"""Layer 3a — the JMdict index.

Parses the English-only JMdict (JMdict_e.gz) once and returns
{form: [best entries...]} for a given set of lookup keys.

Build ONE index for a whole batch and pass it to attach_glosses(idx=...) —
see batch_run.py. The dictionary location defaults to /tmp/JMdict_e.gz and
can be overridden with the JMDICT_E environment variable.
"""
import gzip
import io
import os
import re
import xml.etree.ElementTree as ET

from .tagger import kata_to_hira

JMDICT_E = os.environ.get('JMDICT_E', '/tmp/JMdict_e.gz')


def jmdict_lookup(keys):
    """Parse JMdict_e.gz once, return {form: [best entries...]} for needed keys."""
    wanted = set()
    for k in keys:
        if k:
            wanted.add(k)
            wanted.add(kata_to_hira(k))
    COMMON = {'ichi1', 'news1', 'spec1', 'gai1', 'nf01', 'nf02'}
    matches = {}
    with gzip.open(JMDICT_E, 'rb') as f:
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
