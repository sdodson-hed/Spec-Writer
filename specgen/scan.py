"""Raw-source bracket-group scanner.

Brackets are literal characters in a section's text nodes. This module scans
the raw source (skipping tag markup) and yields bracket groups with exact
source spans, so the SAME scan drives both the decision manifest (IDs,
options, context) and the generator (surgical replacements). A group's raw
span may enclose markup (e.g. an optional list item ``[<OLI>...</OLI>]``),
which is intentionally kept with the chosen/deleted content.

Grouping rule: consecutive balanced bracket spans separated by nothing or by
spaces/tabs (in text content) form one group — one decision with N options.
Nested brackets stay embedded in their enclosing option.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .secfile import _parse_tag

_BLANK_RE = re.compile(r"^[\s_]*_[\s_]*$")
_WS_RE = re.compile(r"\s+")


@dataclass
class Option:
    text: str  # tag-free text of the option (may contain nested brackets)
    src_start: int  # raw-source span of the option's content (inside brackets)
    src_end: int


@dataclass
class Group:
    gid: str  # BRK-0001 ... assigned in document order
    kind: str  # choice | blank | optional
    options: list[Option]
    src_start: int  # raw-source span including the outer brackets
    src_end: int
    char_start: int  # span in the tag-free text stream (for context)
    char_end: int = -1
    safe: bool = True  # tag-balanced: group and options can be spliced safely
    in_note: bool = False  # inside <NTE>: guidance text, never a decision


def balanced(src_slice: str) -> bool:
    """True if every tag opened in the slice closes in it and vice versa."""
    stack: list[str] = []
    i, n = 0, len(src_slice)
    while i < n:
        if src_slice[i] != "<":
            i += 1
            continue
        if src_slice.startswith("<!--", i):
            i = src_slice.find("-->", i) + 3
            continue
        if src_slice.startswith("<?", i):
            i = src_slice.find("?>", i) + 2
            continue
        try:
            raw, i = _parse_tag(src_slice, i)
        except Exception:
            return False
        body = raw[1:-1]
        if body.startswith("/"):
            name = body[1:].strip()
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        elif not body.rstrip().endswith("/"):
            stack.append(body.split()[0].strip())
    return not stack


def text_stream(src: str) -> tuple[str, list[int], list[bool]]:
    """Return (chars, offsets, mask): text outside markup, source offset of
    each char, and mask[i]=True when the char is inside an <NTE> note."""
    chars: list[str] = []
    offs: list[int] = []
    mask: list[bool] = []
    nte_depth = 0
    i, n = 0, len(src)
    while i < n:
        if src[i] == "<":
            if src.startswith("<!--", i):
                i = src.find("-->", i) + 3
            elif src.startswith("<?", i):
                i = src.find("?>", i) + 2
            else:
                raw, i = _parse_tag(src, i)
                body = raw[1:-1]
                if body.startswith("/"):
                    if body[1:].strip() == "NTE":
                        nte_depth = max(0, nte_depth - 1)
                elif not body.rstrip().endswith("/"):
                    if body.split()[0].strip() == "NTE":
                        nte_depth += 1
        else:
            chars.append(src[i])
            offs.append(i)
            mask.append(nte_depth > 0)
            i += 1
    return "".join(chars), offs, mask


def classify(options: list[str]) -> str:
    if len(options) == 1:
        return "blank" if _BLANK_RE.match(options[0]) else "optional"
    if all(_BLANK_RE.match(o) for o in options):
        return "blank"
    return "choice"


def scan_groups(src: str) -> tuple[list[Group], str, list[int]]:
    """Scan the source and return (groups, text_stream, offsets)."""
    text, offs, mask = text_stream(src)
    groups: list[Group] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        group_char_start = i
        in_note = mask[i]
        options: list[Option] = []
        end = i
        while i < n and text[i] == "[":
            depth, j = 0, i
            while j < n:
                if text[j] == "[":
                    depth += 1
                elif text[j] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n:  # unbalanced: treat as literal, abandon this group
                options = []
                break
            inner = text[i + 1 : j]
            # Raw span = everything between the two bracket characters in the
            # source, INCLUDING any markup (e.g. [<OLI>item</OLI><BRK/>]).
            options.append(
                Option(text=inner, src_start=offs[i] + 1, src_end=offs[j])
            )
            end = j + 1
            k = end
            while k < n and text[k] in " \t":
                k += 1
            # adjacent = next '[' with ONLY spaces/tabs between them in the
            # RAW source too (no markup) — a tag between bracket spans means
            # they belong to different structural elements
            if (
                k < n
                and text[k] == "["
                and mask[k] == in_note
                and src[offs[end - 1] + 1 : offs[k]].strip(" \t") == ""
            ):
                i = k
            else:
                i = end
                break
        if options:
            g_start, g_end = offs[group_char_start], offs[end - 1] + 1
            safe = balanced(src[g_start:g_end]) and all(
                balanced(src[o.src_start : o.src_end]) for o in options
            )
            groups.append(
                Group(
                    gid=f"BRK-{len(groups) + 1:04d}",
                    kind=classify([o.text for o in options]),
                    options=options,
                    src_start=g_start,
                    src_end=g_end,
                    char_start=group_char_start,
                    char_end=end,
                    safe=safe,
                    in_note=in_note,
                )
            )
        else:
            i = group_char_start + 1
    return groups, text, offs


def is_plural(group: Group) -> bool:
    """Trivial plural marker like Chiller[s] — one project-level decision."""
    return (
        len(group.options) == 1
        and group.options[0].text.strip().lower() in ("s", "es", "ies")
    )


def duplicate_map(groups: list[Group]) -> dict[str, str]:
    """Map gid -> gid of the first group with identical kind+options.
    Only meaningful decisions participate (multi-option, or optional text of
    substance) — the same design datum answers every instance."""
    first: dict[tuple, str] = {}
    dups: dict[str, str] = {}
    for g in groups:
        if is_plural(g):
            continue
        texts = tuple(_WS_RE.sub(" ", o.text).strip().lower() for o in g.options)
        if len(texts) < 2 and (g.kind != "optional" or len(texts[0]) < 4):
            continue
        key = (g.kind, texts)
        if key in first:
            dups[g.gid] = first[key]
        else:
            first[key] = g.gid
    return dups


def context_excerpt(
    text: str, char_start: int, char_end: int, margin: int = 90
) -> str:
    """Excerpt with the decision span marked »like this«, trimmed to word
    boundaries so it reads as a sentence fragment, not a random slice."""
    lo = max(0, char_start - margin)
    hi = min(len(text), char_end + margin)
    before = _WS_RE.sub(" ", text[lo:char_start]).lstrip()
    inside = _WS_RE.sub(" ", text[char_start:char_end]).strip()
    after = _WS_RE.sub(" ", text[char_end:hi]).rstrip()
    if lo > 0 and before and not before[0].isspace():
        cut = before.find(" ")
        before = before[cut + 1 :] if 0 <= cut < len(before) - 1 else before
    if hi < len(text) and after:
        cut = after.rfind(" ")
        after = after[:cut] if cut > 0 else after
    return f"…{before}»{inside}«{after}…"
