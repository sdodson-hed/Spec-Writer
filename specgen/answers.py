"""Answer workbook: the engineer-facing interface to a section's decisions.

`write_workbook` turns a manifest into an .xlsx with:
  - "Answers" sheet: one row per bracket decision, dropdowns where practical
  - "Profile" sheet: tailoring options with keep/remove dropdowns
  - "ReadMe" sheet: how to fill it in

`read_workbook` loads the answers back:
  - profile: {tailoring option name: "keep" | "remove"}
  - answers: {decision id: raw cell string}

Answer cell semantics (case-insensitive keywords):
  choice   -> option number ("2"), several numbers ("1,3"), exact option
              text, "delete" (remove the whole group), or custom text
  blank    -> the value to fill in (custom text)
  optional -> "keep" (keep text, drop brackets), "delete", or custom text
  (empty)  -> decision left unresolved; reported for engineer review
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_KIND_FILL = {
    "choice": PatternFill("solid", fgColor="FFF2CC"),
    "blank": PatternFill("solid", fgColor="D9EAD3"),
    "optional": PatternFill("solid", fgColor="EAD1DC"),
}

README = """HOW TO FILL IN THIS WORKBOOK

Answers sheet - one row per decision in the spec section:
  choice rows   : pick an option from the dropdown, or type the option
                  number (e.g. 2), several numbers to keep more than one
                  item (e.g. 1,3), the word delete to remove the whole
                  thing, or type your own replacement text.
  blank rows    : type the value that goes in the blank (e.g. 198).
  optional rows : keep (keep the text), delete (remove it), or type
                  replacement text.
  Leave a row empty if you cannot decide - it will be flagged for review
  and left bracketed in the draft, never silently defaulted.

Profile sheet - project-wide tailoring options:
  keep    : the blocks for this option stay in the section.
  remove  : all blocks for this option are removed (e.g. remove ARMY and
            NAVY on an Air Force project).

The Context column shows the sentence around each decision. The Location
column shows the paragraph. Notes are for your own comments; they are
copied into the audit log.
"""


def _short(text: str, limit: int = 180) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def write_workbook(manifest: dict, out_path: Path | str) -> None:
    wb = Workbook()

    # --- Answers sheet ---
    ws = wb.active
    ws.title = "Answers"
    headers = ["ID", "Kind", "Location", "Context", "Options", "Answer", "Notes"]
    ws.append(headers)
    for col, _h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
    widths = [10, 9, 42, 60, 46, 26, 24]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    keep_del = DataValidation(
        type="list", formula1='"keep,delete"', allow_blank=True, showErrorMessage=False
    )
    ws.add_data_validation(keep_del)

    row = 2
    for d in manifest["decisions"]:
        if d["in_note"]:
            continue  # notes drop out on publish; no decision needed
        opts = d["options"]
        opts_display = " | ".join(
            f"{i}) {_short(o, 60)}" for i, o in enumerate(opts, 1)
        )
        if d["kind"] == "blank":
            opts_display = "(fill in a value)"
        elif d["kind"] == "optional":
            opts_display = f"optional: {_short(opts[0], 80)}"
        ws.append(
            [d["id"], d["kind"], d["location"], _short(d["context"]), opts_display, "", ""]
        )
        for col in (1, 2, 3, 4, 5):
            ws.cell(row=row, column=col).alignment = Alignment(
                wrap_text=True, vertical="top"
            )
        ws.cell(row=row, column=2).fill = _KIND_FILL[d["kind"]]
        answer_cell = ws.cell(row=row, column=6)
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

    # --- Profile sheet ---
    ps = wb.create_sheet("Profile")
    ps.append(["Tailoring Option", "Blocks", "Chars", "Action"])
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
    answers: dict[str, dict] = {}
    ws = wb["Answers"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue
        gid = str(row[0]).strip()
        ans = "" if row[5] is None else str(row[5]).strip()
        notes = "" if len(row) < 7 or row[6] is None else str(row[6]).strip()
        if ans or notes:
            answers[gid] = {"answer": ans, "notes": notes}
    profile: dict[str, str] = {}
    if "Profile" in wb.sheetnames:
        for row in wb["Profile"].iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            action = "" if len(row) < 4 or row[3] is None else str(row[3]).strip().lower()
            if action in ("keep", "remove"):
                profile[str(row[0]).strip()] = action
    return profile, answers
