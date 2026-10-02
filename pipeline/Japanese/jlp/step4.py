"""Step 4 — the anchored LLM contextual layer.

Runs LAST, on top of the verified deterministic layers (UniDic -> merger ->
JMdict). Its ONLY job is to add two fields per content chunk:

    contextualMeaning    what the chunk means in THIS sentence
                         (disambiguates the first-sense JMdict gloss)
    literalContribution  how the chunk builds the English translation

Rules of the house, enforced by code:
- The model receives the verified card deck and must echo each content
  surface EXACTLY, in order. Any resegmentation, reordering, rewriting or
  extra/missing chunks makes parse_response reject the WHOLE response —
  no partial application ever touches the deck.
- Segmentation, types, dictionary forms, readings and glosses are final;
  parse_response only ever sets the two new fields.
- One sentence at a time, on demand — never over the whole corpus.

Bring your own model: `llm` is any callable taking the prompt string and
returning the model's text (OpenAI SDK, Anthropic SDK, a human — all work).
For a local Ollama server use ollama_llm() below (standard library only).

Typical flow:

    from jlp import process, build_prompt, parse_response

    result = process("今は、それについてコメントしたくない。", idx=idx)
    prompt = build_prompt(result, translations=["I'd prefer not to comment on that now."])
    reply = my_llm(prompt)                    # your callable
    parse_response(result['chunks'], reply)   # validated, then applied

    # or in one call:
    # result = enrich(sentence, translations, idx=idx, llm=my_llm)
"""
import json

from .cards import process

INSTRUCTIONS = """You are the step-4 contextual layer of a Japanese learner pipeline.
Everything below was produced by deterministic tools (UniDic morphological
analysis + JMdict dictionary lookup) and is VERIFIED: chunk boundaries,
types, dictionary forms, readings and glosses are FINAL. Do not re-analyze,
correct, merge, split or reorder them.

Your only job: for each numbered chunk, write two short fields:
- "contextualMeaning": what this chunk means IN THIS SENTENCE. Pick the
  sense that fits this context; the JMdict gloss shown may be too generic
  or wrong for this sentence.
- "literalContribution": in one short line, how this chunk contributes to
  the English translation(s) given below.

Rules:
- Respond with JSON only. No markdown fences, no commentary.
- Echo each "surface" EXACTLY as given, in the same order, one entry per
  numbered chunk (punctuation chunks are excluded).
- One line per field, in English, at most ~120 characters.
- Use null for a field only if the chunk genuinely adds nothing.
- Never modify anything else about the chunks.

Response format:
{"chunks": [{"surface": "...", "contextualMeaning": "...", "literalContribution": "..."}, ...]}"""


# ------------------------------------------------------------------ prompt

def _describe(i, c):
    """One compact line (plus optional morpheme line) of verified chunk data."""
    parts = [f"[{i}] {c['surface']}"]
    if c['reading'] and c['reading'] != c['surface']:
        parts.append(f"「{c['reading']}」")
    parts.append(c['type'])
    if c['dictionaryForm'] and c['dictionaryForm'] != c['surface']:
        parts.append(f"dict {c['dictionaryForm']}")
    if c['conjugation'] and c['conjugation'] != '*':
        parts.append(f"[{c['conjugation']}]")
    if c['grammarPoint']:
        parts.append(f"GRAMMAR {c['grammarPoint']}")
    line = ' '.join(parts)
    if c['gloss']:
        line += f" — {c['gloss']}"
    if c['breakdown']:
        line += "\n    = " + ' + '.join(f"{m['surface']}({m['lemma']})" for m in c['breakdown'])
    return line


def build_prompt(result, translations=None):
    """Build the step-4 prompt for a process() result.

    `result` is the dict returned by jlp.process (or jlp.cards.process);
    `translations` are reference English translations (e.g. the Tatoeba
    links for the sentence) that ground literalContribution.
    """
    content = [c for c in result['chunks'] if c['type'] != 'punctuation']
    lines = [INSTRUCTIONS, '', f"SENTENCE: {result['sentence']}", '']
    if translations:
        lines.append('TRANSLATIONS (reference, for literalContribution):')
        lines.extend(f'- {t}' for t in translations)
        lines.append('')
    lines.append(f'VERIFIED CHUNKS ({len(content)}, punctuation excluded):')
    lines.extend(_describe(i, c) for i, c in enumerate(content))
    lines.append('')
    lines.append(f'Write the two fields for all {len(content)} chunks now.')
    return '\n'.join(lines)


# ------------------------------------------------------------------ parsing

def _extract_json(text):
    """Pull the JSON object/array out of a model reply (fence-proof)."""
    t = text.strip()
    a = min((x for x in (t.find('{'), t.find('[')) if x >= 0), default=-1)
    b = max(t.rfind('}'), t.rfind(']'))
    if a < 0 or b <= a:
        raise ValueError('no JSON object found in response')
    try:
        return json.loads(t[a:b + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f'response is not valid JSON: {e}') from e


def _clean(v):
    """None for missing/blank; stripped string otherwise."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    return v or None


def parse_response(chunks, text):
    """Validate a step-4 reply against the deck and apply it atomically.

    The reply must contain exactly one entry per content chunk (in deck
    order, punctuation excluded), each echoing the chunk surface exactly.
    On any violation nothing is applied and ValueError is raised.
    """
    data = _extract_json(text)
    items = data.get('chunks') if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError('response must be {"chunks": [...]} or a list of chunk entries')

    content = [c for c in chunks if c['type'] != 'punctuation']
    if len(items) != len(content):
        raise ValueError(f'chunk count mismatch: response has {len(items)}, '
                         f'deck has {len(content)} content chunks')
    for i, (it, c) in enumerate(zip(items, content)):
        if not isinstance(it, dict) or it.get('surface') != c['surface']:
            got = it.get('surface') if isinstance(it, dict) else type(it).__name__
            raise ValueError(f'chunk {i}: surface mismatch (response {got!r}, '
                             f'deck {c["surface"]!r}) — resegmentation is not allowed')

    # validated — now (and only now) apply
    i = 0
    for c in chunks:
        if c['type'] == 'punctuation':
            c['contextualMeaning'] = None
            c['literalContribution'] = None
        else:
            it = items[i]
            i += 1
            c['contextualMeaning'] = _clean(it.get('contextualMeaning'))
            c['literalContribution'] = _clean(it.get('literalContribution'))
    return chunks


# ------------------------------------------------------------------ driver

def enrich(sentence, translations=None, idx=None, llm=None):
    """process -> build_prompt -> llm -> parse_response, in one call.

    `llm` is required: a callable (prompt: str) -> str. For a dry run
    (no model yet), call build_prompt(process(...)) directly.
    """
    if llm is None:
        raise ValueError('llm callable required (for a dry run, use build_prompt)')
    result = process(sentence, idx=idx)
    parse_response(result['chunks'], llm(build_prompt(result, translations)))
    return result


# ------------------------------------------------------------------ providers

def ollama_chat_payload(model, prompt, temperature=0.2):
    """Request body for an Ollama /api/chat call (JSON mode on)."""
    return {
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': False,
        'format': 'json',
        'options': {'temperature': temperature},
    }


def ollama_llm(model='qwen2.5:7b', host='http://localhost:11434', timeout=300):
    """An llm callable for enrich() that talks to an Ollama server.

    Standard library only — no SDK. `format: json` makes Ollama constrain
    the reply to valid JSON, which pairs well with parse_response.
    Requires a running server (`ollama serve`) with the model pulled.
    """
    import urllib.request

    def llm(prompt):
        req = urllib.request.Request(
            host.rstrip('/') + '/api/chat',
            data=json.dumps(ollama_chat_payload(model, prompt)).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
        return data['message']['content']
    return llm
