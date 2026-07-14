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

#layout { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 18px;
  max-width: 1400px; margin: 0 auto; padding: 18px 22px 70px; }
@media (max-width: 900px) { #layout { grid-template-columns: 1fr; }
  #side { position: static !important; max-height: none !important; } }

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

#side { position: sticky; top: 74px; align-self: start;
  max-height: calc(100vh - 96px); overflow-y: auto; display: flex;
  flex-direction: column; gap: 12px; }
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
  <button id="btnView">Redline view: on</button>
</header>
<div id="layout">
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
let state = { profile: {}, answers: {}, view: "redline" };
try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
state.view = state.view || "redline";
let activeId = null;
let overrideIds = new Set();

const ds = DATA.decisions.filter(d => !d.in_note && !d.plural);
const byId = Object.fromEntries(ds.map(d => [d.id, d]));
const nPlural = DATA.decisions.filter(d => d.plural).length;
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const save = () => localStorage.setItem(KEY, JSON.stringify(state));

function eff(d) {
  const own = state.answers[d.id];
  if (own && own.answer) return { a: own.answer, from: null };
  if (d.duplicate_of) {
    const src = state.answers[d.duplicate_of];
    if (src && src.answer) return { a: src.answer, from: d.duplicate_of };
  }
  return { a: "", from: null };
}
function resolvedText(d, a) {
  if (a === "delete") return null;
  if (d.kind === "submittal-review" && a === "keep") {
    const o = (state.answers[d.id] || {}).office;
    return o ? d.options[0].replace(/\[[^\]]*\]/, o) : d.options[0];
  }
  if (a === "keep") return d.options[0];
  if (d.kind === "choice" && /^\d+(,\d+)*$/.test(a))
    return a.split(",").map(n => d.options[+n - 1] ?? "?").join(d.multi ? "\n" : " ");
  return a;
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

function buildDoc() {
  const doc = document.getElementById("doc");
  const spans = activeSpans();
  const roots = spans.filter(sp => !sp.parent);
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
  for (const sp of roots) {
    html += esc(DATA.text.slice(pos, sp.s));
    html += emit(sp);
    pos = sp.e;
  }
  html += esc(DATA.text.slice(pos));
  doc.innerHTML = html;
  doc.querySelectorAll("mark[data-id]").forEach(m => m.onclick = () => select(m.dataset.id, false));
  doc.querySelectorAll("mark.taicut").forEach(m => m.onclick = () => {
    alert("Tailoring block '" + m.dataset.opt + "' is removed by the Project Profile. Set it back to 'keep' to restore the text.");
  });
  ds.forEach(updateMark);
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
  const d = byId[activeId];
  if (!d) {
    p.innerHTML = `<div class="muted">Click any highlighted decision in the text
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
    h += `<div class="dupnote">This bracket crosses structural markup and must be
      resolved in the SpecsIntact editor; it is always listed in the unresolved
      report.</div>` + navRow();
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
  } else if (d.kind === "choice" && d.multi) {
    const picked = new Set(/^\d+(,\d+)*$/.test(e.a) ? e.a.split(",") : []);
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
  h += navRow();
  p.innerHTML = h;
  p.querySelectorAll(".opts button[data-val]").forEach(b =>
    b.onclick = () => setAnswer(d.id, b.dataset.val));
  p.querySelectorAll(".opts button[data-multi]").forEach(b =>
    b.onclick = () => {
      const cur = eff(d).a;
      const picked = new Set(/^\d+(,\d+)*$/.test(cur) ? cur.split(",") : []);
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
    !(d.kind === "choice" && /^\d+(,\d+)*$/.test(e.a)) ? e.a : "";
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
      save(); renderProfile(); updateProgress();
      if (it.key === UNITS_KEY || DATA.tailoring_options[it.key]) buildDoc();
    });
    rows.appendChild(row);
  }
}
function updateProgress() {
  const uniq = ds.filter(d => !d.duplicate_of && d.safe && !inRemovedTai(d));
  const done = uniq.filter(d => eff(d).a).length;
  const profDone = Object.keys(state.profile).length;
  const profAll = Object.keys(DATA.tailoring_options).length + (nPlural ? 1 : 0);
  document.getElementById("pBar").style.width =
    Math.round(100 * (done + profDone) / (uniq.length + profAll)) + "%";
  document.getElementById("pCount").textContent =
    `${done} / ${uniq.length} decisions · ${profDone} / ${profAll} profile`;
}
function refresh() {
  ds.forEach(updateMark);
  renderPanel();
  updateProgress();
}

// ---- header / footer actions ----
document.getElementById("btnNext").onclick = gotoNextUnanswered;
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
  const profOpen = profAll - Object.keys(state.profile).length;
  if (open.length || profOpen > 0) {
    const list = open.slice(0, 15).join(", ") + (open.length > 15 ? " …" : "");
    if (!confirm(`${open.length} decision(s) and ${profOpen} profile setting(s) are still unanswered:\n${list}\n\nExport anyway? They will be flagged for engineer review, never defaulted.`))
      return;
  }
  const payload = { section: DATA.section, title: DATA.title,
    revision: DATA.revision, exported: new Date().toISOString(),
    complete: open.length === 0 && profOpen <= 0,
    unanswered: open,
    profile: state.profile, answers: state.answers };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)],
    { type: "application/json" }));
  a.download = DATA.section.replace(/^SECTION\s+/i, "") + ".answers.json";
  a.click();
};
document.getElementById("btnImport").onclick = () =>
  document.getElementById("fileImport").click();
document.getElementById("fileImport").onchange = ev => {
  const f = ev.target.files[0];
  if (!f) return;
  f.text().then(t => {
    const data = JSON.parse(t);
    state.profile = data.profile || {};
    state.answers = data.answers || {};
    save(); buildDoc(); renderPanel(); updateProgress(); renderProfile();
  });
};
document.getElementById("btnClear").onclick = () => {
  if (confirm("Clear every answer on this page?")) {
    state = { profile: {}, answers: {}, view: state.view || "redline" }; overrideIds.clear();
    save(); buildDoc(); renderPanel(); updateProgress(); renderProfile();
  }
};

document.getElementById("hTitle").textContent = DATA.section + " — " + DATA.title;
document.getElementById("hSub").textContent =
  (DATA.revision || DATA.date_code || "") +
  (DATA.umrl_date ? " · UMRL " + DATA.umrl_date : "") +
  " · answers autosave in this browser";
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
    )
    Path(out_path).write_text(html, encoding="utf-8")
