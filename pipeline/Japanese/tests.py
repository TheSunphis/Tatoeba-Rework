#!/usr/bin/env python3
"""Regression suite for the Japanese learner pipeline.

Run from pipeline/Japanese/ (builds one shared JMdict index, ~15 s):

    python3 tests.py

Exit code 0 = all green. Add a case by writing a test_* function that uses
IDX (the shared index) and asserts known-good facts.
"""
import json
import sys

import learner_pipeline as lp
from batch_run import TORTURE

MONSTER = 'その問いかけに答えるチャンスを今、私たちは手にしました。今この時こそが、私たちの瞬間です。今この時にこそ、私たちは人々がまた仕事につけるようにしなくてはなりません。子供たちのために、チャンスの扉を開かなくてはなりません。繁栄を取り戻し、平和を推進しなくてはなりません。今この時にこそ、アメリカの夢を取り戻し、基本的な真理を再確認しなくてはなりません。大勢の中にあって、私たちはひとつなのだと。息をし続ける限り、私たちは希望をもち続けるのだと。そして疑り深く悲観し否定する声に対しては、そんなことできないという人たちに対しては、ひとつ国民の魂を端的に象徴するあの不朽の信条でもって、必ずやこう答えましょう。'

EVERYDAY = '今は、それについてコメントしたくない。'


def _build_shared_idx():
    sentences = ['ただいま帰りました', EVERYDAY, MONSTER] + TORTURE
    keys = set()
    for s in sentences:
        _, chunks = lp.build_chunks(s)
        keys.update(k for k in lp.chunks_lookup_keys(chunks) if k)
    return lp.jmdict_lookup(sorted(keys))


IDX = _build_shared_idx()


def test_sanity_sentence():
    r = lp.process('ただいま帰りました', idx=IDX)
    cards = [(c['surface'], c['dictionaryForm'], c['conjugation'], c['gloss'])
             for c in r['chunks'] if c['type'] != 'punctuation']
    assert cards == [('ただいま', 'ただいま', '*', "I'm home!; I'm back!"),
                     ('帰りました', '帰る', 'polite, past', 'to return; to come home')], cards


def test_everyday_sentence():
    r = lp.process(EVERYDAY, idx=IDX)
    cards = [(c['surface'], c['type'], c['dictionaryForm'], c['conjugation'], c['gloss'])
             for c in r['chunks'] if c['type'] != 'punctuation']
    assert len(cards) == 6, cards
    assert cards[0][:2] == ('今', 'noun') and cards[0][4] == 'now; the present time'
    assert cards[1][:2] == ('は', 'particle') and cards[1][4].startswith('indicates sentence topic')
    assert cards[2][:2] == ('それ', 'pronoun') and cards[2][4] == 'that; it'
    assert cards[3] == ('について', 'grammar point', 'について', None, 'about; on')
    assert cards[4] == ('コメント', 'noun', 'コメント', '*', 'comment')
    assert cards[5] == ('したくない', 'verb', 'する', 'want to, negative', 'to do; to carry out')
    assert r['stats']['jmdictHits'] == '6/6'


def test_monster_sentence():
    r = lp.process(MONSTER, idx=IDX)
    s = r['stats']
    assert len(MONSTER) == 302
    assert s['rawMorphemes'] == 197, s
    assert s['learnerChunks'] == 151, s
    assert s['jmdictHits'] == '130/130', s
    gp = [c for c in r['chunks'] if c['type'] == 'grammar point']
    assert len(gp) == 4 and all('ならない' in c['grammarPoint'] for c in gp)
    shimashita = next(c for c in r['chunks'] if c['surface'] == 'しました')
    assert shimashita['dictionaryForm'] == 'する' and shimashita['gloss'] == 'to do; to carry out'
    tsuzukeru = next(c for c in r['chunks'] if c['surface'] == 'し続ける')
    assert (tsuzukeru['dictionaryForm'], tsuzukeru['conjugation'],
            tsuzukeru['gloss']) == ('し続ける', None, 'to continue to do; to persist in doing')
    shunkan = next(c for c in r['chunks'] if c['surface'] == '瞬間です')
    assert (shunkan['dictionaryForm'], shunkan['conjugation'],
            shunkan['gloss']) == ('瞬間', 'polite copula', 'moment; instant')
    sono = next(c for c in r['chunks'] if c['surface'] == 'その')
    assert (sono['type'], sono['dictionaryForm'], sono['gloss']) == ('pre-noun adjectival', '其の', 'that; the')


def test_schema_complete_everywhere():
    for s in ['ただいま帰りました', EVERYDAY, MONSTER] + TORTURE:
        r = lp.process(s, idx=IDX)
        problems = lp.validate_chunks(r['chunks'])
        assert not problems, (s[:40], problems)


def test_cli_shim_reexports():
    for name in ('process', 'build_chunks', 'attach_glosses', 'chunks_lookup_keys',
                 'jmdict_lookup', 'get_tagger', 'validate_chunks', 'CARD_KEYS'):
        assert hasattr(lp, name), name


# ------- step 4: anchored LLM contextual layer -------

def _everyday_result():
    return lp.process(EVERYDAY, idx=IDX)


def test_step4_prompt_is_anchored():
    prompt = lp.build_prompt(_everyday_result(), ["I'd prefer not to comment on that now."])
    for needle in (EVERYDAY, 'したくない', 'want to, negative', '〜について',
                   'VERIFIED', 'EXACTLY', 'punctuation chunks are excluded'):
        assert needle in prompt, needle
    assert 'I\'d prefer not to comment on that now.' in prompt


def test_step4_parse_applies_and_preserves():
    r = _everyday_result()
    surfaces = [c['surface'] for c in r['chunks'] if c['type'] != 'punctuation']
    reply = json.dumps({'chunks': [
        {'surface': s, 'contextualMeaning': f'cm-{i}', 'literalContribution': f'lc-{i}'}
        for i, s in enumerate(surfaces)]})
    lp.parse_response(r['chunks'], reply)
    content = [c for c in r['chunks'] if c['type'] != 'punctuation']
    assert all(c['contextualMeaning'] == f'cm-{i}' for i, c in enumerate(content))
    assert all(c['literalContribution'] == f'lc-{i}' for i, c in enumerate(content))
    # punctuation chunks get uniform nulls; deterministic fields untouched
    assert all(c['contextualMeaning'] is None for c in r['chunks'] if c['type'] == 'punctuation')
    assert r['chunks'][3]['surface'] == 'それ' and r['chunks'][3]['gloss'] == 'that; it'
    assert lp.validate_chunks(r['chunks']) == []
    # markdown-fenced replies are accepted too
    r2 = _everyday_result()
    lp.parse_response(r2['chunks'], '```json\n' + reply + '\n```')
    assert r2['chunks'][0]['contextualMeaning'] == 'cm-0'


def test_step4_rejects_bad_responses_atomically():
    surfaces = [c['surface'] for c in _everyday_result()['chunks']
                if c['type'] != 'punctuation']
    bad = [
        'not json at all',
        json.dumps({'chunks': [{'surface': s, 'contextualMeaning': 'x',
                                'literalContribution': 'y'} for s in surfaces[:-1]]}),
        json.dumps({'chunks': [{'surface': 'WRONG' if i == 0 else s,
                                'contextualMeaning': 'x',
                                'literalContribution': 'y'}
                               for i, s in enumerate(surfaces)]}),
        json.dumps({'nope': []}),
    ]
    for b in bad:
        r = _everyday_result()
        try:
            lp.parse_response(r['chunks'], b)
            raise AssertionError('should have been rejected: ' + b[:50])
        except ValueError:
            pass
        assert all('contextualMeaning' not in c for c in r['chunks']), 'partial apply leaked'


def test_step4_enrich_requires_llm():
    try:
        lp.enrich(EVERYDAY)
        raise AssertionError('enrich should require an llm callable')
    except ValueError:
        pass


def test_step4_ollama_payload():
    p = lp.ollama_chat_payload('qwen2.5:7b', 'hello')
    assert p['model'] == 'qwen2.5:7b'
    assert p['messages'] == [{'role': 'user', 'content': 'hello'}]
    assert p['stream'] is False and p['format'] == 'json'
    assert p['options']['temperature'] == 0.2


def test_step4_ollama_callable_end_to_end():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Stub(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            reply = {'message': {'role': 'assistant', 'content': json.dumps({'chunks': [
                {'surface': '今', 'contextualMeaning': 'now',
                 'literalContribution': 'sets the time frame'}]})}}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(('127.0.0.1', 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        llm = lp.ollama_llm(model='stub', host=f'http://127.0.0.1:{srv.server_port}')
        r = lp.process('今。', idx=IDX)
        lp.parse_response(r['chunks'], llm(lp.build_prompt(r)))
        c = next(c for c in r['chunks'] if c['type'] != 'punctuation')
        assert c['contextualMeaning'] == 'now'
        assert c['literalContribution'] == 'sets the time frame'
    finally:
        srv.shutdown()


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith('test_') and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  PASS {name}')
        except AssertionError as e:
            failed += 1
            print(f'  FAIL {name}: {e}')
        except Exception:
            failed += 1
            import traceback
            print(f'  ERROR {name}:')
            traceback.print_exc()
    print(f'\n{len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
