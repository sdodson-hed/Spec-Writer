"""Corpus gate. Runs on $SPECGEN_CORPUS (e.g. an extracted WBDG release) or
masters/Specifications; skips when neither exists."""

import os
from pathlib import Path

import pytest

from specgen import secfile
from specgen.audit import audit_source

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path(os.environ.get("SPECGEN_CORPUS") or ROOT / "masters" / "Specifications")
FILES = (
    sorted(p for p in CORPUS.rglob("*") if p.suffix.lower() == ".sec")
    if CORPUS.is_dir()
    else []
)

# Masters with a known source defect, parsed in tolerant mode. A defect in
# any other master fails until someone has looked at it.
KNOWN_DEFECTS = {"01 42 00"}  # NORSOK entry: stray </URL> (UMRL July 2026)

pytestmark = pytest.mark.skipif(not FILES, reason="corpus not present")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_roundtrip_and_audit(path):
    sec = secfile.parse(path, tolerant=True)
    assert sec.roundtrips(), "round-trip must stay byte-identical"
    report = audit_source(sec.source, sec.root, sec.defects)
    assert report["unknowns"] == [], report["unknowns"][:3]
    assert not sec.defects or path.stem in KNOWN_DEFECTS, sec.defects
