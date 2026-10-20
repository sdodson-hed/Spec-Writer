"""Maxwell 23 64 10 acceptance (spec 2026-10-13, "Maxwell expected outcome";
plan 2026-10-20 maxwell-annotation, Task 2).

prefill (projects/maxwell/design-data.json + annotations/23 64 10.yaml)
then generate --strict --revisions on masters/23 64 10.SEC, checked against
the spec's table row by row. Two departures, both recorded in the spec:
the table's "Confirm" rows are not automated until an engineer signs off
(they stay kept by default), and 23 64 10 has no refrigerant / capacity /
EER / OAT / electrical blanks to fill.

Numbers are pinned (measured 2026-10-20). If one changes, find out why
before touching it."""

import json
import re
from pathlib import Path

import pytest

from specgen import secfile
from specgen.annotation import load_annotation
from specgen.answers import read_answers_json
from specgen.cli import main
from specgen.designdata import load_design_data
from specgen.generate import generate
from specgen.manifest import build_manifest
from specgen.prefill import dumps, prefill

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "masters" / "23 64 10.SEC"
DESIGN = ROOT / "projects" / "maxwell" / "design-data.json"
ANNOTATION = ROOT / "annotations" / "23 64 10.yaml"
WS = re.compile(r"\s+")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = tmp_path_factory.mktemp("maxwell")
    res = prefill(build_manifest(secfile.parse(MASTER, tolerant=True)),
                  load_design_data(DESIGN), load_annotation(ANNOTATION))
    (d / "a.json").write_text(dumps(res), encoding="utf-8")
    profile, answers, fp = read_answers_json(d / "a.json")
    summary = generate(MASTER, profile, answers, d / "o.sec", revisions=True,
                       fingerprint=fp, strict=True)
    out = secfile.parse(d / "o.sec", tolerant=True)
    titles = [WS.sub(" ", s.first("TTL").text()).strip() for s in out.root.iter("SPT")
              if s.first("TTL") is not None]
    return {
        "res": res, "summary": summary, "src": out.source, "titles": titles,
        "unresolved": (d / "o.unresolved.md").read_text(encoding="utf-8"),
        "changes": json.loads((d / "o.redline.json").read_text(encoding="utf-8"))["changes"],
    }


def _has_title(run, prefix):
    return any(t.startswith(prefix) for t in run["titles"])


def test_annotation_checks_clean():
    assert main(["annotate-check", str(MASTER), "--annotation", str(ANNOTATION)]) == 0


# --- the spec's table, row by row ----------------------------------------------

def test_2_4_1_compressor_choice_scroll(run):
    # the title is wrapped in <SUB>; plural left open (no quantity on the schedule)
    assert "<TTL><SUB>Scroll Type Water Chiller[s]</SUB></TTL>" in run["src"]
    # the same choice in the submittal list follows (prefill answers the first
    # instance of a duplicate)
    assert "<ITM><SUB>Scroll Type Water Chiller[s]</SUB></ITM>" in run["src"]
    assert "[Scroll][Reciprocating][Rotary Screw]" not in run["src"]


@pytest.mark.parametrize("title", [
    "Centrifugal Type Water Chiller",          # 2.4.2
    "SPLIT-SYSTEM WATER CHILLER",              # 2.5 (all)
    "Rotary Screw Compressor",                 # 2.6.5.2
    "Centrifugal Compressor",                  # 2.6.5.3
    "Compressor Driver, Gas-Engine",           # 2.6.7
    "Water-Cooled Condenser Coil",             # 2.6.11
    "Cooling Tower",                           # 2.10.3
])
def test_rule_rows_removed(run, title):
    assert not _has_title(run, title)


def test_removed_subtrees_include_children(run):
    # 2.5 with its 13 children, 2.6.7 with its 10 (spec: "and 10 children")
    for child in ("Remote Water Cooler (Evaporator)", "Condenser Casing",
                  "Starting System", "Exhaust Muffler"):
        assert not _has_title(run, child)
    assert run["summary"]["subsections_removed"] == 7
    # 30 in the 7 removed subtrees, plus 2 ARMY-only subsections (2.6.15
    # Tools, 3.1.3 Posted Instructions) that go with the ARMY tailoring
    assert len(run["titles"]) == 122 - 30 - 2


@pytest.mark.parametrize("title", [
    "Scroll Compressor",                       # 2.6.5.1
    "Compressor Driver, Electric Motor",       # 2.6.6
    "Air-Cooled Condenser Coil",               # 2.6.10
    "Receivers",                               # 2.6.13: needs engineer, no rule
    "Chiller Purge System",                    # 2.6.14: Confirm row, not automated
    "Air-Source Heat Pump Type Water Chiller",  # 2.4.3-2.4.7: Confirm rows
    "Water-Source Multipipe Type Water Chiller",
])
def test_kept(run, title):
    assert _has_title(run, title)


def test_tube_brush_confirm_row_left_open(run):
    # 2.7.4 is governed by an optional bracket; unanswered, it stays bracketed
    assert "[<SPT><TTL>Automatic Tube Brush Cleaning System" in run["src"]


def test_driver_and_condenser_choices(run):
    assert "Compressor driver, electric motor" in run["src"]
    assert "[ gas-engine]" not in run["src"]
    assert "Air-cooled condenser coil" in run["src"]
    assert "[Water-cooled condenser]" not in run["src"]


def test_heat_recovery_unresolved_with_reason(run):
    assert _has_title(run, "Heat Recovery Condenser Coil")    # kept by default
    md = run["unresolved"]
    assert "2.6.12 Heat Recovery Condenser Coil" in md
    assert "needs bod.heat_recovery; kept by default until answered" in md


def test_army_and_navy_tailoring_removed(run):
    assert '<TAI OPT="ARMY">' not in run["src"] and '<TAI OPT="NAVY">' not in run["src"]
    assert '<TAI OPT="AIR FORCE' in run["src"]
    assert run["summary"]["tailoring_blocks_removed"] == 33


def test_units_ip(run):
    # every SI value outside designer notes is gone (notes are never edited)
    out = secfile.parse_source(run["src"], tolerant=True)
    assert not [e for e in out.root.iter("MET") if not any(a.name == "NTE" for a in e.ancestors())]
    assert run["summary"]["units_removed"] == 53


def test_no_fills_in_this_section(run):
    # 23 64 10 has no refrigerant/capacity/EER/OAT/electrical blanks (D2)
    assert not [c for c in run["changes"] if c["kind"] == "blank"]


def test_cleanup_from_step_4(run):
    s = run["summary"]
    assert (s["submittal_items_removed"], s["references_removed"]) == (2, 12)


def test_unresolved_count(run):
    # baseline 102 (old demo: 8 hand-picked answers, no removals); prefill,
    # with no hand answers: 80
    assert run["summary"]["unresolved"] == 80
    assert run["summary"]["answers_fingerprint"] == "anchors"


def test_every_prefill_answer_has_a_source(run):
    for rec in run["res"].payload["answers"].values():
        if rec["answer"]:
            assert rec["state"] == "auto" and rec["source"]["data_source"] == "acc-sched-35"


# --- re-run round trip (plan 2026-10-20 provenance, Task 5) ---------------------
#
# The engineer overrides the condenser choice with custom text (the choice has
# two options, so picking the other one would agree with the water-cooled
# schedule below instead of conflicting with it).

MINE = "Air-cooled condenser coil with factory-applied coil coating"


def _rec(path, rule):
    p = json.loads(path.read_text(encoding="utf-8"))
    return p, next(k for k, v in p["answers"].items() if (v.get("source") or {}).get("rule") == rule
                   or ((v.get("source") or {}).get("was") or {}).get("rule") == rule)


@pytest.fixture(scope="module")
def rerun(tmp_path_factory):
    d = tmp_path_factory.mktemp("maxwell-rerun")
    a = d / "a.json"
    pre = ["prefill", str(MASTER), "--annotation", str(ANNOTATION), "-o", str(a)]
    steps = {}

    assert main([*pre, "--design-data", str(DESIGN)]) == 0                   # 1. prefill
    p, key = _rec(a, "condenser")
    rec = p["answers"][key]
    assert rec["answer"] == "1" and rec["state"] == "auto"
    p["answers"][key] = {**rec, "answer": MINE, "state": "overridden",        # 2. override
                         "source": {"kind": "manual", "was": {**rec["source"], "answer": "1"}}}
    a.write_text(json.dumps(p, indent=2), encoding="utf-8")

    assert main([*pre, "--design-data", str(DESIGN)]) == 0                   # 3. unchanged data
    steps["kept"] = json.loads(a.read_text(encoding="utf-8"))

    dd = json.loads(DESIGN.read_text(encoding="utf-8"))                       # 4. schedule change
    dd["equipment"][0]["type"] = "WATER-COOLED SCROLL"
    (d / "dd.json").write_text(json.dumps(dd), encoding="utf-8")
    assert main([*pre, "--design-data", str(d / "dd.json")]) == 0
    steps["changed"] = json.loads(a.read_text(encoding="utf-8"))

    profile, answers, fp = read_answers_json(a)                               # 5. generate
    summary = generate(MASTER, profile, answers, d / "o.sec", fingerprint=fp)
    out = secfile.parse(d / "o.sec", tolerant=True)
    steps.update(
        key=key, summary=summary, src=out.source,
        titles=[WS.sub(" ", s.first("TTL").text()).strip() for s in out.root.iter("SPT")
                if s.first("TTL") is not None],
        unresolved=(d / "o.unresolved.md").read_text(encoding="utf-8"),
        strict=main(["generate", str(MASTER), "--answers", str(a), "-o", str(d / "s.sec"), "--strict"]),
    )
    return steps


def _outcomes(payload):
    return {r["id"]: r["outcome"] for r in payload["prefill"]["merge"]}


def test_rerun_with_unchanged_data_keeps_the_override(rerun):
    rec = rerun["kept"]["answers"][rerun["key"]]
    assert rec["answer"] == MINE and rec["state"] == "overridden"
    assert _outcomes(rerun["kept"]) == {rec["id"]: "kept override"}   # nothing else moved


def test_schedule_change_makes_a_conflict_with_both_values(rerun):
    rec = rerun["changed"]["answers"][rerun["key"]]
    assert rec["state"] == "conflict" and rec["answer"] == MINE
    # source.value is the derived fact the rule matched, mapped from the type
    assert rec["source"]["was"]["value"] == "Air-cooled condenser coil"
    assert rec["source"]["now"]["value"] == "Water-cooled condenser"
    assert rec["source"]["now"]["answer"] == "2"
    assert _outcomes(rerun["changed"])[rec["id"]] == "conflict"


def test_schedule_change_moves_the_condenser_subsections(rerun):
    for title in ("Water-Cooled Condenser Coil", "Cooling Tower"):   # 2.6.11, 2.10.3 stay
        assert _has_title(rerun, title)
    assert not _has_title(rerun, "Air-Cooled Condenser Coil")        # 2.6.10 goes


def test_generate_leaves_the_conflict_unresolved(rerun):
    md = rerun["unresolved"]
    assert (f"conflict: engineer answer {MINE!r}; prefill now '2' from "
            f"ACC-1.condenser_component (derived) = 'Water-cooled condenser'") in md
    assert "»[Air-cooled condenser coil][Water-cooled condenser]«" in md   # still open
    assert MINE not in rerun["src"]                                   # neither value applied
    assert rerun["strict"] == 1                                       # --strict refuses
