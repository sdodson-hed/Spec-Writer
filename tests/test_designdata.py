"""Design data file (spec 2026-10-13, section 4; plan 2026-10-20, Task 1)."""

import copy
import json
from pathlib import Path

import pytest

from specgen.designdata import DesignDataError, from_dict, load_design_data

MAXWELL = Path(__file__).resolve().parent.parent / "projects" / "maxwell" / "design-data.json"


def _data():
    return json.loads(MAXWELL.read_text(encoding="utf-8"))


def test_maxwell_loads():
    dd = load_design_data(MAXWELL)
    assert dd.project["agency"] == "AIR FORCE" and dd.project["units"] == "IP"
    [acc] = dd.rows("air_cooled_chiller")
    assert acc["mark"] == "ACC-1" and acc["compressor_type"] == "SCROLL"
    assert dd.rows("pump") == []
    assert dd.source("ACC-1") == {
        "kind": "schedule", "title": "Air Cooled Chiller Schedule",
        "phase": "35%", "date": "2026-10-13", "id": "acc-sched-35"}
    assert dd.bod == {}


def _broken(mutate):
    d = _data()
    mutate(d)
    with pytest.raises(DesignDataError) as e:
        from_dict(d)
    return str(e.value)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(schema="specgen.design-data/2"), "schema must be 'specgen.design-data/1'"),
    (lambda d: d.update(extra=1), "unknown top-level key 'extra'"),
    (lambda d: d["project"].pop("agency"), "project.agency is required"),
    (lambda d: d["project"].update(units="metric"), "project.units must be IP or SI"),
    (lambda d: d["equipment"][0].pop("mark"), "equipment[0]: mark is required"),
    (lambda d: d["equipment"][0].update(source="nope"),
     "equipment[0] (ACC-1): source 'nope' is not in sources"),
    (lambda d: d["equipment"].append(copy.deepcopy(d["equipment"][0])), "duplicate mark 'ACC-1'"),
    (lambda d: d.update(equipment={}), "equipment must be a list"),
    (lambda d: d.update(bod=[]), "bod must be an object"),
])
def test_each_rule_is_checked(mutate, message):
    assert message in _broken(mutate)


def test_all_problems_reported_together():
    def two(d):
        d["project"].pop("agency")
        d["equipment"][0].pop("schedule")
    msg = _broken(two)
    assert "project.agency is required" in msg
    assert "equipment[0] (ACC-1): schedule is required" in msg


def test_missing_bod_means_empty():
    d = _data()
    d.pop("bod")
    assert from_dict(d).bod == {}
