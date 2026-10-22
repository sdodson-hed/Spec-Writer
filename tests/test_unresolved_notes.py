"""Unanswered decisions carry their reason into .unresolved.md (plan
2026-10-20, Task 5, decision D3)."""

import json

import yaml

from specgen import secfile
from specgen.annotation import from_dict as annotation_from_dict
from specgen.answers import read_answers_json
from specgen.designdata import from_dict as dd_from_dict
from specgen.generate import generate
from specgen.manifest import build_manifest
from specgen.prefill import prefill
from tests.test_annotation import ANNOTATION, MINI
from tests.test_prefill import DD

M = build_manifest(secfile.parse_source(MINI))
SUBS = {s["title"]: s for s in M["subsections"]}


def _gen(tmp_path, answers, **kw):
    p = tmp_path / "m.SEC"
    p.write_bytes(MINI.encode(secfile.ENCODING))
    s = generate(p, {}, answers, tmp_path / "o.sec", **kw)
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    changes = json.loads((tmp_path / "o.redline.json").read_text(encoding="utf-8"))["changes"]
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    return s, md, {c["id"]: c for c in changes}, out


def test_bracket_note_shown(tmp_path):
    d = next(d for d in M["decisions"] if d["kind"] == "optional")
    note = "prefill (sound-test): needs bod.sound_test"
    _, md, _, _ = _gen(tmp_path, {d["anchor"]: {"answer": "", "notes": note, "id": d["id"]}})
    block = md.split(f"## {d['id']}", 1)[1].split("## ", 1)[0]
    assert note in block


def test_bracket_keeps_its_id_and_note_when_edits_reshape_it(tmp_path):
    # Units removal edits text INSIDE an open optional bracket, so its option
    # text no longer matches the original exactly (23 64 26: 2.11.3 Glycol
    # Solution, 3.8 one-year inspection). It must still be reported as itself,
    # with prefill's note, not as an anonymous OPEN@ group.
    src = MINI.replace("[Provide a factory sound test.]",
                       "[Provide a factory sound test at <MET>3 m</MET><ENG>10 feet</ENG>.]")
    m = build_manifest(secfile.parse_source(src))
    d = next(d for d in m["decisions"] if d["kind"] == "optional" and "sound test" in d["options"][0])
    note = "prefill (sound-test): needs bod.sound_test"
    p = tmp_path / "m.SEC"
    p.write_bytes(src.encode(secfile.ENCODING))
    s = generate(p, {"UNITS OF MEASURE (SI/IP)": "ip"},
                 {d["anchor"]: {"answer": "", "notes": note, "id": d["id"]}}, tmp_path / "o.sec")
    assert s["units_removed"] >= 1
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    block = md.split(f"## {d['id']}", 1)[1].split("## ", 1)[0]
    assert note in block and "10 feet" in block and "3 m" not in block
    assert "OPEN@" not in md


def test_subsection_note_kept_by_default_and_listed(tmp_path):
    s = SUBS["Heat Recovery Condenser Coil"]
    note = "prefill (heat-recovery): needs bod.heat_recovery"
    summary, md, ch, out = _gen(tmp_path, {s["anchor"]: {"answer": "", "notes": note, "id": s["id"]}},
                                strict=True)
    assert "Heat recovery text." in out                      # kept by default
    assert (ch[s["id"]]["action"], ch[s["id"]]["source"]["kind"]) == ("kept by default", "default")
    assert ch[s["id"]]["notes"] == note
    block = md.split(f"## {s['id']}", 1)[1].split("## ", 1)[0]
    assert "subsection" in block and note in block and "kept by default until answered" in block
    assert f"{s['num']} Heat Recovery Condenser Coil" in block
    assert summary["subsections_answered"] == 0


def test_governed_subsection_note_goes_to_its_bracket(tmp_path):
    from tests.test_subsections import SRC as GOV_SRC

    m = build_manifest(secfile.parse_source(GOV_SRC))
    s = next(x for x in m["subsections"] if x["governed_by"])
    note = "prefill (no-centrifugal): needs ACC-1.compressor_type"
    p = tmp_path / "g.SEC"
    p.write_bytes(GOV_SRC.encode(secfile.ENCODING))
    generate(p, {}, {s["anchor"]: {"answer": "", "notes": note, "id": s["id"]}},
             tmp_path / "o.sec", strict=True)
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    block = md.split(f"## {s['governed_by']}", 1)[1].split("## ", 1)[0]
    assert note in block


def test_prefill_reasons_reach_unresolved(tmp_path):
    res = prefill(M, dd_from_dict(json.loads(json.dumps(DD))),
                  annotation_from_dict(yaml.safe_load(ANNOTATION)))
    a = tmp_path / "a.json"
    a.write_text(json.dumps(res.payload), encoding="utf-8")
    profile, answers, fp = read_answers_json(a)
    p = tmp_path / "m.SEC"
    p.write_bytes(MINI.encode(secfile.ENCODING))
    generate(p, profile, answers, tmp_path / "o.sec", fingerprint=fp, strict=True)
    md = (tmp_path / "o.unresolved.md").read_text(encoding="utf-8")
    assert "prefill (heat-recovery): needs bod.heat_recovery" in md
    assert "prefill (sound-test): needs bod.sound_test" in md
