"""Regression gate: audit + round-trip every master in masters/Specifications."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specgen import secfile
from specgen.audit import audit_source

CORPUS = Path(__file__).resolve().parent.parent / "masters" / "Specifications"


def main() -> int:
    failures = 0
    for f in sorted(CORPUS.glob("*.SEC")):
        sec = secfile.parse(f)
        problems = []
        if not sec.roundtrips():
            problems.append("ROUNDTRIP-FAIL")
        report = audit_source(sec.source, sec.root)
        if report["unknowns"]:
            problems.append(f"{len(report['unknowns'])} unknown signal(s)")
        status = "OK " if not problems else "FAIL"
        print(f"{status} {f.name:24s} {'; '.join(problems)}")
        for u in report["unknowns"]:
            print(f"     UNKNOWN {u['type']} @ {u['offset']}: {u['context'][:100]}")
        failures += bool(problems)
    print(f"\n{failures} of {len(list(CORPUS.glob('*.SEC')))} sections failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
