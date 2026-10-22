"""Bytes windows-1252 leaves undefined (0x81 0x8D 0x8F 0x90 0x9D) round-trip
and are reported as source defects. SpecsIntact's own UFGS library has one:
02 83 00 ships "off\\x81-site" (July 2026). Python's windows-1252 codec
refuses those bytes, so the parser crashed on the whole file."""

import pytest

from specgen import secfile
from specgen.audit import audit_file
from specgen.cli import main
from specgen.generate import generate
from tests.test_annotation import MINI

UNDEFINED = [0x81, 0x8D, 0x8F, 0x90, 0x9D]


def test_every_byte_round_trips():
    raw = bytes(range(256))
    assert raw.decode(secfile.ENCODING).encode(secfile.ENCODING) == raw


def test_defined_bytes_decode_as_windows_1252():
    defined = bytes(b for b in range(256) if b not in UNDEFINED)
    assert defined.decode(secfile.ENCODING) == defined.decode("windows-1252")
    for b in UNDEFINED:
        assert bytes([b]).decode(secfile.ENCODING) == chr(b)   # as Windows maps them


def _master(tmp_path):
    src = MINI.encode("windows-1252").replace(b"Centrifugal text.", b"off\x81-site text.")
    p = tmp_path / "m.SEC"
    p.write_bytes(src)
    return p, src


def test_parse_round_trips_and_reports_the_byte(tmp_path):
    p, src = _master(tmp_path)
    for tolerant in (False, True):
        sec = secfile.parse(p, tolerant=tolerant)
        assert sec.serialize().encode(secfile.ENCODING) == src
        (d,) = sec.defects
        assert d["type"] == "undefined-byte" and d["raw"] == "\x81"
        assert sec.source[d["offset"]] == "\x81"


def test_audit_reports_a_source_defect(tmp_path, capsys):
    p, _ = _master(tmp_path)
    assert [d["type"] for d in audit_file(p)["defects"]] == ["undefined-byte"]
    assert main(["audit", str(p)]) == 2
    out = capsys.readouterr().out
    assert "DEFECT undefined-byte '\\x81'" in out and "SOURCE DEFECT: 1" in out


def test_generate_keeps_the_byte(tmp_path, capsys):
    p, _ = _master(tmp_path)
    s = generate(p, {}, {}, tmp_path / "o.sec")
    assert s["source_defects"] == 1
    assert b"off\x81-site text." in (tmp_path / "o.sec").read_bytes()


@pytest.mark.parametrize("b", UNDEFINED)
def test_each_undefined_byte_is_reported(b):
    src = MINI.replace("Centrifugal text.", "x" + chr(b) + "y")
    assert [d["raw"] for d in secfile.parse_source(src).defects] == [chr(b)]
