"""Layer 2a — grammar pattern rules (the extensible part of the merger).

Rules are REGISTERED, not inlined: adding a pattern means adding one small
function in this file — the merger loop (merger.py) picks it up
automatically. This is where most future pipeline work will land.

Two phases, matching where a pattern can fire in the chunker:

  @pre   tried at the current position BEFORE head-token handling.
         signature:  match(toks, i, n) -> (end_index, template) | None
         template = chunk fields except 'morphemes' (the merger fills
         morphemes=toks[i:end_index]).

  @post  tried AFTER the auxiliary run has been absorbed into the chunk
         being built. signature:  absorb(morph, aux, toks, i, n) -> new_i | None
         Mutate morph/aux IN PLACE (append/extend — rebinding is invisible
         to the caller) and return the new index.

Order matters within a phase: rules are tried in registration order.
Keep the most specific patterns first.
"""

NARU = {'なる', '成る'}

PRE_RULES = []
POST_RULES = []


def pre(fn):
    """Register a pre-head pattern rule (see module docstring)."""
    PRE_RULES.append(fn)
    return fn


def post(fn):
    """Register a post-aux absorption rule (see module docstring)."""
    POST_RULES.append(fn)
    return fn


# ---------------------------------------------------------------- pre rules

def _match_must_pattern(toks, i):
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


@pre
def must_pattern(toks, i, n):
    """〜なくてはならない / 〜なければならない (must, have to)."""
    j = _match_must_pattern(toks, i)
    if not j:
        return None
    return j, {'type': 'grammar point',
               'grammarPoint': '〜なくてはならない / 〜なければならない (must, have to)',
               'aux': [], 'te': None, 'compound': False}


@pre
def ni_tsuite(toks, i, n):
    """compound particle について: に + つい(つく) + て."""
    t = toks[i]
    if t['p1'] == '助詞' and t['s'] == 'に' and i + 2 < n and \
       toks[i+1]['p1'] == '動詞' and toks[i+1]['lemma'] in ('つく', '付く') and \
       toks[i+2]['s'] == 'て':
        return i + 3, {'type': 'grammar point',
                       'grammarPoint': '〜について (about, regarding)',
                       'aux': [], 'te': None, 'compound': False,
                       'dictform': 'について'}
    return None


# ---------------------------------------------------------------- post rules

@post
def tai_negative(morph, aux, toks, i, n):
    """negative of ~たい: したく + ない -> したくない."""
    if aux and any(x['lemma'] == 'たい' for x in aux) and i < n and \
       toks[i]['s'] == 'ない' and toks[i]['p1'] in ('助動詞', '形容詞'):
        aux.append(toks[i])
        morph.append(toks[i])
        return i + 1
    return None


@post
def formal_noun_copula(morph, aux, toks, i, n):
    """explanatory の + copula after a noun: ひとつ + な + の + だ."""
    if i < n and '形式名詞' in toks[i]['pos'] and i + 1 < n and \
       toks[i + 1]['p1'] == '助動詞' and toks[i + 1]['lemma'] in ('だ', 'です'):
        morph.extend([toks[i], toks[i + 1]])
        return i + 2
    return None
