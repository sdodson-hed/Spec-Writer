"""prefill re-runs merge into the existing answers file (plan 2026-10-20
provenance, Task 2, decisions D4 and D5)."""

import json

from specgen import secfile
from specgen.cli import main
from tests.test_annotation import ANNOTATION, MINI
from tests.test_prefill import ACC1, DD


def _setup(tmp_path, dd=DD):
    master = tmp_path / "m.SEC"
    master.write_bytes(MINI.encode(secfile.ENCODING))
    ddf = tmp_path / "dd.json"
    ddf.write_text(json.dumps(dd), encoding="utf-8")
    annf = tmp_path / "a.yaml"
    annf.write_text(ANNOTATION, encoding="utf-8")
    out = tmp_path / "m.answers.json"
    args = ["prefill", str(master), "--design-data", str(ddf), "--annotation", str(annf), "-o", str(out)]
    return args, ddf, out


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_profile_meta_written():
    from specgen.annotation import from_dict as ann
    from specgen.designdata import from_dict as dd
    from specgen.manifest import build_manifest
    from specgen.prefill import prefill
    import yaml
    res = prefill(build_manifest(secfile.parse_source(MINI)), dd(json.loads(json.dumps(DD))),
                  ann(yaml.safe_load(ANNOTATION)))
    meta = res.payload["profile_meta"]
    assert meta["ARMY"] == {"source": {"kind": "rule", "ref": "project.agency", "value": "AIR FORCE"},
                            "state": "auto"}
    assert meta["UNITS OF MEASURE (SI/IP)"]["source"]["ref"] == "project.units"
    assert res.payload["prefill"]["merge"] == []


def test_rerun_unchanged_is_byte_identical(tmp_path):
    args, _, out = _setup(tmp_path)
    assert main(args) == 0
    first = out.read_bytes()
    assert main(args) == 0          # merges now (D4), no --force needed
    assert out.read_bytes() == first


def test_override_survives_and_conflicts_when_data_changes(tmp_path, capsys):
    args, ddf, out = _setup(tmp_path)
    assert main(args) == 0
    p = _load(out)
    answers = p["answers"]
    ref_key = next(k for k, v in answers.items() if v.get("source", {}).get("rule") == "refrigerant")
    # the engineer overrides the refrigerant on the page
    rec = answers[ref_key]
    answers[ref_key] = {**rec, "answer": "R-32",
                        "source": {"kind": "manual", "was": {**rec["source"], "answer": rec["answer"]}},
                        "state": "overridden"}
    # and sets an option prefill knows nothing about
    p["profile"]["NIAGARA"] = "remove"
    out.write_text(json.dumps(p), encoding="utf-8")

    assert main(args) == 0           # same data: override kept
    q = _load(out)
    assert q["answers"][ref_key]["answer"] == "R-32" and q["answers"][ref_key]["state"] == "overridden"
    assert q["profile"]["NIAGARA"] == "remove"
    capsys.readouterr()

    ddf.write_text(json.dumps({**DD, "equipment": [{**ACC1, "refrigerant": "R-1234ze"}]}),
                   encoding="utf-8")
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert "1 conflict" in printed
    r = _load(out)["answers"][ref_key]
    assert r["state"] == "conflict" and r["answer"] == "R-32"
    assert r["source"]["now"]["answer"] == "R-1234ze"
    md = (tmp_path / "m.answers.prefill.md").read_text(encoding="utf-8")
    assert "## Merge" in md
    assert "conflict" in md and "engineer answer 'R-32'; prefill now 'R-1234ze'" in md


def test_force_replaces(tmp_path):
    args, _, out = _setup(tmp_path)
    main(args)
    p = _load(out)
    k = next(iter(p["answers"]))
    p["answers"][k]["answer"] = "edited"
    p["answers"][k]["state"] = "overridden"
    out.write_text(json.dumps(p), encoding="utf-8")
    assert main(args + ["--force"]) == 0
    assert _load(out)["answers"][k]["answer"] != "edited"


def test_unreadable_existing_file_is_an_error(tmp_path, capsys):
    args, _, out = _setup(tmp_path)
    out.write_text("{not json", encoding="utf-8")
    assert main(args) == 1
    assert "cannot merge into" in capsys.readouterr().out
