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
    char_start: int  # position in the tag-free text stream (for context)
    safe: bool = True  # tag-balanced: group and options can be spliced safely


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


def text_stream(src: str) -> tuple[str, list[int]]:
    """Return (chars, offsets): the concatenation of all text outside markup,
    with offsets[i] = source offset of chars[i]."""
    chars: list[str] = []
    offs: list[int] = []
    i, n = 0, len(src)
    while i < n:
        if src[i] == "<":
            if src.startswith("<!--", i):
                i = src.find("-->", i) + 3
            elif src.startswith("<?", i):
                i = src.find("?>", i) + 2
            else:
                _, i = _parse_tag(src, i)
        else:
            chars.append(src[i])
            offs.append(i)
            i += 1
    return "".join(chars), offs


def classify(options: list[str]) -> str:
    if len(options) == 1:
        return "blank" if _BLANK_RE.match(options[0]) else "optional"
    if all(_BLANK_RE.match(o) for o in options):
        return "blank"
    return "choice"


def scan_groups(src: str) -> tuple[list[Group], str, list[int]]:
    """Scan the source and return (groups, text_stream, offsets)."""
    text, offs = text_stream(src)
    groups: list[Group] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        group_char_start = i
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
                    safe=safe,
                )
            )
        else:
            i = group_char_start + 1
    return groups, text, offs


def context_excerpt(text: str, char_start: int, length: int, margin: int = 100) -> str:
    lo = max(0, char_start - margin)
    hi = min(len(text), char_start + length + margin)
    return _WS_RE.sub(" ", text[lo:hi]).strip()
