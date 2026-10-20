"""A duplicate's first instance answered by prefill follows the decision it
copies (same_as), including the engineer's override or a conflict. Without
this, overriding the 2.4.1 compressor choice left the submittal list's copy
at Scroll (found in the step 7 browser check)."""

import json

import yaml

from specgen import secfile
from specgen.annotation import from_dict as ann_from_dict
from specgen.designdata import from_dict as dd_from_dict
from specgen.generate import generate
from specgen.manifest import build_manifest
from specgen.prefill import prefill
from tests.test_annotation import ANNOTATION, MINI
from tests.test_prefill import DD

SRC = MINI.replace(
    "<SPT><TTL>SUMMARY</TTL>",
    "<SPT><TTL>SUBMITTALS</TTL><ITM><SUB>[Scroll][Screw][Centrifugal] Type Chiller</SUB></ITM></SPT>"
    "<SPT><TTL>SUMMARY</TTL>")


def _payload():
    m = build_manifest(secfile.parse_source(SRC))
    res = prefill(m, dd_from_dict(json.loads(json.dumps(DD))), ann_from_dict(yaml.safe_load(ANNOTATION)))
    return m, res.payload


def _ids(p):
    by_id = {v["id"]: k for k, v in p["answers"].items()}
    target = next(v for v in p["answers"].values() if v.get("source", {}).get("rule") == "compressor-type"
                  and not v.get("same_as"))["id"]
    first = next(v for v in p["answers"].values() if v.get("same_as") == target)["id"]
    return by_id, target, first


def test_prefill_marks_the_first_instance():
    _, p = _payload()
    by_id, target, first = _ids(p)
    assert p["answers"][by_id[first]]["same_as"] == target


def _gen(tmp_path, p):
    master = tmp_path / "m.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    a = tmp_path / "a.json"
    a.write_text(json.dumps(p), encoding="utf-8")
    from specgen.answers import read_answers_json
    profile, answers, fp = read_answers_json(a)
    generate(master, profile, answers, tmp_path / "o.sec", fingerprint=fp)
    return ((tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING),
            (tmp_path / "o.unresolved.md").read_text(encoding="utf-8"))


def test_override_reaches_the_first_instance(tmp_path):
    _, p = _payload()
    by_id, target, first = _ids(p)
    rec = p["answers"][by_id[target]]
    p["answers"][by_id[target]] = {**rec, "answer": "2", "state": "overridden",
                                   "source": {"kind": "manual", "was": {**rec["source"], "answer": "1"}}}
    out, _ = _gen(tmp_path, p)
    assert "<SUB>Screw Type Chiller</SUB>" in out          # the submittal-list copy
    assert "<TTL>Screw Type Chiller</TTL>" in out
    assert "Scroll" not in out


def test_conflict_holds_both_instances(tmp_path):
    _, p = _payload()
    by_id, target, first = _ids(p)
    rec = p["answers"][by_id[target]]
    p["answers"][by_id[target]] = {
        **rec, "answer": "2", "state": "conflict",
        "source": {"kind": "manual", "was": {**rec["source"], "answer": "1"},
                   "now": {**rec["source"], "value": "CENTRIFUGAL", "answer": "3"}}}
    out, md = _gen(tmp_path, p)
    assert out.count("[Scroll][Screw][Centrifugal]") == 2
    assert md.count("conflict: engineer answer '2'") == 2
