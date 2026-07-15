from pathlib import Path

import pytest

from specgen import secfile
from specgen.audit import audit_source

CORPUS = Path(__file__).resolve().parent.parent / "masters" / "Specifications"

pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="corpus not present")


@pytest.mark.parametrize("path", sorted(CORPUS.glob("*.SEC")), ids=lambda p: p.stem)
def test_roundtrip_and_audit(path):
    sec = secfile.parse(path)
    assert sec.roundtrips(), "round-trip must stay byte-identical"
    report = audit_source(sec.source, sec.root)
    assert report["unknowns"] == [], report["unknowns"][:3]
