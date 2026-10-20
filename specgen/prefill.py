"""prefill: design data + section annotation -> answers (spec 2026-10-13, sections 4-6).

Deterministic. Writes the specgen.answers/2 JSON that the decision page and
`generate` already read, keyed by anchor. Every answer records where it came
from (`source`: kind, ref, rule, data_source, value) with state "auto".

Never defaults: a rule whose data is missing, whose equipment rows
disagree, or whose value matches no option leaves its decision with an
empty answer and a note naming why ("prefill (heat-recovery): needs
bod.heat_recovery"), which the page and .unresolved.md show.

Order: project-level answers (agency tailoring, units, plural from
quantity), then the annotation's profile overrides, then structural rules
(remove_unless on subsections), then everything else; a rule whose target
sits inside a subsection removed by an earlier rule is skipped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .annotation import Annotation, Rule, check_targets, resolve_targets, section_number
from .answers import PLURAL_KEY, UNITS_KEY
from .conditions import Context, derive_rows, evaluate
from .designdata import DesignData

# Tailoring options named after an agency, answered from project.agency
AGENCIES = ("ARMY", "NAVY", "AIR FORCE", "NASA", "USACE")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_WS_RE = re.compile(r"\s+")
_UNKNOWN = "__unknown__"


class PrefillError(Exception):
    pass


@dataclass
class PrefillResult:
    payload: dict  # the answers JSON
    report: list[dict]  # one entry per project setting and per rule


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _same(a, b) -> bool:
    return _fmt(a).strip().casefold() == _fmt(b).strip().casefold()


class _Lookup:
    """Reads fields for one rule and remembers which ones it used, for the
    answer's source and for the unresolved reason."""

    def __init__(self, rows: list[dict], dd: DesignData, ann: Annotation):
        self.rows, self.dd, self.ann = rows, dd, ann
        self.missing: list[str] = []
        self.disagree: list[str] = []
        self.used: list[tuple[str, str, object]] = []  # (scope, field, value)

    def get(self, name: str):
        if name.startswith(("bod.", "project.")):
            scope, f = name.split(".", 1)
            obj = self.dd.bod if scope == "bod" else self.dd.project
            if f not in obj:
                self.missing.append(name)
                return None
            self.used.append((scope, f, obj[f]))
            return obj[f]
        f = name[len("equipment."):] if name.startswith("equipment.") else name
        if not self.rows:
            self.missing.append(f"{self.ann.schedule} rows")
            return None
        vals = []
        for r in self.rows:
            if f not in r:
                self.missing.append(r.get(_UNKNOWN, {}).get(f, f"{r['mark']}.{f}"))
            else:
                vals.append((r["mark"], r[f]))
        if len(vals) < len(self.rows):
            return None
        if any(not _same(v, vals[0][1]) for _, v in vals[1:]):
            self.disagree.append(", ".join(f"{m}={v!r}" for m, v in vals))
            return None
        self.used.append(("equipment", f, vals[0][1]))
        return vals[0][1]

    def problem(self) -> str | None:
        if self.disagree:
            return "equipment rows disagree: " + "; ".join(self.disagree)
        if self.missing:
            return "needs " + ", ".join(dict.fromkeys(self.missing))
        return None

    def source(self, rule: Rule, value) -> dict:
        marks = ",".join(r["mark"] for r in self.rows)
        refs, kinds = [], []
        for scope, f, _ in self.used:
            if scope == "equipment":
                derived = " (derived)" if f in (self.ann.derive or {}) else ""
                refs.append(f"{marks}.{f}{derived}")
                kinds.append("schedule")
            else:
                refs.append(f"{scope}.{f}")
                kinds.append("bod" if scope == "bod" else "rule")
        kind = next((k for k in ("schedule", "bod", "rule") if k in kinds), "rule")
        if "schedule" in kinds:
            data_source = ",".join(sorted({r["source"] for r in self.rows}))
        else:
            data_source = "bod" if kind == "bod" else "project"
        return {"kind": kind, "ref": ", ".join(dict.fromkeys(refs)), "rule": rule.id,
                "data_source": data_source, "value": value}


def _render(template, look: _Lookup):
    text = str(template)
    names = _PLACEHOLDER_RE.findall(text)
    vals = {n: look.get(n) for n in names}
    if look.problem():
        return None, None
    if len(names) == 1 and text == "{" + names[0] + "}":
        raw = vals[names[0]]
        return _fmt(raw), raw
    out = _PLACEHOLDER_RE.sub(lambda m: _fmt(vals[m.group(1)]), text)
    return out, out


def _cond_fields(cond, scope: str | None = None) -> list[tuple[str, str]]:
    out = []
    for k, v in cond.items():
        if k in ("all", "any"):
            for c in v:
                out += _cond_fields(c, scope)
        elif k == "not":
            out += _cond_fields(v, scope)
        elif scope is None and k in ("any_equipment", "all_equipment", "bod", "project"):
            out += _cond_fields(v, "equipment" if k.endswith("equipment") else k)
        elif scope is not None:
            out.append((scope, k))
    return out


def _requires(rule: Rule, look: _Lookup) -> str | None:
    probe = _Lookup(look.rows, look.dd, look.ann)
    for req in rule.requires:
        probe.get(req)
    return probe.problem()


def prefill(manifest: dict, dd: DesignData, ann: Annotation) -> PrefillResult:
    problems = check_targets(ann, manifest)
    if problems:
        raise PrefillError(
            "annotation does not pass annotate-check:\n  - " + "\n  - ".join(problems)
        )
    hits = {rid: h[0] for rid, h in resolve_targets(ann, manifest).items()}
    subs = {s["id"]: s for s in manifest.get("subsections", [])}
    decisions = {d["id"]: d for d in manifest["decisions"]}
    rows = derive_rows(dd.rows(ann.schedule), ann.derive)
    ctx = Context(rows=rows, bod=dd.bod, project=dd.project, schedule=ann.schedule)
    report: list[dict] = []
    answers: dict[str, dict] = {}
    profile: dict[str, str] = {}

    # --- project level (plan D2, D6) ---
    agency = str(dd.project["agency"]).strip().upper()
    for name in sorted(manifest.get("tailoring_options", {})):
        if name.strip().upper() in AGENCIES:
            profile[name] = "keep" if name.strip().upper() == agency else "remove"
            report.append({"kind": "project", "setting": name, "outcome": "answered",
                           "answer": profile[name], "reason": f"project.agency = {dd.project['agency']}"})
    if manifest["counts"].get("unit_pairs"):
        profile[UNITS_KEY] = dd.project["units"].lower()
        report.append({"kind": "project", "setting": UNITS_KEY, "outcome": "answered",
                       "answer": profile[UNITS_KEY], "reason": f"project.units = {dd.project['units']}"})
    if any(d.get("plural") and not d["in_note"] for d in manifest["decisions"]):
        qty = [r.get("quantity") for r in rows]
        if rows and all(isinstance(q, (int, float)) and not isinstance(q, bool) for q in qty):
            total = sum(qty)
            profile[PLURAL_KEY] = "keep" if total > 1 else "remove"
            report.append({"kind": "project", "setting": PLURAL_KEY, "outcome": "answered",
                           "answer": profile[PLURAL_KEY], "reason": f"equipment quantity = {_fmt(total)}"})
        else:
            report.append({"kind": "project", "setting": PLURAL_KEY, "outcome": "unresolved",
                           "answer": "", "reason": f"needs equipment.quantity on every {ann.schedule} row"})
    for name, action in (ann.profile or {}).items():
        profile[name] = str(action).strip().lower()
        report.append({"kind": "project", "setting": name, "outcome": "answered",
                       "answer": profile[name], "reason": "annotation profile"})

    # --- rules: structural first, then the rest, each in annotation order ---
    def record(hit: dict, answer: str, notes: str = "") -> dict:
        rec = {"answer": answer, "notes": notes, "id": hit["id"]}
        if hit["kind"] == "spt":
            rec.update(num=subs[hit["id"]]["num"], title=subs[hit["id"]]["title"])
        else:
            rec["options"] = decisions[hit["id"]]["options"]
        return rec

    removed: list[tuple[int, int, str]] = []
    ordered = [r for r in ann.rules if r.action == "remove_unless" and r.target["kind"] == "spt"]
    ordered += [r for r in ann.rules if r not in ordered]
    for rule in ordered:
        hit = hits[rule.id]
        entry = {"kind": "rule", "rule": rule.id, "target": hit["id"], "label": hit["label"]}
        inside = next((sid for a, b, sid in removed if a <= hit["offset"] < b), None)
        if inside:
            report.append({**entry, "outcome": "skipped", "answer": "",
                           "reason": f"inside removed {inside}"})
            continue
        look = _Lookup(rows, dd, ann)
        why = _requires(rule, look)
        answer = value = None
        if why is None and rule.action == "remove_unless":
            res = evaluate(rule.arg, ctx)
            if res.value is None:
                why = "needs " + ", ".join(res.missing)
            else:
                for scope, f in _cond_fields(rule.arg):
                    name = f"{scope}.{f}" if scope != "equipment" else f
                    look.get(name)
                yes = "keep"
                no = "remove" if hit["kind"] == "spt" else "delete"
                answer = yes if res.value else no
                value = {f"{s}.{f}" if s != "equipment" else f: v for s, f, v in look.used}
        elif why is None:
            template = rule.arg["match"] if rule.action == "choose" else rule.arg
            text, value = _render(template, look)
            why = look.problem()
            if why is None and rule.action == "choose":
                opts = decisions[hit["id"]]["options"]
                pick = [i for i, o in enumerate(opts) if _same(o, text)]
                if not pick:
                    why = f"value {text!r} matches no option ({' | '.join(opts)})"
                else:
                    answer = str(pick[0] + 1)
            elif why is None:
                answer = text
        if why is not None:
            answers[hit["anchor"]] = record(hit, "", f"prefill ({rule.id}): {why}")
            report.append({**entry, "outcome": "unresolved", "answer": "", "reason": why})
            continue
        rec = record(hit, answer)
        rec["source"] = look.source(rule, value)
        rec["state"] = "auto"
        answers[hit["anchor"]] = rec
        report.append({**entry, "outcome": "answered", "answer": answer,
                       "reason": rec["source"]["ref"]})
        if hit["kind"] == "spt" and answer == "remove":
            a, b = subs[hit["id"]]["src"]
            removed.append((a, b, hit["id"]))

    # Duplicates: generate copies an answer only from a decision's FIRST
    # instance to the later ones. When a rule answered a later instance
    # (23 64 10: the 2.4.1 compressor choice repeats the submittal list's),
    # give the first instance the same answer so every instance follows.
    for rec in list(answers.values()):
        if not rec["answer"] or "options" not in rec:
            continue
        first_id = decisions[rec["id"]].get("duplicate_of")
        if not first_id:
            continue
        first = decisions[first_id]
        if first["anchor"] in answers or any(a <= first["offset"] < b for a, b, _ in removed):
            continue
        rule_id = rec["source"]["rule"]
        answers[first["anchor"]] = {
            **rec, "id": first_id, "options": first["options"],
            "notes": f"prefill ({rule_id}): same decision as {rec['id']}",
        }
        report.append({"kind": "duplicate", "rule": f"{rule_id} (first instance)", "target": first_id,
                       "label": " | ".join(first["options"]), "outcome": "answered",
                       "answer": rec["answer"], "reason": f"same decision as {rec['id']}"})

    payload = {
        "schema": "specgen.answers/2",
        "section": manifest["section"],
        "title": manifest["title"],
        "revision": manifest.get("revision"),
        "fingerprint": manifest["fingerprint"],
        "generated_by": "specgen prefill",
        "inputs": {
            "project": dd.project.get("name"),
            "design_data": dd.path.name if dd.path else None,
            "annotation": ann.path.name if ann.path else None,
            "section": section_number(manifest),
        },
        "profile": profile,
        "answers": answers,
        "prefill": {"report": report},
    }
    return PrefillResult(payload=payload, report=report)


def dumps(res: PrefillResult) -> str:
    """Deterministic JSON: sorted keys, no timestamps."""
    return json.dumps(res.payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def report_markdown(res: PrefillResult) -> str:
    p = res.payload
    rules = [r for r in res.report if r["kind"] == "rule"]
    proj = [r for r in res.report if r["kind"] == "project"]
    n = {k: sum(r["outcome"] == k for r in rules) for k in ("answered", "unresolved", "skipped")}
    md = [
        f"# Prefill for {p['section']}, {p['title']}",
        "",
        f"Project {p['inputs']['project'] or '?'}; design data "
        f"{p['inputs']['design_data'] or '?'}; annotation {p['inputs']['annotation'] or '?'}.",
        "",
        f"{len(rules)} rules: {n['answered']} answered, {n['unresolved']} left for the "
        f"engineer, {n['skipped']} skipped (inside a removed subsection).",
        "",
        "## Project settings",
        "",
    ]
    md += [f"- {r['setting']}: {r['answer'] or 'unresolved'} ({r['reason']})" for r in proj]
    md += ["", "## Rules", ""]
    for r in rules + [r for r in res.report if r["kind"] == "duplicate"]:
        line = f"- **{r['rule']}** -> {r['target']} ({r['label'][:60]}): "
        if r["outcome"] == "answered":
            line += f"`{r['answer']}` from {r['reason']}"
        else:
            line += f"{r['outcome']}: {r['reason']}"
        md.append(line)
    open_ = [r for r in res.report if r["outcome"] == "unresolved"]
    md += ["", "## Left for the engineer", ""]
    md += [f"- {r.get('rule') or r.get('setting')}: {r['reason']}" for r in open_] or ["- nothing"]
    return "\n".join(md) + "\n"
