"""Decision page: subsection keep/remove (plan 2026-10-19, Task 6).

The pure helpers in STRUCT_CORE_JS run under Node when available (CI has
it); the template tests check the page wires them in."""

import shutil
import subprocess

import pytest

from specgen import secfile
from specgen.htmlpage import STRUCT_CORE_JS, write_html
from specgen.manifest import build_manifest
from tests.test_subsections import SRC

HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
// P > C1 > G (governed by BRK-1); P > C2; Q (no parent)
const SUBS = [
  {id: "P", parent: null, governed_by: null, span: [0, 100]},
  {id: "C1", parent: "P", governed_by: null, span: [10, 40]},
  {id: "G", parent: "C1", governed_by: "BRK-1", span: [20, 30]},
  {id: "C2", parent: "P", governed_by: null, span: [50, 90]},
  {id: "Q", parent: null, governed_by: "BRK-2", span: [120, 160]},
];
const none = () => "";
const ids = s => [...s].sort();

eq(ids(removedSubsections(SUBS, {}, none)), [], "nothing answered");
eq(ids(removedSubsections(SUBS, {C1: "remove"}, none)), ["C1", "G"], "child goes with parent");
eq(ids(removedSubsections(SUBS, {P: "remove", C2: "keep"}, none)),
   ["C1", "C2", "G", "P"], "keep under a removed parent has no effect");
eq(ids(removedSubsections(SUBS, {G: "remove"}, none)), [],
   "governed rows follow their bracket, not state.spt");
eq(ids(removedSubsections(SUBS, {}, id => id === "BRK-2" ? "Delete" : "")), ["Q"],
   "bracket delete removes its governed subsection");
eq(ids(removedSubsections(SUBS, {}, id => id === "BRK-1" ? "keep" : "")), [],
   "bracket keep keeps it");

// collapsed blocks: removed subsections whose parent stays, and not governed
// (a governed one already renders through its bracket mark)
eq(removedRoots(SUBS, removedSubsections(SUBS, {C1: "remove"}, none)).map(s => s.id),
   ["C1"], "root of a removed subtree");
eq(removedRoots(SUBS, removedSubsections(SUBS, {}, id => id === "BRK-2" ? "delete" : "")),
   [], "governed removal renders through the bracket");

eq(insideAny(12, 18, [[10, 40]]), true, "inside");
eq(insideAny(10, 40, [[10, 40]]), true, "same bounds");
eq(insideAny(5, 18, [[10, 40]]), false, "straddles");
eq(insideAny(12, 18, []), false, "no spans");
console.log("OK");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_struct_core_under_node(tmp_path):
    js = tmp_path / "t.js"
    js.write_text(STRUCT_CORE_JS + HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "OK"


def _page(tmp_path):
    out = tmp_path / "t.html"
    m = build_manifest(secfile.parse_source(SRC))
    write_html(m, out)
    return m, out.read_text(encoding="utf-8")


def test_nav_entries_point_at_their_subsection():
    m = build_manifest(secfile.parse_source(SRC))
    spt_rows = [n for n in m["nav"] if n["depth"] > 0]
    assert [n["spt"] for n in spt_rows] == [s["id"] for s in m["subsections"]]
    assert all("spt" not in n for n in m["nav"] if n["depth"] == 0)


def test_page_wires_subsection_decisions(tmp_path):
    _, html = _page(tmp_path)
    assert "function removedSubsections(" in html      # core injected
    assert "__STRUCT_CORE__" not in html
    assert 'data-spt-act="remove"' in html               # outline buttons
    assert "sptcut" in html                              # collapsed block
    assert "inRemoved(d)" in html                        # counter / gate filter
    assert "state.spt" in html


def test_export_and_import_handle_subsection_anchors(tmp_path):
    _, html = _page(tmp_path)
    assert "subByAnchor" in html                         # import side
    assert "keyed[s.anchor]" in html                     # export side
