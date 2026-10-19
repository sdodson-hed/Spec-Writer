"""Tolerant parse mode: UFGS 01 42 00 (UMRL July 2026) ships a stray </URL>
in its NORSOK entry. Tolerant mode keeps it as a Misc node so round-trip
stays byte-identical, and records it as a source defect for audit."""

import pytest

from specgen import secfile
from specgen.audit import audit_source
from specgen.cli import main
from specgen.generate import generate
from specgen.secfile import Misc, SecParseError

# 01 42 00 (WBDG, UMRL July 2026), NORSOK entry, reduced
NORSOK = (
    '<SEC><PRT><TTL>PART 1 GENERAL</TTL><OAD>Internet: '
    '<URL HREF="https://standard.no/en"/>http://www.nsf.org</URL><BRK/>\r\n'
    "</OAD><TXT>Provide [one][two].</TXT></PRT></SEC>"
)


def test_strict_mode_still_rejects():
    with pytest.raises(SecParseError, match="Mismatched </URL>"):
        secfile.parse_source(NORSOK)


def test_tolerant_mode_keeps_bytes_and_records_defect():
    sec = secfile.parse_source(NORSOK, tolerant=True)
    assert sec.roundtrips()
    assert sec.serialize() == NORSOK
    [d] = sec.defects
    assert (d["type"], d["tag"], d["raw"], d["open"]) == (
        "stray-close-tag", "URL", "</URL>", "OAD")
    assert NORSOK[d["offset"]:].startswith("</URL>")
    oad = next(sec.root.iter("OAD"))
    assert any(isinstance(c, Misc) and c.raw == "</URL>" for c in oad.children)


def test_clean_file_has_no_defects():
    assert secfile.parse_source("<SEC><TXT>x</TXT></SEC>", tolerant=True).defects == []


def test_tolerant_mode_does_not_hide_real_nesting_errors():
    # </TXT> matches an element deeper in the stack: a structural error, not
    # a stray tag, and it must still raise
    with pytest.raises(SecParseError):
        secfile.parse_source("<SEC><TXT><B>x</TXT></B></SEC>", tolerant=True)


def test_audit_reports_defect_not_pass():
    sec = secfile.parse_source(NORSOK, tolerant=True)
    rep = audit_source(sec.source, sec.root, sec.defects)
    assert rep["unknowns"] == []
    [d] = rep["defects"]
    assert d["raw"] == "</URL>" and "nsf.org" in d["context"]


def test_audit_cli_exit_codes(tmp_path):
    defect = tmp_path / "defect.SEC"
    defect.write_bytes(NORSOK.encode(secfile.ENCODING))
    assert main(["audit", str(defect)]) == 2
    both = tmp_path / "both.SEC"
    both.write_bytes(NORSOK.replace("[one][two]", "[one").encode(secfile.ENCODING))
    assert main(["audit", str(both)]) == 1  # unknowns outrank defects
    clean = tmp_path / "clean.SEC"
    clean.write_bytes(b"<SEC><TXT>Provide [a][b].</TXT></SEC>")
    assert main(["audit", str(clean)]) == 0


def test_generate_runs_on_defective_master(tmp_path):
    m = tmp_path / "01 42 00.SEC"
    m.write_bytes(NORSOK.encode(secfile.ENCODING))
    s = generate(m, {}, {"BRK-0001": {"answer": "2"}}, tmp_path / "o.sec",
                 revisions=True)
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    assert "Provide two." in out and "</URL>" in out
    assert s["source_defects"] == 1


def test_verification_rejects_a_new_defect():
    from specgen.generate import GenerateError, _check_well_formed

    out = secfile.parse_source(NORSOK.replace("</OAD>", "</B></OAD>"), tolerant=True)
    master = secfile.parse_source(NORSOK, tolerant=True)
    with pytest.raises(GenerateError, match="defects the master does not"):
        _check_well_formed(out, master.defects, "output")


def test_defect_removed_with_tailoring_block_is_fine(tmp_path):
    src = NORSOK.replace("<OAD>", '<TAI OPT="NAVY"><OAD>').replace(
        "</OAD>", "</OAD></TAI>")
    m = tmp_path / "t.SEC"
    m.write_bytes(src.encode(secfile.ENCODING))
    generate(m, {"NAVY": "remove"}, {}, tmp_path / "o.sec", revisions=True)
    out = (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING)
    assert "</URL>" not in out
