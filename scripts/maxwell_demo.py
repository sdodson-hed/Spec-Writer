"""End-to-end demo: fill the 23 64 10 answer workbook with the Maxwell AFB
design values (air-cooled chiller, electric drive, AFCEC/Air Force project)
and generate the tailored section.

This plays the role the Hedral platform (or the partner firm's engineer)
will play: producing answers. Everything downstream is the real pipeline.
"""

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MANIFEST = ROOT / "out" / "23 64 10.manifest.json"
WORKBOOK = ROOT / "out" / "23 64 10.answers.xlsx"
FILLED = ROOT / "out" / "23 64 10.answers.maxwell.xlsx"

m = json.loads(MANIFEST.read_text(encoding="utf-8"))
answers: dict[str, str] = {}


def match(d, *needles):
    joined = " || ".join(d["options"]).lower()
    return all(n.lower() in joined for n in needles)


for d in m["decisions"]:
    if d["in_note"]:
        continue
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
    elif kind == "optional" and opts[0].strip().lower() == "s":
        answers[gid] = "keep"  # two chillers on the project: plural stays

print(f"Answering {len(answers)} of "
      f"{sum(1 for d in m['decisions'] if not d['in_note'])} decisions")

wb = load_workbook(str(WORKBOOK))
ws = wb["Answers"]
hit = 0
for row in ws.iter_rows(min_row=2):
    gid = row[0].value
    if gid in answers:
        row[5].value = answers[gid]
        row[6].value = "Maxwell AFB demo: from chiller schedule / system alternative"
        hit += 1
assert hit == len(answers), (hit, len(answers))

ps = wb["Profile"]
profile = {"ARMY": "remove", "NAVY": "remove", "AIR FORCE,NAVY": "keep"}
for row in ps.iter_rows(min_row=2):
    if row[0].value in profile:
        row[3].value = profile[row[0].value]

wb.save(str(FILLED))
print(f"Wrote {FILLED.name}")
