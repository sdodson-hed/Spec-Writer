"""Build a project decision folder from UFGS masters.

Usage: python scripts/build_project.py <project_dir> <master.SEC> [...] [--revisions]

Creates <project_dir>/decisions/<name>.decisions.html for every master, runs
generate for every master that has <project_dir>/answers/<name>.answers.json
(or .xlsx), and writes an index.html with per-section progress. Rerun any
time answers change — outputs are rebuilt idempotently.
"""

import argparse
import html as html_mod
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from specgen import secfile
from specgen.answers import read_answers
from specgen.audit import audit_source
from specgen.generate import generate
from specgen.htmlpage import write_html
from specgen.manifest import build_manifest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("masters", nargs="+")
    ap.add_argument("--revisions", action="store_true")
    args = ap.parse_args()

    proj = Path(args.project_dir)
    for sub in ("decisions", "answers", "generated"):
        (proj / sub).mkdir(parents=True, exist_ok=True)

    rows = []
    failed = 0
    for mpath in args.masters:
        mpath = Path(mpath)
        name = mpath.stem
        try:
            sec = secfile.parse(mpath)
            report = audit_source(sec.source, sec.root)
            if report["unknowns"]:
                n = len(report["unknowns"])
                print(f"FAIL {name}: {n} unattributed signals — skipped")
                failed += 1
                rows.append(
                    f"<tr><td>{html_mod.escape(name)}</td><td></td><td></td>"
                    f"<td>skipped: {n} unattributed signals</td><td></td></tr>"
                )
                continue
            m = build_manifest(sec)
            write_html(m, proj / "decisions" / f"{name}.decisions.html")
            uniq = [
                d for d in m["decisions"]
                if not d["in_note"] and not d.get("plural")
                and not d.get("duplicate_of") and d["safe"]
            ]
            status, unresolved = "no answers yet", ""
            answers_file = next(
                (p for ext in (".answers.json", ".answers.xlsx")
                 for p in [proj / "answers" / f"{name}{ext}"] if p.exists()),
                None,
            )
            if answers_file is not None:
                profile, ans = read_answers(answers_file)
                summary = generate(
                    mpath, profile, ans, proj / "generated" / f"{name}.sec",
                    revisions=args.revisions,
                )
                status = f"{summary['resolved']} resolved"
                unresolved = f"{summary['unresolved']} unresolved"
        except Exception as e:
            print(f"FAIL {name}: {e}")
            failed += 1
            rows.append(
                f"<tr><td>{html_mod.escape(name)}</td><td></td><td></td>"
                f"<td>FAILED: {html_mod.escape(str(e)[:120])}</td><td></td></tr>"
            )
            continue
        rows.append(
            f"<tr><td><a href='decisions/{html_mod.escape(name)}.decisions.html'>"
            f"{html_mod.escape(m['section'])}</a></td>"
            f"<td>{html_mod.escape(m['title'])}</td><td>{len(uniq)} decisions</td>"
            f"<td>{status}</td><td>{unresolved}</td></tr>"
        )
        print(f"OK   {name}: {len(uniq)} decisions, {status} {unresolved}")

    (proj / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Project decisions</title>"
        "<style>body{font:15px system-ui;max-width:900px;margin:40px auto}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;"
        "padding:6px 10px;text-align:left}</style>"
        "<h1>Project decision pages</h1><table><tr><th>Section</th><th>Title</th>"
        "<th>Scope</th><th>Answers</th><th>Open</th></tr>"
        + "".join(rows) + "</table>",
        encoding="utf-8",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
