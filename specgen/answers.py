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

Answer cell semantics (case-insensitive keywords):
  choice   -> option number ("2"), several numbers ("1,3"), exact option
              text, "delete" (remove the whole group), or custom text
  blank    -> the value to fill in (custom text)
  optional -> "keep" (keep text, drop brackets), "delete", or custom text
  (empty)  -> unresolved (flagged for review), unless the row duplicates an
              answered decision, in which case that answer propagates
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# Special Profile-sheet key: resolves every plural [s] marker in one answer.
PLURAL_KEY = "PLURAL MARKERS [s]"

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_DUP_FONT = Font(color="808080", italic=True)
_KIND_FILL = {
    "choice": PatternFill("solid", fgColor="FFF2CC"),
    "blank": PatternFill("solid", fgColor="D9EAD3"),
    "optional": PatternFill("solid", fgColor="EAD1DC"),
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
"""


def _short(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_workbook(manifest: dict, out_path: Path | str) -> None:
    wb = Workbook()

    # --- Answers sheet ---
    ws = wb.active
    ws.title = "Answers"
    headers = ["ID", "Kind", "Same as", "Location", "Context", "Options", "Hint",
               "Answer", "Notes"]
    ws.append(headers)
    for col, _h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
    for col, w in enumerate([10, 9, 10, 34, 64, 42, 30, 24, 22], 1):
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
        else:
            opts_display = "  |  ".join(
                f"{i}) {_short(o, 55)}" for i, o in enumerate(opts, 1)
            )
        dup = d.get("duplicate_of") or ""
        ws.append(
            [
                d["id"],
                d["kind"],
                f"= {dup}" if dup else "",
                d["location"],
                _short(d["context"]),
                opts_display,
                d.get("hint", ""),
                "",
                "",
            ]
        )
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
        if d["kind"] == "optional":
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
    ws.auto_filter.ref = f"A1:I{row - 1}"

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
    n_plural = sum(1 for d in manifest["decisions"] if d.get("plural"))
    if n_plural:
        ps.append([PLURAL_KEY, n_plural, "", ""])
        action_dv.add(ps.cell(row=prow, column=4))
    ps.freeze_panes = "A2"

    # --- ReadMe sheet ---
    rs = wb.create_sheet("ReadMe")
    rs.column_dimensions["A"].width = 100
    for i, line in enumerate(README.strip().splitlines(), 1):
        rs.cell(row=i, column=1, value=line)

    wb.save(str(out_path))


def read_workbook(path: Path | str) -> tuple[dict[str, str], dict[str, dict]]:
    """Return (profile, answers). answers[id] = {"answer": str, "notes": str}."""
    wb = load_workbook(str(path), data_only=True)
    ws = wb["Answers"]
    head = {str(c.value).strip().lower(): i for i, c in enumerate(ws[1]) if c.value}
    id_i, ans_i = head["id"], head["answer"]
    notes_i = head.get("notes")
    answers: dict[str, dict] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[id_i]:
            continue
        gid = str(row[id_i]).strip()
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
            if action in ("keep", "remove"):
                profile[str(row[key_i]).strip()] = action
    return profile, answers
