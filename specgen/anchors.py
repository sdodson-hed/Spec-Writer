"""Stable decision anchors (spec 2026-10-13, section 2).

    anchor = <path>#<kind>:<hash8>[~n]

BRK-NNNN ids are positional, so one inserted bracket group renumbers every
group after it. An anchor names a decision by where it sits (the PRT/SPT
title chain) and what it says (a hash of its normalized option texts), so it
survives quarterly UFGS releases and CRLF/LF differences whenever that
decision's text and location are unchanged.

  path   PRT/SPT chain from the root: a PRT contributes its positional number
         ("PART 2"), an SPT its normalized title. "(HEADER)" before PART 1.
  kind   choice | blank | optional | submittal-review | plural
  hash8  first 8 hex of SHA-1 over the normalized option texts joined by
         \\x1f (UTF-8)
  ~n     only when the same path#kind:hash8 repeats, numbered in document
         order from 2
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter

from .scan import Group, is_plural, scan_groups

_WS_RE = re.compile(r"\s+")


def norm_text(t: str) -> str:
    return _WS_RE.sub(" ", t).strip()


def norm_title(t: str) -> str:
    """Uppercase, brackets dropped (contents kept), whitespace collapsed;
    "/" is the path separator, so a literal one is escaped as %2F."""
    t = t.replace("[", "").replace("]", "")
    return _WS_RE.sub(" ", t).strip().upper().replace("/", "%2F")


def option_hash(texts: list[str]) -> str:
    joined = "\x1f".join(norm_text(t) for t in texts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]


def group_path(locs, offset: int) -> str:
    parts = [
        s.num if s.depth == 0 else norm_title(s.title)
        for s in locs
        if s.start <= offset < s.end
    ]
    return "/".join(parts) or "(HEADER)"


def assign_anchors(groups: list[Group], locs) -> dict[str, str]:
    """gid -> anchor for every scanned group (note groups included)."""
    seen: Counter[str] = Counter()
    out: dict[str, str] = {}
    for g in groups:
        kind = "plural" if is_plural(g) else g.kind
        base = (
            f"{group_path(locs, g.src_start)}#{kind}:"
            f"{option_hash([o.text for o in g.options])}"
        )
        seen[base] += 1
        out[g.gid] = base if seen[base] == 1 else f"{base}~{seen[base]}"
    return out


def section_anchors(sec) -> dict[str, str]:
    from .manifest import location_index

    return assign_anchors(scan_groups(sec.source)[0], location_index(sec.root))


def spt_ids(locs) -> list[tuple[str, object]]:
    """(SPT-NNNN, loc) for every <SPT> in document order."""
    spts = [s for s in locs if s.name == "SPT"]
    return [(f"SPT-{i:04d}", s) for i, s in enumerate(spts, 1)]


def assign_spt_anchors(locs) -> dict[str, str]:
    """SPT-NNNN -> <path>#spt:<hash8>[~n]. The path ends with the
    subsection's own title; the hash covers that normalized title only."""
    seen: Counter[str] = Counter()
    out: dict[str, str] = {}
    for sid, s in spt_ids(locs):
        base = f"{group_path(locs, s.start)}#spt:{option_hash([norm_title(s.title)])}"
        seen[base] += 1
        out[sid] = base if seen[base] == 1 else f"{base}~{seen[base]}"
    return out


def section_spt_anchors(sec) -> dict[str, str]:
    from .manifest import location_index

    return assign_spt_anchors(location_index(sec.root))
