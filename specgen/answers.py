"""Answer workbook: the engineer-facing interface to a section's decisions.

`write_workbook` turns a manifest into an .xlsx with:
  - "Answers" sheet: one row per UNIQUE decision. Plural markers ([s]) are
    excluded (answered once on the Profile sheet); duplicate decisions are
    listed but auto-follow the first instance unless answered explicitly.
  - "Profile" sheet: tailoring options + project-wide settings (keep/remove)
  - "ReadMe" sheet: how to fill it in

`read_workbook` loads the answers back (header-based, robust to column
reordering):
  - profile: {option or setting name: "keep" | "remove"}
  - answers: {decision id: {"answer": str, "notes": str}}

`read_answers_json` additionally passes through manual text edits (keys
prefixed ``ME@``, as exported by the HTML decision page) with their
{"start", "end", "before", "after", "notes"} fields. The .xlsx workbook path
has no manual-edit support: direct text editing is JSON/HTML only.

Answer cell semantics (case-insensitive keywords):
  choice   -> option number ("2"), several numbers ("1,3"), exact option
              text, "delete" (remove the whole group), or custom text
  blank    -> the value to fill in (custom text)
  optional -> "keep" (keep text, drop brackets), "delete", or custom text
  (empty)  -> unresolved (flagged for review), unless the row duplicates an
              answered decision, in which case that answer propagates
"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# Special Profile-sheet key: resolves every plural [s] marker in one answer.
PLURAL_KEY = "PLURAL MARKERS [s]"

# Special Profile-sheet key: SI vs inch-pound units — one answer resolves
# every <MET>/<ENG> pair in the section.
UNITS_KEY = "UNITS OF MEASURE (SI/IP)"

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_DUP_FONT = Font(color="808080", italic=True)
_KIND_FILL = {
    "choice": PatternFill("solid", fgColor="FFF2CC"),
    "blank": PatternFill("solid", fgColor="D9EAD3"),
    "optional": PatternFill("solid", fgColor="EAD1DC"),
    "submittal-review": PatternFill("solid", fgColor="DDEBF7"),
}

README = """HOW TO FILL IN THIS WORKBOOK

Answers sheet - one row per decision in the spec section. The Context
column shows the surrounding sentence with the decision marked >>like this<<.

  choice rows   : pick an option from the dropdown, or type the option
                  number (e.g. 2), several numbers to keep more than one
                  item (e.g. 1,3), the word delete to remove the whole
                  thing, or type your own replacement text.
  blank rows    : type the value that goes in the blank (e.g. 198).
  optional rows : keep (keep the text), delete (remove it), or type
                  replacement text.

  Rows marked "= BRK-xxxx" are the same decision appearing again later in
  the section; they automatically follow the answer you give the first
  instance. Only fill them if this instance should differ.

  Leave a row empty if you cannot decide - it will be flagged for review
  and left bracketed in the draft, never silently defaulted.

Profile sheet - project-wide settings:
  Tailoring options : keep or remove all blocks for that option
                      (e.g. remove ARMY and NAVY on an Air Force project).
  PLURAL MARKERS [s]: keep = plural wording (multiple units, "Chillers"),
                      remove = singular ("Chiller"). One answer covers
                      every [s] in the section.
  UNITS OF MEASURE (SI/IP): SI = keep metric values, IP = keep inch-pound
                      values. One answer resolves every <MET>/<ENG> pair
                      in the section.

Subsections sheet - one row per subsection (article/paragraph):
  remove deletes the whole subsection, its children and every decision
  inside it; keep or blank keeps it (blank is logged as "kept by default").
  Rows with "Governed by" are the same decision as that bracket row on the
  Answers sheet: answering either one is enough; conflicting answers are
  flagged for review and neither is applied.
"""


def _short(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_workbook(manifest: dict, out_path: Path | str) -> None:
    wb = Workbook()

    # --- Answers sheet ---
    ws = wb.active
    ws.title = "Answers"
    # Anchor is the key answers are recorded against (survives UFGS releases);
    # ID is positional and for display only
    headers = ["ID", "Kind", "Same as", "Location", "Context", "Options", "Hint",
               "Answer", "Notes", "Anchor"]
    ws.append(headers)
    for col, _h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
    for col, w in enumerate([10, 9, 10, 34, 64, 42, 30, 24, 22, 40], 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    keep_del = DataValidation(
        type="list", formula1='"keep,delete"', allow_blank=True, showErrorMessage=False
    )
    ws.add_data_validation(keep_del)

    row = 2
    for d in manifest["decisions"]:
        if d["in_note"] or d.get("plural"):
            continue
        opts = d["options"]
        if d["kind"] == "blank":
            opts_display = "(fill in a value)"
        elif d["kind"] == "optional":
            opts_display = f"optional text: {_short(opts[0], 90)}"
        elif d["kind"] == "submittal-review":
            opts_display = (
                "keep = Government-reviewed (G); in the HTML page you can also "
                "set the reviewer office; delete = for-information-only"
            )
        else:
            opts_display = "  |  ".join(
                f"{i}) {_short(o, 55)}" for i, o in enumerate(opts, 1)
            )
            if d.get("multi") or d.get("additive"):
                opts_display = "SELECT ALL THAT APPLY (e.g. 1,3): " + opts_display
        dup = d.get("duplicate_of") or ""
        ws.append(
            [
                d["id"],
                d["kind"],
                f"same as {dup}" if dup else "",
                d["location"],
                _short(d["context"]),
                opts_display,
                d.get("hint", ""),
                "",
                "",
                d.get("anchor", ""),
            ]
        )
        ws.cell(row=row, column=10).font = _DUP_FONT
        for col in range(1, 8):
            ws.cell(row=row, column=col).alignment = Alignment(
                wrap_text=True, vertical="top"
            )
        ws.cell(row=row, column=2).fill = _KIND_FILL[d["kind"]]
        if dup:
            for col in (1, 3, 5, 6):
                ws.cell(row=row, column=col).font = _DUP_FONT
        answer_cell = ws.cell(row=row, column=8)
        answer_cell.alignment = Alignment(wrap_text=True, vertical="top")
        if d["kind"] in ("optional", "submittal-review"):
            keep_del.add(answer_cell)
        elif d["kind"] == "choice":
            formula = '"' + ",".join(
                o.replace(",", " /").replace('"', "'")[:80] for o in opts
            ) + ',delete"'
            if len(formula) <= 255:
                dv = DataValidation(
                    type="list",
                    formula1=formula,
                    allow_blank=True,
                    showErrorMessage=False,
                )
                ws.add_data_validation(dv)
                dv.add(answer_cell)
        row += 1
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:J{row - 1}"

    # --- Profile sheet ---
    ps = wb.create_sheet("Profile")
    ps.append(["Setting", "Blocks", "Chars", "Action"])
    for col in range(1, 5):
        c = ps.cell(row=1, column=col)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
    ps.column_dimensions["A"].width = 36
    ps.column_dimensions["D"].width = 14
    action_dv = DataValidation(
        type="list", formula1='"keep,remove"', allow_blank=True, showErrorMessage=False
    )
    ps.add_data_validation(action_dv)
    prow = 2
    for opt, v in manifest["tailoring_options"].items():
        ps.append([opt, v["blocks"], v["chars"], ""])
        action_dv.add(ps.cell(row=prow, column=4))
        prow += 1
    units_dv = DataValidation(
        type="list", formula1='"SI,IP"', allow_blank=True, showErrorMessage=False
    )
    ps.add_data_validation(units_dv)
    if manifest["counts"].get("unit_pairs"):
        ps.append([UNITS_KEY, manifest["counts"]["unit_pairs"], "", ""])
        units_dv.add(ps.cell(row=prow, column=4))
        prow += 1
    n_plural = sum(1 for d in manifest["decisions"] if d.get("plural"))
    if n_plural:
        ps.append([PLURAL_KEY, n_plural, "", ""])
        action_dv.add(ps.cell(row=prow, column=4))
    ps.freeze_panes = "A2"

    # --- Subsections sheet: keep/remove per <SPT>; blank = kept by default ---
    ss = wb.create_sheet("Subsections")
    ss.append(["ID", "Number", "Title", "Governed by", "Action", "Anchor"])
    for col in range(1, 7):
        c = ss.cell(row=1, column=col)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
    for col, w in zip("ABCDEF", [10, 10, 60, 12, 12, 50]):
        ss.column_dimensions[col].width = w
    spt_dv = DataValidation(
        type="list", formula1='"keep,remove"', allow_blank=True, showErrorMessage=False
    )
    ss.add_data_validation(spt_dv)
    for i, s in enumerate(manifest.get("subsections", []), 2):
        ss.append(
            [s["id"], s["num"], "  " * (s["depth"] - 1) + s["title"],
             s.get("governed_by") or "", "", s["anchor"]]
        )
        spt_dv.add(ss.cell(row=i, column=5))
        ss.cell(row=i, column=6).font = _DUP_FONT
        if s.get("governed_by"):
            ss.cell(row=i, column=4).font = _DUP_FONT
    ss.freeze_panes = "A2"

    # --- ReadMe sheet ---
    rs = wb.create_sheet("ReadMe")
    rs.column_dimensions["A"].width = 100
    for i, line in enumerate(README.strip().splitlines(), 1):
        rs.cell(row=i, column=1, value=line)

    # --- Meta sheet: ties the workbook to the exact scan it was built from
    # (generate refuses answers recorded against a different scan) ---
    ms = wb.create_sheet("Meta")
    ms.column_dimensions["A"].width = 22
    ms.column_dimensions["B"].width = 44
    ms.append(["Section", manifest.get("section", "")])
    ms.append(["Fingerprint", manifest.get("fingerprint", "")])
    ms.append(["Do not edit this sheet.", ""])

    wb.save(str(out_path))


def read_answers_json(
    path: Path | str,
) -> tuple[dict[str, str], dict[str, dict], str | None]:
    """Read an answers JSON (as exported by the HTML decision page or written
    by the platform). Same return shape as read_workbook: (profile, answers,
    fingerprint-or-None)."""
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fingerprint = data.get("fingerprint")
    fingerprint = str(fingerprint).strip() if fingerprint else None
    profile = {
        k: str(v).strip().lower()
        for k, v in (data.get("profile") or {}).items()
        if str(v).strip().lower() in ("keep", "remove", "si", "ip")
    }
    answers: dict[str, dict] = {}
    for gid, v in (data.get("answers") or {}).items():
        key = str(gid).strip()
        if key.startswith("ME@"):
            if not isinstance(v, dict):
                continue  # malformed manual edit: skip
            try:
                start, end = int(v["start"]), int(v["end"])
            except (KeyError, TypeError, ValueError):
                continue  # non-int-able start/end: skip
            before, after = v.get("before"), v.get("after")
            if not isinstance(before, str) or not isinstance(after, str):
                continue  # missing/non-string before/after: skip
            rec = {"start": start, "end": end, "before": before, "after": after}
            notes = v.get("notes")
            rec["notes"] = notes.strip() if isinstance(notes, str) else ""
            answers[key] = rec
            continue
        if isinstance(v, dict):
            ans = str(v.get("answer", "")).strip()
            notes = str(v.get("notes", "")).strip()
        else:
            ans, notes = str(v).strip(), ""
        office = str(v.get("office", "")).strip() if isinstance(v, dict) else ""
        if ans or notes:
            rec = {"answer": ans, "notes": notes}
            if office:
                rec["office"] = office
            if isinstance(v, dict):
                # display fields from an anchor-keyed (v2) export: the BRK id
                # and option texts the answer was given against, shown in the
                # orphan report when the anchor no longer resolves
                if v.get("id"):
                    rec["id"] = str(v["id"]).strip()
                if isinstance(v.get("options"), list):
                    rec["options"] = [str(o) for o in v["options"]]
                # subsection answers: outline number and title, for display
                for k in ("num", "title"):
                    if isinstance(v.get(k), str) and v[k].strip():
                        rec[k] = v[k].strip()
            answers[key] = rec
    return profile, answers, fingerprint


def resolve_answer_keys(
    answers: dict[str, dict],
    groups: list,
    anchors: dict[str, str],
    fingerprint: str | None,
    *,
    force_stale: bool = False,
    strict: bool = False,
    subsections: list[dict] | None = None,
) -> tuple[dict[str, dict], list[dict], str]:
    """Map an answers dict onto THIS master's BRK and SPT ids.

    Returns (answers keyed by gid, orphans/problems, fingerprint status).
      - ME@ manual edits pass through unchanged.
      - Anchor keys (contain "#") resolve to the group with that anchor. An
        anchor with no match is an orphan: reported in .unresolved.md with
        the option text it was answered against, applied to nothing.
      - BRK keys are positional. They load only when the file is unstamped
        (legacy behavior) or its fingerprint matches the current or legacy
        scan; otherwise GenerateError unless force_stale.
      - Subsection keys (#spt: anchors, matched against `subsections` from
        the manifest) come back keyed SPT-NNNN with answer "keep" or
        "remove"; any other value is a problem entry, never guessed. A
        positional SPT-NNNN key is an error: no fingerprint covers
        subsections. A subsection governed by a bracket (governed_by) is
        the same decision: its answer becomes that bracket's answer
        (remove -> delete), and a disagreeing bracket answer leaves the
        bracket unanswered with a "conflict" note.
      - strict: any orphan or problem, or a stamped fingerprint matching
        neither scan, raises.
    """
    from .errors import GenerateError
    from .scan import legacy_scan_fingerprint, scan_fingerprint

    positional_spt = [k for k in answers if re.match(r"SPT-\d+$", k.strip())]
    if positional_spt:
        raise GenerateError(
            f"subsection answers must be keyed by anchor, not by position: "
            f"{positional_spt[:5]}"
        )
    expected = scan_fingerprint(groups)
    legacy = legacy_scan_fingerprint(groups)
    fp_ok = fingerprint in (expected, legacy)
    by_anchor = {a: gid for gid, a in anchors.items()}
    by_spt_anchor = {s["anchor"]: s for s in subsections or []}
    brk_keys = [k for k in answers if not k.startswith("ME@") and "#" not in k]

    stale_msg = (
        f"answers were recorded against a different scan of this section "
        f"(answers fingerprint {fingerprint}, master scan {expected}) — the "
        f"master or the scanner has changed since the answer file was made. "
        f"Re-open the decision page / workbook built from THIS master and "
        f"re-export, or pass --force to apply anyway"
    )
    if fingerprint and not fp_ok:
        if strict or (brk_keys and not force_stale):
            raise GenerateError(stale_msg)

    out: dict[str, dict] = {}
    spt_out: dict[str, dict] = {}
    source_key: dict[str, str] = {}
    orphans: list[dict] = []

    def _label(rec: dict) -> list[str]:
        label = " ".join(p for p in (rec.get("num"), rec.get("title")) if p)
        return [label] if label else []

    for key, rec in answers.items():
        if key.startswith("ME@"):
            out[key] = rec
            continue
        if "#spt:" in key:
            s = by_spt_anchor.get(key)
            if s is None:
                orphans.append(
                    {
                        "id": key,
                        "kind": "orphan",
                        "options": _label(rec),
                        "answer": rec.get("answer", ""),
                        "note": f"master changed: decision not found "
                                f"(was {rec.get('id') or '?'}); answer was "
                                f"{rec.get('answer', '')!r}",
                    }
                )
                continue
            sid = s["id"]
            if sid in source_key:
                raise GenerateError(f"two answers for {sid}: {source_key[sid]}, {key}")
            source_key[sid] = key
            value = str(rec.get("answer", "")).strip().lower()
            if value not in ("keep", "remove"):
                orphans.append(
                    {
                        "id": sid,
                        "kind": "subsection",
                        "options": [f"{s['num']} {s['title']}"],
                        "note": f"subsection answer must be keep or remove "
                                f"(got {rec.get('answer', '')!r}); not applied",
                    }
                )
                continue
            spt_out[sid] = {**rec, "answer": value}
            continue
        if "#" in key:
            gid = by_anchor.get(key)
            if gid is None:
                was = rec.get("id") or "?"
                orphans.append(
                    {
                        "id": key,
                        "kind": "orphan",
                        "options": list(rec.get("options") or []),
                        "answer": rec.get("answer", ""),
                        "note": f"master changed: decision not found (was {was}); "
                                f"answer was {rec.get('answer', '')!r}",
                    }
                )
                continue
        else:
            gid = key
        if gid in source_key:
            raise GenerateError(
                f"two answers for {gid}: {source_key[gid]}, {key}"
            )
        source_key[gid] = key
        out[gid] = rec

    # Governed subsections (plan D1): "[<SPT>...</SPT>]" is ONE decision. The
    # subsection answer becomes the bracket answer; a disagreeing bracket
    # answer leaves the bracket unanswered (never guessed) with a note.
    spts = {s["id"]: s for s in subsections or []}
    for sid, rec in spt_out.items():
        brk = spts[sid].get("governed_by")
        if not brk:
            out[sid] = rec
            continue
        wanted = "delete" if rec["answer"] == "remove" else "keep"
        current = str(out.get(brk, {}).get("answer", "")).strip()
        if not current:
            out[brk] = {"answer": wanted, "notes": rec.get("notes", ""), "via": sid}
        elif current.lower() != wanted:
            out[brk] = {
                **out[brk],
                "answer": "",
                "conflict": f"conflicting answers: {sid} "
                            f"({spts[sid]['num']} {spts[sid]['title']}) says "
                            f"{rec['answer']}, {brk} says {current!r}; neither "
                            f"applied",
            }

    if strict and orphans:
        raise GenerateError(
            f"{len(orphans)} answer(s) not applied (master changed, or an "
            f"invalid value): {[o['id'] for o in orphans][:5]}"
        )

    if not brk_keys and len(source_key) + len(orphans) > 0:
        status = "anchors"
    elif not fingerprint:
        status = "unstamped"
    elif fingerprint == expected:
        status = "match"
    elif fingerprint == legacy:
        status = "match (legacy)"
    else:
        status = "MISMATCH (forced)"
    return out, orphans, status


def read_answers(
    path: Path | str,
) -> tuple[dict[str, str], dict[str, dict], str | None]:
    """Dispatch on file type: .json or .xlsx."""
    if str(path).lower().endswith(".json"):
        return read_answers_json(path)
    return read_workbook(path)


def read_workbook(
    path: Path | str,
) -> tuple[dict[str, str], dict[str, dict], str | None]:
    """Return (profile, answers, fingerprint-or-None).
    answers[id] = {"answer": str, "notes": str}."""
    wb = load_workbook(str(path), data_only=True)
    fingerprint: str | None = None
    if "Meta" in wb.sheetnames:
        for row in wb["Meta"].iter_rows(min_row=1, values_only=True):
            if row and str(row[0]).strip().lower() == "fingerprint":
                v = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                fingerprint = v or None
    ws = wb["Answers"]
    head = {str(c.value).strip().lower(): i for i, c in enumerate(ws[1]) if c.value}
    id_i, ans_i = head["id"], head["answer"]
    notes_i = head.get("notes")
    anc_i = head.get("anchor")  # absent in workbooks made before anchors
    answers: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[id_i]:
            continue
        gid = str(row[id_i]).strip()
        if anc_i is not None and len(row) > anc_i and row[anc_i]:
            gid = str(row[anc_i]).strip()
        ans = "" if row[ans_i] is None else str(row[ans_i]).strip()
        notes = ""
        if notes_i is not None and len(row) > notes_i and row[notes_i] is not None:
            notes = str(row[notes_i]).strip()
        if ans or notes:
            answers[gid] = {"answer": ans, "notes": notes}
    profile: dict[str, str] = {}
    if "Profile" in wb.sheetnames:
        ps = wb["Profile"]
        phead = {str(c.value).strip().lower(): i for i, c in enumerate(ps[1]) if c.value}
        key_i = phead.get("setting", phead.get("tailoring option", 0))
        act_i = phead.get("action", 3)
        for row in ps.iter_rows(min_row=2, values_only=True):
            if not row or not row[key_i]:
                continue
            action = "" if len(row) <= act_i or row[act_i] is None else str(row[act_i]).strip().lower()
            if action in ("keep", "remove", "si", "ip"):
                profile[str(row[key_i]).strip()] = action
    if "Subsections" in wb.sheetnames:  # absent in workbooks made before step 3
        ss = wb["Subsections"]
        shead = {str(c.value).strip().lower(): i for i, c in enumerate(ss[1]) if c.value}
        sid_i, act_i, anc_i = shead["id"], shead["action"], shead.get("anchor")
        for row in ss.iter_rows(min_row=2, values_only=True):
            if not row or not row[sid_i] or len(row) <= act_i or row[act_i] is None:
                continue
            action = str(row[act_i]).strip()
            if not action:
                continue
            # any value is passed on; resolve_answer_keys rejects anything
            # but keep/remove into the unresolved report
            key = str(row[anc_i]).strip() if anc_i is not None and row[anc_i] else str(row[sid_i]).strip()
            answers[key] = {"answer": action, "notes": ""}
    return profile, answers, fingerprint
