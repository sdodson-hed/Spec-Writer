"""End-to-end demo: answer UFGS 23 64 10 for Maxwell AFB from its design data
and generate the tailored section. Walkthrough: docs/maxwell-demo.md.

1-prefill/   the 35% schedule as issued
    prefill  projects/maxwell/design-data.json (ACC-1) + annotations/23 64 10.yaml
    generate masters/23 64 10.SEC with those answers, --strict --revisions
    html     the decision page, opening with prefill's answers loaded

2-schedule-revision/   what happens when the schedule changes after review
    an engineer's review of 1-prefill (scripted here, as it would be exported
    from the page): the condenser line rewritten in their own words, and
    2.6.12 Heat Recovery Condenser Coil kept, which the data could not decide
    the schedule then revises ACC-1 to WATER-COOLED SCROLL, and prefill runs
    again on the reviewed file: auto answers follow the new data, the
    engineer's condenser line becomes a conflict showing both values, and
    generate leaves it open for the engineer to decide on the page

Nothing in 1-prefill is hand-coded: every answer comes from the schedule
through the annotation, with its source recorded. The two engineer answers in
2-schedule-revision are the only scripted inputs, and are labeled as such.
"""

import html
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from specgen import secfile  # noqa: E402
from specgen.answers import read_answers_json, read_profile_conflicts  # noqa: E402
from specgen.cli import main as cli  # noqa: E402
from specgen.generate import generate  # noqa: E402
from specgen.htmlpage import write_html  # noqa: E402
from specgen.manifest import build_manifest  # noqa: E402

MASTER = ROOT / "masters" / "23 64 10.SEC"
DESIGN = ROOT / "projects" / "maxwell" / "design-data.json"
ANNOTATION = ROOT / "annotations" / "23 64 10.yaml"
OUT = ROOT / "out" / "maxwell-demo"
STEM = "23_64_10"

# the scripted engineer review (2-schedule-revision)
CONDENSER_TEXT = "Air-cooled condenser coil with factory-applied coil coating"
REVISED_TYPE = "WATER-COOLED SCROLL"


def _prefill(design: Path, answers: Path) -> None:
    if cli(["prefill", str(MASTER), "--design-data", str(design),
            "--annotation", str(ANNOTATION), "-o", str(answers)]) != 0:
        raise SystemExit("prefill failed")


def _generate(answers: Path, out: Path, strict: bool) -> dict:
    profile, ans, fp = read_answers_json(answers)
    return generate(MASTER, profile, ans, out, revisions=True, fingerprint=fp, strict=strict,
                    profile_conflicts=read_profile_conflicts(answers))


def _page(manifest: dict, answers: Path, out: Path) -> None:
    write_html(manifest, out, preload=json.loads(answers.read_text(encoding="utf-8")))


def _say(label: str, s: dict) -> str:
    line = (f"{s['subsections_removed']} subsections removed, {s['tailoring_blocks_removed']} "
            f"tailoring blocks removed, {s['submittal_items_removed']} submittal items and "
            f"{s['references_removed']} references cleaned up, {s['unresolved']} decisions "
            f"left for the engineer")
    print(f"{label}: {line}")
    return line


def _engineer_review(answers: Path) -> None:
    """Two answers an engineer gives on the decision page, written the way the
    page exports them (an edited prefill answer becomes an override)."""
    p = json.loads(answers.read_text(encoding="utf-8"))
    for key, rec in p["answers"].items():
        src = rec.get("source") or {}
        if src.get("rule") == "condenser":
            p["answers"][key] = {**rec, "answer": CONDENSER_TEXT, "state": "overridden",
                                 "source": {"kind": "manual", "was": {**src, "answer": rec["answer"]}},
                                 "notes": "engineer: coated coil per base standard"}
        elif rec.get("title") == "Heat Recovery Condenser Coil":
            p["answers"][key] = {**rec, "answer": "keep", "source": {"kind": "manual"},
                                 "notes": "engineer: heat recovery is in the basis of design"}
    answers.write_text(json.dumps(p, indent=2), encoding="utf-8")


def main(out: Path = OUT) -> int:
    # start clean: delete the files, keep the folders (Windows refuses to
    # remove a folder that Explorer, a terminal or a web server has open)
    out.mkdir(parents=True, exist_ok=True)
    for p in out.rglob("*"):
        if p.is_file():
            p.unlink()
    one, two = out / "1-prefill", out / "2-schedule-revision"
    one.mkdir(exist_ok=True)
    two.mkdir(exist_ok=True)
    manifest = build_manifest(secfile.parse(MASTER, tolerant=True))

    # 1. the schedule as issued
    a1 = one / f"{STEM}.answers.json"
    _prefill(DESIGN, a1)
    s1 = _generate(a1, one / f"{STEM}.sec", strict=True)
    _page(manifest, a1, one / f"{STEM}.decisions.html")
    line1 = _say("1-prefill", s1)

    # 2. engineer review, then the schedule revision and a prefill re-run
    a2 = two / f"{STEM}.answers.json"
    shutil.copyfile(a1, a2)
    _engineer_review(a2)
    shutil.copyfile(a2, two / f"{STEM}.reviewed.answers.json")   # before the re-run
    dd = json.loads(DESIGN.read_text(encoding="utf-8"))
    dd["equipment"][0]["type"] = REVISED_TYPE
    dd["sources"]["acc-sched-35"]["title"] += f" (demo revision: ACC-1 {REVISED_TYPE})"
    (two / "design-data.json").write_text(json.dumps(dd, indent=2), encoding="utf-8")
    _prefill(two / "design-data.json", a2)
    s2 = _generate(a2, two / f"{STEM}.sec", strict=False)   # --strict would refuse: 1 conflict
    _page(manifest, a2, two / f"{STEM}.decisions.html")
    line2 = _say("2-schedule-revision", s2)
    p2 = json.loads(a2.read_text(encoding="utf-8"))
    merge = [{**r, "label": _label(r, p2["answers"].get(r["key"]) or {})} for r in p2["prefill"]["merge"]]

    _index(out, line1, line2, merge)
    print(f"outputs in {out}; open {out / 'index.html'}")
    return 0


def _label(row: dict, rec: dict) -> str:
    """What a reviewer recognizes: '2.6.10 Air-Cooled Condenser Coil', or a
    choice's options."""
    if rec.get("num"):
        return f"{rec['num']} {rec.get('title', '')}"
    if rec.get("options"):
        return f"{row['id']}: " + " | ".join(rec["options"])
    return row["id"] or row["key"]


def _index(out: Path, line1: str, line2: str, merge: list[dict]) -> None:
    def files(folder: str, names: list[tuple[str, str]]) -> str:
        return "".join(f'<li><a href="{folder}/{n}">{html.escape(n)}</a> {html.escape(d)}</li>'
                       for n, d in names)

    common = [
        (f"{STEM}.decisions.html", "the decision page, opening with these answers"),
        (f"{STEM}.sec", "the tailored section"),
        (f"{STEM}.revisions.sec", "the same, as SpecsIntact tracked changes"),
        (f"{STEM}.redline.md", "every change, with its source"),
        (f"{STEM}.unresolved.md", "what is left for the engineer"),
        (f"{STEM}.answers.json", "the answers file"),
        (f"{STEM}.answers.prefill.md", "what prefill answered and why"),
    ]
    rows = "".join(f"<tr><td>{html.escape(r['label'])}</td><td>{html.escape(r['outcome'])}</td>"
                   f"<td>{html.escape(r['detail'])}</td></tr>" for r in merge)
    page = f"""<!doctype html><meta charset="utf-8"><title>Maxwell demo</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:32px auto;padding:0 16px}}
td{{padding:3px 10px 3px 0;vertical-align:top}}code{{background:#f1f5f9;padding:0 3px}}</style>
<h1>Maxwell AFB: UFGS 23 64 10 from the chiller schedule</h1>
<p>Walkthrough: <code>docs/maxwell-demo.md</code>. Regenerate with <code>python scripts/maxwell_demo.py</code>.</p>
<h2>1. The 35% schedule as issued</h2><p>{html.escape(line1)}.</p>
<ul>{files("1-prefill", common)}</ul>
<h2>2. Schedule revision after engineer review</h2>
<p>Scripted engineer review of step 1: the condenser line rewritten as
<q>{html.escape(CONDENSER_TEXT)}</q>, and 2.6.12 Heat Recovery Condenser Coil kept.
Then ACC-1 becomes {html.escape(REVISED_TYPE)} and prefill runs again.</p>
<table>{rows}</table>
<p>{html.escape(line2)}.</p>
<ul>{files("2-schedule-revision", common + [
        (f"{STEM}.reviewed.answers.json", "the reviewed answers, before the re-run"),
        ("design-data.json", "the revised schedule")])}</ul>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
