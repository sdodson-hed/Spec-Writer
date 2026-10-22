"""Maxwell 23 64 26 (chilled, chilled-hot and condenser water piping) from
annotations/23 64 26.yaml.

A piping section serves the whole project, so its rules need explicit
basis-of-design facts (bod.condenser_water, bod.glycol), not the chiller
schedule: a cooling tower can exist without a water-cooled chiller (user
decision 2026-10-22). Maxwell's bod is empty, so every rule stays open with
the missing fact named. The two variants record the facts both ways.

Numbers measured 2026-10-22. If one changes, find out why first."""

import json
import re
from pathlib import Path

import pytest

from specgen import secfile
from specgen.annotation import load_annotation
from specgen.answers import read_answers_json
from specgen.cli import main
from specgen.designdata import from_dict
from specgen.generate import generate
from specgen.manifest import build_manifest
from specgen.prefill import dumps, prefill

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "masters" / "23 64 26.SEC"
DESIGN = ROOT / "projects" / "maxwell" / "design-data.json"
ANNOTATION = ROOT / "annotations" / "23 64 26.yaml"
WS = re.compile(r"\s+")

REMOVABLE = ["Condenser Water", "Condenser Water Quality Test Reports",
             "ONE-YEAR INSPECTION REPORT FOR COOLING WATER", "Glycol Solution"]


def _run(tmp, bod):
    dd = {**json.loads(DESIGN.read_text(encoding="utf-8")), "bod": bod}
    res = prefill(build_manifest(secfile.parse(MASTER, tolerant=True)), from_dict(dd),
                  load_annotation(ANNOTATION))
    (tmp / "a.json").write_text(dumps(res), encoding="utf-8")
    profile, answers, fp = read_answers_json(tmp / "a.json")
    s = generate(MASTER, profile, answers, tmp / "o.sec", fingerprint=fp, strict=True)
    out = secfile.parse(tmp / "o.sec", tolerant=True)
    titles = [WS.sub(" ", t.first("TTL").text()).strip() for t in out.root.iter("SPT")
              if t.first("TTL") is not None]
    return {"res": res, "summary": s, "src": out.source, "titles": titles,
            "unresolved": (tmp / "o.unresolved.md").read_text(encoding="utf-8")}


@pytest.fixture(scope="module")
def maxwell(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("as-recorded"), {})


@pytest.fixture(scope="module")
def no_condenser_water(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("no-cw"), {"condenser_water": False, "glycol": False})


@pytest.fixture(scope="module")
def condenser_water(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("cw"), {"condenser_water": True, "glycol": True})


def test_annotation_checks_clean():
    assert main(["annotate-check", str(MASTER), "--annotation", str(ANNOTATION)]) == 0


# --- Maxwell as recorded: the schedule alone decides nothing here ---------------

def test_every_rule_waits_for_its_fact(maxwell):
    outcomes = {r["rule"]: (r["outcome"], r.get("reason")) for r in maxwell["res"].report
                if r["kind"] == "rule"}
    assert outcomes == {
        "condenser-water-treatment": ("unresolved", "needs bod.condenser_water"),
        "condenser-water-tests": ("unresolved", "needs bod.condenser_water"),
        "cooling-water-inspection": ("unresolved", "needs bod.condenser_water"),
        "cooling-water-inspection-submittal": ("unresolved", "needs bod.condenser_water"),
        "glycol": ("unresolved", "needs bod.glycol"),
    }
    md = maxwell["unresolved"]
    assert md.count("needs bod.condenser_water") == 4 and md.count("needs bod.glycol") == 1


def test_project_settings_still_apply(maxwell):
    assert maxwell["res"].payload["profile"] == {
        "AIR FORCE": "keep", "ARMY": "remove", "NAVY": "remove", "UNITS OF MEASURE (SI/IP)": "ip"}
    s = maxwell["summary"]
    assert (s["tailoring_blocks_removed"], s["units_removed"]) == (30, 134)
    assert s["subsections_removed"] == 0 and s["unresolved"] == 78
    for title in REMOVABLE:
        assert any(t.startswith(title) for t in maxwell["titles"]), title


# --- facts recorded false: no condenser water, no glycol -------------------------

def test_condenser_water_and_glycol_removed(no_condenser_water):
    run = no_condenser_water
    for title in REMOVABLE:
        assert not any(t.startswith(title) for t in run["titles"]), title
    assert any(t.startswith("Chilled and Condenser Water") for t in run["titles"])  # 2.11.2 stays
    assert "One-Year Inspection Report For Cooling Water" not in run["src"]
    # cleanup: the submittal item and the reference only the removed text used
    assert "Condenser Water Quality Test Reports" not in run["src"]
    s = run["summary"]
    assert (s["submittal_items_removed"], s["references_removed"]) == (1, 1)
    assert s["unresolved"] == 53


# --- facts recorded true: everything kept, and its own decisions open ------------

def test_condenser_water_and_glycol_kept(condenser_water):
    run = condenser_water
    for title in REMOVABLE:
        assert any(t.startswith(title) for t in run["titles"]), title
    assert "[Condenser Water" not in run["src"] and "[Glycol Solution" not in run["src"]
    assert run["summary"]["unresolved"] == 82   # the kept brackets' own choices now count
