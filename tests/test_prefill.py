"""prefill: design data + annotation -> answers (plan 2026-10-20, Task 4)."""

import json

import pytest
import yaml

from specgen import secfile
from specgen.annotation import from_dict as annotation_from_dict
from specgen.answers import PLURAL_KEY, UNITS_KEY, read_answers_json
from specgen.cli import main
from specgen.designdata import from_dict as dd_from_dict
from specgen.generate import generate
from specgen.manifest import build_manifest
from specgen.prefill import PrefillError, prefill
from tests.test_annotation import ANNOTATION, MINI

ACC1 = {"mark": "ACC-1", "schedule": "air_cooled_chiller", "source": "acc-sched-35",
        "type": "AIR-COOLED SCROLL", "compressor_type": "SCROLL",
        "refrigerant": "R-454B", "capacity_mbh": 1123.1}
DD = {"schema": "specgen.design-data/1",
      "project": {"name": "Mini", "agency": "AIR FORCE", "units": "IP"},
      "sources": {"acc-sched-35": {"kind": "schedule", "title": "Chiller Schedule", "phase": "35%"},
                  "acc-sched-65": {"kind": "schedule", "title": "Chiller Schedule", "phase": "65%"}},
      "equipment": [ACC1], "bod": {}}


def _run(dd=DD, ann=ANNOTATION, src=MINI):
    m = build_manifest(secfile.parse_source(src))
    res = prefill(m, dd_from_dict(json.loads(json.dumps(dd))), annotation_from_dict(yaml.safe_load(ann)))
    return m, res


def _by_id(res):
    return {rec["id"]: rec for rec in res.payload["answers"].values()}


def _rules(res):
    return {r["rule"]: r for r in res.report if r.get("rule")}


def test_choices_fills_and_removals():
    m, res = _run()
    a, rules = _by_id(res), _rules(res)
    comp = a[rules["compressor-type"]["target"]]
    assert comp["answer"] == "1" and comp["state"] == "auto"
    assert comp["source"] == {"kind": "schedule", "ref": "ACC-1.compressor_type",
                              "rule": "compressor-type", "data_source": "acc-sched-35",
                              "value": "SCROLL"}
    driver = a[rules["driver"]["target"]]
    assert driver["answer"] == "1"
    assert driver["source"]["ref"] == "ACC-1.driver (derived)"
    assert a[rules["refrigerant"]["target"]]["answer"] == "R-454B"
    assert a[rules["capacity"]["target"]]["answer"] == "1123.1"
    cen = a[rules["no-centrifugal"]["target"]]
    assert (cen["answer"], cen["title"]) == ("remove", "Centrifugal Type Chiller")
    assert a[rules["no-gas-engine"]["target"]]["answer"] == "remove"


def test_missing_data_stays_unresolved_with_the_field_named():
    _, res = _run()
    a, rules = _by_id(res), _rules(res)
    hr = a[rules["heat-recovery"]["target"]]
    assert hr["answer"] == "" and "source" not in hr
    assert hr["notes"] == "prefill (heat-recovery): needs bod.heat_recovery"
    st = a[rules["sound-test"]["target"]]
    assert st["answer"] == "" and st["notes"] == "prefill (sound-test): needs bod.sound_test"
    assert rules["heat-recovery"]["outcome"] == "unresolved"


def test_rule_inside_a_removed_subsection_is_skipped():
    _, res = _run()
    r = _rules(res)["engine-hp"]
    assert r["outcome"] == "skipped"
    assert r["reason"].startswith("inside removed SPT-")
    assert r["target"] not in _by_id(res)


def test_bod_answers_when_present():
    _, res = _run(dd={**DD, "bod": {"heat_recovery": True, "sound_test": False}})
    a, rules = _by_id(res), _rules(res)
    hr = a[rules["heat-recovery"]["target"]]
    assert hr["answer"] == "keep" and hr["source"]["kind"] == "bod"
    assert hr["source"]["ref"] == "bod.heat_recovery"
    assert a[rules["sound-test"]["target"]]["answer"] == "delete"


def test_project_level_profile():
    _, res = _run()
    assert res.payload["profile"] == {"AIR FORCE": "keep", "ARMY": "remove", UNITS_KEY: "ip"}
    proj = [r for r in res.report if r["kind"] == "project"]
    assert {r["setting"] for r in proj} == {"AIR FORCE", "ARMY", UNITS_KEY}


def test_annotation_profile_overrides():
    _, res = _run(ann=ANNOTATION + 'profile: {"ARMY": keep}\n')
    assert res.payload["profile"]["ARMY"] == "keep"


def test_rows_disagree():
    acc2 = {**ACC1, "mark": "ACC-2", "source": "acc-sched-65", "refrigerant": "R-32"}
    _, res = _run(dd={**DD, "equipment": [ACC1, acc2]})
    a, rules = _by_id(res), _rules(res)
    ref = a[rules["refrigerant"]["target"]]
    assert ref["answer"] == ""
    assert ref["notes"] == ("prefill (refrigerant): equipment rows disagree: "
                            "ACC-1='R-454B', ACC-2='R-32'")
    # agreeing fields still answer, citing both rows and both sources
    comp = a[rules["compressor-type"]["target"]]
    assert comp["source"]["ref"] == "ACC-1,ACC-2.compressor_type"
    assert comp["source"]["data_source"] == "acc-sched-35,acc-sched-65"


def test_value_matching_no_option():
    _, res = _run(dd={**DD, "equipment": [{**ACC1, "compressor_type": "RECIPROCATING"}]})
    rec = _by_id(res)[_rules(res)["compressor-type"]["target"]]
    assert rec["answer"] == ""
    assert rec["notes"] == ("prefill (compressor-type): value 'RECIPROCATING' matches no "
                            "option (Scroll | Screw | Centrifugal)")


def test_no_equipment_rows():
    _, res = _run(dd={**DD, "equipment": []})
    rec = _by_id(res)[_rules(res)["refrigerant"]["target"]]
    assert rec["notes"] == "prefill (refrigerant): needs air_cooled_chiller rows"


PLURAL_SRC = MINI.replace("Centrifugal text.", "Provide Chiller[s].")


@pytest.mark.parametrize("rows, want", [
    ([{**ACC1, "quantity": 2}], "keep"),
    ([{**ACC1, "quantity": 1}], "remove"),
    ([{**ACC1, "quantity": 1}, {**ACC1, "mark": "ACC-2", "quantity": 1}], "keep"),
    ([ACC1], None),
])
def test_plural_from_quantity(rows, want):
    _, res = _run(dd={**DD, "equipment": rows}, src=PLURAL_SRC)
    assert res.payload["profile"].get(PLURAL_KEY) == want
    if want is None:
        p = next(r for r in res.report if r.get("setting") == PLURAL_KEY)
        assert p["outcome"] == "unresolved" and "equipment.quantity" in p["reason"]


def test_answer_reaches_the_first_instance_of_a_duplicate():
    # 23 64 10: the 2.4.1 compressor choice (BRK-0023) is a duplicate of the
    # same choice in the submittal list (BRK-0002). generate propagates only
    # from the first instance, so prefill answers that one too.
    src = MINI.replace(
        "<SPT><TTL>SUMMARY</TTL>",
        "<SPT><TTL>SUBMITTALS</TTL><ITM><SUB>[Scroll][Screw][Centrifugal] Type Chiller</SUB></ITM></SPT>"
        "<SPT><TTL>SUMMARY</TTL>")
    m, res = _run(src=src)
    first = next(d for d in m["decisions"] if d["options"] == ["Scroll", "Screw", "Centrifugal"]
                 and not d["duplicate_of"])
    target = _rules(res)["compressor-type"]["target"]
    assert target != first["id"]
    a = _by_id(res)
    assert a[target]["answer"] == "1" and a[first["id"]]["answer"] == "1"
    assert a[first["id"]]["source"]["rule"] == "compressor-type"
    assert a[first["id"]]["notes"] == f"prefill (compressor-type): same decision as {target}"


def test_annotation_must_check_clean():
    with pytest.raises(PrefillError, match="annotate-check"):
        _run(ann=ANNOTATION.replace("HEAT RECOVERY CONDENSER COIL", "NOPE"))


def test_output_is_deterministic_and_loads(tmp_path):
    master = tmp_path / "m.SEC"
    master.write_bytes(MINI.encode(secfile.ENCODING))
    ddf = tmp_path / "dd.json"
    ddf.write_text(json.dumps(DD), encoding="utf-8")
    annf = tmp_path / "a.yaml"
    annf.write_text(ANNOTATION, encoding="utf-8")
    out = tmp_path / "m.answers.json"
    args = ["prefill", str(master), "--design-data", str(ddf), "--annotation", str(annf), "-o", str(out)]
    assert main(args) == 0
    first = out.read_bytes()
    assert main(args) == 1                     # refuses to overwrite (D5)
    assert main(args + ["--force"]) == 0
    assert out.read_bytes() == first           # byte-identical rerun
    report = (tmp_path / "m.answers.prefill.md").read_text(encoding="utf-8")
    assert "heat-recovery" in report and "needs bod.heat_recovery" in report
    profile, answers, fp = read_answers_json(out)
    assert profile["ARMY"] == "remove" and fp
    assert any(r.get("notes", "").endswith("needs bod.heat_recovery") for r in answers.values())


def test_prefill_then_generate(tmp_path):
    master = tmp_path / "m.SEC"
    master.write_bytes(MINI.encode(secfile.ENCODING))
    _, res = _run()
    p = tmp_path / "a.json"
    p.write_text(json.dumps(res.payload), encoding="utf-8")
    profile, answers, fp = read_answers_json(p)
    s = generate(master, profile, answers, tmp_path / "o.sec", revisions=True,
                 fingerprint=fp, strict=True)
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    assert "<TTL>Scroll Type Chiller</TTL>" in out
    assert "Compressor driver: electric motor." in out
    assert "Refrigerant R-454B." in out and "Capacity 1123.1 kW" in out
    assert "Centrifugal text" not in out and "Engine" not in out
    assert "Army reviewer" not in out and "Air Force reviewer" in out
    assert "100 tons" in out and "352 kW" not in out
    assert "Heat recovery text." in out          # unresolved: kept by default
    assert "[Provide a factory sound test.]" in out
    assert s["subsections_removed"] == 2
