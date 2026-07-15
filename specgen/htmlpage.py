"""Single-file interactive HTML decision page — document-first layout.

`write_html(manifest, out_path)` renders the section's FULL TEXT as the main
view with every decision highlighted in place. Clicking a highlight opens
that decision's controls in the right-hand panel; answering updates the text
live (the chosen option replaces the bracketed alternatives), so the
engineer watches the spec resolve as they work.

No server, no dependencies; answers autosave to localStorage; Export
downloads an answers JSON that `specgen generate --answers x.json` consumes.
Semantics mirror the Excel workbook: choices pick options (or custom text or
delete), blanks take a value, optionals keep/delete, duplicates follow the
first instance unless overridden, plurals and tailoring are answered once in
the Project Profile block.
"""

from __future__ import annotations

import json
from pathlib import Path

from .answers import PLURAL_KEY, UNITS_KEY

# Pure edit-core: the run model behind inline editing. DOM-free by design so
# it is unit-testable under Node (tests/test_edit_core.py). Injected into
# _TEMPLATE at __EDIT_CORE__.
EDIT_CORE_JS = r"""
// ---- inline edit core (pure; no DOM, no globals) ----
// Runs {t:"o"|"d"|"i", text}: original kept, deleted original, inserted.
// Invariant: concatenated o+d texts === text.slice(s, e).
// "Display offsets" index the concatenation of ALL run texts (the visible
// redline text). Records are the ME@ format: {start,end,before,after,notes}
// in original-text offsets; insertion-only records have start === end.
function gapRuns(text, records, s, e) {
  const recs = Object.values(records || {})
    .filter(r => r.start >= s && r.end <= e)
    .sort((a, b) => a.start - b.start);
  const runs = [];
  let pos = s;
  for (const r of recs) {
    if (r.start > pos) runs.push({ t: "o", text: text.slice(pos, r.start) });
    if (r.before) runs.push({ t: "d", text: r.before });
    if (r.after) runs.push({ t: "i", text: r.after });
    pos = r.end;
  }
  if (pos < e) runs.push({ t: "o", text: text.slice(pos, e) });
  return runs;
}
function mergeRuns(runs) {
  const out = [];
  for (const r of runs) {
    if (!r.text) continue;
    const top = out[out.length - 1];
    if (top && top.t === r.t) top.text += r.text;
    else out.push({ t: r.t, text: r.text });
  }
  return out;
}
function splitRuns(runs, at) {
  const L = [], R = [];
  let pos = 0;
  for (const r of runs) {
    const end = pos + r.text.length;
    if (end <= at) L.push({ t: r.t, text: r.text });
    else if (pos >= at) R.push({ t: r.t, text: r.text });
    else {
      L.push({ t: r.t, text: r.text.slice(0, at - pos) });
      R.push({ t: r.t, text: r.text.slice(at - pos) });
    }
    pos = end;
  }
  return [L, R];
}
function runsToRecords(runs, gapStart, oldRecords) {
  const recs = {};
  let orig = gapStart, i = 0;
  while (i < runs.length) {
    if (runs[i].t === "o") { orig += runs[i].text.length; i++; continue; }
    const start = orig;
    let before = "", after = "";
    while (i < runs.length && runs[i].t !== "o") {
      if (runs[i].t === "d") { before += runs[i].text; orig += runs[i].text.length; }
      else after += runs[i].text;
      i++;
    }
    if (before === after) continue;   // typed-then-erased no-op
    const rec = { start, end: orig, before, after, notes: "" };
    for (const old of Object.values(oldRecords || {}))
      if (old.notes && old.start === start && old.before === before)
        rec.notes = old.notes;
    recs["ME@" + start] = rec;
  }
  return recs;
}
function origToDisplay(runs, gapStart, origOff) {
  let disp = 0, orig = gapStart;
  for (const r of runs) {
    if (r.t === "i") { disp += r.text.length; continue; }
    if (origOff <= orig + r.text.length) return disp + (origOff - orig);
    orig += r.text.length;
    disp += r.text.length;
  }
  return disp;
}
function displayToOrig(runs, gapStart, at) {
  // original offset at display position `at` (i chars are zero-width)
  let disp = 0, orig = gapStart;
  for (const r of runs) {
    const end = disp + r.text.length;
    if (at <= end) {
      if (r.t === "i") return orig;
      return orig + (at - disp);
    }
    disp = end;
    if (r.t !== "i") orig += r.text.length;
  }
  return orig;
}
function deleteTarget(runs, caret, dir) {
  // The single display char a collapsed Backspace (dir -1) / Delete (dir +1)
  // affects, skipping already-struck chars; null at the gap boundary.
  const types = [];
  for (const r of runs)
    for (let k = 0; k < r.text.length; k++) types.push(r.t);
  let i = dir < 0 ? caret - 1 : caret;
  while (i >= 0 && i < types.length && types[i] === "d") i += dir;
  if (i < 0 || i >= types.length) return null;
  return { from: i, to: i + 1 };
}
function skipDel(runs, at) {
  // an insertion point strictly inside a struck run moves to its end, so
  // replacement text always follows its strikethrough
  let pos = 0;
  for (const r of runs) {
    const end = pos + r.text.length;
    if (r.t === "d" && at > pos && at < end) return end;
    pos = end;
  }
  return at;
}
function insLead(runs, at) {
  // i chars in the caret's cluster strictly before display `at` (clusters
  // are maximal d/i stretches; an o run resets the count)
  let disp = 0, lead = 0;
  for (const r of runs) {
    const end = disp + r.text.length;
    if (r.t === "o" && end <= at) lead = 0;
    if (r.t === "i" && at > disp) lead += Math.min(at, end) - disp;
    if (end >= at) break;
    disp = end;
  }
  return lead;
}
function opBlocked(runs, gapStart, lockedOrig, from, to) {
  const a = displayToOrig(runs, gapStart, from);
  const b = displayToOrig(runs, gapStart, to);
  for (const [ls, le] of lockedOrig || []) {
    if (from === to ? a > ls && a < le : a < le && b > ls) return true;
  }
  return false;
}
function applyGapOp(text, records, s, e, op, lockedOrig) {
  let runs = gapRuns(text, records, s, e);
  const dispLen = runs.reduce((n, r) => n + r.text.length, 0);
  let from, to, ins = "";
  if (op.kind === "ins") { from = to = skipDel(runs, op.at); ins = op.text; }
  else if (op.kind === "replace") { from = op.from; to = op.to; ins = op.text; }
  else if (op.kind === "del") { from = op.from; to = op.to; }
  else {
    const t = deleteTarget(runs, op.caret, op.kind === "bs" ? -1 : 1);
    if (!t) return null;
    from = t.from; to = t.to;
  }
  if (from > to) { const x = from; from = to; to = x; }
  if (from < 0 || to > dispLen) return null;
  if (opBlocked(runs, s, lockedOrig, from, to)) return { blocked: true };
  // 1) strike/remove the selected range
  let struckEnd = from, struckNew = false;
  if (to > from) {
    const [L, MR] = splitRuns(runs, from);
    const [M, R] = splitRuns(MR, to - from);
    const mid = M.filter(r => r.t !== "i").map(r => ({ t: "d", text: r.text }));
    struckNew = mid.length > 0;
    struckEnd = from + mid.reduce((n, r) => n + r.text.length, 0);
    runs = mergeRuns([].concat(L, mid, R));
  }
  // 2) insert after the strikethrough
  let insAt = struckEnd, lead = 0;
  if (ins) {
    insAt = skipDel(runs, insAt);
    lead = insLead(runs, insAt);
    const [L2, R2] = splitRuns(runs, insAt);
    runs = mergeRuns([].concat(L2, [{ t: "i", text: ins }], R2));
  }
  const recs = runsToRecords(runs, s, records);
  // 3) caret in CANONICAL display space (records render d-then-i per cluster)
  let caret;
  if (!ins && !struckNew) {
    // pure removal of previously-inserted text with no new strikethrough:
    // nothing shifts left of the cut point, so it's still the caret
    caret = from;
  } else {
    const canon = gapRuns(text, recs, s, e);
    const opOrig = displayToOrig(runs, s, ins ? insAt : from);
    const cluster = Object.values(recs)
      .find(r => r.start <= opOrig && opOrig <= r.end);
    if (!cluster) {
      caret = origToDisplay(canon, s, opOrig);
    } else {
      // display start of the cluster's strikethrough
      let dispStart = 0, orig = s;
      for (const r of canon) {
        if (orig === cluster.start && (r.t === "d" || r.t === "i")) break;
        dispStart += r.text.length;
        if (r.t !== "i") orig += r.text.length;
      }
      if (ins) caret = dispStart + cluster.before.length + lead + ins.length;
      else if (op.kind === "bs") caret = dispStart;
      else caret = dispStart + cluster.before.length;
    }
  }
  return { records: recs, caret };
}
"""

_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #eef0f4; --card: #ffffff; --ink: #1a2330; --muted: #64748b;
  --line: #e2e8f0; --accent: #1f4e79; --accent-ink: #ffffff;
  --choice: #b45309; --blank: #15803d; --optional: #9d174d;
  --todo: #fef3c7; --todo-ink: #78350f; --todo-line: #f5d878;
  --done: #dcfce7; --done-ink: #14532d; --done-line: #86efac;
  --del: #fee2e2; --del-ink: #7f1d1d;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0c1118; --card: #161e2a; --ink: #e6edf6; --muted: #8b9bb0;
    --line: #2c3a4f; --accent: #6ea8d8; --accent-ink: #0f1520;
    --choice: #f0a860; --blank: #7fd49a; --optional: #f28cb4;
    --todo: #453510; --todo-ink: #fbd77e; --todo-line: #6b5518;
    --done: #143323; --done-ink: #a7e8c0; --done-line: #245a38;
    --del: #451717; --del-ink: #f5b5b5;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; }
header { position: sticky; top: 0; z-index: 10; background: var(--card);
  border-bottom: 1px solid var(--line); padding: 12px 22px;
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }
header h1 { font-size: 16px; margin: 0; }
header .sub { color: var(--muted); font-size: 12.5px; }
.progress { flex: 1; min-width: 200px; display: flex; align-items: center; gap: 10px; }
.bar { flex: 1; height: 8px; background: var(--line); border-radius: 99px; overflow: hidden; }
.bar i { display: block; height: 100%; width: 0; background: var(--accent); transition: width .25s; }
.count { font-size: 12.5px; color: var(--muted); white-space: nowrap; }
button { font: inherit; border: 1px solid var(--line); background: var(--card);
  color: var(--ink); border-radius: 8px; padding: 6px 12px; cursor: pointer; }
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }

#layout { display: grid; grid-template-columns: 240px minmax(0, 1fr) 400px; gap: 18px;
  max-width: 1400px; margin: 0 auto; padding: 18px 22px 70px; }
#layout.nonav { grid-template-columns: minmax(0,1fr) 400px; }
#layout.nonav #navPanel { display: none; }
@media (max-width: 1200px) { #navPanel { display: none; } #navPanel.open { display: block; } }
@media (max-width: 900px) { #layout { grid-template-columns: 1fr; }
  #side { position: static !important; max-height: none !important; }
  #navPanel, #navPanel.open { display: none !important; } }

#doc { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 26px 30px; white-space: pre-wrap; font-size: 13.5px; line-height: 1.75;
  overflow-wrap: break-word; }
#doc mark { padding: 0 3px; border-radius: 4px; cursor: pointer; font-weight: 600;
  scroll-margin: 25vh; border: 1px solid transparent; }
#doc mark.todo { background: var(--todo); color: var(--todo-ink);
  border-color: var(--todo-line); }
#doc mark.answered { background: var(--done); color: var(--done-ink);
  border-color: var(--done-line); }
#doc mark.deleted { background: var(--del); color: var(--del-ink);
  font-size: 11px; padding: 0 5px; text-decoration: none; }
#doc mark.unsafe { outline: 1px dashed #b91c1c; }
#doc mark.active { outline: 2px solid var(--accent); }
#doc mark s { color: var(--del-ink); background: var(--del);
  text-decoration: line-through; font-weight: 400; border-radius: 3px; }
#doc mark ins { color: var(--done-ink); background: var(--done);
  text-decoration: underline; font-weight: 600; border-radius: 3px; }
#doc mark s.fold { cursor: pointer; font-style: italic; }
#doc s.unitcut { color: var(--del-ink); background: var(--del); text-decoration: line-through; }
#doc mark.taicut { cursor: pointer; }
#doc s.me { color: var(--del-ink); background: var(--del);
  text-decoration: line-through; cursor: pointer; border-radius: 3px; }
#doc ins.me { color: var(--done-ink); background: var(--done);
  text-decoration: underline; cursor: pointer; border-radius: 3px; }
#doc span.me { cursor: pointer; border-bottom: 1px dashed var(--accent); }
#doc .lockedtxt { border-radius: 3px; }
#doc.editing .gap { cursor: text; }
#doc.editing .gap:focus { outline: none; }
#doc.editing mark, #doc.editing .lockedtxt, #doc.editing s.unitcut {
  box-shadow: 0 0 0 1px var(--line) inset; background-clip: padding-box; }

#side { position: sticky; top: 74px; align-self: start;
  max-height: calc(100vh - 96px); overflow-y: auto; display: flex;
  flex-direction: column; gap: 12px; }
#navPanel { position: sticky; top: 74px; align-self: start;
  max-height: calc(100vh - 96px); overflow-y: auto; }
.navroot { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .05em; color: var(--muted); padding: 4px 8px 8px; }
.navrow2 { display: flex; align-items: baseline; gap: 6px; white-space: nowrap;
  overflow: hidden; padding: 3px 8px 3px calc(8px + var(--nd) * 14px);
  cursor: pointer; border-radius: 6px; font-size: 12.5px; }
.navrow2:hover { background: var(--bg); }
.navrow2.active { background: var(--accent); color: var(--accent-ink); }
.navrow2.d0 { font-weight: 700; margin-top: 6px; }
.navtwist { flex: none; width: 14px; display: inline-block; text-align: center;
  color: var(--muted); cursor: pointer; }
.navrow2.active .navtwist { color: var(--accent-ink); }
.navnum { color: var(--muted); font-weight: 600; flex: none; min-width: 34px; }
.navrow2.active .navnum { color: var(--accent-ink); }
.navttl { overflow: hidden; text-overflow: ellipsis; }
.navanchor { scroll-margin-top: 80px; }
.paranum { font-weight: 700; margin-right: 8px; }
.navall { font-size: 12px; color: var(--muted); padding: 0 8px 8px; }
.navall a { color: var(--muted); cursor: pointer; }
.navall a:hover { text-decoration: underline; }
.panel { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 14px 16px; }
.panel h2 { font-size: 13px; margin: 0 0 8px; text-transform: uppercase;
  letter-spacing: .04em; color: var(--muted); }
.chip { font-size: 11px; font-weight: 700; letter-spacing: .03em; padding: 2px 8px;
  border-radius: 99px; border: 1px solid var(--line); color: var(--muted); }
.chip.kind-choice { color: var(--choice); border-color: currentColor; }
.chip.kind-blank { color: var(--blank); border-color: currentColor; }
.chip.kind-optional { color: var(--optional); border-color: currentColor; }
.chip.kind-submittal-review { color: #2563eb; border-color: currentColor; }
.chip.warn { color: #b91c1c; border-color: currentColor; }
.dec-top { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.loc { font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.hint { font-size: 12.5px; color: var(--muted); font-style: italic; margin-bottom: 8px; }
.opts { display: flex; flex-direction: column; gap: 6px; }
.opts button { text-align: left; line-height: 1.4; }
.opts button.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.opts button.danger.on { background: #b91c1c; border-color: #b91c1c; color: #fff; }
.freeform { display: flex; gap: 6px; margin-top: 8px; }
.freeform input { flex: 1; min-width: 0; font: inherit; font-size: 13.5px; padding: 6px 10px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg); color: var(--ink); }
.notes-row { margin-top: 8px; }
.notes-row input { width: 100%; font: inherit; font-size: 12.5px; padding: 5px 10px;
  border: 1px dashed var(--line); border-radius: 8px; background: transparent; color: var(--ink); }
.dupnote { font-size: 12.5px; color: var(--muted); margin-bottom: 8px; }
.dupnote a { color: var(--accent); cursor: pointer; }
.navrow { display: flex; gap: 6px; margin-top: 10px; }
.navrow button { flex: 1; font-size: 12.5px; }
.muted { color: var(--muted); font-size: 13px; }

.profile .row { display: flex; align-items: center; gap: 8px; padding: 5px 0;
  border-top: 1px solid var(--line); }
.profile .row:first-of-type { border-top: none; }
.profile .name { flex: 1; font-weight: 600; font-size: 12.5px; }
.profile .meta { color: var(--muted); font-size: 11px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg button { border: none; border-radius: 0; padding: 4px 10px; font-size: 12px;
  background: transparent; }
.seg button.on { background: var(--accent); color: var(--accent-ink); }
details.profile summary { cursor: pointer; font-size: 13px; font-weight: 600;
  color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }

#editHint { position: fixed; bottom: 64px; left: 50%; transform: translateX(-50%);
  background: var(--ink); color: var(--bg); font-size: 12.5px; padding: 7px 14px;
  border-radius: 99px; opacity: 0; pointer-events: none; transition: opacity .2s;
  z-index: 20; }
#editHint.show { opacity: .92; }

footer.actions { position: fixed; bottom: 0; left: 0; right: 0; background: var(--card);
  border-top: 1px solid var(--line); padding: 9px 22px; display: flex; gap: 10px;
  justify-content: center; z-index: 10; }
.hide { display: none !important; }
</style>
</head>
<body>
<header>
  <div>
    <h1 id="hTitle"></h1>
    <div class="sub" id="hSub"></div>
  </div>
  <div class="progress"><div class="bar"><i id="pBar"></i></div>
    <span class="count" id="pCount"></span></div>
  <button id="btnNext" class="primary">Next unanswered ↓</button>
  <button id="btnNavToggle">Sections</button>
  <button id="btnEdit">Edit: off</button>
  <button id="btnView">Redline view: on</button>
</header>
<div id="layout">
  <nav id="navPanel" class="panel"></nav>
  <div id="doc"></div>
  <aside id="side">
    <details class="panel profile" id="profilePanel" open>
      <summary>Project profile — answer once</summary>
      <div id="profileRows" style="margin-top:8px"></div>
    </details>
    <div class="panel" id="decPanel">
      <div class="muted">Click any highlighted decision in the text to answer it
      here. Yellow = to answer, green = answered.</div>
    </div>
  </aside>
</div>
<footer class="actions">
  <button class="primary" id="btnExport">Export answers (JSON)</button>
  <button id="btnImport">Import answers</button>
  <button id="btnClear">Clear all</button>
  <input type="file" id="fileImport" accept=".json" class="hide">
</footer>
<script>
const DATA = __DATA__;
const PLURAL_KEY = __PLURAL_KEY__;
const UNITS_KEY = __UNITS_KEY__;
const KEY = "specgen:" + DATA.section + ":" + (DATA.revision || "");
let state = { profile: {}, answers: {}, edits: {}, view: "redline", navOpen: true };
try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
state.view = state.view || "redline";
state.navOpen = state.navOpen === undefined ? true : state.navOpen;
state.edits = state.edits || {};
let activeId = null;
let overrideIds = new Set();
let editMode = false; let meCardId = null;

const ds = DATA.decisions.filter(d => !d.in_note && !d.plural);
const byId = Object.fromEntries(ds.map(d => [d.id, d]));
const nPlural = DATA.decisions.filter(d => d.plural).length;
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
__EDIT_CORE__
let dirty = false;
const save = () => { dirty = true; localStorage.setItem(KEY, JSON.stringify(state)); };
// after ds/byId: pruneStaleEdits -> meConflict reads ds and the profile
let staleEditsDropped = pruneStaleEdits();

function eff(d) {
  const own = state.answers[d.id];
  if (own && own.answer) return { a: own.answer, from: null };
  if (d.duplicate_of) {
    const src = state.answers[d.duplicate_of];
    if (src && src.answer) return { a: src.answer, from: d.duplicate_of };
  }
  return { a: "", from: null };
}
// A digit string is an option reference only when every number is in
// range for this group's options; otherwise it is literal custom text
// (e.g. typing "5" as a replacement on a 3-option group).
function optionIdx(d, a) {
  if (!(d.kind === "choice" && /^\d+(,\d+)*$/.test(a || ""))) return null;
  const idx = a.split(",").map(n => +n - 1);
  return idx.every(i => i >= 0 && i < d.options.length) ? idx : null;
}
function resolvedText(d, a) {
  if (a === "delete") return null;
  if (d.kind === "submittal-review" && a === "keep") {
    const o = (state.answers[d.id] || {}).office;
    return o ? d.options[0].replace(/\[[^\]]*\]/, o) : d.options[0];
  }
  if (a === "keep") return d.options[0];
  const idx = optionIdx(d, a);
  if (idx) return idx.map(i => d.options[i]).join(d.multi ? "\n" : " ");
  return a;  // out-of-range digits (or non-numeric) = literal custom text
}
function setAnswer(id, val) {
  const cur = state.answers[id] || {};
  if (cur.answer === val) delete cur.answer; else cur.answer = val;
  if (cur.answer || cur.notes) state.answers[id] = cur; else delete state.answers[id];
  save(); refresh();
}
function setNotes(id, val) {
  const cur = state.answers[id] || {};
  if (val) cur.notes = val; else delete cur.notes;
  if (cur.answer || cur.notes) state.answers[id] = cur; else delete state.answers[id];
  save(); updateProgress();
}

// ---- document view ----
function activeSpans() {
  const spans = ds.map(d => ({ s: d.char_start, e: d.char_end, pri: 3, d }));
  for (const t of DATA.tailoring_spans || []) {
    const names = t.opt.split(",").map(x => x.trim());
    if (names.every(nm => state.profile[nm] === "remove"))
      spans.push({ s: t.span[0], e: t.span[1], pri: 2, tai: t.opt });
  }
  const u = state.profile[UNITS_KEY];
  if (u === "si" || u === "ip")
    for (const pr of DATA.unit_spans || []) {
      const drop = u === "si" ? pr.eng : pr.met;
      if (drop) spans.push({ s: drop[0], e: drop[1], pri: 1, unit: true });
    }
  spans.sort((a, b) => a.s - b.s || b.e - a.e || b.pri - a.pri);
  // drop zero-length, contained-in-equal-or-lower-pri conflicts, partial overlaps
  const out = [], stack = [];
  for (const sp of spans) {
    while (stack.length && stack[stack.length - 1].e <= sp.s) stack.pop();
    const top = stack[stack.length - 1];
    if (top) {
      if (sp.e > top.e) continue;              // partial overlap: drop
      if (sp.pri >= top.pri) continue;         // decision inside decision etc.
      sp.parent = top;
    }
    out.push(sp); stack.push(sp);
  }
  return out;
}

function inRemovedTai(d) {
  return (DATA.tailoring_spans || []).some(t =>
    t.span[0] <= d.char_start && d.char_end <= t.span[1] &&
    t.opt.split(",").map(x => x.trim()).every(nm => state.profile[nm] === "remove"));
}

let docAnchors = [];
function computeDocAnchors(roots) {
  // pin anchors that fall inside a root island to the island start, then
  // assign each anchor to the gap that renders it (same cursor walk the old
  // gapHtml used, so boundary anchors land exactly once)
  const anchors = (DATA.nav || [])
    .map((n, i) => ({ c: n.char, i }))
    .sort((a, b) => a.c - b.c);
  for (const a of anchors)
    for (const sp of roots)
      if (a.c > sp.s && a.c < sp.e) { a.c = sp.s; break; }
  const gaps = [];
  let pos = 0;
  for (const sp of roots) { gaps.push([pos, sp.s]); pos = sp.e; }
  gaps.push([pos, DATA.text.length]);
  let ai = 0;
  for (const [from, to] of gaps)
    while (ai < anchors.length && anchors[ai].c <= to) {
      anchors[ai].gap = from;
      anchors[ai].c = Math.max(anchors[ai].c, from);
      ai++;
    }
  docAnchors = anchors;
}
// Memo is keyed by full-gap bounds only (callers pass gap [s,e), never
// per-render windows), so it stays bounded by the number of gaps.
// Safe to cache forever: DATA.decisions never changes.
const lockedOrigMemo = new Map();
function lockedOrigIn(s, e) {
  const key = s + ":" + e;
  let v = lockedOrigMemo.get(key);
  if (!v) {
    v = DATA.decisions
      .filter(d => (d.in_note || d.plural) && d.char_start >= s && d.char_end <= e)
      .map(d => [d.char_start, d.char_end])
      .sort((a, b) => a[0] - b[0]);
    lockedOrigMemo.set(key, v);
  }
  return v;
}
function origHtml(gapStart, a, b, emitted, rec, locked) {
  // original text slice [a,b) with nav anchors and locked-span tints.
  // `locked` is the gap's full locked-range list (from lockedOrigIn on the
  // whole gap); only ranges fully contained in [a,b) are rendered here.
  // `rec` (if given) is the edit record whose original span [r.start, r.end)
  // immediately follows this window (b === rec.start): an anchor that falls
  // strictly inside that span is clamped to rec.start so it still renders
  // (just before the record's strikethrough) instead of being dropped.
  // `emitted` tracks anchor indices already rendered by an earlier window in
  // this gap so a zero-length record can't cause the same anchor to satisfy
  // both its neighboring windows and render twice.
  const marks = docAnchors
    .filter(an => an.gap === gapStart && !emitted.has(an.i))
    .map(an => {
      const at = rec && an.c > rec.start && an.c < rec.end ? rec.start : an.c;
      return { an, at };
    })
    .filter(m => m.at >= a && m.at <= b)
    .map(m => { emitted.add(m.an.i); return { at: m.at, anchor: m.an.i }; });
  for (const [ls, le] of locked)
    if (ls >= a && le <= b) marks.push({ at: ls, lockEnd: le });
  marks.sort((x, y) => x.at - y.at);
  let html = "", pos = a;
  for (const m of marks) {
    html += esc(DATA.text.slice(pos, m.at));
    pos = m.at;
    if (m.anchor !== undefined) {
      const n = DATA.nav[m.anchor];
      const num = n && n.depth > 0 && n.num
        ? `<span class="paranum">${esc(n.num)}</span>` : "";
      html += `<span class="navanchor" contenteditable="false" id="nav-${m.anchor}">${num}</span>`;
    } else {
      html += `<span class="lockedtxt" contenteditable="false">${esc(DATA.text.slice(m.at, m.lockEnd))}</span>`;
      pos = m.lockEnd;
    }
  }
  html += esc(DATA.text.slice(pos, b));
  return html;
}
function gapInner(s, e) {
  const recs = Object.values(state.edits || {})
    .filter(r => r.start >= s && r.end <= e)
    .sort((a, b) => a.start - b.start);
  const emitted = new Set();
  const locked = lockedOrigIn(s, e);
  let html = "", pos = s;
  for (const r of recs) {
    html += origHtml(s, pos, r.start, emitted, r, locked);
    const id = "ME@" + r.start;
    if (state.view === "redline") {
      if (r.before) html += `<s class="me" data-me="${esc(id)}">${esc(r.before)}</s>`;
      if (r.after) html += `<ins class="me" data-me="${esc(id)}">${esc(r.after)}</ins>`;
    } else if (r.after) {
      html += `<span class="me" data-me="${esc(id)}">${esc(r.after)}</span>`;
    }
    pos = r.end;
  }
  html += origHtml(s, pos, e, emitted, null, locked);
  return html;
}
function gapAttrs() {
  return editMode ? ' contenteditable="true" spellcheck="false"' : "";
}
function wireMeRuns(root) {
  root.querySelectorAll(".me[data-me]").forEach(el => el.onclick = () => {
    meCardId = el.dataset.me;
    const prev = activeId;
    activeId = null;
    if (prev && byId[prev]) updateMark(byId[prev]);
    renderPanel();
  });
}
function renderGap(gapEl) {
  gapEl.innerHTML = gapInner(+gapEl.dataset.s, +gapEl.dataset.e);
  wireMeRuns(gapEl);
}
function buildDoc() {
  const doc = document.getElementById("doc");
  const spans = activeSpans();
  const roots = spans.filter(sp => !sp.parent);
  computeDocAnchors(roots);
  let html = "", pos = 0;
  const emit = (sp) => {
    const kids = spans.filter(k => k.parent === sp);
    let inner = "", p = sp.s;
    for (const k of kids) { inner += esc(DATA.text.slice(p, k.s)); inner += emit(k); p = k.e; }
    inner += esc(DATA.text.slice(p, sp.e));
    if (sp.d) return `<mark data-id="${sp.d.id}" id="mk-${sp.d.id}">${inner}</mark>`;
    if (sp.tai) {
      const n = sp.e - sp.s;
      return state.view === "redline"
        ? `<mark class="deleted taicut" data-opt="${esc(sp.tai)}" title="click to expand">▸ ${esc(sp.tai)} removed (${n} chars)</mark>`
        : "";
    }
    return state.view === "redline" ? `<s class="unitcut">${inner}</s>` : "";
  };
  const gap = (from, to) =>
    `<span class="gap" data-s="${from}" data-e="${to}"${gapAttrs()}>${gapInner(from, to)}</span>`;
  for (const sp of roots) {
    html += gap(pos, sp.s);
    html += emit(sp);
    pos = sp.e;
  }
  html += gap(pos, DATA.text.length);
  doc.innerHTML = html;
  doc.classList.toggle("editing", editMode);
  doc.querySelectorAll("mark[data-id]").forEach(m => m.onclick = () => select(m.dataset.id, false));
  doc.querySelectorAll("mark.taicut").forEach(m => m.onclick = () => {
    alert("Tailoring block '" + m.dataset.opt + "' is removed by the Project Profile. Set it back to 'keep' to restore the text.");
  });
  wireMeRuns(doc);
  ds.forEach(updateMark);
}
let navCollapsed = new Set();
function renderNav() {
  const nav = document.getElementById("navPanel");
  const items = DATA.nav || [];
  const isBranch = i => i + 1 < items.length && items[i + 1].depth > items[i].depth;
  let html = `<div class="navroot">${esc(DATA.section)}</div>`;
  html += `<div class="navall"><a data-navall="collapse">collapse all</a> · ` +
    `<a data-navall="expand">expand all</a></div>`;
  html += items.map((n, i) => {
    const twist = isBranch(i)
      ? `<span class="navtwist" data-twist="${i}">${navCollapsed.has(i) ? "▸" : "▾"}</span>`
      : `<span class="navtwist"></span>`;
    return `<div class="navrow2 d${n.depth}" data-i="${i}" style="--nd:${n.depth}" title="${esc(n.title)}">` +
      twist + `<span class="navnum">${esc(n.num)}</span>` +
      `<span class="navttl">${esc(n.title)}</span></div>`;
  }).join("");
  nav.innerHTML = html;
  applyNavCollapse();
  nav.querySelectorAll(".navtwist[data-twist]").forEach(t => t.onclick = ev => {
    ev.stopPropagation();
    const i = +t.dataset.twist;
    if (navCollapsed.has(i)) navCollapsed.delete(i); else navCollapsed.add(i);
    t.textContent = navCollapsed.has(i) ? "▸" : "▾";
    applyNavCollapse();
  });
  nav.querySelectorAll(".navrow2").forEach(row => row.onclick = () => {
    nav.querySelectorAll(".navrow2").forEach(r => r.classList.remove("active"));
    row.classList.add("active");
    document.getElementById("nav-" + row.dataset.i)?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  nav.querySelectorAll("[data-navall]").forEach(a => a.onclick = () => {
    navCollapsed = a.dataset.navall === "collapse"
      ? new Set(items.map((n, i) => i).filter(isBranch))
      : new Set();
    renderNav();
  });
}
function applyNavCollapse() {
  const nav = document.getElementById("navPanel");
  const items = DATA.nav || [];
  let hideDepth = null;
  nav.querySelectorAll(".navrow2").forEach((row, i) => {
    const d = items[i].depth;
    if (hideDepth !== null && d > hideDepth) {
      row.style.display = "none";
      return;
    }
    hideDepth = null;
    row.style.display = "";
    if (navCollapsed.has(i)) hideDepth = d;
  });
}
function updateMark(d) {
  const m = document.getElementById("mk-" + d.id);
  if (!m) return;
  const e = eff(d);
  const cls = [];
  if (!d.safe) cls.push("unsafe");
  if (d.id === activeId) cls.push("active");
  if (!e.a) {
    cls.push("todo");
    m.textContent = DATA.text.slice(d.char_start, d.char_end);
    m.title = "click to answer";
  } else {
    const txt = resolvedText(d, e.a);
    cls.push(txt === null ? "deleted" : "answered");
    m.className = cls.join(" ");
    m.title = txt === null ? "removed — click to change" : "answered — click to change";
    renderRedline(m, d, txt);
    return;
  }
  m.className = cls.join(" ");
}
function renderRedline(m, d, txt) {
  const orig = DATA.text.slice(d.char_start, d.char_end);
  if (state.view !== "redline") {
    if (txt === null) { m.classList.add("deleted"); m.textContent = "deleted"; }
    else { m.textContent = txt; }
    return;
  }
  const del = orig.length > 200
    ? `<s class="fold" data-full="1">${esc(orig.slice(0, 80))}… ⟨${orig.length} chars removed — click⟩</s>`
    : `<s>${esc(orig)}</s>`;
  m.innerHTML = txt === null ? del : del + `<ins>${esc(txt)}</ins>`;
  const f = m.querySelector("s.fold");
  if (f) f.onclick = ev => { ev.stopPropagation(); f.outerHTML = `<s>${esc(orig)}</s>`; };
}

// ---- side panel ----
function select(id, scrollDoc) {
  meCardId = null;
  const prev = activeId;
  activeId = id;
  if (prev && byId[prev]) updateMark(byId[prev]);
  const d = byId[id];
  if (d) updateMark(d);
  renderPanel();
  if (scrollDoc && d) {
    const m = document.getElementById("mk-" + id);
    if (m) m.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}
function renderPanel() {
  const p = document.getElementById("decPanel");
  if (meCardId) { renderMeCard(p); return; }
  const d = byId[activeId];
  if (!d) {
    const notice = staleEditsDropped
      ? `<div class="muted" style="margin-bottom:8px">${staleEditsDropped} text
        edit(s) were stale or conflicting and were dropped — see console.</div>`
      : "";
    p.innerHTML = notice + `<div class="muted">Click any highlighted decision in the text
      to answer it here. Yellow = to answer, green = answered.</div>`;
    return;
  }
  const e = eff(d);
  let h = `<div class="dec-top"><span class="chip">${d.id}</span>
    <span class="chip kind-${d.kind}">${d.kind}</span>`;
  if (!d.safe) h += `<span class="chip warn">manual edit needed</span>`;
  h += `</div><div class="loc">${esc(d.location)}</div>`;
  if (d.note_guidance) h += `<details class="panel" style="padding:8px 10px">
    <summary style="cursor:pointer;font-size:12px;color:var(--muted)">Designer note</summary>
    <div style="font-size:12.5px;margin-top:6px">${esc(d.note_guidance)}</div></details>`;
  if (d.hint) h += `<div class="hint">${esc(d.hint)}</div>`;
  if (!d.safe) {
    h += `<div class="dupnote">This bracket crosses structural markup and can't be answered as a choice; it is flagged in the unresolved report for manual editing in SI Editor after generation.</div>` + navRow();
    p.innerHTML = h; wireNav(p); return;
  }
  const overridden = state.answers[d.id] && state.answers[d.id].answer;
  if (d.duplicate_of && !overridden && !overrideIds.has(d.id)) {
    const srcTxt = e.a ? `following its answer: <b>${esc(e.a)}</b>` : "unanswered so far";
    h += `<div class="dupnote">Same decision as <a data-goto="${d.duplicate_of}">
      ${d.duplicate_of}</a> — ${srcTxt}.<br>
      <a data-act="override">Answer this instance differently…</a></div>` + navRow();
    p.innerHTML = h;
    p.querySelector("[data-act=override]").onclick = () => {
      overrideIds.add(d.id); renderPanel(); };
    const g = p.querySelector("[data-goto]");
    if (g) g.onclick = () => select(g.dataset.goto, true);
    wireNav(p);
    return;
  }
  const own = state.answers[d.id] || {};
  if (d.kind === "submittal-review") {
    h += `<div class="loc">${esc(d.label || "")}</div>`;
    h += `<div class="hint">Government review flag for this submittal item.</div>`;
    h += `<div class="opts">
      <button data-val="keep" class="${e.a === "keep" ? "on" : ""}">keep — Government-reviewed (G)</button>
      <button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">remove — for information only</button></div>`;
    h += `<div class="freeform"><input type="text" data-office
      placeholder="reviewer office (e.g. AE) — optional"
      value="${esc(own.office || "")}"><button data-act="setoffice">Set</button></div>`;
    h += freeform(d, e, "…or type replacement text");
  } else if (d.kind === "choice" && d.multi) {
    const eIdx = optionIdx(d, e.a);
    const picked = new Set(eIdx ? eIdx.map(i => String(i + 1)) : []);
    h += `<div class="hint">Select all that apply — these are independent items,
      keep any combination.</div>`;
    h += `<div class="opts">` + d.options.map((o, i) =>
      `<button data-multi="${i + 1}" class="${picked.has(String(i + 1)) ? "on" : ""}">` +
      `${picked.has(String(i + 1)) ? "☑" : "☐"} ${esc(o)}${nestedTag(o)}</button>`).join("") +
      `<button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">none of these — remove all</button></div>`;
    h += freeform(d, e, "…or type replacement text");
  } else if (d.kind === "choice") {
    h += `<div class="hint">Choose one.</div>`;
    h += `<div class="opts">` + d.options.map((o, i) =>
      `<button data-val="${i + 1}" class="${e.a == String(i + 1) ? "on" : ""}">` +
      `${i + 1}) ${esc(o)}${nestedTag(o)}</button>`).join("") +
      `<button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">remove entirely</button></div>`;
    h += freeform(d, e, "…or type replacement text");
  } else if (d.kind === "optional") {
    h += `<div class="opts">
      <button data-val="keep" class="${e.a === "keep" ? "on" : ""}">keep this text</button>
      <button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">delete it</button></div>`;
    h += freeform(d, e, "…or type replacement text");
  } else {
    h += freeform(d, e, "value to fill in");
  }
  h += `<div class="notes-row"><input data-notes
        placeholder="note for the audit log (optional)" value="${esc(own.notes || "")}"></div>`;
  h += `<div class="navrow"><button data-act="edittext">Edit text… (start from the original)</button></div>`;
  h += navRow();
  p.innerHTML = h;
  p.querySelectorAll(".opts button[data-val]").forEach(b =>
    b.onclick = () => setAnswer(d.id, b.dataset.val));
  p.querySelectorAll(".opts button[data-multi]").forEach(b =>
    b.onclick = () => {
      const cur = eff(d).a;
      const curIdx = optionIdx(d, cur);
      const picked = new Set(curIdx ? curIdx.map(i => String(i + 1)) : []);
      const v = b.dataset.multi;
      picked.has(v) ? picked.delete(v) : picked.add(v);
      const val = [...picked].map(Number).sort((a, b2) => a - b2).join(",");
      // setAnswer toggles off when unchanged; force-set instead
      const rec = state.answers[d.id] || {};
      if (val) rec.answer = val; else delete rec.answer;
      if (rec.answer || rec.notes) state.answers[d.id] = rec;
      else delete state.answers[d.id];
      save(); refresh();
    });
  const inp = p.querySelector("[data-custom]");
  const btn = p.querySelector("[data-act=apply]");
  if (btn) btn.onclick = () => { if (inp.value.trim()) setAnswer(d.id, inp.value.trim()); };
  if (inp) inp.onkeydown = ev => { if (ev.key === "Enter" && inp.value.trim())
    setAnswer(d.id, inp.value.trim()); };
  const et = p.querySelector("[data-act=edittext]");
  if (et) et.onclick = () => {
    const ci = p.querySelector("[data-custom]");
    if (ci) {
      ci.value = DATA.text.slice(d.char_start, d.char_end);
      ci.focus();
    }
  };
  const notes = p.querySelector("[data-notes]");
  if (notes) notes.onchange = () => setNotes(d.id, notes.value.trim());
  const off = p.querySelector("[data-office]");
  const offBtn = p.querySelector("[data-act=setoffice]");
  if (offBtn) offBtn.onclick = () => {
    const cur = state.answers[d.id] || {};
    if (off.value.trim()) cur.office = off.value.trim(); else delete cur.office;
    if (cur.answer || cur.notes || cur.office) state.answers[d.id] = cur;
    else delete state.answers[d.id];
    save(); refresh();
  };
  wireNav(p);
}
function nestedTag(o) {
  return o.includes("[") ?
    ` <span style="color:var(--choice);font-size:11px;font-weight:700">
      ⚠ contains further choices — they return as follow-up decisions</span>` : "";
}
function freeform(d, e, ph) {
  const custom = e.a && !["keep", "delete"].includes(e.a) &&
    !optionIdx(d, e.a) ? e.a : "";
  return `<div class="freeform"><input type="text" data-custom placeholder="${ph}"
    value="${esc(custom)}"><button data-act="apply">Set</button></div>`;
}
function navRow() {
  return `<div class="navrow"><button data-nav="prev">← previous</button>
    <button data-nav="next">next unanswered →</button></div>`;
}
function wireNav(p) {
  p.querySelectorAll("[data-nav]").forEach(b => b.onclick = () => {
    if (b.dataset.nav === "next") gotoNextUnanswered();
    else gotoPrev();
  });
}
function gotoNextUnanswered() {
  const start = activeId ? ds.findIndex(d => d.id === activeId) : -1;
  for (let i = 1; i <= ds.length; i++) {
    const d = ds[(start + i + ds.length) % ds.length];
    if (d.safe && !eff(d).a && !d.duplicate_of && !inRemovedTai(d)) { select(d.id, true); return; }
  }
  for (let i = 1; i <= ds.length; i++) {  // fall back to any unanswered
    const d = ds[(start + i + ds.length) % ds.length];
    if (d.safe && !eff(d).a && !inRemovedTai(d)) { select(d.id, true); return; }
  }
}
function gotoPrev() {
  const i = ds.findIndex(d => d.id === activeId);
  if (i > 0) select(ds[i - 1].id, true);
}

// ---- manual text edits (inline, tracked changes) ----
function pruneStaleEdits() {
  let dropped = 0;
  // ascending start: on overlap between imported edits, the first kept wins
  const entries = Object.entries(state.edits || {})
    .sort((a, b) => a[1].start - b[1].start);
  for (const [id, rec] of entries) {
    let why = null;
    if (DATA.text.slice(rec.start, rec.end) !== rec.before)
      why = "no longer matches this master";
    else {
      const conflict = meConflict(rec.start, rec.end, id);
      if (conflict) why = "overlaps " + conflict;
    }
    if (why) {
      delete state.edits[id];
      dropped++;
      console.warn("Dropped text edit " + id + ": " + why + ".");
    }
  }
  return dropped;
}
function meConflict(s, e, excludeId) {
  for (const d of ds)
    if (s < d.char_end && e > d.char_start) return `decision ${d.id}`;
  for (const t of DATA.tailoring_spans || []) {
    const names = t.opt.split(",").map(x => x.trim());
    if (names.every(nm => state.profile[nm] === "remove") &&
        s < t.span[1] && e > t.span[0]) return `removed tailoring block (${t.opt})`;
  }
  const u = state.profile[UNITS_KEY];
  if (u === "si" || u === "ip")
    for (const pr of DATA.unit_spans || []) {
      const drop = u === "si" ? pr.eng : pr.met;
      if (drop && s < drop[1] && e > drop[0]) return "a removed unit value";
    }
  for (const [eid, rec] of Object.entries(state.edits || {})) {
    if (eid === excludeId) continue;
    if (s < rec.end && e > rec.start) return `edit ${eid}`;
  }
  for (const d of DATA.decisions)
    if ((d.in_note || d.plural) && s < d.char_end && e > d.char_start)
      return `locked text (${d.id})`;
  return null;
}
function renderMeCard(p) {
  const rec = state.edits[meCardId];
  if (!rec) { meCardId = null; renderPanel(); return; }
  let h = `<div class="dec-top"><span class="chip">TEXT EDIT</span>
    <span class="chip">${esc(meCardId)}</span></div>`;
  h += `<div class="loc">Deleted text</div>
    <div class="hint" style="font-style:normal;white-space:pre-wrap;text-decoration:line-through">${esc(rec.before) || "(nothing)"}</div>`;
  h += `<div class="loc">Inserted text</div>
    <div class="hint" style="font-style:normal;white-space:pre-wrap">${esc(rec.after) || "(nothing)"}</div>`;
  h += `<div class="notes-row"><input id="meNotes"
    placeholder="note for the audit log (optional)" value="${esc(rec.notes || "")}"></div>`;
  h += `<div class="navrow"><button class="danger" id="meRevert">Revert this change</button></div>`;
  h += `<div class="muted" style="margin-top:6px">All retyping happens in the
    document — turn Edit on and type. This card reviews one change.</div>`;
  p.innerHTML = h;
  // handlers must re-read state.edits[meCardId] at event time: edit ops swap
  // in fresh record objects (replaceEditsIn), orphaning any `rec` captured at
  // render time — writing the note to that dead object would silently lose it.
  document.getElementById("meNotes").onchange = ev => {
    const cur = state.edits[meCardId];
    if (!cur) return;
    cur.notes = ev.target.value.trim();
    save();
  };
  document.getElementById("meRevert").onclick = () => {
    if (state.edits[meCardId]) delete state.edits[meCardId];
    meCardId = null;
    editUndo = []; editRedo = [];  // revert bypasses the undo system
    save(); buildDoc(); refresh();
  };
}

// ---- edit mode (Word-like typing with live tracked changes) ----
let editUndo = [], editRedo = [];
let hintTimer = null;
function showHint(msg) {
  let el = document.getElementById("editHint");
  if (!el) {
    el = document.createElement("div");
    el.id = "editHint";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => el.classList.remove("show"), 1800);
}
function textLenNoAnchors(n) {
  if (n.nodeType === 3)
    return n.parentElement && n.parentElement.closest(".navanchor")
      ? 0 : n.textContent.length;
  if (n.classList && n.classList.contains("navanchor")) return 0;
  let sum = 0;
  for (const c of n.childNodes) sum += textLenNoAnchors(c);
  return sum;
}
function dispOffset(gapEl, node, off) {
  // display offset of (node, off) within the gap, skipping anchor content
  if (node.nodeType !== 3) {
    let sum = 0;
    const el = node;
    if (!gapEl.contains(el)) return null;
    for (let i = 0; i < off && i < el.childNodes.length; i++)
      sum += textLenNoAnchors(el.childNodes[i]);
    // add everything before `el` inside the gap
    let n2 = el;
    while (n2 !== gapEl) {
      let sib = n2.previousSibling;
      while (sib) { sum += textLenNoAnchors(sib); sib = sib.previousSibling; }
      n2 = n2.parentNode;
    }
    return sum;
  }
  if (node.parentElement.closest(".navanchor")) return null;
  let sum = off, n2 = node;
  while (n2 !== gapEl) {
    let sib = n2.previousSibling;
    while (sib) { sum += textLenNoAnchors(sib); sib = sib.previousSibling; }
    n2 = n2.parentNode;
    if (!n2) return null;
  }
  return sum;
}
function setCaretAt(gapEl, disp) {
  const sel = window.getSelection();
  const place = (node, off) => {
    const r = document.createRange();
    r.setStart(node, off);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
  };
  const walker = document.createTreeWalker(gapEl, NodeFilter.SHOW_TEXT);
  let n, pos = 0, last = null;
  while ((n = walker.nextNode())) {
    if (n.parentElement.closest(".navanchor")) continue;
    const len = n.textContent.length;
    if (disp <= pos + len) { place(n, disp - pos); return; }
    pos += len;
    last = n;
  }
  if (last) place(last, last.textContent.length);
  else place(gapEl, 0);   // gap rendered no editable text (e.g. undo emptied it)
}
function selCtx() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const r = sel.getRangeAt(0);
  const gapEl = (r.startContainer.nodeType === 1 ? r.startContainer
    : r.startContainer.parentElement).closest(".gap");
  const gapEl2 = (r.endContainer.nodeType === 1 ? r.endContainer
    : r.endContainer.parentElement).closest(".gap");
  if (!gapEl || gapEl !== gapEl2) return null;
  const a = dispOffset(gapEl, r.startContainer, r.startOffset);
  const b = dispOffset(gapEl, r.endContainer, r.endOffset);
  if (a == null || b == null) return null;
  return { gap: gapEl, s: +gapEl.dataset.s, e: +gapEl.dataset.e,
           from: Math.min(a, b), to: Math.max(a, b) };
}
function editsIn(s, e) {
  const out = {};
  for (const [k, r] of Object.entries(state.edits))
    if (r.start >= s && r.end <= e) out[k] = r;
  return out;
}
function replaceEditsIn(s, e, recs) {
  for (const [k, r] of Object.entries(state.edits))
    if (r.start >= s && r.end <= e) delete state.edits[k];
  Object.assign(state.edits, recs);
}
function applyDocOp(ctx, op) {
  const before = editsIn(ctx.s, ctx.e);
  const res = applyGapOp(DATA.text, state.edits, ctx.s, ctx.e, op,
    lockedOrigIn(ctx.s, ctx.e));
  if (!res) return;
  if (res.blocked) {
    showHint("That text is locked — brackets are answered from the panel.");
    return;
  }
  replaceEditsIn(ctx.s, ctx.e, res.records);
  editUndo.push({ s: ctx.s, e: ctx.e, before,
    after: editsIn(ctx.s, ctx.e), caretBefore: ctx.from, caretAfter: res.caret });
  if (editUndo.length > 100) editUndo.shift();
  editRedo = [];
  save();
  renderGap(ctx.gap);
  // If the review card is open, refresh it passively so it shows the fresh
  // record (or closes when the record no longer exists). renderPanel only
  // rewrites the side panel's innerHTML and never calls focus(), but restore
  // the document caret AFTER it anyway so it cannot disturb the selection.
  if (meCardId) renderPanel();
  setCaretAt(ctx.gap, res.caret);
  updateProgress();
}
// Known, spec-scoped-out limitation: insertCompositionText (IME) is not
// cancelable, so preventDefault can't block it — composition mutates the DOM
// untracked until the next op re-renders the gap from records. Records remain
// the source of truth, so no offset corruption reaches state or export.
function onBeforeInput(ev) {
  if (!editMode) return;
  ev.preventDefault();
  const ctx = selCtx();
  if (!ctx) {
    showHint("Edit one text region at a time — brackets are answered from the panel.");
    return;
  }
  const it = ev.inputType;
  let op = null;
  if (it === "insertText" || it === "insertParagraph" ||
      it === "insertLineBreak" || it === "insertFromPaste") {
    const text = it === "insertParagraph" || it === "insertLineBreak" ? "\n"
      : it === "insertFromPaste"
        ? ((ev.dataTransfer && ev.dataTransfer.getData("text/plain")) || "")
        : (ev.data || "");
    if (!text) return;
    op = ctx.from < ctx.to
      ? { kind: "replace", from: ctx.from, to: ctx.to, text }
      : { kind: "ins", at: ctx.from, text };
  } else if (it === "deleteContentBackward") {
    op = ctx.from < ctx.to ? { kind: "del", from: ctx.from, to: ctx.to }
                           : { kind: "bs", caret: ctx.from };
  } else if (it === "deleteContentForward") {
    op = ctx.from < ctx.to ? { kind: "del", from: ctx.from, to: ctx.to }
                           : { kind: "fwd", caret: ctx.from };
  } else if (it === "deleteByCut" || it === "deleteByDrag") {
    if (ctx.from < ctx.to) op = { kind: "del", from: ctx.from, to: ctx.to };
  }
  if (op) applyDocOp(ctx, op);
}
document.getElementById("doc").addEventListener("beforeinput", onBeforeInput);
document.addEventListener("keydown", ev => {
  if (!editMode || !(ev.ctrlKey || ev.metaKey)) return;
  const tag = ev.target && ev.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return;  // panel inputs keep native undo
  const key = (ev.key || "").toLowerCase();
  if (key !== "z" && key !== "y") return;
  ev.preventDefault();
  const redo = key === "y" || (key === "z" && ev.shiftKey);
  const stack = redo ? editRedo : editUndo;
  const other = redo ? editUndo : editRedo;
  const step = stack.pop();
  if (!step) return;
  other.push(step);
  replaceEditsIn(step.s, step.e, redo ? step.after : step.before);
  save();
  const gapEl = document.querySelector(`.gap[data-s="${step.s}"]`);
  if (gapEl) {
    renderGap(gapEl);
    setCaretAt(gapEl, redo ? step.caretAfter : step.caretBefore);
  }
  updateProgress();
});
document.getElementById("btnEdit").onclick = () => {
  editMode = !editMode;
  if (editMode && state.view !== "redline") {
    state.view = "redline";
    document.getElementById("btnView").textContent = "Redline view: on";
    save();
  }
  document.getElementById("btnView").disabled = editMode;
  const b = document.getElementById("btnEdit");
  b.textContent = "Edit: " + (editMode ? "on" : "off");
  b.classList.toggle("primary", editMode);
  buildDoc();
};

// ---- profile ----
function renderProfile() {
  const rows = document.getElementById("profileRows");
  rows.innerHTML = "";
  const items = Object.entries(DATA.tailoring_options).map(([k, v]) =>
    ({ key: k, meta: v.blocks + " block" + (v.blocks > 1 ? "s" : "") }));
  if ((DATA.unit_spans || []).length) items.push({ key: UNITS_KEY,
    meta: DATA.unit_spans.length + " unit pairs",
    labels: ["SI", "IP"], values: ["si", "ip"] });
  if (nPlural) items.push({ key: PLURAL_KEY,
    meta: nPlural + " [s] markers", labels: ["plural", "singular"] });
  for (const it of items) {
    const val = state.profile[it.key] || "";
    const row = document.createElement("div");
    row.className = "row";
    const l1 = it.labels ? it.labels[0] : "keep", l2 = it.labels ? it.labels[1] : "remove";
    const v1 = it.values ? it.values[0] : "keep", v2 = it.values ? it.values[1] : "remove";
    row.innerHTML = `<span class="name">${esc(it.key)}</span>
      <span class="meta">${esc(it.meta)}</span>
      <span class="seg">
        <button data-v="${v1}" class="${val === v1 ? "on" : ""}">${l1}</button>
        <button data-v="${v2}" class="${val === v2 ? "on" : ""}">${l2}</button></span>`;
    row.querySelectorAll(".seg button").forEach(b => b.onclick = () => {
      state.profile[it.key] = state.profile[it.key] === b.dataset.v ? "" : b.dataset.v;
      if (!state.profile[it.key]) delete state.profile[it.key];
      // profile changes can move gap boundaries (buildDoc below); stale undo
      // steps keyed to old data-s offsets would corrupt the record set.
      editUndo = []; editRedo = [];
      save(); renderProfile(); updateProgress();
      if (it.key === UNITS_KEY || DATA.tailoring_options[it.key]) buildDoc();
    });
    rows.appendChild(row);
  }
}
function updateProgress() {
  const uniq = ds.filter(d => !d.duplicate_of && d.safe && !inRemovedTai(d));
  const done = uniq.filter(d => eff(d).a).length;
  const profAll = Object.keys(DATA.tailoring_options).length
    + (nPlural ? 1 : 0) + ((DATA.unit_spans || []).length ? 1 : 0);
  const profOpen = Math.max(0, profAll - Object.keys(state.profile).length);
  const profDone = profAll - profOpen;
  document.getElementById("pBar").style.width =
    Math.round(100 * (done + profDone) / (uniq.length + profAll)) + "%";
  const meCount = Object.keys(state.edits || {}).length;
  document.getElementById("pCount").textContent =
    `${done} / ${uniq.length} decisions · ${profDone} / ${profAll} profile` +
    (meCount ? ` · ${meCount} text edits` : "");
}
function refresh() {
  ds.forEach(updateMark);
  renderPanel();
  updateProgress();
}

// ---- header / footer actions ----
document.getElementById("btnNext").onclick = gotoNextUnanswered;
document.getElementById("btnNavToggle").onclick = () => {
  state.navOpen = !state.navOpen;
  document.getElementById("layout").classList.toggle("nonav", !state.navOpen);
  document.getElementById("navPanel").classList.toggle("open", state.navOpen);
  save();
};
document.getElementById("btnView").onclick = () => {
  state.view = state.view === "redline" ? "clean" : "redline";
  document.getElementById("btnView").textContent =
    "Redline view: " + (state.view === "redline" ? "on" : "off");
  save(); buildDoc(); renderPanel(); updateProgress();
};
document.getElementById("btnExport").onclick = () => {
  const uniq = ds.filter(d => !d.duplicate_of && d.safe && !inRemovedTai(d));
  const open = uniq.filter(d => !eff(d).a).map(d => d.id);
  const profAll = Object.keys(DATA.tailoring_options).length
    + (nPlural ? 1 : 0) + ((DATA.unit_spans || []).length ? 1 : 0);
  const profOpen = Math.max(0, profAll - Object.keys(state.profile).length);
  if (open.length || profOpen > 0) {
    const list = open.slice(0, 15).join(", ") + (open.length > 15 ? " …" : "");
    if (!confirm(`${open.length} decision(s) and ${profOpen} profile setting(s) are still unanswered:\n${list}\n\nExport anyway? They will be flagged for engineer review, never defaulted.`))
      return;
  }
  const payload = { section: DATA.section, title: DATA.title,
    revision: DATA.revision, exported: new Date().toISOString(),
    complete: open.length === 0 && profOpen <= 0,
    unanswered: open,
    profile: state.profile,
    answers: { ...state.answers, ...state.edits } };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)],
    { type: "application/json" }));
  a.download = DATA.section.replace(/^SECTION\s+/i, "") + ".answers.json";
  a.click();
  dirty = false;
};
document.getElementById("btnImport").onclick = () =>
  document.getElementById("fileImport").click();
document.getElementById("fileImport").onchange = ev => {
  const f = ev.target.files[0];
  if (!f) return;
  f.text().then(t => {
    const data = JSON.parse(t);
    state.profile = data.profile || {};
    state.answers = {}; state.edits = {};
    for (const [k, v] of Object.entries(data.answers || {})) {
      if (k.startsWith("ME@")) state.edits[k] = v; else state.answers[k] = v;
    }
    editUndo = []; editRedo = [];
    staleEditsDropped = pruneStaleEdits();
    save(); buildDoc(); renderPanel(); updateProgress(); renderProfile();
  });
};
document.getElementById("btnClear").onclick = () => {
  if (confirm("Clear every answer on this page?")) {
    state = { profile: {}, answers: {}, edits: {}, view: state.view || "redline",
      navOpen: state.navOpen }; overrideIds.clear(); meCardId = null;
    editUndo = []; editRedo = [];
    save(); buildDoc(); renderPanel(); updateProgress(); renderProfile();
  }
};

window.addEventListener("beforeunload", ev => {
  if (dirty) { ev.preventDefault(); ev.returnValue = ""; }
});

document.getElementById("hTitle").textContent = DATA.section + " — " + DATA.title;
document.getElementById("hSub").textContent =
  (DATA.revision || DATA.date_code || "") +
  (DATA.umrl_date ? " · UMRL " + DATA.umrl_date : "") +
  " · answers autosave in this browser";
document.getElementById("layout").classList.toggle("nonav", !state.navOpen);
document.getElementById("navPanel").classList.toggle("open", state.navOpen);
renderNav();
buildDoc();
renderProfile();
document.getElementById("btnView").textContent =
  "Redline view: " + (state.view === "redline" ? "on" : "off");
updateProgress();
renderPanel();
</script>
</body>
</html>
"""


def write_html(manifest: dict, out_path: Path | str) -> None:
    data = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
    html = (
        _TEMPLATE.replace("__TITLE__", f"{manifest['section']} — decisions")
        .replace("__DATA__", data)
        .replace("__PLURAL_KEY__", json.dumps(PLURAL_KEY))
        .replace("__UNITS_KEY__", json.dumps(UNITS_KEY))
        .replace("__EDIT_CORE__", EDIT_CORE_JS)
    )
    Path(out_path).write_text(html, encoding="utf-8")
