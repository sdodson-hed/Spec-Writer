from specgen import secfile
from specgen.answers import UNITS_KEY, read_answers_json
from specgen.generate import generate
from specgen.manifest import build_manifest

UNITS = (
    "<SEC><TXT>capacity of<MET> 500 kW</MET><ENG> 142 tons</ENG> minimum, "
    "weight<MET> 23 kg</MET><ENG> 50 pounds</ENG>.</TXT></SEC>"
)


def test_manifest_unit_spans(tmp_path):
    p = tmp_path / "u.SEC"
    p.write_bytes(UNITS.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    assert m["counts"]["unit_pairs"] == 2
    s = m["unit_spans"][0]
    assert m["text"][s["met"][0] : s["met"][1]] == " 500 kW"
    assert m["text"][s["eng"][0] : s["eng"][1]] == " 142 tons"


def test_generate_keeps_si(tmp_path):
    p = tmp_path / "u.SEC"
    p.write_bytes(UNITS.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    generate(p, {UNITS_KEY: "si"}, {}, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "500 kW" in result and "142 tons" not in result
    assert "<ENG>" not in result and "</ENG>" not in result


NOTE_UNITS = (
    "<SEC><NTE>Use<MET> 1 kW</MET><ENG> 1 ton</ENG> in schedules.</NTE>"
    "<TXT>capacity of<MET> 500 kW</MET><ENG> 142 tons</ENG> minimum.</TXT></SEC>"
)


def test_note_units_never_touched(tmp_path):
    p = tmp_path / "n.SEC"
    p.write_bytes(NOTE_UNITS.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    assert m["counts"]["unit_pairs"] == 1  # note pair not counted
    assert len(m["unit_spans"]) == 1
    out = tmp_path / "out.sec"
    generate(p, {UNITS_KEY: "si"}, {}, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "<ENG> 1 ton</ENG>" in result  # designer note untouched
    assert "142 tons" not in result  # body ENG removed


def test_readers_accept_units(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        '{"profile": {"%s": "si", "ARMY": "remove"}}' % UNITS_KEY,
        encoding="utf-8",
    )
    profile, _, _ = read_answers_json(p)
    assert profile[UNITS_KEY] == "si"
    assert profile["ARMY"] == "remove"
