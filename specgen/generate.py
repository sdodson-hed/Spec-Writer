"""Generator: apply an answer workbook to a master section.

Order of operations:
  1. Resolve bracket decisions (reverse document order, so earlier source
     offsets stay valid while splicing).
  2. Remove tailoring blocks whose every OPT name is marked "remove"
     (spans recomputed on the already-edited source).
  3. Remove the unchosen <MET>/<ENG> unit elements per the project-level
     SI/IP profile answer (spans recomputed on the already-edited source).
  4. Verify: re-parse, byte round-trip, well-formed XML — before writing.

Outputs: the tailored .sec, a redline log (every change, machine-readable),
and an unresolved-decisions report for engineer review.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import secfile
from .answers import PLURAL_KEY, UNITS_KEY
from .scan import context_excerpt, duplicate_map, is_plural, scan_groups

_WS_RE = re.compile(r"\s+")


class GenerateError(Exception):
    pass


def _strip_revisions(source: str, drop: str, unwrap: str) -> str:
    """Serialize with <drop> elements removed and <unwrap> elements replaced
    by their children. Both are only ever wrapped around balanced spans."""
    sec = secfile.parse_source(source)

    def emit(node) -> str:
        if not isinstance(node, secfile.Element):
            return node.serialize()
        if node.name == drop:
            return ""
        if node.name == unwrap:
            return "".join(emit(c) for c in node.children)
        if node.self_closing:
            return node.open_raw
        inner = "".join(emit(c) for c in node.children)
        return f"{node.open_raw}{inner}{node.close_raw}"

    parts = [n.serialize() for n in sec.prolog]
    parts.append(emit(sec.root))
    parts.extend(n.serialize() for n in sec.epilog)
    return "".join(parts)


def resolve_revisions(source: str) -> str:
    """Accept all changes: drop <DEL> content, keep <ADD> content."""
    return _strip_revisions(source, drop="DEL", unwrap="ADD")


def revert_revisions(source: str) -> str:
    """Reject all changes: keep <DEL> content, drop <ADD> content."""
    return _strip_revisions(source, drop="ADD", unwrap="DEL")


def _rev_wrap(g, src: str, low: str, after: str, picked, office: str) -> str:
    before = src[g.src_start : g.src_end]
    if low == "delete":
        return f"<DEL>{before}</DEL>"
    if low == "keep":
        content = src[g.options[0].src_start : g.options[0].src_end]
        if office:
            content = re.sub(
                r"\[[^][]*\]",
                lambda m: f"<DEL>{m.group(0)}</DEL><ADD>{office}</ADD>",
                content,
                count=1,
            )
        return f"<DEL>[</DEL>{content}<DEL>]</DEL>"
    if picked is not None:
        parts, keep = [], set(picked)
        for i, o in enumerate(g.options):
            body = src[o.src_start : o.src_end]
            if i in keep:
                parts.append(f"<DEL>[</DEL>{body}<DEL>]</DEL>")
            else:
                parts.append(f"<DEL>[{body}]</DEL>")
        # Inter-option gaps are DEL-wrapped so resolve() joins picked bodies
        # exactly like the clean output does. Gaps are whitespace-only here:
        # markup-gap groups are always safe=False and never reach the splicer.
        out, pos = [], g.src_start
        for i, o in enumerate(g.options):
            gap = src[pos : o.src_start - 1]  # up to the '['
            if gap:
                out.append(f"<DEL>{gap}</DEL>")
            out.append(parts[i])
            pos = o.src_end + 1  # past the ']'
        tail = src[pos : g.src_end]
        if tail:
            out.append(f"<DEL>{tail}</DEL>")
        return "".join(out)
    return f"<DEL>{before}</DEL><ADD>{after}</ADD>"  # custom / fill-in


def _match_option(groups_options: list, ans: str) -> list[int] | None:
    """Interpret an answer against a choice group's options.
    Returns list of 0-based option indices, or None if not an option ref."""
    parts = [p.strip() for p in ans.split(",") if p.strip()]
    if parts and all(p.isdigit() for p in parts):
        idx = sorted({int(p) - 1 for p in parts})  # document order, deduped
        if all(0 <= i < len(groups_options) for i in idx):
            return idx
        raise GenerateError(f"option number out of range: {ans!r}")
    # exact (whitespace-normalized) text match against a single option
    norm = _WS_RE.sub(" ", ans).strip().lower()
    matches = [
        i
        for i, o in enumerate(groups_options)
        if _WS_RE.sub(" ", o.text).strip().lower() == norm
    ]
    # also accept the workbook-dropdown variant where "," was shown as " /"
    if not matches and " /" in ans:
        norm2 = norm.replace(" /", ",")
        matches = [
            i
            for i, o in enumerate(groups_options)
            if _WS_RE.sub(" ", o.text).strip().lower() == norm2
        ]
    return matches if matches else None


def generate(
    master: Path | str,
    profile: dict[str, str],
    answers: dict[str, dict],
    out_sec: Path | str,
    revisions: bool = False,
) -> dict:
    master = Path(master)
    src = secfile.parse(master).source
    rev = src
    groups, _stream, _offs = scan_groups(src)
    by_id = {g.gid: g for g in groups}

    unknown = sorted(set(answers) - set(by_id))
    if unknown:
        raise GenerateError(f"answer IDs not in section: {unknown}")

    dups = duplicate_map(groups)
    plural_action = profile.get(PLURAL_KEY, "")

    redline: list[dict] = []
    unresolved: list[dict] = []

    for g in sorted(groups, key=lambda g: -g.src_start):
        if g.in_note:
            continue  # designer-note text is never edited
        entry = answers.get(g.gid, {})
        propagated = ""
        if not entry.get("answer") and g.gid in dups and dups[g.gid] in answers:
            entry = answers[dups[g.gid]]
            propagated = dups[g.gid]
        if not entry.get("answer") and is_plural(g) and plural_action:
            entry = {
                "answer": "keep" if plural_action == "keep" else "delete",
                "notes": "",
            }
            propagated = PLURAL_KEY
        ans = entry.get("answer", "")
        notes = entry.get("notes", "")
        before = src[g.src_start : g.src_end]
        low = ans.lower()
        picked_for_rev = None

        if not ans or (
            low == "keep" and g.kind not in ("optional", "submittal-review")
        ):
            unresolved.append(
                {
                    "id": g.gid,
                    "kind": g.kind,
                    "options": [o.text for o in g.options],
                }
            )
            continue

        if not g.safe:
            unresolved.append(
                {
                    "id": g.gid,
                    "kind": g.kind,
                    "options": [o.text for o in g.options],
                    "note": "answer given but group spans markup unevenly; "
                    "needs manual edit in SI Editor",
                }
            )
            continue

        if low == "delete":
            after = ""
            action = "deleted"
        elif low == "keep":  # optional: keep text, drop brackets
            after = src[g.options[0].src_start : g.options[0].src_end]
            action = "kept (brackets removed)"
            if g.kind == "submittal-review" and entry.get("office"):
                filled = re.sub(
                    r"\[[^][]*\]", lambda _m: entry["office"], after, count=1
                )
                if filled != after:  # only claim the fill if a blank existed
                    after = filled
                    action = f"kept; reviewer office = {entry['office']}"
        else:
            picked = _match_option(g.options, ans) if g.kind == "choice" else None
            if picked is not None:
                after = "".join(
                    src[g.options[i].src_start : g.options[i].src_end] for i in picked
                )
                action = f"chose option {[i + 1 for i in picked]}"
                picked_for_rev = picked
            else:
                after = ans  # custom / fill-in text (plain text, no markup)
                action = "filled custom value" if g.kind == "blank" else "custom text"
        if revisions:
            office = (
                entry.get("office", "") if g.kind == "submittal-review" else ""
            )
            wrapped = _rev_wrap(g, rev, low, after, picked_for_rev, office)
            rev = rev[: g.src_start] + wrapped + rev[g.src_end :]
        src = src[: g.src_start] + after + src[g.src_end :]
        if propagated:
            action += f" (propagated from {propagated})"
        redline.append(
            {
                "id": g.gid,
                "kind": g.kind,
                "action": action,
                "answer": ans,
                "notes": notes,
                "before": before,
                "after": after,
            }
        )

    # --- tailoring removal (on the edited source) ---
    removed_tai = 0
    if any(v == "remove" for v in profile.values()):

        def removable(opt_attr: str) -> bool:
            names = [n.strip() for n in opt_attr.split(",")]
            return all(profile.get(n) == "remove" for n in names)

        tmp = master.parent / (master.name + ".gen.tmp")
        while True:
            tmp.write_bytes(src.encode(secfile.ENCODING))
            tree = secfile.parse(tmp)
            spans = [
                (t.src_start, t.src_end, t.attrs.get("OPT", ""))
                for t in tree.root.iter("TAI")
                if removable(t.attrs.get("OPT", ""))
            ]
            # outermost only; nested removable blocks go with their parent
            spans = [
                s
                for s in spans
                if not any(o[0] < s[0] and s[1] <= o[1] for o in spans if o != s)
            ]
            if not spans:
                break
            for start, end, opt in sorted(spans, key=lambda s: -s[0]):
                redline.append(
                    {
                        "id": f"TAI@{start}",
                        "kind": "tailoring",
                        "action": "removed block",
                        "answer": f"remove {opt}",
                        "notes": "",
                        "before": src[start:end][:200],
                        "after": "",
                    }
                )
                src = src[:start] + src[end:]
                removed_tai += 1
            if revisions:
                rtmp = master.parent / (master.name + ".rev.tmp")
                rtmp.write_bytes(rev.encode(secfile.ENCODING))
                rtree = secfile.parse(rtmp)
                rspans = [
                    (t.src_start, t.src_end)
                    for t in rtree.root.iter("TAI")
                    if removable(t.attrs.get("OPT", ""))
                    and not any(a.name == "DEL" for a in t.ancestors())
                ]
                rspans = [
                    s for s in rspans
                    if not any(o[0] < s[0] and s[1] <= o[1] for o in rspans if o != s)
                ]
                for start, end in sorted(rspans, key=lambda s: -s[0]):
                    rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
                rtmp.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)

    # --- unit-system resolution (on the edited source) ---
    units = profile.get(UNITS_KEY, "")
    removed_units = 0
    if units in ("si", "ip"):
        drop = "ENG" if units == "si" else "MET"
        tmp = master.parent / (master.name + ".gen.tmp")
        tmp.write_bytes(src.encode(secfile.ENCODING))
        tree = secfile.parse(tmp)
        spans = sorted(
            (
                (el.src_start, el.src_end)
                for el in tree.root.iter(drop)
                # designer-note text is never edited
                if not any(a.name == "NTE" for a in el.ancestors())
            ),
            key=lambda s: -s[0],
        )
        for start, end in spans:
            src = src[:start] + src[end:]
            removed_units += 1
        if revisions:
            rtmp = master.parent / (master.name + ".rev.tmp")
            rtmp.write_bytes(rev.encode(secfile.ENCODING))
            rtree = secfile.parse(rtmp)
            rspans = sorted(
                (
                    (el.src_start, el.src_end)
                    for el in rtree.root.iter(drop)
                    if not any(a.name == "NTE" for a in el.ancestors())
                    and not any(a.name == "DEL" for a in el.ancestors())
                ),
                key=lambda s: -s[0],
            )
            for start, end in rspans:
                rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
            rtmp.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
        if removed_units:
            redline.append(
                {
                    "id": "UNITS",
                    "kind": "units",
                    "action": f"kept {'SI' if units == 'si' else 'IP'} units; "
                    f"removed {removed_units} <{drop}> elements",
                    "answer": units,
                    "notes": "",
                    "before": "",
                    "after": "",
                }
            )

    # --- rescan the OUTPUT: the unresolved report is defined by what
    # actually remains bracketed, so choices that carried nested brackets
    # (e.g. picking a paragraph that itself contains [copper][aluminum])
    # surface as new open decisions instead of slipping through ---
    def _sig(opts: list[str]) -> tuple:
        return tuple(_WS_RE.sub(" ", o).strip() for o in opts)

    pool: dict[tuple, list[dict]] = {}
    for u in unresolved:
        pool.setdefault(_sig(u["options"]), []).append(u)
    final_groups, final_stream, _ = scan_groups(src)
    unresolved = []
    for fg in final_groups:
        if fg.in_note:
            continue
        opts = [o.text for o in fg.options]
        bucket = pool.get(_sig(opts))
        origin = bucket.pop(0) if bucket else None
        entry = {
            "id": origin["id"] if origin else f"OPEN@{fg.src_start}",
            "kind": fg.kind,
            "options": opts,
            "context": context_excerpt(final_stream, fg.char_start, fg.char_end),
        }
        if origin and origin.get("note"):
            entry["note"] = origin["note"]
        if origin is None:
            entry["note"] = (
                "not one of the original decision IDs — it was nested inside "
                "a resolved choice or reshaped by neighboring edits; answer "
                "in a follow-up pass or in SI Editor"
            )
        unresolved.append(entry)

    # --- verify before writing ---
    out_sec = Path(out_sec)
    out_sec.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_sec.with_suffix(out_sec.suffix + ".tmp")
    tmp.write_bytes(src.encode(secfile.ENCODING))
    parsed = secfile.parse(tmp)
    if not parsed.roundtrips():
        raise GenerateError("internal error: output does not round-trip")
    ET.parse(tmp)  # raises if not well-formed
    tmp.replace(out_sec)

    summary = {
        "master": str(master),
        "output": str(out_sec),
        "decisions_total": len(groups),
        "resolved": len([r for r in redline if r["kind"] != "tailoring"]),
        "unresolved": len(unresolved),
        "tailoring_blocks_removed": removed_tai,
        "units_removed": removed_units,
        "bracket_chars_remaining": src.count("[") + src.count("]"),
    }

    if revisions:
        original = secfile.parse(master).source
        if resolve_revisions(rev) != src:
            raise GenerateError("revisions do not resolve to the clean output")
        if revert_revisions(rev) != original:
            raise GenerateError("revisions do not revert to the master")
        rev_path = out_sec.with_suffix(".revisions.sec")
        rev_path.write_bytes(rev.encode(secfile.ENCODING))
        ET.parse(rev_path)  # well-formed
        summary["revisions_output"] = str(rev_path)

    out_sec.with_suffix(".redline.json").write_text(
        json.dumps({"summary": summary, "changes": redline}, indent=2),
        encoding="utf-8",
    )

    def _plain(raw: str, limit: int = 300) -> str:
        txt = _WS_RE.sub(" ", re.sub(r"<[^>]+>", " ", raw)).strip()
        return (txt[: limit - 1] + "…") if len(txt) > limit else (txt or "(nothing)")

    md = [
        f"# Redline — {out_sec.name}",
        "",
        f"{summary['resolved']} decisions applied, "
        f"{summary['tailoring_blocks_removed']} tailoring blocks removed, "
        f"{summary['unresolved']} left for engineer review.",
        "",
    ]
    plural = [
        c for c in redline if PLURAL_KEY in c["action"] and c["kind"] != "tailoring"
    ]
    brk = [
        c
        for c in redline
        if c["kind"] not in ("tailoring", "units") and PLURAL_KEY not in c["action"]
    ]
    tai = [c for c in redline if c["kind"] == "tailoring"]
    if plural:
        verb = "kept (plural)" if plural[0]["answer"] == "keep" else "made singular"
        md += [f"_{len(plural)} plural [s] markers {verb} — profile setting._", ""]
    units_c = [c for c in redline if c["kind"] == "units"]
    if units_c:
        md += [f"_{units_c[0]['action']}._", ""]
    for c in sorted(brk, key=lambda c: c["id"]):
        md += [
            f"## {c['id']} — {c['action']}",
            "",
            f"- **Was:** {_plain(c['before'])}",
            f"- **Now:** {_plain(c['after'])}",
        ]
        if c.get("notes"):
            md.append(f"- Note: {c['notes']}")
        md.append("")
    if tai:
        md += ["## Tailoring blocks removed", ""]
        for c in tai:
            md.append(f"- {c['answer']}: {_plain(c['before'], 120)}")
    out_sec.with_suffix(".redline.md").write_text("\n".join(md), encoding="utf-8")
    unresolved_md = [
        f"# Unresolved decisions — {out_sec.name}",
        "",
        f"{len(unresolved)} decision(s) need engineer input:",
        "",
    ]
    for u in unresolved:
        opts = " | ".join(u["options"]) if u["kind"] != "blank" else "(fill in)"
        unresolved_md += [f"## {u['id']} · {u['kind']}", f"- Options: {opts}",
                          f"- Context: {u['context']}"]
        if u.get("note"):
            unresolved_md.append(f"- **Note:** {u['note']}")
        unresolved_md.append("")
    out_sec.with_suffix(".unresolved.md").write_text(
        "\n".join(unresolved_md), encoding="utf-8"
    )
    return summary
