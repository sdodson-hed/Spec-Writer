"""Corpus gate for subsection removal (plan 2026-10-19, Task 5).

For every master, answer every 5th subsection "remove" and run generate
with --revisions. generate's own verification is the main assertion: the
output parses, round-trips, is well-formed, carries no tracking marker, and
the revisions file resolves to the output and reverts to the master. Runs
only with SPECGEN_CORPUS set (the corpus is not in the repo)."""

import os
from pathlib import Path

import pytest

from specgen import secfile
from specgen.generate import generate
from specgen.manifest import build_manifest

CORPUS = Path(os.environ["SPECGEN_CORPUS"]) if os.environ.get("SPECGEN_CORPUS") else None
FILES = (
    sorted(p for p in CORPUS.rglob("*") if p.suffix.lower() == ".sec")
    if CORPUS and CORPUS.is_dir()
    else []
)

# Masters generate cannot verify as shipped, with the reason.
KNOWN_MALFORMED = {
    "22 60 70": "\\x13 control character in a <DTA> header field (not XML 1.0)",
}

pytestmark = pytest.mark.skipif(not FILES, reason="SPECGEN_CORPUS not set")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_remove_every_fifth_subsection(path, tmp_path):
    if path.stem in KNOWN_MALFORMED:
        pytest.skip(KNOWN_MALFORMED[path.stem])
    m = build_manifest(secfile.parse(path, tolerant=True))
    subs = {s["id"]: s for s in m["subsections"]}
    asked = [s for s in m["subsections"][::5]]
    asked_ids = {s["id"] for s in asked}
    answers = {s["anchor"]: {"answer": "remove", "id": s["id"]} for s in asked}

    summary = generate(path, {}, answers, tmp_path / "o.sec", revisions=True)

    def has_asked_ancestor(sid):
        p = subs[sid]["parent"]
        while p:
            if p in asked_ids:
                return True
            p = subs[p]["parent"]
        return False

    # governed subsections become bracket deletions, nested ones go with
    # their ancestor; every other answered subsection is removed itself
    expected = sum(
        1 for s in asked if not s["governed_by"] and not has_asked_ancestor(s["id"])
    )
    assert summary["subsections_removed"] == expected
    assert summary["answers_orphaned"] == 0

    # independent of generate's own bookkeeping: count what is left. Every
    # asked subsection without an asked ancestor goes, with its whole
    # subtree (governed ones through their bracket); nothing else changes.
    def subtree(sid):
        return 1 + sum(subtree(c) for c, s in subs.items() if s["parent"] == sid)

    gone = sum(subtree(s["id"]) for s in asked if not has_asked_ancestor(s["id"]))
    out = secfile.parse(tmp_path / "o.sec", tolerant=True)
    assert sum(1 for _ in out.root.iter("SPT")) == len(subs) - gone
