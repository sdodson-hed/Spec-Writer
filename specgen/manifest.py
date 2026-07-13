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

import re
from dataclasses import dataclass

from .scan import context_excerpt, scan_groups
from .secfile import Element, SecFile

_SD_GROUP_RE = re.compile(r"^SD-\d+")
_WS_RE = re.compile(r"\s+")


def _title_of(el: Element) -> str:
    ttl = el.first("TTL")
    return _WS_RE.sub(" ", ttl.text()).strip() if ttl is not None else el.name


@dataclass
class _LocSpan:
    start: int
    end: int
    title: str
    depth: int


def _location_index(root: Element) -> tuple[list[_LocSpan], list[tuple[int, int]]]:
    """Source spans of PRT/SPT (with titles) and NTE elements."""
    locs: list[_LocSpan] = []
    notes: list[tuple[int, int]] = []

    def walk(el: Element, depth: int) -> None:
        for child in el.children:
            if not isinstance(child, Element):
                continue
            if child.name in ("PRT", "SPT"):
                locs.append(
                    _LocSpan(child.src_start, child.src_end, _title_of(child), depth)
                )
                walk(child, depth + 1)
            else:
                if child.name == "NTE":
                    notes.append((child.src_start, child.src_end))
                walk(child, depth)

    walk(root, 0)
    return locs, notes


def _locate(locs: list[_LocSpan], offset: int) -> str:
    chain = [s.title for s in locs if s.start <= offset < s.end]
    return " > ".join(chain) if chain else "(header)"


def build_manifest(sec: SecFile) -> dict:
    root = sec.root
    groups, stream, _offs = scan_groups(sec.source)
    locs, notes = _location_index(root)

    scn = root.first("SCN")
    stl = root.first("STL")
    dte = root.first("DTE")

    header_text = ""
    hdr = root.first("HDR")
    if hdr is not None:
        header_text = _WS_RE.sub(" ", hdr.text()).strip()
    umrl = re.search(r"UMRL dated ([A-Za-z]+ \d{4})", header_text)
    rev = re.search(r"UFGS-[\d .]+\(([^)]+)\)", header_text)

    decisions = []
    for g in groups:
        in_note = any(s <= g.src_start < e for s, e in notes)
        decisions.append(
            {
                "id": g.gid,
                "kind": g.kind,
                "options": [_WS_RE.sub(" ", o.text).strip() for o in g.options],
                "location": _locate(locs, g.src_start),
                "in_note": in_note,
                "safe": g.safe,
                "context": context_excerpt(
                    stream, g.char_start, g.src_end - g.src_start
                ),
                "offset": g.src_start,
            }
        )

    # Tailoring
    tai_counts: dict[str, dict] = {}
    for tai in root.iter("TAI"):
        opt = tai.attrs.get("OPT", "?")
        entry = tai_counts.setdefault(opt, {"blocks": 0, "chars": 0})
        entry["blocks"] += 1
        entry["chars"] += len(tai.text())

    # Submittals: grouped walk inside the SUBMITTALS subpart, usage elsewhere
    submittal_items: list[dict] = []
    sub_article: Element | None = None
    for spt in root.iter("SPT"):
        if _title_of(spt).upper().startswith("SUBMITTAL"):
            sub_article = spt
            break
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
                        }
                    )
                    rid_el = None
    used_ids = set()
    for rid in root.iter("RID"):
        if not any(a.name == "REF" for a in rid.ancestors()):
            used_ids.add(_WS_RE.sub(" ", rid.text()).strip())

    kinds = {"choice": 0, "blank": 0, "optional": 0}
    for d in decisions:
        kinds[d["kind"]] += 1
    body_decisions = [d for d in decisions if not d["in_note"]]

    return {
        "section": _WS_RE.sub(" ", scn.text()).strip() if scn is not None else "?",
        "title": _WS_RE.sub(" ", stl.text()).strip() if stl is not None else "?",
        "date_code": dte.text().strip() if dte is not None else "?",
        "revision": rev.group(1) if rev else None,
        "umrl_date": umrl.group(1) if umrl else None,
        "counts": {
            "bracket_groups_total": len(decisions),
            "bracket_groups_in_body": len(body_decisions),
            "bracket_groups_in_notes": len(decisions) - len(body_decisions),
            **{f"kind_{k}": v for k, v in kinds.items()},
            "tailoring_blocks": sum(v["blocks"] for v in tai_counts.values()),
            "notes_to_specifier": sum(1 for _ in root.iter("NTE")),
            "submittal_items": len(submittal_items),
            "references_declared": len(declared),
            "references_used_in_body": len(used_ids),
            "references_declared_but_unused": sorted(declared_ids - used_ids),
            "references_used_but_undeclared": sorted(used_ids - declared_ids),
        },
        "tailoring_options": {
            k: v for k, v in sorted(tai_counts.items(), key=lambda kv: -kv[1]["chars"])
        },
        "decisions": decisions,
        "submittals": submittal_items,
        "references": declared,
        "body_submittal_tag_uses": body_sub_uses,
    }
