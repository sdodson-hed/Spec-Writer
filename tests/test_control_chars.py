"""Control characters XML 1.0 forbids (C0 except tab, LF, CR) are kept byte
for byte and reported as source defects. 22 60 70 ships one: "Dental
Surgical Vacuum\\x13" in a table cell (WBDG and SpecsIntact, July 2026).
Before, the audit passed it as clean and generate crashed in its XML check."""

import pytest

from specgen import secfile
from specgen.audit import audit_file
from specgen.cli import main
from specgen.generate import generate
from tests.test_annotation import MINI

FORBIDDEN = [c for c in range(32) if c not in (9, 10, 13)]


def _master(tmp_path, ch=b"\x13"):
    src = MINI.encode("windows-1252").replace(b"Centrifugal text.", b"Dental Surgical Vacuum" + ch)
    p = tmp_path / "m.SEC"
    p.write_bytes(src)
    return p, src


def test_parse_round_trips_and_reports_the_character(tmp_path):
    p, src = _master(tmp_path)
    for tolerant in (False, True):
        sec = secfile.parse(p, tolerant=tolerant)
        assert sec.serialize().encode(secfile.ENCODING) == src
        (d,) = sec.defects
        assert d["type"] == "control-character" and d["raw"] == "\x13"
        assert sec.source[d["offset"]] == "\x13"


def test_audit_reports_a_source_defect(tmp_path, capsys):
    p, _ = _master(tmp_path)
    assert main(["audit", str(p)]) == 2
    out = capsys.readouterr().out
    assert "DEFECT control-character '\\x13'" in out and "Vacuum\\x13" in out


def test_generate_keeps_the_character_instead_of_crashing(tmp_path):
    p, _ = _master(tmp_path)
    s = generate(p, {}, {}, tmp_path / "o.sec")
    assert s["source_defects"] == 1
    assert b"Dental Surgical Vacuum\x13" in (tmp_path / "o.sec").read_bytes()


@pytest.mark.parametrize("c", FORBIDDEN)
def test_each_forbidden_character_is_reported(c):
    src = MINI.replace("Centrifugal text.", "x" + chr(c) + "y")
    assert [d["type"] for d in secfile.parse_source(src).defects] == ["control-character"]


def test_tab_lf_cr_are_not_defects():
    src = MINI.replace("Centrifugal text.", "a\tb\r\nc\nd")
    assert secfile.parse_source(src).defects == []
