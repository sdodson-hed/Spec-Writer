"""Coverage audit: every decision signal in a section must be attributed.

Buckets: surfaced (appears in the manifest / HTML), excluded:<named-rule>
(note-text, contractor-form-blank, header-metadata), or unknown — in which
case the section may contain a decision the tooling would silently miss,
so audit exits non-zero and html/generate refuse to run without --force.
"""

from __future__ import annotations

import re

from .scan import context_excerpt, scan_groups, text_stream
from .secfile import Element

_UNDERSCORE_RE = re.compile(r"_{3,}")


def audit_source(src: str, root: Element, defects=()) -> dict:
    """`defects` are tolerant-parse source defects (SecFile.defects). They
    are reported, never counted as a clean pass."""
    groups, text, offs = scan_groups(src)
    _, _, mask = text_stream(src)
    signals: dict[str, dict[str, int]] = {}
    unknowns: list[dict] = []

    def tally(sig: str, bucket: str) -> None:
        signals.setdefault(sig, {})[bucket] = (
            signals.setdefault(sig, {}).get(bucket, 0) + 1
        )

    def unknown(sig: str, char_pos: int) -> None:
        tally(sig, "unknown")
        unknowns.append(
            {
                "type": sig,
                "offset": offs[char_pos] if char_pos < len(offs) else -1,
                "context": context_excerpt(text, char_pos, char_pos + 1),
            }
        )

    # 1. bracket groups
    covered = [False] * len(text)
    for g in groups:
        for c in range(g.char_start, g.char_end):
            covered[c] = True
        if g.in_note:
            tally("bracket-group", "excluded:note-text")
        elif g.kind == "submittal-review":
            tally("submittal-classification", "surfaced")
        else:
            tally("bracket-group", "surfaced")

    # 2. stray bracket characters outside any group
    for i, ch in enumerate(text):
        if ch in "[]" and not covered[i]:
            if mask[i]:
                tally("stray-bracket", "excluded:note-text")
            else:
                unknown("stray-bracket", i)

    # 3. bare underscore blanks outside brackets
    first_part = next(root.iter("PRT"), None)
    body_start = first_part.src_start if first_part is not None else 0
    for m in _UNDERSCORE_RE.finditer(text):
        if covered[m.start()]:
            continue  # inside a surfaced bracket group
        if mask[m.start()]:
            tally("bare-blank", "excluded:note-text")
        elif offs[m.start()] < body_start:
            tally("bare-blank", "excluded:header-metadata")
        else:
            tally("bare-blank", "excluded:contractor-form-blank")

    # 4. tailoring and units: surfaced via the Project Profile
    for _ in root.iter("TAI"):
        tally("tailoring", "surfaced")
    for name in ("MET", "ENG"):
        for _ in root.iter(name):
            tally("units", "surfaced")

    # 5. submittal classifications that did NOT get recognized
    for m in re.finditer(r"<SUB>\s*[GS]\s*[<,;\]]", src):
        # Inside ANY recognized group (top-level or nested)? Nested brackets
        # stay embedded in their enclosing option by design (see scan.py) —
        # e.g. a whole submittal <ITM> wrapped as one optional bracket, with
        # the "; <SUB>G, [office]" idiom nested inside it. The enclosing
        # group's own surfaced/excluded tally already accounts for it.
        if any(g.src_start <= m.start() < g.src_end for g in groups):
            continue
        # Not inside any bracket at all: a bare "<SUB>G"/"<SUB>S" with no
        # [...] around it is not a decision — the author already fixed the
        # reviewing-office requirement, there is nothing left to choose.
        # (Verified against the full masters corpus: every such occurrence
        # is bracket-free; none correspond to an unbalanced/missed bracket
        # idiom — those would already surface as a stray-bracket unknown.)
        tally("submittal-classification", "excluded:fixed-classification")

    # 6. source defects the tolerant parser kept as raw text
    reported = []
    for d in defects:
        off = d["offset"]
        context = re.sub(r"\s+", " ", src[max(0, off - 80) : off + 40]).strip()
        reported.append({**d, "context": context})
    return {"signals": signals, "unknowns": unknowns, "defects": reported}


def printable(s: str) -> str:
    """For console output: a control character (an undefined-byte defect)
    prints escaped, e.g. \\x81, instead of invisibly."""
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in s)


def audit_file(path, tolerant: bool = True) -> dict:
    from . import secfile

    sec = secfile.parse(path, tolerant=tolerant)
    return audit_source(sec.source, sec.root, sec.defects)
