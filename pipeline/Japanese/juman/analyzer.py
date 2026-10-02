#!/usr/bin/env python3
"""Japanese morphology, syntax, and dictionary analysis.

Juman++ supplies morphemes, KNP groups them into bunsetsu, and Jamdict adds
local JMdict and KANJIDIC2 information.  The resulting dictionaries contain
only JSON-serializable values and are suitable for an interactive frontend.

Juman++ and KNP must be installed and available on ``PATH``.  Install the
Python dependencies with ``pip install wheel`` followed by
``pip install -r requirements.txt`` (``jamdict-data`` has a legacy build that
imports wheel during installation).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from typing import Any

from jamdict import Jamdict
from rhoknp import Jumanpp, KNP


def _unique(values: Iterable[str]) -> list[str]:
    """Return non-empty strings in their original order without duplicates."""
    return list(dict.fromkeys(value for value in values if value))


def _is_kanji(character: str) -> bool:
    """Return whether *character* is in a CJK ideograph Unicode block."""
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF  # CJK Extension A
        or 0x4E00 <= codepoint <= 0x9FFF  # CJK Unified Ideographs
        or 0xF900 <= codepoint <= 0xFAFF  # CJK Compatibility Ideographs
        or 0x20000 <= codepoint <= 0x2EBEF  # CJK Extensions B-F and I
        or 0x30000 <= codepoint <= 0x323AF  # CJK Extensions G-H
    )


def _can_appear_in_jmdict(text: str) -> bool:
    """Avoid querying Jamdict for punctuation and Juman++ sentinel values."""
    return any(_is_kanji(char) or 0x3040 <= ord(char) <= 0x30FF for char in text)


class JapaneseAnalyzer:
    """Analyze Japanese sentences with persistent Juman++, KNP, and Jamdict.

    Keeping one instance alive is recommended when processing many sentences:
    rhoknp reuses its Juman++ and KNP subprocesses, while the small in-memory
    caches avoid repeated SQLite lookups for common lemmas and kanji.
    """

    def __init__(self) -> None:
        self.jumanpp = Jumanpp()
        # Pass the same Juman++ processor to KNP.  ``analyze`` still applies
        # Juman++ explicitly first, so KNP receives its morphological output.
        self.knp = KNP(jumanpp=self.jumanpp)
        self.jamdict = Jamdict()
        self._word_cache: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
        self._kanji_cache: dict[str, dict[str, Any]] = {}

    def _lookup_word(self, lemma: str, reading: str) -> tuple[list[str], list[str]]:
        """Return primary English glosses and JMdict POS tags for a lemma."""
        cache_key = (lemma, reading)
        if cache_key in self._word_cache:
            return self._word_cache[cache_key]
        if not lemma or not _can_appear_in_jmdict(lemma):
            return [], []

        result = self.jamdict.lookup(
            lemma,
            strict_lookup=True,
            lookup_chars=False,
            lookup_ne=False,
        )
        entries = list(result.entries)
        if not entries:
            self._word_cache[cache_key] = ([], [])
            return [], []

        # Jamdict may return orthographic variants.  Prefer an entry whose
        # written or kana form exactly matches the Juman++ lemma, then use the
        # reading to break ties.
        exact_entries = [
            entry
            for entry in entries
            if lemma
            in {
                *(form.text for form in entry.kanji_forms),
                *(form.text for form in entry.kana_forms),
            }
        ]
        candidates = exact_entries or entries
        entry = next(
            (
                candidate
                for candidate in candidates
                if reading and any(form.text == reading for form in candidate.kana_forms)
            ),
            candidates[0],
        )

        if not entry.senses:
            word_info = ([], [])
        else:
            primary_sense = entry.senses[0]
            glosses = _unique(
                gloss.text
                for gloss in primary_sense.gloss
                if not gloss.lang or gloss.lang == "eng"
            )
            word_info = (glosses, _unique(primary_sense.pos))

        self._word_cache[cache_key] = word_info
        return word_info

    def _lookup_kanji(self, character: str) -> dict[str, Any]:
        """Return KANJIDIC2 meanings and Japanese readings for one kanji."""
        if character in self._kanji_cache:
            return self._kanji_cache[character]

        result = self.jamdict.lookup(
            character,
            strict_lookup=True,
            lookup_chars=True,
            lookup_ne=False,
        )
        kanji = next((item for item in result.chars if item.literal == character), None)
        if kanji is None:
            breakdown: dict[str, Any] = {
                "character": character,
                "meanings": [],
                "readings": {"on": [], "kun": []},
            }
        else:
            on_readings: list[str] = []
            kun_readings: list[str] = []
            for group in kanji.rm_groups:
                on_readings.extend(reading.value for reading in group.on_readings)
                kun_readings.extend(reading.value for reading in group.kun_readings)
            breakdown = {
                "character": character,
                "meanings": _unique(kanji.meanings(english_only=True)),
                "readings": {
                    "on": _unique(on_readings),
                    "kun": _unique(kun_readings),
                },
            }

        self._kanji_cache[character] = breakdown
        return breakdown

    def _token(self, morpheme: Any) -> dict[str, Any]:
        glosses, dictionary_pos = self._lookup_word(morpheme.lemma, morpheme.reading)
        return {
            "surface": morpheme.text,
            "reading": morpheme.reading,
            "lemma": morpheme.lemma,
            "pos": morpheme.pos,
            "english_glosses": glosses,
            "kanji_breakdown": [
                self._lookup_kanji(character)
                for character in morpheme.text
                if _is_kanji(character)
            ],
            # Keep JMdict's English POS labels in addition to Juman++'s POS.
            "jmdict_pos": dictionary_pos,
        }

    def analyze(self, sentence: str) -> dict[str, Any]:
        """Analyze one non-empty Japanese sentence into bunsetsu and tokens."""
        sentence = sentence.strip()
        if not sentence:
            raise ValueError("sentence must not be empty")

        morphological_sentence = self.jumanpp.apply_to_sentence(sentence)
        parsed_sentence = self.knp.apply_to_sentence(morphological_sentence)
        tokens = [self._token(morpheme) for morpheme in parsed_sentence.morphemes]

        bunsetsu = [
            {
                "index": phrase.index,
                "surface": "".join(morpheme.text for morpheme in phrase.morphemes),
                "parent_index": phrase.parent_index,
                "dependency_type": phrase.dep_type.value if phrase.dep_type is not None else None,
                "token_indexes": [morpheme.index for morpheme in phrase.morphemes],
            }
            for phrase in parsed_sentence.phrases
        ]
        return {"sentence": sentence, "bunsetsu": bunsetsu, "tokens": tokens}


def analyze(sentence: str) -> dict[str, Any]:
    """Convenience API for analyzing one sentence with a new analyzer."""
    return JapaneseAnalyzer().analyze(sentence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze a Japanese sentence with Juman++, KNP, and Jamdict."
    )
    parser.add_argument("sentence", help="Japanese sentence to analyze")
    args = parser.parse_args(argv)

    try:
        payload = analyze(args.sentence)
    except (RuntimeError, TimeoutError, ValueError) as error:
        parser.exit(1, f"analyzer: error: {error}\n")

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
