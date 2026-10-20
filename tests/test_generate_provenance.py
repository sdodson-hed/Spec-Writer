"""generate honors provenance (plan 2026-10-20 provenance, Task 3, D2)."""

import json

import pytest

from specgen import secfile
from specgen.answers import read_profile_conflicts
from specgen.generate import GenerateError, generate
from specgen.manifest import build_manifest
from tests.test_annotation import MINI

M = build_manifest(secfile.parse_source(MINI))
CHOICE = next(d for d in M["decisions"] if d["options"] == ["Scroll", "Screw", "Centrifugal"])
DRIVER = next(d for d in M["decisions"] if d["options"] == ["electric motor", "gas-engine"])
HR = next(s for s in M["subsections"] if s["title"] == "Heat Recovery Condenser Coil")


def src(value, rule="compressor-type", ref="ACC-1.compressor_type"):
    return {"kind": "schedule", "ref": ref, "rule": rule, "data_source": "acc-sched-35", "value": value}


def conflict(rec_id, answer, was, now):
    return {"answer": answer, "notes": "", "id": rec_id, "state": "conflict",
            "source": {"kind": "manual", "was": was, "now": now}}


CHOICE_CONFLICT = conflict(CHOICE["id"], "1", {**src("SCROLL"), "answer": "1"},
                           {**src("ROTARY SCREW"), "answer": "2"})


def _gen(tmp_path, answers, profile=None, **kw):
    p = tmp_path / "m.SEC"
    p.write_bytes(MINI.encode(secfile.ENCODING))
    s = generate(p, profile or {}, answers, tmp_path / "o.sec", **kw)
    return (s, (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING),
            (tmp_path / "o.unresolved.md").read_text(encoding="utf-8"),
            json.loads((tmp_path / "o.redline.json").read_text(encoding="utf-8"))["changes"])


def test_conflict_applies_neither_value(tmp_path):
    _, out, md, changes = _gen(tmp_path, {CHOICE["anchor"]: CHOICE_CONFLICT})
    assert "[Scroll][Screw][Centrifugal]" in out
    block = md.split(f"## {CHOICE['id']}", 1)[1].split("## ", 1)[0]
    assert ("conflict: engineer answer '1'; prefill now '2' from ACC-1.compressor_type = "
            "'ROTARY SCREW'") in block
    assert not [c for c in changes if c["id"] == CHOICE["id"]]


def test_strict_refuses_open_conflicts(tmp_path):
    with pytest.raises(GenerateError, match="1 conflict"):
        _gen(tmp_path, {CHOICE["anchor"]: CHOICE_CONFLICT}, strict=True)


def test_subsection_conflict_kept_by_default_and_listed(tmp_path):
    rec = {"answer": "remove", "notes": "", "id": HR["id"], "num": HR["num"], "title": HR["title"],
           "state": "conflict",
           "source": {"kind": "manual",
                      "now": {"kind": "bod", "ref": "bod.heat_recovery", "value": True, "answer": "keep"}}}
    s, out, md, _ = _gen(tmp_path, {HR["anchor"]: rec})
    assert "Heat recovery text." in out
    assert "conflict: engineer answer 'remove'; prefill now 'keep' from bod.heat_recovery = True" in md
    assert s["subsections_removed"] == 0


def test_profile_conflicts(tmp_path):
    msg = "conflict: engineer answer 'keep'; prefill now 'remove' from project.agency = 'NAVY'"
    _, out, md, _ = _gen(tmp_path, {}, profile_conflicts={"ARMY": msg})
    assert "Army reviewer." in out                      # unanswered: block kept
    assert "## ARMY · profile setting" in md and msg in md
    with pytest.raises(GenerateError, match="1 conflict"):
        _gen(tmp_path, {}, profile_conflicts={"ARMY": msg}, strict=True)


def test_read_profile_conflicts(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"profile": {}, "profile_meta": {
        "ARMY": {"state": "conflict", "answer": "keep",
                 "source": {"kind": "manual", "now": {"kind": "rule", "ref": "project.agency",
                                                      "value": "NAVY", "answer": "remove"}}},
        "NAVY": {"state": "auto", "source": {"kind": "rule", "ref": "project.agency", "value": "NAVY"}}}}))
    assert read_profile_conflicts(p) == {
        "ARMY": "conflict: engineer answer 'keep'; prefill now 'remove' from project.agency = 'NAVY'"}


def test_redline_carries_provenance_and_sec_does_not(tmp_path):
    auto = {"answer": "1", "notes": "", "id": CHOICE["id"], "state": "auto", "source": src("SCROLL")}
    over = {"answer": "2", "notes": "", "id": DRIVER["id"], "state": "overridden",
            "source": {"kind": "manual", "was": {**src("electric motor", "compressor-driver",
                                                       "ACC-1.driver (derived)"), "answer": "1"}}}
    _, out, _, changes = _gen(tmp_path, {CHOICE["anchor"]: auto, DRIVER["anchor"]: over})
    by_id = {c["id"]: c for c in changes}
    assert by_id[CHOICE["id"]]["state"] == "auto"
    assert by_id[CHOICE["id"]]["source"] == src("SCROLL")
    assert by_id[DRIVER["id"]]["state"] == "overridden"
    assert by_id[DRIVER["id"]]["source"]["was"]["answer"] == "1"
    assert "acc-sched-35" not in out and "overridden" not in out
