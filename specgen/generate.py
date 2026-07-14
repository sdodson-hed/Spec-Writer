"""Generator: apply an answer workbook to a master section.

Order of operations:
  1. Resolve bracket decisions (reverse document order, so earlier source
     offsets stay valid while splicing).
  2. Remove tailoring blocks whose every OPT name is marked "remove"
     (spans recomputed on the already-edited source).
  3. Verify: re-parse, byte round-trip, well-formed XML — before writing.

Outputs: the tailored .sec, a redline log (every change, machine-readable),
and an unresolved-decisions report for engineer review.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import secfile
from .answers import PLURAL_KEY
from .scan import context_excerpt, duplicate_map, is_plural, scan_groups

_WS_RE = re.compile(r"\s+")


class GenerateError(Exception):
    pass


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
) -> dict:
    master = Path(master)
    src = secfile.parse(master).source
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

        if not ans or (low == "keep" and g.kind != "optional"):
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
        else:
            picked = _match_option(g.options, ans) if g.kind == "choice" else None
            if picked is not None:
                after = "".join(
                    src[g.options[i].src_start : g.options[i].src_end] for i in picked
                )
                action = f"chose option {[i + 1 for i in picked]}"
            else:
                after = ans  # custom / fill-in text (plain text, no markup)
                action = "filled custom value" if g.kind == "blank" else "custom text"
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
        tmp.unlink(missing_ok=True)

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
        "bracket_chars_remaining": src.count("[") + src.count("]"),
    }

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
        if c["kind"] != "tailoring" and PLURAL_KEY not in c["action"]
    ]
    tai = [c for c in redline if c["kind"] == "tailoring"]
    if plural:
        verb = "kept (plural)" if plural[0]["answer"] == "keep" else "made singular"
        md += [f"_{len(plural)} plural [s] markers {verb} — profile setting._", ""]
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
