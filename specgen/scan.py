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

import hashlib
import json
import re
from dataclasses import dataclass

from .secfile import _parse_tag

_BLANK_RE = re.compile(r"^[\s_]*_[\s_]*$")
_WS_RE = re.compile(r"\s+")
# A span that is ONLY a list connector ("[ or ]", "[, and]", "[,]"): never a
# selectable option — it joins its neighbors when both are kept.
_CONNECTOR_ONLY_RE = re.compile(r"^\s*(?:[,;]\s*)?(?:(?:and|or)\b\s*)?$", re.I)
# Leading/trailing connectors on an option body (", double pole", "brass,",
# " and control center"): stripped before additive joining, separators are
# recomputed. Trailing strip prevents double commas from "[brass,][ steel,]".
_LEAD_CONNECTOR_RE = re.compile(r"(?:[,;]\s*)?(?:(?:and|or)\b\s*)?", re.I)
_TRAIL_CONNECTOR_RE = re.compile(r"(?:\s*[,;]|\s+(?:and|or)\b)+\s*$", re.I)
_CONNECTOR_WORD_RE = re.compile(r"\b(and|or)\b", re.I)
# Tags that are invisible in the rendered section: a gap made only of these
# (and spaces/tabs) leaves two bracket spans visually adjacent — one choice.
_INVISIBLE_GAP_RE = re.compile(
    r"^(?:[ \t]|</?(?:SPT|TAI|MET|ENG)(?:\s[^>]*)?>)+$"
)
# "[; <SUB>G, [_____]</SUB>]" (G or S, optional <TAI> wrapping): the
# submittal-classification idiom — keep/remove the reviewer flag and
# fill in the reviewing office.
_SUBREV_RE = re.compile(r"^;?\s*<SUB>\s*[GS]\b")
# Subsection-level structural markup inside an option: the span wraps a whole
# titled block, so adjacency runs split into independent optionals.
_STRUCT_TAG_RE = re.compile(r"</?(?:SPT|PRT|TTL)\b")


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
    each char, and mask[i]=True when the char is inside an <NTE> note.

    Two layout-bearing tags contribute synthetic whitespace so the flat
    stream reads the way SpecsIntact publishes it (issue #42):
      * <BRK/> — an explicit hard line break — emits "\\n".
      * an <RTL> that directly follows </RID> with nothing between them (the
        reference-article two-column idiom) emits a leading "\\t", so the
        designation and its title don't run together ("ACI 117(2010)…").
    Each synthetic char is mapped to the source offset of its originating
    tag, keeping the char→source map monotonic (bisect- and splice-safe)."""
    chars: list[str] = []
    offs: list[int] = []
    mask: list[bool] = []
    nte_depth = 0
    prev_close_rid = False  # last tag event was </RID> with no char since
    i, n = 0, len(src)
    while i < n:
        if src[i] == "<":
            tag_start = i
            if src.startswith("<!--", i):
                i = src.find("-->", i) + 3
            elif src.startswith("<?", i):
                i = src.find("?>", i) + 2
            else:
                raw, i = _parse_tag(src, i)
                body = raw[1:-1]
                is_close = body.startswith("/")
                is_self = not is_close and body.rstrip().endswith("/")
                name = body.lstrip("/").split()[0].rstrip("/").strip()
                if is_close:
                    if name == "NTE":
                        nte_depth = max(0, nte_depth - 1)
                    prev_close_rid = name == "RID"
                elif is_self:
                    if name == "BRK":
                        chars.append("\n")
                        offs.append(tag_start)
                        mask.append(nte_depth > 0)
                    prev_close_rid = False
                else:
                    if name == "NTE":
                        nte_depth += 1
                    # a two-column reference row (RTL right after RID) or a
                    # list item (<ITM>) gets a leading tab so it indents under
                    # its heading instead of sitting flat at the margin
                    if (name == "RTL" and prev_close_rid) or name == "ITM":
                        chars.append("\t")
                        offs.append(tag_start)
                        mask.append(nte_depth > 0)
                    prev_close_rid = False
        else:
            chars.append(src[i])
            offs.append(i)
            mask.append(nte_depth > 0)
            prev_close_rid = False  # real text separates RID from any RTL
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
        char_spans: list[tuple[int, int]] = []  # per-option [ .. ] char bounds
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
            char_spans.append((i, j + 1))
            end = j + 1
            k = end
            while k < n and text[k] in " \t":
                k += 1
            # adjacent = next '[' with ONLY spaces/tabs between them in the
            # RAW source too (no markup) — a tag between bracket spans means
            # they belong to different structural elements
            gap = src[offs[end - 1] + 1 : offs[k]] if k < n else ""
            if (
                k < n
                and text[k] == "["
                and mask[k] == in_note
                and (gap.strip(" \t") == "" or _INVISIBLE_GAP_RE.match(gap))
            ):
                i = k
            else:
                i = end
                break
        if options:
            # Adjacent spans that carry whole SUBSECTIONS (an option
            # containing SPT/PRT/TTL markup) are independent include-or-
            # delete blocks butted together, not one N-way choice — a run
            # like "[Service Entrance Cables…][Nonmetallic Sheathed Cable…]"
            # must not become an unanswerable mega-group. Split every such
            # group into one single-option group per span.
            split = len(options) > 1 and any(
                _STRUCT_TAG_RE.search(src[o.src_start : o.src_end])
                for o in options
            )
            chunks = (
                [[k] for k in range(len(options))]
                if split
                else [list(range(len(options)))]
            )
            for chunk in chunks:
                opts = [options[k] for k in chunk]
                c_lo = char_spans[chunk[0]][0]
                c_hi = char_spans[chunk[-1]][1]
                g_start, g_end = offs[c_lo], offs[c_hi - 1] + 1
                safe = balanced(src[g_start:g_end]) and all(
                    balanced(src[o.src_start : o.src_end]) for o in opts
                )
                g = Group(
                    gid=f"BRK-{len(groups) + 1:04d}",
                    kind=classify([o.text for o in opts]),
                    options=opts,
                    src_start=g_start,
                    src_end=g_end,
                    char_start=c_lo,
                    char_end=c_hi,
                    safe=safe,
                    in_note=in_note,
                )
                if g.kind == "optional" and len(g.options) == 1:
                    raw_opt = src[g.options[0].src_start : g.options[0].src_end]
                    if _SUBREV_RE.match(raw_opt.strip()):
                        g.kind = "submittal-review"
                groups.append(g)
        else:
            i = group_char_start + 1
    return groups, text, offs


def scan_fingerprint(groups: list[Group]) -> str:
    """Stable hash of the decision surface: ids, kinds and option texts in
    document order. Any change that shifts what an answer id means changes
    it (issue #23). Whitespace is normalized and positions are left out, so
    CRLF vs LF copies, and edits to text outside brackets, do not."""
    payload = [
        (g.gid, g.kind, [_WS_RE.sub(" ", o.text).strip() for o in g.options])
        for g in groups
    ]
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    return digest.hexdigest()[:16]


def legacy_scan_fingerprint(groups: list[Group]) -> str:
    """Pre-2026-10 fingerprint: kept so older answer files still verify.
    Hashes raw option text and char positions, so it differs between CRLF
    and LF copies and moves whenever text before a group changes length."""
    payload = [
        (g.gid, g.kind, [o.text for o in g.options], g.char_start, g.char_end)
        for g in groups
    ]
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    return digest.hexdigest()[:16]


def is_connector(text: str) -> bool:
    """True for a span that is nothing but a list connector (or/and/comma)."""
    return bool(text.strip()) and _CONNECTOR_ONLY_RE.match(text) is not None


def is_additive(group: Group) -> bool:
    """True when a choice group is an additive list ("select all that
    apply"), not an exclusive either/or. Signals: a connector-only span
    anywhere, or an option after the first carrying a leading connector
    (", double pole", " and control center")."""
    if group.kind != "choice":
        return False
    texts = [o.text for o in group.options]
    if any(is_connector(t) for t in texts):
        return True
    for t in texts[1:]:
        lead = _LEAD_CONNECTOR_RE.match(t.lstrip()).group(0)
        if lead.strip():
            return True
    return False


def connector_word(group: Group) -> str:
    """The list-joining word ("and"/"or") for an additive group — the last
    and/or that appears in a connector-only span or an option's leading
    connector. Defaults to "and" (comma-only lists)."""
    word = "and"
    for o in group.options:
        t = o.text
        if is_connector(t):
            m = _CONNECTOR_WORD_RE.search(t)
            if m:
                word = m.group(1).lower()
            continue
        lead = _LEAD_CONNECTOR_RE.match(t.lstrip()).group(0)
        m = _CONNECTOR_WORD_RE.search(lead)
        if m:
            word = m.group(1).lower()
    return word


def strip_connector(text: str) -> str:
    """Option body with leading AND trailing connectors removed — the "core"
    that additive joining recomposes with fresh separators (trailing strip
    prevents "[brass,][ steel,]" from rejoining with double commas). Bodies
    that open with markup ('<') keep their start intact (nothing literal to
    strip)."""
    t = text.lstrip()
    lead = _LEAD_CONNECTOR_RE.match(t).group(0)
    if lead.strip():
        t = t[len(lead):]
    t = _TRAIL_CONNECTOR_RE.sub("", t)
    return t.strip()


def connector_runs(group: Group) -> tuple[int, int]:
    """(lo, hi): options[:lo] and options[hi:] are connector-only spans at
    the group's EDGES. Edge connectors join the group to surrounding text
    ("pumps[ and][ motors]"), so they are kept verbatim whenever any core
    is kept; interior connectors are recomposed by additive_join."""
    flags = [is_connector(o.text) for o in group.options]
    lo, hi = 0, len(flags)
    while lo < hi and flags[lo]:
        lo += 1
    while hi > lo and flags[hi - 1]:
        hi -= 1
    return lo, hi


def additive_join(cores: list[str], conn: str) -> str:
    """Join kept option cores as an English list: "a", "a and b",
    "a, b, and c" (the connector word comes from the master's own text)."""
    if not cores:
        return ""
    if len(cores) == 1:
        return cores[0]
    if len(cores) == 2:
        return f"{cores[0]} {conn} {cores[1]}"
    return ", ".join(cores[:-1]) + f", {conn} " + cores[-1]


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
