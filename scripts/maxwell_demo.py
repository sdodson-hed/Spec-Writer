"""End-to-end demo: answer UFGS 23 64 10 for Maxwell AFB from its design data
and generate the tailored section.

    prefill  projects/maxwell/design-data.json (ACC-1, 35% chiller schedule)
             + annotations/23 64 10.yaml
             -> out/maxwell-demo/23_64_10.answers.json  (+ .prefill.md)
    generate masters/23 64 10.SEC with those answers, --strict --revisions
             -> out/maxwell-demo/23_64_10.sec, .revisions.sec, .redline.md,
                .redline.json, .unresolved.md

Nothing is hand-coded here: every answer comes from the schedule through the
annotation, with its source recorded. What the data cannot answer (heat
recovery, plural markers, the spec table's "Confirm" rows, the rest of the
section's engineering choices) stays in .unresolved.md for the engineer, or
open on the decision page:

    python -m specgen html "masters/23 64 10.SEC" -o out/maxwell-demo/23_64_10.html

then Import answers -> out/maxwell-demo/23_64_10.answers.json.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from specgen import secfile  # noqa: E402
from specgen.annotation import load_annotation  # noqa: E402
from specgen.answers import read_answers_json  # noqa: E402
from specgen.designdata import load_design_data  # noqa: E402
from specgen.generate import generate  # noqa: E402
from specgen.manifest import build_manifest  # noqa: E402
from specgen.prefill import dumps, prefill, report_markdown  # noqa: E402

MASTER = ROOT / "masters" / "23 64 10.SEC"
DESIGN = ROOT / "projects" / "maxwell" / "design-data.json"
ANNOTATION = ROOT / "annotations" / "23 64 10.yaml"
OUT = ROOT / "out" / "maxwell-demo"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    res = prefill(build_manifest(secfile.parse(MASTER, tolerant=True)),
                  load_design_data(DESIGN), load_annotation(ANNOTATION))
    answers_path = OUT / "23_64_10.answers.json"
    answers_path.write_text(dumps(res), encoding="utf-8")
    (OUT / "23_64_10.answers.prefill.md").write_text(report_markdown(res), encoding="utf-8")
    rules = [r for r in res.report if r["kind"] == "rule"]
    print(f"prefill: {sum(r['outcome'] == 'answered' for r in rules)} of {len(rules)} rules "
          f"answered from {DESIGN.relative_to(ROOT)}")

    profile, answers, fingerprint = read_answers_json(answers_path)
    s = generate(MASTER, profile, answers, OUT / "23_64_10.sec", revisions=True,
                 fingerprint=fingerprint, strict=True)
    print(f"generate: {s['subsections_removed']} subsections removed, "
          f"{s['tailoring_blocks_removed']} tailoring blocks removed, "
          f"{s['submittal_items_removed']} submittal items and {s['references_removed']} "
          f"references cleaned up, {s['unresolved']} decisions left for the engineer")
    print(f"outputs in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
