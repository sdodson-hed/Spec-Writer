"""Phase 0 smoke edit: resolve a handful of brackets in the SGTEST job copy
of 23 64 10 the way the generator would for the Maxwell air-cooled chiller,
then re-verify the file. Each edit is an exact, unique substring replacement
on the raw source (brackets are literal text; tags are never touched).

Run:  python scripts/sgtest_edit.py
"""

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from specgen import secfile  # noqa: E402

JOB_FILE = Path(
    r"C:\Users\Victor Colosi\Documents\SpecsIntactWD\Jobs\SGTEST\pulldata\23 64 10.sec"
)
OUT_DIR = Path(__file__).resolve().parent.parent / "out"
BACKUP = OUT_DIR / "23 64 10.sec.pre-edit.bak"

# (edit id, reason, exact old text, new text, expected occurrences)
EDITS = [
    (
        "E1",
        "Condenser type <- system alternative: air-cooled chiller",
        "<OLI>[Air-cooled condenser coil][Water-cooled condenser]</OLI>",
        "<OLI>Air-cooled condenser coil</OLI>",
        1,
    ),
    (
        "E2",
        "Compressor driver <- schedule: electric motor "
        "(occurs in both the scroll/recip/screw and centrifugal articles)",
        "<OLI>Compressor driver,[ electric motor][ gas-engine]</OLI>",
        "<OLI>Compressor driver, electric motor</OLI>",
        2,
    ),
    (
        "E3",
        "Minimum stable load <- default choice 10 percent",
        "[10][_____] percent of total capacity",
        "10 percent of total capacity",
        1,
    ),
    (
        "E4a",
        "Low ambient compressor operation limit, SI units",
        "[4.4][minus 17.7][_____]",
        "4.4",
        1,
    ),
    (
        "E4b",
        "Low ambient compressor operation limit, imperial units",
        "[40][zero][_____]",
        "40",
        1,
    ),
    (
        "E5",
        "Heat recovery condenser not in design -> optional block deleted",
        "[<OLI>Heat recovery condenser</OLI><BRK/>\r\n<BRK/>\r\n]",
        "",
        1,
    ),
]


def main() -> int:
    src = JOB_FILE.read_bytes().decode(secfile.ENCODING)
    before_brackets = src.count("[") + src.count("]")

    log = []
    for eid, reason, old, new, expect in EDITS:
        n = src.count(old)
        if n != expect:
            print(f"ABORT {eid}: expected {expect} occurrence(s), found {n}: {old!r}")
            return 1
        src = src.replace(old, new)
        log.append(
            {
                "id": eid,
                "reason": reason,
                "removed": old,
                "inserted": new,
                "occurrences": n,
                "bracket_chars_removed": n
                * ((old.count("[") + old.count("]"))
                   - (new.count("[") + new.count("]"))),
            }
        )

    # verify BEFORE writing anything
    tmp = OUT_DIR / "23 64 10.sec.edited.tmp"
    OUT_DIR.mkdir(exist_ok=True)
    tmp.write_bytes(src.encode(secfile.ENCODING))
    sec = secfile.parse(tmp)  # raises on structural damage
    assert sec.roundtrips()
    import xml.etree.ElementTree as ET

    ET.parse(tmp)  # well-formedness

    shutil.copy2(JOB_FILE, BACKUP)
    JOB_FILE.write_bytes(src.encode(secfile.ENCODING))
    tmp.unlink()

    after_brackets = src.count("[") + src.count("]")
    removed_pairs = (before_brackets - after_brackets) // 2
    summary = {
        "file": str(JOB_FILE),
        "backup": str(BACKUP),
        "edits": log,
        "bracket_chars_before": before_brackets,
        "bracket_chars_after": after_brackets,
        "bracket_pairs_resolved": removed_pairs,
    }
    (OUT_DIR / "sgtest-edit-log.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"Applied {len(EDITS)} edits, resolved {removed_pairs} bracket pairs "
          f"({before_brackets} -> {after_brackets} bracket chars).")
    print(f"Backup: {BACKUP}")
    print("Edited file parses, round-trips, and is well-formed XML.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
