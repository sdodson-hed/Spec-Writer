"""Removal cleanup (spec 2026-10-13, section 3; work order step 4).

When subsections are removed, submittal items and reference entries whose
ONLY body uses were inside the removed content become orphans that
SpecsIntact's submittal and reference verification would flag. plan_cleanup
decides, in master coordinates, what goes with them:

  - an orphaned submittal item (<ITM>) or reference entry (<RID><RTL>) is
    removed, with the <BRK/>/whitespace run that follows it;
  - an orphan inside a bracket group is BLOCKED, not removed: deleting it
    would answer that bracket decision for the engineer (plan D1);
  - an SD heading whose items were all removed goes too, and a <REF>
    organization block whose entries were all orphaned goes whole (D2);
  - section cross-references (<SRF>) with no use left are reported.

Only subsections removed by decision count as "removed content" (D3).
Pure: no edits here; generate applies the plan.
"""

from __future__ import annotations

import re

from .scan import scan_groups

_TRAIL_RE = re.compile(r"(?:\s|<BRK/>)*")


def _with_trailing(src: str, start: int, end: int) -> list[int]:
    """[start, end) extended over the <BRK/>/whitespace run after it."""
    return [start, _TRAIL_RE.match(src, end).end()]


def plan_cleanup(sec, manifest: dict, removed: dict[str, tuple[int, int]]) -> dict:
    src = sec.source
    spans = sorted(removed.items(), key=lambda kv: kv[1][0])

    def inside(a: int, b: int) -> list[str]:
        return [sid for sid, (x, y) in spans if x <= a and b <= y]

    def orphaned(uses: list) -> list[str] | None:
        """SPT ids that removed every use, or None if any use survives."""
        if not uses:
            return None
        causes: set[str] = set()
        for a, b in uses:
            hit = inside(a, b)
            if not hit:
                return None
            causes.update(hit)
        return sorted(causes)

    actions: list[dict] = []
    blocked: list[dict] = []
    if spans:
        # submittal items
        removed_items: dict[str, list[str]] = {}
        for e in manifest.get("submittal_entries", []):
            if inside(*e["src"]):
                continue  # goes with its subsection
            causes = orphaned(e["uses"])
            if causes is None:
                continue
            act = {
                "kind": "submittal-item",
                "id": e["id"],
                "name": e["name"],
                "caused_by": causes,
                "reviewer": e["reviewer"],
            }
            if e["in_bracket"]:
                blocked.append({**act, "src": list(e["src"]), "in_bracket": e["in_bracket"]})
            else:
                actions.append({**act, "src": _with_trailing(src, *e["src"])})
                removed_items[e["id"]] = causes
        for h in manifest.get("submittal_groups", []):
            if h["items"] and all(i in removed_items for i in h["items"]):
                causes = sorted({c for i in h["items"] for c in removed_items[i]})
                actions.append(
                    {"kind": "sd-heading", "id": h["name"], "name": h["name"],
                     "caused_by": causes, "src": _with_trailing(src, *h["src"])}
                )

        # references: entry = <RID>, its <RTL>, and the spacing after
        groups = [g for g in scan_groups(src)[0] if not g.in_note]
        rtl_end = {}
        for ref in sec.root.iter("REF"):
            prev = None
            for child in ref.children:
                if getattr(child, "name", None) == "RID":
                    prev = child
                elif getattr(child, "name", None) == "RTL" and prev is not None:
                    rtl_end[prev.src_start] = child.src_end
                    prev = None
        orphan_refs: dict[str, dict] = {}
        for r in manifest.get("references", []):
            if inside(*r["src"]):
                continue
            causes = orphaned(r.get("uses", []))
            if causes is None:
                continue
            start = r["src"][0]
            end = rtl_end.get(start, r["src"][1])
            act = {"kind": "reference", "id": r["rid"], "name": r["rid"], "caused_by": causes}
            enc = [g for g in groups if g.src_start < start and end <= g.src_end]
            if enc:
                inner = min(enc, key=lambda g: g.src_end - g.src_start)
                blocked.append({**act, "src": [start, end], "in_bracket": inner.gid})
            else:
                orphan_refs[r["rid"]] = {**act, "src": _with_trailing(src, start, end)}
        for o in manifest.get("reference_orgs", []):
            if inside(*o["src"]):
                continue
            if o["rids"] and all(rid in orphan_refs for rid in o["rids"]):
                causes = sorted({c for rid in o["rids"] for c in orphan_refs.pop(rid)["caused_by"]})
                actions.append(
                    {"kind": "reference-org", "id": o["org"], "name": o["org"],
                     "rids": list(o["rids"]), "caused_by": causes,
                     "src": _with_trailing(src, *o["src"])}
                )
        actions.extend(orphan_refs.values())

    dropped = sorted(
        num for num, uses in manifest.get("section_refs", {}).items()
        if spans and orphaned(uses) is not None
    )
    actions.sort(key=lambda a: a["src"][0])
    return {"remove": actions, "blocked": blocked, "section_refs_dropped": dropped}
