"""Single-file interactive HTML decision page.

`write_html(manifest, out_path)` renders the decision manifest as a
self-contained HTML file: no server, no dependencies, works from disk or
email. The engineer clicks through decisions grouped by spec article,
answers autosave to the browser's localStorage, and Export downloads an
answers JSON that `specgen generate --answers x.json` consumes directly.

Semantics mirror the Excel workbook: choices pick options (or custom text
or delete), blanks take a value, optionals keep/delete, duplicates follow
the first instance unless overridden, plurals and tailoring are answered
once in the Project Profile block.
"""

from __future__ import annotations

import json
from pathlib import Path

from .answers import PLURAL_KEY

_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #f5f6f8; --card: #ffffff; --ink: #1a2330; --muted: #64748b;
  --line: #e2e8f0; --accent: #1f4e79; --accent-ink: #ffffff;
  --choice: #b45309; --blank: #15803d; --optional: #9d174d;
  --mark: #fef3c7; --mark-ink: #78350f; --done: #f0fdf4; --done-line: #86efac;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1520; --card: #1a2330; --ink: #e6edf6; --muted: #8b9bb0;
    --line: #2c3a4f; --accent: #6ea8d8; --accent-ink: #0f1520;
    --choice: #f0a860; --blank: #7fd49a; --optional: #f28cb4;
    --mark: #4a3a12; --mark-ink: #fbd77e; --done: #12271a; --done-line: #245a38;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; }
header { position: sticky; top: 0; z-index: 5; background: var(--card);
  border-bottom: 1px solid var(--line); padding: 14px 22px;
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }
header h1 { font-size: 17px; margin: 0; }
header .sub { color: var(--muted); font-size: 13px; }
.progress { flex: 1; min-width: 220px; display: flex; align-items: center; gap: 10px; }
.bar { flex: 1; height: 8px; background: var(--line); border-radius: 99px; overflow: hidden; }
.bar i { display: block; height: 100%; width: 0; background: var(--accent); transition: width .25s; }
.count { font-size: 13px; color: var(--muted); white-space: nowrap; }
button, .btn { font: inherit; border: 1px solid var(--line); background: var(--card);
  color: var(--ink); border-radius: 8px; padding: 6px 12px; cursor: pointer; }
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
main { max-width: 980px; margin: 0 auto; padding: 20px 22px 80px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 16px 18px; margin-bottom: 14px; }
.profile h2 { margin: 0 0 4px; font-size: 15px; }
.profile p { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.profile .row { display: flex; align-items: center; gap: 10px; padding: 6px 0;
  border-top: 1px solid var(--line); }
.profile .row:first-of-type { border-top: none; }
.profile .name { flex: 1; font-weight: 600; font-size: 14px; }
.profile .meta { color: var(--muted); font-size: 12px; margin-right: 8px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg button { border: none; border-radius: 0; padding: 5px 14px; background: transparent; }
.seg button.on { background: var(--accent); color: var(--accent-ink); }
.tabs { display: flex; gap: 8px; margin: 18px 0 12px; }
.tabs button.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
h3.art { font-size: 13px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--muted); margin: 26px 0 10px; }
.dec { border-left: 4px solid var(--line); }
.dec.answered { background: var(--done); border-color: var(--done-line); }
.dec .top { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.chip { font-size: 11px; font-weight: 700; letter-spacing: .03em; padding: 2px 8px;
  border-radius: 99px; border: 1px solid var(--line); color: var(--muted); }
.chip.kind-choice { color: var(--choice); border-color: currentColor; }
.chip.kind-blank { color: var(--blank); border-color: currentColor; }
.chip.kind-optional { color: var(--optional); border-color: currentColor; }
.chip.warn { color: #b91c1c; border-color: currentColor; }
.hint { font-size: 13px; color: var(--muted); font-style: italic; margin: 2px 0 8px; }
.ctx { font-size: 14px; color: var(--ink); margin: 4px 0 12px; }
.ctx mark { background: var(--mark); color: var(--mark-ink); padding: 1px 4px;
  border-radius: 4px; font-weight: 600; }
.opts { display: flex; flex-wrap: wrap; gap: 8px; }
.opts button { max-width: 100%; text-align: left; }
.opts button.on { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
.opts button.danger.on { background: #b91c1c; border-color: #b91c1c; color: #fff; }
.freeform { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
.freeform input[type=text] { flex: 1; min-width: 200px; font: inherit; padding: 6px 10px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg); color: var(--ink); }
.dupnote { font-size: 13px; color: var(--muted); }
.dupnote a { color: var(--accent); cursor: pointer; }
.notes-row { margin-top: 10px; }
.notes-row input { width: 100%; font: inherit; font-size: 13px; padding: 5px 10px;
  border: 1px dashed var(--line); border-radius: 8px; background: transparent; color: var(--ink); }
footer.actions { position: fixed; bottom: 0; left: 0; right: 0; background: var(--card);
  border-top: 1px solid var(--line); padding: 10px 22px; display: flex; gap: 10px;
  justify-content: center; }
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
</header>
<main>
  <section class="card profile" id="profileCard">
    <h2>Project profile — answer once, applies everywhere</h2>
    <p>Tailoring options control whole blocks of the section. Keep what applies
       to this project; remove what does not.</p>
    <div id="profileRows"></div>
  </section>
  <div class="tabs">
    <button data-f="todo" class="on">To answer</button>
    <button data-f="done">Answered</button>
    <button data-f="all">All</button>
  </div>
  <div id="decisions"></div>
</main>
<footer class="actions">
  <button class="primary" id="btnExport">Export answers (JSON)</button>
  <button id="btnImport">Import answers</button>
  <button id="btnClear">Clear all</button>
  <input type="file" id="fileImport" accept=".json" class="hide">
</footer>
<script>
const DATA = __DATA__;
const PLURAL_KEY = __PLURAL_KEY__;
const KEY = "specgen:" + DATA.section + ":" + (DATA.revision || "");
let state = { profile: {}, answers: {} };
try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
let filter = "todo";

const ds = DATA.decisions.filter(d => !d.in_note && !d.plural);
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
function setAnswer(id, val) {
  const cur = state.answers[id] || {};
  if (cur.answer === val) delete cur.answer; else cur.answer = val;
  if (cur.answer || cur.notes) state.answers[id] = cur; else delete state.answers[id];
  save(); renderAll();
}
function setNotes(id, val) {
  const cur = state.answers[id] || {};
  if (val) cur.notes = val; else delete cur.notes;
  if (cur.answer || cur.notes) state.answers[id] = cur; else delete state.answers[id];
  save(); updateProgress();
}

function ctxHtml(c) {
  const m = c.match(/^(.*)»(.*)«(.*)$/s);
  if (!m) return esc(c);
  return esc(m[1]) + "<mark>" + esc(m[2]) + "</mark>" + esc(m[3]);
}

function decCard(d) {
  const e = eff(d);
  const answered = !!e.a;
  const div = document.createElement("article");
  div.className = "card dec" + (answered ? " answered" : "");
  div.dataset.id = d.id;
  let top = `<div class="top"><span class="chip">${d.id}</span>` +
    `<span class="chip kind-${d.kind}">${d.kind}</span>`;
  if (!d.safe) top += `<span class="chip warn">manual edit needed</span>`;
  if (d.duplicate_of) top += `<span class="chip">same as ${d.duplicate_of}</span>`;
  top += `</div>`;
  let body = top;
  if (d.hint) body += `<div class="hint">${esc(d.hint)}</div>`;
  body += `<div class="ctx">${ctxHtml(d.context)}</div>`;
  if (!d.safe) {
    body += `<div class="dupnote">This bracket crosses structural markup; resolve it
      in the SpecsIntact editor. It is always listed in the unresolved report.</div>`;
    div.innerHTML = body; return div;
  }
  if (d.duplicate_of && !(state.answers[d.id] && state.answers[d.id].answer)) {
    const srcTxt = e.a ? `following its answer: <b>${esc(e.a)}</b>` : "unanswered so far";
    body += `<div class="dupnote">Same decision as ${d.duplicate_of} — ${srcTxt}.
      <a data-act="override">Answer this instance differently…</a></div>`;
    div.innerHTML = body;
    div.querySelector("[data-act=override]").onclick = () => {
      div.replaceWith(fullCard(d)); };
    return div;
  }
  div.innerHTML = body + controlsHtml(d, e);
  wire(div, d);
  return div;
}
function fullCard(d) {
  const e = eff(d);
  const div = document.createElement("article");
  div.className = "card dec" + (e.a ? " answered" : "");
  div.dataset.id = d.id;
  let top = `<div class="top"><span class="chip">${d.id}</span>` +
    `<span class="chip kind-${d.kind}">${d.kind}</span></div>`;
  div.innerHTML = top + `<div class="ctx">${ctxHtml(d.context)}</div>` + controlsHtml(d, e);
  wire(div, d);
  return div;
}
function controlsHtml(d, e) {
  const own = state.answers[d.id] || {};
  let h = "";
  if (d.kind === "choice") {
    h += `<div class="opts">` + d.options.map((o, i) =>
      `<button data-val="${i + 1}" class="${e.a == String(i + 1) ? "on" : ""}">` +
      `${i + 1}) ${esc(o)}</button>`).join("") +
      `<button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">remove entirely</button></div>`;
    h += freeform(d, e, "…or type replacement text");
  } else if (d.kind === "optional") {
    h += `<div class="opts">` +
      `<button data-val="keep" class="${e.a === "keep" ? "on" : ""}">keep</button>` +
      `<button data-val="delete" class="danger ${e.a === "delete" ? "on" : ""}">delete</button></div>`;
    h += freeform(d, e, "…or type replacement text");
  } else {
    h += freeform(d, e, "value to fill in", true);
  }
  h += `<div class="notes-row"><input data-notes placeholder="note for the audit log (optional)"
        value="${esc(own.notes || "")}"></div>`;
  return h;
}
function freeform(d, e, ph, isBlank) {
  const custom = e.a && !["keep", "delete"].includes(e.a) &&
    !(d.kind === "choice" && /^\d+(,\d+)*$/.test(e.a)) ? e.a : "";
  return `<div class="freeform"><input type="text" data-custom placeholder="${ph}"
    value="${esc(custom)}"><button data-act="apply">${isBlank ? "Set" : "Use text"}</button></div>`;
}
function wire(div, d) {
  div.querySelectorAll(".opts button").forEach(b =>
    b.onclick = () => setAnswer(d.id, b.dataset.val));
  const inp = div.querySelector("[data-custom]");
  const btn = div.querySelector("[data-act=apply]");
  if (btn) btn.onclick = () => { if (inp.value.trim()) setAnswer(d.id, inp.value.trim()); };
  if (inp) inp.onkeydown = ev => { if (ev.key === "Enter" && inp.value.trim())
    setAnswer(d.id, inp.value.trim()); };
  const notes = div.querySelector("[data-notes]");
  if (notes) notes.onchange = () => setNotes(d.id, notes.value.trim());
}

function renderProfile() {
  const rows = document.getElementById("profileRows");
  rows.innerHTML = "";
  const items = Object.entries(DATA.tailoring_options).map(([k, v]) =>
    ({ key: k, meta: v.blocks + " block" + (v.blocks > 1 ? "s" : "") }));
  if (nPlural) items.push({ key: PLURAL_KEY,
    meta: nPlural + " plural [s] markers", labels: ["plural", "singular"] });
  for (const it of items) {
    const val = state.profile[it.key] || "";
    const row = document.createElement("div");
    row.className = "row";
    const l1 = it.labels ? it.labels[0] : "keep", l2 = it.labels ? it.labels[1] : "remove";
    row.innerHTML = `<span class="name">${esc(it.key)}</span>
      <span class="meta">${esc(it.meta)}</span>
      <span class="seg">
        <button data-v="keep" class="${val === "keep" ? "on" : ""}">${l1}</button>
        <button data-v="remove" class="${val === "remove" ? "on" : ""}">${l2}</button></span>`;
    row.querySelectorAll(".seg button").forEach(b => b.onclick = () => {
      state.profile[it.key] = state.profile[it.key] === b.dataset.v ? "" : b.dataset.v;
      if (!state.profile[it.key]) delete state.profile[it.key];
      save(); renderAll();
    });
    rows.appendChild(row);
  }
}
function updateProgress() {
  const uniq = ds.filter(d => !d.duplicate_of && d.safe);
  const done = uniq.filter(d => eff(d).a).length;
  const profDone = Object.keys(state.profile).length;
  const profAll = Object.keys(DATA.tailoring_options).length + (nPlural ? 1 : 0);
  document.getElementById("pBar").style.width =
    Math.round(100 * (done + profDone) / (uniq.length + profAll)) + "%";
  document.getElementById("pCount").textContent =
    `${done} / ${uniq.length} decisions · ${profDone} / ${profAll} profile`;
}
function renderAll() {
  renderProfile();
  const box = document.getElementById("decisions");
  box.innerHTML = "";
  let lastLoc = null;
  for (const d of ds) {
    const answered = !!eff(d).a;
    if (filter === "todo" && answered) continue;
    if (filter === "done" && !answered) continue;
    if (d.location !== lastLoc) {
      const h = document.createElement("h3");
      h.className = "art"; h.textContent = d.location || "(header)";
      box.appendChild(h); lastLoc = d.location;
    }
    box.appendChild(decCard(d));
  }
  if (!box.children.length) {
    const p = document.createElement("p");
    p.style.color = "var(--muted)";
    p.textContent = filter === "todo" ? "Nothing left to answer here — export your answers below."
      : "Nothing here yet.";
    box.appendChild(p);
  }
  updateProgress();
}

document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  filter = b.dataset.f;
  document.querySelectorAll(".tabs button").forEach(x => x.classList.toggle("on", x === b));
  renderAll();
});
document.getElementById("btnExport").onclick = () => {
  const payload = { section: DATA.section, title: DATA.title,
    revision: DATA.revision, exported: new Date().toISOString(),
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
    save(); renderAll();
  });
};
document.getElementById("btnClear").onclick = () => {
  if (confirm("Clear every answer on this page?")) {
    state = { profile: {}, answers: {} }; save(); renderAll();
  }
};

document.getElementById("hTitle").textContent = DATA.section + " — " + DATA.title;
document.getElementById("hSub").textContent =
  (DATA.revision || DATA.date_code || "") +
  (DATA.umrl_date ? " · UMRL " + DATA.umrl_date : "") +
  " · answers autosave in this browser";
renderAll();
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
    )
    Path(out_path).write_text(html, encoding="utf-8")
