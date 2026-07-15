"""Unit tests for the pure JS edit core, run under Node when available.

The core is DOM-free by design so it can be tested headlessly. The harness
appends assertions to the core source and runs `node` on the result; any
failed assertion exits non-zero with a message.
"""

import shutil
import subprocess

import pytest

from specgen.htmlpage import EDIT_CORE_JS

HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
const TEXT = "0123456789ABCDEF";       // stand-in master text
const S = 2, E = 12;                   // gap covers "23456789AB"

// fresh gap: one original run
eq(gapRuns(TEXT, {}, S, E), [{t:"o",text:"23456789AB"}], "fresh gap");

// type "xy" at display 3 -> ins run, caret after typed text
let r = applyGapOp(TEXT, {}, S, E, {kind:"ins", at:3, text:"xy"}, []);
eq(r.records, {"ME@5":{start:5,end:5,before:"",after:"xy",notes:""}}, "insert record");
eq(r.caret, 5, "insert caret");
// display is now "234xy56789AB"

// backspace at caret 5 removes the typed 'y' for real
r = applyGapOp(TEXT, r.records, S, E, {kind:"bs", caret:5}, []);
eq(r.records, {"ME@5":{start:5,end:5,before:"",after:"x",notes:""}}, "bs on ins char");
eq(r.caret, 4, "bs caret");
// display "234x56789AB"

// select display [4,6) = original "56" and delete -> strikethrough, coalesced
r = applyGapOp(TEXT, r.records, S, E, {kind:"del", from:4, to:6}, []);
eq(r.records, {"ME@5":{start:5,end:7,before:"56",after:"x",notes:""}}, "coalesced d+i");
// canonical display "234" + del"56" + ins"x" + "789AB" = "23456x789AB"
eq(r.caret, 5, "selection-delete caret sits after the strikethrough");

// backspace with the caret right after the struck run skips it, strikes '4'
r = applyGapOp(TEXT, r.records, S, E, {kind:"bs", caret:5}, []);
eq(r.records["ME@4"], {start:4,end:7,before:"456",after:"x",notes:""}, "bs skips struck run");
eq(Object.keys(r.records).length, 1, "records merged");
eq(r.caret, 2, "bs caret lands before the strikethrough");

// typed-then-erased no-op records are dropped
let n = applyGapOp(TEXT, {}, S, E, {kind:"ins", at:3, text:"q"}, []);
n = applyGapOp(TEXT, n.records, S, E, {kind:"bs", caret:4}, []);
eq(n.records, {}, "no-op record dropped");

// notes carry over when start+before are unchanged
let withNote = {"ME@5":{start:5,end:7,before:"56",after:"x",notes:"why"}};
// display is "234"+d"56"+i"x"+"789AB"; at:8 sits right before orig '9' (ME@9)
let k = applyGapOp(TEXT, withNote, S, E, {kind:"ins", at:8, text:"Z"}, []);
eq(k.records["ME@5"].notes, "why", "note carried");
eq(k.records["ME@9"], {start:9,end:9,before:"",after:"Z",notes:""}, "second record");

// replace: selection typed over -> strike + insert after the strikethrough
let rp = applyGapOp(TEXT, {}, S, E, {kind:"replace", from:1, to:3, text:"NEW"}, []);
eq(rp.records, {"ME@3":{start:3,end:5,before:"34",after:"NEW",notes:""}}, "replace record");
eq(rp.caret, 6, "replace caret after inserted text");

// forward delete targets the next unstruck char
let fw = applyGapOp(TEXT, {"ME@3":{start:3,end:5,before:"34",after:"",notes:""}}, S, E,
                    {kind:"fwd", caret:1}, []);
eq(fw.records["ME@3"], {start:3,end:6,before:"345",after:"",notes:""}, "fwd extends strike");

// boundary: backspace at display 0 is a null (nothing to do)
eq(applyGapOp(TEXT, {}, S, E, {kind:"bs", caret:0}, []), null, "bs at gap start");

// locked ranges block ops that touch them; boundary insert is allowed
const LOCKED = [[7, 9]];  // original "78"
eq(applyGapOp(TEXT, {}, S, E, {kind:"del", from:4, to:6}, LOCKED), {blocked:true}, "del into locked");
eq(applyGapOp(TEXT, {}, S, E, {kind:"ins", at:6, text:"w"}, LOCKED), {blocked:true}, "ins inside locked");
let ok = applyGapOp(TEXT, {}, S, E, {kind:"ins", at:5, text:"w"}, LOCKED);
eq(ok.records, {"ME@7":{start:7,end:7,before:"",after:"w",notes:""}}, "ins at locked boundary ok");

// invariant: o+d text always reconstructs the original slice
function odText(runs) { return runs.filter(r2 => r2.t !== "i").map(r2 => r2.text).join(""); }
eq(odText(gapRuns(TEXT, r.records, S, E)), TEXT.slice(S, E), "o+d invariant");

// origToDisplay maps original offsets through insertions: display is
// "234" + "56"(struck) + "xxx"(ins) + "789AB"; orig 9 ("9") -> display 10
let runs2 = gapRuns(TEXT, {"ME@5":{start:5,end:7,before:"56",after:"xxx",notes:""}}, S, E);
eq(origToDisplay(runs2, S, 9), 10, "orig offset through a d+i cluster");

// DOM<->display conversion: the HTML parser collapses \r\n to \n, so a \r
// followed by \n is zero-width in the DOM
const D = "ab\r\ncd\r\nef";
eq(dispToDom(D, D.length), 8, "CRLF pairs are one DOM char");
eq(domToDisp(D, 8), D.length, "DOM end maps to display end");
eq(dispToDom(D, 4), 3, "display offset after a CRLF pair");
eq(domToDisp(D, 3), 4, "DOM offset after the collapsed newline");
eq(domToDisp(D, 2), 2, "end-of-line DOM caret maps before the \\r");
eq(dispToDom(D, 2), 2, "display offset before the \\r round-trips");
eq(domToDisp("abc", 2), 2, "LF-free text is identity");
eq(dispToDom("a\rb", 3), 3, "lone \\r keeps its width (parser turns it into \\n)");
console.log("OK");
"""


def _node():
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="node not on PATH")
def test_edit_core_under_node(tmp_path):
    js = tmp_path / "core_test.js"
    js.write_text(EDIT_CORE_JS + HARNESS, encoding="utf-8")
    proc = subprocess.run(
        [_node(), str(js)], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "OK" in proc.stdout


def test_edit_core_is_injected_into_page(tmp_path):
    from specgen import secfile
    from specgen.htmlpage import write_html
    from specgen.manifest import build_manifest

    p = tmp_path / "t.SEC"
    p.write_bytes(
        "<SEC><TXT>Provide [scroll][screw] compressors.</TXT></SEC>".encode(
            secfile.ENCODING
        )
    )
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "function applyGapOp(" in html
    assert "function gapRuns(" in html
    assert "__EDIT_CORE__" not in html
