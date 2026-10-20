"""Decision page: cleanup preview (plan 2026-10-20, Task 5).

cleanupPreview mirrors specgen.cleanup.plan_cleanup in text positions, so
the page strikes what generate will drop. Runs under Node when available
(CI); the template tests check the page wires it in."""

import shutil
import subprocess

import pytest

from specgen import secfile
from specgen.htmlpage import STRUCT_CORE_JS, write_html
from specgen.manifest import build_manifest
from tests.test_cleanup_manifest import SRC

HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
// removed subsection covers text [100, 200), labeled for the tooltip
const R = [[100, 200, "2.6.7 Gas Engine"]];
const C = {
  items: [
    {id: "I1", name: "Scroll", chars: [10, 20], use_chars: [[110, 115], [300, 305]], in_bracket: null},
    {id: "I2", name: "Engine", chars: [20, 30], use_chars: [[120, 126]], in_bracket: null},
    {id: "I3", name: "Plan", chars: [30, 40], use_chars: [[130, 134]], in_bracket: "BRK-9"},
    {id: "I4", name: "Unused", chars: [40, 50], use_chars: [], in_bracket: null},
    {id: "I5", name: "Inside", chars: [150, 160], use_chars: [[170, 175]], in_bracket: null},
    {id: "I6", name: "Log", chars: [60, 70], use_chars: [[140, 143]], in_bracket: null},
  ],
  heads: [
    {name: "SD-03", chars: [5, 9], items: ["I1", "I2", "I3"]},
    {name: "SD-06", chars: [55, 59], items: ["I6"]},
  ],
  refs: [
    {rid: "NFPA 37", chars: [80, 88], use_chars: [[180, 187]], in_bracket: null},
    {rid: "AHRI 450", chars: [70, 78], use_chars: [[190, 198]], in_bracket: null},
    {rid: "AHRI 550", chars: [78, 80], use_chars: [[400, 408]], in_bracket: null},
  ],
  orgs: [
    {org: "AHRI", chars: [70, 80], rids: ["AHRI 450", "AHRI 550"]},
    {org: "NFPA", chars: [80, 90], rids: ["NFPA 37"]},
  ],
};
const p = cleanupPreview(C, R);
const ids = p.struck.map(s => s.kind + ":" + s.id).sort();
eq(ids, ["reference-org:NFPA", "reference:AHRI 450", "sd-heading:SD-06",
         "submittal-item:I2", "submittal-item:I6"], "struck");
eq(p.struck.find(s => s.id === "I2").why, "2.6.7 Gas Engine", "tooltip label");
eq(p.struck.find(s => s.id === "I2").chars, [20, 30], "span");
eq(p.blocked, {"BRK-9": "Plan"}, "bracketed orphan blocked, not struck");
eq(cleanupPreview(C, []), {struck: [], blocked: {}}, "nothing removed");
console.log("OK");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_cleanup_preview_under_node(tmp_path):
    js = tmp_path / "t.js"
    js.write_text(STRUCT_CORE_JS + HARNESS, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "OK"


def test_page_wires_cleanup_preview(tmp_path):
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse_source(SRC)), out)
    html = out.read_text(encoding="utf-8")
    assert "function cleanupPreview(" in html
    assert "clncut" in html                    # struck item / reference
    assert "clnhint" in html                   # amber note on a blocked bracket
    assert "cleanupNow()" in html
