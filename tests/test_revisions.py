import pytest

from specgen import secfile
from specgen.answers import UNITS_KEY
from specgen.generate import (
    GenerateError,
    generate,
    resolve_revisions,
    revert_revisions,
)

SRC = (
    "<SEC><TXT>Provide [scroll][screw] compressors "
    "rated<MET> 5 kW</MET><ENG> 2 tons</ENG> with [_____] starts "
    "[and vibration isolation].</TXT>"
    '<TAI OPT="ARMY"><TXT2>army-only text</TXT2></TAI></SEC>'
)

ANSWERS = {
    "BRK-0001": {"answer": "1", "notes": ""},       # choose scroll
    "BRK-0002": {"answer": "6", "notes": ""},       # fill blank
    "BRK-0003": {"answer": "keep", "notes": ""},    # keep optional
}
PROFILE = {"ARMY": "remove", UNITS_KEY: "si"}


def test_revisions_identities(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    generate(master, PROFILE, ANSWERS, out, revisions=True)
    clean = out.read_bytes().decode(secfile.ENCODING)
    rev = (tmp_path / "out.revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert "<DEL>" in rev and "<ADD>" in rev
    assert resolve_revisions(rev) == clean
    assert revert_revisions(rev) == SRC


def test_clean_output_unchanged_by_flag(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    out1, out2 = tmp_path / "a.sec", tmp_path / "b.sec"
    generate(master, PROFILE, ANSWERS, out1, revisions=False)
    generate(master, PROFILE, ANSWERS, out2, revisions=True)
    assert out1.read_bytes() == out2.read_bytes()


def test_master_with_existing_revision_markup_refused(tmp_path):
    marked = "<SEC><TXT>Provide <DEL>x</DEL> compressors [scroll][screw].</TXT></SEC>"
    master = tmp_path / "t.SEC"
    master.write_bytes(marked.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    with pytest.raises(GenerateError, match="revision markup"):
        generate(master, {}, {"BRK-0001": {"answer": "1", "notes": ""}}, out,
                 revisions=True)
    # flag-off path is unaffected
    generate(master, {}, {"BRK-0001": {"answer": "1", "notes": ""}}, out,
             revisions=False)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "scroll" in result and "[screw]" not in result
