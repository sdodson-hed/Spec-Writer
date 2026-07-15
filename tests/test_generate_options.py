import json

from specgen import secfile
from specgen.generate import generate

SRC = "<SEC><TXT>Provide [scroll][screw][rotary] compressors.</TXT></SEC>"


def _redline(tmp_path, answer):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    summary = generate(
        master, {}, {"BRK-0001": {"answer": answer, "notes": ""}}, out
    )
    result = out.read_bytes().decode(secfile.ENCODING)
    changes = json.loads(
        out.with_suffix(".redline.json").read_text(encoding="utf-8")
    )["changes"]
    change = next(c for c in changes if c["id"] == "BRK-0001")
    return summary, result, change


def test_out_of_range_option_number_is_literal_custom_text(tmp_path):
    # 3-option group; "5" is not a valid option number, so it must be
    # spliced in as literal custom text rather than raising.
    _summary, result, change = _redline(tmp_path, "5")
    assert "5" in result
    assert "[scroll]" not in result and "[screw]" not in result
    assert change["action"] == "custom text"
    assert change["after"] == "5"


def test_in_range_option_number_still_picks_option(tmp_path):
    _summary, result, change = _redline(tmp_path, "2")
    assert "screw" in result
    assert "scroll" not in result and "rotary" not in result
    assert change["action"] == "chose option [2]"


def test_multi_number_answer_picks_both_options(tmp_path):
    _summary, result, change = _redline(tmp_path, "1,3")
    assert "scroll" in result and "rotary" in result
    assert "screw" not in result
    assert change["action"] == "chose option [1, 3]"
