"""End-to-end demo: fill the 23 64 10 answer workbook with the Maxwell AFB
design values (air-cooled chiller, electric drive, AFCEC/Air Force project)
and generate the tailored section.

This plays the role the Hedral platform (or the partner firm's engineer)
will play: producing answers. Everything downstream is the real pipeline.
Duplicate decisions are answered once (propagation handles the rest);
plural [s] markers are answered once on the Profile sheet.
"""

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from specgen.answers import PLURAL_KEY  # noqa: E402

MANIFEST = ROOT / "out" / "23 64 10.manifest.json"
WORKBOOK = ROOT / "out" / "23 64 10.answers.xlsx"
FILLED = ROOT / "out" / "23 64 10.answers.maxwell.xlsx"

m = json.loads(MANIFEST.read_text(encoding="utf-8"))
answers: dict[str, str] = {}


def match(d, *needles):
    joined = " || ".join(d["options"]).lower()
    return all(n.lower() in joined for n in needles)


for d in m["decisions"]:
    if d["in_note"] or d.get("plural") or d.get("duplicate_of"):
        continue  # duplicates auto-follow the first instance
    gid, kind, opts = d["id"], d["kind"], d["options"]
    if kind == "choice" and match(d, "air-cooled condenser coil", "water-cooled"):
        answers[gid] = "1"  # air-cooled machine
    elif kind == "choice" and match(d, "electric motor", "gas-engine"):
        answers[gid] = "1"  # electric drive
    elif kind == "choice" and match(d, "scroll", "reciprocating", "rotary screw"):
        answers[gid] = "1"  # scroll compressors
    elif kind == "choice" and opts[:1] == ["10"] and match(d, "10", "___"):
        answers[gid] = "1"  # minimum stable load: 10 percent
    elif kind == "choice" and match(d, "4.4", "minus 17.7"):
        answers[gid] = "1"  # low ambient limit 4.4 degC
    elif kind == "choice" and match(d, "40", "zero") and len(opts) == 3:
        answers[gid] = "1"  # low ambient limit 40 degF
    elif kind == "choice" and match(d, "heat recovery condenser", "receiver"):
        answers[gid] = "delete"  # no heat recovery / receiver / economizer

print(f"Answering {len(answers)} unique decisions "
      f"(duplicates and plural [s] handled by propagation/profile)")

wb = load_workbook(str(WORKBOOK))
ws = wb["Answers"]
head = {str(c.value).strip().lower(): i for i, c in enumerate(ws[1], 1) if c.value}
hit = 0
for row in ws.iter_rows(min_row=2):
    gid = row[head["id"] - 1].value
    if gid in answers:
        row[head["answer"] - 1].value = answers[gid]
        row[head["notes"] - 1].value = "Maxwell demo: from chiller schedule"
        hit += 1
assert hit == len(answers), (hit, len(answers))

ps = wb["Profile"]
profile = {
    "ARMY": "remove",
    "NAVY": "remove",
    "AIR FORCE,NAVY": "keep",
    PLURAL_KEY: "keep",  # two chillers on the project
}
for row in ps.iter_rows(min_row=2):
    if row[0].value in profile:
        row[3].value = profile[row[0].value]

target = FILLED
try:
    wb.save(str(target))
except PermissionError:  # workbook open in Excel — write a versioned copy
    for n in range(2, 20):
        target = FILLED.with_name(f"{FILLED.stem}-v{n}{FILLED.suffix}")
        try:
            wb.save(str(target))
            break
        except PermissionError:
            continue
print(f"Wrote {target.name}")
