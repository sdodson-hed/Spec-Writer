"""Decision-manifest extraction for a parsed .SEC file.

The manifest enumerates every decision the section demands of a specifier:

- bracket groups in the text: choices ("[air-cooled][water-cooled]"),
  fill-in blanks ("[_____]"), and optional include-or-delete phrases
- tailoring options (<TAI OPT="...">) and how much text each governs
- submittal items (<SUB>) grouped under their SD-xx classification
- references (<RID>/<RTL>) declared in the Reference Article and used in body
- notes to the specifier (<NTE>), which carry the editing instructions

Bracket decisions come from specgen.scan (raw-source spans), which is the
same scan the generator edits with — so a manifest ID always addresses the
exact same span the generator will modify.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from .anchors import assign_anchors, assign_spt_anchors, spt_ids
from .scan import (
    connector_word,
    context_excerpt,
    duplicate_map,
    is_additive,
    is_connector,
    is_plural,
    scan_fingerprint,
    scan_groups,
    text_stream,
)
from .secfile import Element, SecFile

_SD_GROUP_RE = re.compile(r"^SD-\d+")
_WS_RE = re.compile(r"\s+")

_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"G,?\s*»?\["), "Submittal reviewer code (G = Govt-approved; add office, e.g. G, AE)"),
    (re.compile(r"degrees\s*[CF]", re.I), "Temperature — fill both the SI and imperial instances consistently"),
    (re.compile(r"\b(GPM|L/s)\b", re.I), "Flow rate from equipment schedule"),
    (re.compile(r"\bpercent\b", re.I), "Percentage value"),
    (re.compile(r"\b(weeks?|days?|hours?)\b", re.I), "Duration / lead time"),
    (re.compile(r"\bcopies\b", re.I), "Number of copies"),
    (re.compile(r"\bSD-\d\d", re.I), "Submittal list item — keep only if this equipment applies"),
]


def _hint(kind: str, context: str) -> str:
    if kind not in ("blank", "optional"):
        return ""
    for pat, hint in _HINTS:
        if pat.search(context):
            return hint
    return ""


def _title_of(el: Element) -> str:
    ttl = el.first("TTL")
    return _WS_RE.sub(" ", ttl.text()).strip() if ttl is not None else el.name


_PART_TITLE_STRIP_RE = re.compile(r"^PART\s+\d+\s*", re.I)


@dataclass
class _LocSpan:
    start: int
    end: int
    title: str
    depth: int
    num: str = ""
    name: str = ""  # PRT or SPT


def location_index(root: Element) -> list[_LocSpan]:
    """Source spans of PRT/SPT (with titles and positionally-computed numbers).

    Real masters carry no numbering attributes on PRT/SPT — SI's own Navigate
    panel computes numbers from document position, so we do the same: depth-0
    (PRT) children of root are "PART 1", "PART 2", ... in order; each PRT/SPT's
    j-th PRT/SPT child gets "<parent-prefix>.j".
    """
    locs: list[_LocSpan] = []

    # counter is a 1-item list (not a plain int) so that non-PRT/SPT wrapper
    # children (e.g. <TAI> alternates) share and advance the SAME sibling
    # count as their surrounding siblings, instead of each wrapper starting
    # its own count from zero — masters interleave tailoring wrappers between
    # true PRT/SPT siblings, and SI's positional numbering does not reset there.
    def walk(el: Element, depth: int, prefix: str, counter: list[int]) -> None:
        for child in el.children:
            if not isinstance(child, Element):
                continue
            if child.name in ("PRT", "SPT"):
                counter[0] += 1
                child_no = counter[0]
                if depth == 0:
                    num, child_prefix = f"PART {child_no}", str(child_no)
                else:
                    num = child_prefix = f"{prefix}.{child_no}"
                title = _title_of(child)
                if depth == 0:
                    title = _PART_TITLE_STRIP_RE.sub("", title)
                locs.append(
                    _LocSpan(child.src_start, child.src_end, title, depth, num,
                             child.name)
                )
                walk(child, depth + 1, child_prefix, [0])
            else:
                walk(child, depth, prefix, counter)

    walk(root, 0, "", [0])
    return locs


def _subsections(sec: SecFile, locs: list[_LocSpan], groups, offs) -> list[dict]:
    """Every <SPT> as a keep/remove decision (spec 2026-10-13, section 3).

    governed_by: the subsection is the whole content of a one-option
    optional bracket ("[<SPT>...</SPT>]"), so that bracket decision already
    keeps or removes exactly this text; the page and generate treat the two
    as one decision. in_bracket: innermost enclosing bracket group, governed
    or not. tailoring: OPT of the innermost enclosing <TAI>."""
    src = sec.source
    anchors = assign_spt_anchors(locs)
    tais = sorted(
        ((t.src_start, t.src_end, t.attrs.get("OPT", "?")) for t in sec.root.iter("TAI")),
        key=lambda t: t[1] - t[0],
    )
    out: list[dict] = []
    open_spts: list[tuple[int, str]] = []  # (end, id) stack of enclosing SPTs
    for sid, s in spt_ids(locs):
        while open_spts and open_spts[-1][0] <= s.start:
            open_spts.pop()
        enclosing = [g for g in groups if g.src_start < s.start and s.end <= g.src_end]
        inner = min(enclosing, key=lambda g: g.src_end - g.src_start, default=None)
        governed = None
        if inner is not None and inner.kind == "optional" and len(inner.options) == 1:
            o = inner.options[0]
            if not src[o.src_start : s.start].strip() and not src[s.end : o.src_end].strip():
                governed = inner.gid
        tai = next((opt for a, b, opt in tais if a <= s.start and s.end <= b), None)
        out.append(
            {
                "id": sid,
                "anchor": anchors[sid],
                "num": s.num,
                "title": s.title,
                "depth": s.depth,
                "parent": open_spts[-1][1] if open_spts else None,
                "src": [s.start, s.end],
                "span": [bisect.bisect_left(offs, s.start), bisect.bisect_left(offs, s.end)],
                "governed_by": governed,
                "in_bracket": inner.gid if inner is not None else None,
                "tailoring": tai,
            }
        )
        open_spts.append((s.end, sid))
    return out


_REVIEWER_RE = re.compile(r"^[GS]\b")


def _norm_key(t: str) -> str:
    return _WS_RE.sub(" ", t).strip().lower()


def _cleanup_data(root: Element, sub_article, groups, declared: list[dict], offs) -> dict:
    """Where submittal items, references and section cross-references are
    declared and used, in master source spans, so cleanup (work order step
    4) can tell which ones lose every body use when subsections are removed.
    Each span also comes as text-stream positions ("chars", "use_chars")
    for the decision page's preview.

    A submittal item is one <ITM> in the submittals article, matched to body
    <SUB> uses by its first <SUB>'s normalized text; its reviewer code is a
    later <SUB> starting G or S. A reference is matched by its <RID> text.
    `declared` (the manifest's references list) gains uses/in_bracket in
    place."""

    def chars(span) -> list[int]:
        return [bisect.bisect_left(offs, span[0]), bisect.bisect_left(offs, span[1])]

    def innermost(a: int, b: int):
        enc = [g for g in groups if not g.in_note and g.src_start < a and b <= g.src_end]
        return min(enc, key=lambda g: g.src_end - g.src_start, default=None)
    body_subs: dict[str, list[list[int]]] = {}
    a0, a1 = (sub_article.src_start, sub_article.src_end) if sub_article is not None else (-1, -1)
    for el in root.iter("SUB"):
        if not a0 <= el.src_start < a1:
            body_subs.setdefault(_norm_key(el.text()), []).append([el.src_start, el.src_end])

    entries: list[dict] = []
    sd_groups: list[dict] = []
    if sub_article is not None:
        heads = []
        for lst in sub_article.iter("LST"):
            # from the <LST> text: 26 32 15 writes some headings without <SUB>
            name = _WS_RE.sub(" ", lst.text()).strip()
            if _SD_GROUP_RE.match(name):
                heads.append({"name": name, "src": [lst.src_start, lst.src_end], "items": []})
        for itm in sub_article.iter("ITM"):
            subs = [e for e in itm.iter("SUB")]
            if not subs:
                continue
            name = _WS_RE.sub(" ", subs[0].text()).strip()
            reviewer = next(
                (_WS_RE.sub(" ", e.text()).strip() for e in subs[1:]
                 if _REVIEWER_RE.match(_WS_RE.sub(" ", e.text()).strip())),
                None,
            )
            inner = innermost(itm.src_start, itm.src_end)
            head = next((h for h in reversed(heads) if h["src"][0] < itm.src_start), None)
            eid = f"ITM-{len(entries) + 1:04d}"
            if head is not None:
                head["items"].append(eid)
            entries.append(
                {
                    "id": eid,
                    "name": name,
                    "sd_group": head["name"] if head else None,
                    "src": [itm.src_start, itm.src_end],
                    "uses": body_subs.get(_norm_key(name), []),
                    "reviewer": reviewer,
                    "in_bracket": inner.gid if inner is not None else None,
                }
            )
        sd_groups = heads
    for e in entries:
        e["chars"] = chars(e["src"])
        e["use_chars"] = [chars(u) for u in e["uses"]]
    for h in sd_groups:
        h["chars"] = chars(h["src"])

    body_rids: dict[str, list[list[int]]] = {}
    for rid in root.iter("RID"):
        if not any(a.name == "REF" for a in rid.ancestors()):
            body_rids.setdefault(_norm_key(rid.text()), []).append([rid.src_start, rid.src_end])
    for d in declared:
        d["uses"] = body_rids.get(_norm_key(d["rid"]), [])
        d["chars"] = chars(d["entry_src"])
        d["use_chars"] = [chars(u) for u in d["uses"]]
        inner = innermost(*d["entry_src"])
        d["in_bracket"] = inner.gid if inner is not None else None
    orgs = []
    for ref in root.iter("REF"):
        org_el = ref.first("ORG")
        orgs.append(
            {
                "org": _WS_RE.sub(" ", org_el.text()).strip() if org_el is not None else "",
                "src": [ref.src_start, ref.src_end],
                "chars": chars([ref.src_start, ref.src_end]),
                "rids": [d["rid"] for d in declared if ref.src_start <= d["src"][0] < ref.src_end],
            }
        )

    section_refs: dict[str, list[list[int]]] = {}
    for srf in root.iter("SRF"):
        section_refs.setdefault(_WS_RE.sub(" ", srf.text()).strip(), []).append(
            [srf.src_start, srf.src_end]
        )
    return {
        "submittal_entries": entries,
        "submittal_groups": sd_groups,
        "reference_orgs": orgs,
        "section_refs": section_refs,
    }


def section_subsections(sec: SecFile) -> list[dict]:
    """The manifest's subsections list without building the whole manifest."""
    groups, _text, offs = scan_groups(sec.source)
    return _subsections(sec, location_index(sec.root), groups, offs)


def _locate(locs: list[_LocSpan], offset: int) -> str:
    chain = [s.title for s in locs if s.start <= offset < s.end]
    return " > ".join(chain) if chain else "(header)"


def build_manifest(sec: SecFile) -> dict:
    root = sec.root
    groups, stream, _offs = scan_groups(sec.source)
    locs = location_index(root)
    anchors = assign_anchors(groups, locs)
    sid_at = {s.start: sid for sid, s in spt_ids(locs)}
    nav = [
        {
            "num": s.num,
            "title": s.title,
            "depth": s.depth,
            "char": bisect.bisect_left(_offs, s.start),
            # outline rows for subsections carry their keep/remove decision id
            **({"spt": sid_at[s.start]} if s.name == "SPT" else {}),
        }
        for s in locs
    ]

    scn = root.first("SCN")
    stl = root.first("STL")
    dte = root.first("DTE")

    header_text = ""
    hdr = root.first("HDR")
    if hdr is not None:
        header_text = _WS_RE.sub(" ", hdr.text()).strip()
    umrl = re.search(r"UMRL dated ([A-Za-z]+ \d{4})", header_text)
    rev = re.search(r"UFGS-[\d .]+\(([^)]+)\)", header_text)

    dups = duplicate_map(groups)
    _BLOCK_TAGS = ("<OLI", "<ITM", "<LST", "<TXT", "<SPT")
    sub_spans = [
        (s.src_end, _WS_RE.sub(" ", s.text()).strip()) for s in root.iter("SUB")
    ]
    sub_spans.sort()
    note_spans_src = sorted(
        (nte.src_start, nte.src_end, _WS_RE.sub(" ", nte.text()).strip()[:1500])
        for nte in root.iter("NTE")
    )

    def _guidance(g) -> str:
        # A bracketed subsection carries its own note INSIDE the group span
        # ("[<SPT><TTL>…</TTL><NTE>NOTE: Include when…</NTE>…]") — that note
        # is the decision's instruction, so it wins. Only when the group
        # contains no note does the nearest PRECEDING note apply (the usual
        # "note, then the bracketed text it governs" layout).
        for s2, e2, t in note_spans_src:
            if g.src_start <= s2 and e2 <= g.src_end:
                return t
        return next(
            (t for _s2, e2, t in reversed(note_spans_src) if e2 <= g.src_start),
            "",
        )
    decisions = []
    for g in groups:
        in_note = g.in_note
        context = context_excerpt(stream, g.char_start, g.char_end)
        # options that are whole list items / blocks are independent includes
        # (select any subset); inline text alternatives are choose-one
        multi = g.kind == "choice" and all(
            any(t in sec.source[o.src_start : o.src_end] for t in _BLOCK_TAGS)
            for o in g.options
        )
        additive = not multi and is_additive(g)
        # inline = the group sits mid-sentence (text on the same line right
        # before or after it): removing it entirely would leave a fragment,
        # so the UI demotes "remove entirely" behind a confirmation
        i = g.char_start - 1
        while i >= 0 and stream[i] in " \t":
            i -= 1
        j = g.char_end
        while j < len(stream) and stream[j] in " \t":
            j += 1
        inline = (i >= 0 and stream[i] not in "\r\n") or (
            j < len(stream) and stream[j] not in "\r\n"
        )
        decisions.append(
            {
                "id": g.gid,
                "anchor": anchors[g.gid],
                "kind": g.kind,
                "options": [_WS_RE.sub(" ", o.text).strip() for o in g.options],
                "location": _locate(locs, g.src_start),
                "in_note": in_note,
                "safe": g.safe,
                "multi": multi,
                "additive": additive,
                "connector": connector_word(g) if additive else "",
                "conn_opts": (
                    [i for i, o in enumerate(g.options) if is_connector(o.text)]
                    if additive
                    else []
                ),
                "inline": inline,
                "plural": is_plural(g),
                "duplicate_of": dups.get(g.gid),
                "hint": _hint(g.kind, context),
                "context": context,
                "label": (
                    next(
                        (t for e, t in reversed(sub_spans) if e <= g.src_start),
                        "",
                    )
                    if g.kind == "submittal-review"
                    else ""
                ),
                "offset": g.src_start,
                "char_start": g.char_start,
                "char_end": g.char_end,
                "note_guidance": _guidance(g),
            }
        )

    # Tailoring — the profile is keyed by INDIVIDUAL option names: a joint
    # OPT="AIR FORCE,NAVY" block is removed only when ALL its names are
    # "remove" (generate.removable comma-splits), so each name gets its own
    # row and the joint block's counters are credited to every name.
    tai_counts: dict[str, dict] = {}
    n_tai_blocks = 0
    for tai in root.iter("TAI"):
        n_tai_blocks += 1
        chars = len(tai.text())
        for name in tai.attrs.get("OPT", "?").split(","):
            entry = tai_counts.setdefault(name.strip(), {"blocks": 0, "chars": 0})
            entry["blocks"] += 1
            entry["chars"] += chars

    # Submittals: grouped walk inside the SUBMITTALS subpart, usage elsewhere
    submittal_items: list[dict] = []
    # the article titled exactly SUBMITTALS; else the first SUBMITTAL* one
    # (01 33 00 has "Submittal Information" at 1.1.1 before its 1.3 SUBMITTALS)
    sub_titled = [s for s in root.iter("SPT") if _title_of(s).upper().startswith("SUBMITTAL")]
    sub_article: Element | None = next(
        (s for s in sub_titled if _title_of(s).upper() == "SUBMITTALS"),
        sub_titled[0] if sub_titled else None,
    )
    seen = set()
    if sub_article is not None:
        group = None
        for sub in sub_article.iter("SUB"):
            name = _WS_RE.sub(" ", sub.text()).strip()
            if _SD_GROUP_RE.match(name):
                group = name
                continue
            key = (group, name)
            if key not in seen:
                seen.add(key)
                submittal_items.append(
                    {"name": name, "sd_group": group, "has_brackets": "[" in name}
                )
    body_sub_uses = sum(1 for _ in root.iter("SUB")) - (
        sum(1 for _ in sub_article.iter("SUB")) if sub_article is not None else 0
    )

    # References: declared in <REF> blocks, used as bare <RID> elsewhere
    declared: list[dict] = []
    declared_ids = set()
    for ref in root.iter("REF"):
        org_el = ref.first("ORG")
        org = _WS_RE.sub(" ", org_el.text()).strip() if org_el is not None else ""
        rid_el: Element | None = None
        for child in ref.children:
            if isinstance(child, Element):
                if child.name == "RID":
                    rid_el = child
                elif child.name == "RTL" and rid_el is not None:
                    rid = _WS_RE.sub(" ", rid_el.text()).strip()
                    declared_ids.add(rid)
                    declared.append(
                        {
                            "rid": rid,
                            "title": _WS_RE.sub(" ", child.text()).strip(),
                            "org": org,
                            "src": [rid_el.src_start, rid_el.src_end],
                            # the whole entry: <RID> through its <RTL>
                            "entry_src": [rid_el.src_start, child.src_end],
                        }
                    )
                    rid_el = None
    used_ids = set()
    for rid in root.iter("RID"):
        if not any(a.name == "REF" for a in rid.ancestors()):
            used_ids.add(_WS_RE.sub(" ", rid.text()).strip())

    cleanup = _cleanup_data(root, sub_article, groups, declared, _offs)

    # Legacy kinds are seeded so counts always carry kind_choice/kind_blank/
    # kind_optional (cli.cmd_report subscripts them); new kinds count in too.
    kinds: dict[str, int] = {"choice": 0, "blank": 0, "optional": 0}
    for d in decisions:
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    body_decisions = [d for d in decisions if not d["in_note"]]

    def _content_span(el: Element) -> list[int] | None:
        if el.self_closing:
            return None
        a = bisect.bisect_left(_offs, el.src_start + len(el.open_raw))
        b = bisect.bisect_left(_offs, el.src_end - len(el.close_raw))
        return [a, b]

    tailoring_spans = [
        {"opt": t.attrs.get("OPT", "?"), "span": _content_span(t)}
        for t in root.iter("TAI")
        if _content_span(t) is not None
    ]

    # contiguous <NTE> ranges in the text stream, so the page can style
    # designer notes distinctly (they read as guidance, not spec text)
    _, _, mask = text_stream(sec.source)
    note_spans: list[list[int]] = []
    run_start: int | None = None
    for idx, in_nte in enumerate(mask):
        if in_nte and run_start is None:
            run_start = idx
        elif not in_nte and run_start is not None:
            note_spans.append([run_start, idx])
            run_start = None
    if run_start is not None:
        note_spans.append([run_start, len(mask)])

    unit_spans: list[dict] = []

    def _walk_units(el: Element) -> None:
        kids = [c for c in el.children if isinstance(c, Element)]
        i = 0
        while i < len(kids):
            c = kids[i]
            if c.name == "NTE":  # designer-note text is never edited
                i += 1
                continue
            if c.name == "MET":
                eng = kids[i + 1] if i + 1 < len(kids) and kids[i + 1].name == "ENG" else None
                unit_spans.append(
                    {"met": _content_span(c),
                     "eng": _content_span(eng) if eng is not None else None}
                )
                if eng is not None:
                    i += 2
                    continue
            elif c.name == "ENG":
                unit_spans.append({"met": None, "eng": _content_span(c)})
            else:
                _walk_units(c)
            i += 1

    _walk_units(root)

    subsections = _subsections(sec, locs, groups, _offs)

    return {
        "section": _WS_RE.sub(" ", scn.text()).strip() if scn is not None else "?",
        "title": _WS_RE.sub(" ", stl.text()).strip() if stl is not None else "?",
        "date_code": dte.text().strip() if dte is not None else "?",
        "revision": rev.group(1) if rev else None,
        "umrl_date": umrl.group(1) if umrl else None,
        "fingerprint": scan_fingerprint(groups),
        "counts": {
            "bracket_groups_total": len(decisions),
            "bracket_groups_in_body": len(body_decisions),
            "bracket_groups_in_notes": len(decisions) - len(body_decisions),
            **{f"kind_{k}": v for k, v in sorted(kinds.items())},
            "tailoring_blocks": n_tai_blocks,
            "notes_to_specifier": sum(1 for _ in root.iter("NTE")),
            "submittal_items": len(submittal_items),
            "references_declared": len(declared),
            "references_used_in_body": len(used_ids),
            "references_declared_but_unused": sorted(declared_ids - used_ids),
            "references_used_but_undeclared": sorted(used_ids - declared_ids),
            "unit_pairs": len(unit_spans),
            "subsections": len(subsections),
        },
        "tailoring_options": {
            k: v for k, v in sorted(tai_counts.items(), key=lambda kv: -kv[1]["chars"])
        },
        "tailoring_spans": tailoring_spans,
        "decisions": decisions,
        # keep/remove structural decisions; separate from bracket decisions
        # so their ids, counts and the unanswered gate are unaffected
        "subsections": subsections,
        # where submittal items, references and section cross-references are
        # declared and used (master source spans), for removal cleanup
        **cleanup,
        "submittals": submittal_items,
        "references": declared,
        "unit_spans": unit_spans,
        "note_spans": note_spans,
        "body_submittal_tag_uses": body_sub_uses,
        # full tag-free text of the section; char_start/char_end above index
        # into this, so a UI can show every decision in situ
        "text": stream,
        "nav": nav,
    }
