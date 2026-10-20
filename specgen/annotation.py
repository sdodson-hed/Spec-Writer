"""Section annotations (spec 2026-10-13, section 5).

One YAML file per section, e.g. annotations/23 64 10.yaml. An annotation
never contains spec text: each rule points at decisions by anchor path and
kind, and says how design data answers them.

    section: "23 64 10"
    applies_to: {schedule: air_cooled_chiller}
    derive: {fact: {from: field, map: {...}} | {value: v}}       # optional
    profile: {"ARMY": remove, ...}                              # optional overrides
    rules:
      - id: compressor-type
        target: {path: "PART 2/SELF-CONTAINED*/*TYPE*", kind: choice,
                 options: [Scroll, Reciprocating, Rotary Screw], nth: 1}
        choose: {match: "{compressor_type}"}     # or: fill: "{refrigerant}"
                                                 # or: remove_unless: <condition>
        requires: [bod.heat_recovery]            # optional

Targets match the anchor path segment by segment (fnmatch within a
segment, titles normalized like anchors), then kind, then option text.
Every rule must resolve to exactly one decision: check_targets / the
annotate-check command fail otherwise, which catches annotations broken by a
UFGS release before they write a wrong spec. Unknown keys are errors.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

from .anchors import norm_title
from .conditions import ConditionError, validate, validate_derive

KINDS = ("choice", "blank", "optional", "submittal-review", "plural", "spt")
ACTIONS = {
    "choose": ("choice",),
    "fill": ("blank",),
    "remove_unless": ("spt", "optional", "submittal-review"),
}
_TOP = {"section", "applies_to", "derive", "profile", "rules"}
_RULE = {"id", "target", "requires", "note", *ACTIONS}
_TARGET = {"path", "kind", "options", "nth"}
_REQUIRES_RE = re.compile(r"^(bod|project|equipment)\.[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_FIELD_RE = re.compile(r"^((bod|project)\.)?[A-Za-z_][A-Za-z0-9_]*$")
_WS_RE = re.compile(r"\s+")


class AnnotationError(Exception):
    pass


@dataclass
class Rule:
    id: str
    target: dict
    action: str  # choose | fill | remove_unless
    arg: object
    requires: list[str] = field(default_factory=list)


@dataclass
class Annotation:
    section: str
    schedule: str
    rules: list[Rule]
    derive: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    path: Path | None = None


def _check_template(where: str, text, problems: list[str]) -> None:
    if not isinstance(text, (str, int, float)):
        problems.append(f"{where}: expected text with {{field}} placeholders")
        return
    for name in _PLACEHOLDER_RE.findall(str(text)):
        if not _FIELD_RE.match(name):
            problems.append(f"{where}: placeholder {{{name}}} is not a field name")


def from_dict(d: dict, path: Path | None = None) -> Annotation:
    problems: list[str] = []
    if not isinstance(d, dict):
        raise AnnotationError("an annotation is a YAML mapping")
    for k in sorted(set(d) - _TOP):
        problems.append(f"unknown key {k!r}")
    section = str(d.get("section", "")).strip()
    if not section:
        problems.append("section is required")
    applies = d.get("applies_to")
    schedule = applies.get("schedule") if isinstance(applies, dict) else None
    if not schedule or set(applies) != {"schedule"}:
        problems.append("applies_to must be {schedule: <name>}")
    try:
        validate_derive(d.get("derive"))
    except ConditionError as e:
        problems.append(str(e))
    profile = d.get("profile") or {}
    if not isinstance(profile, dict):
        problems.append("profile must be a mapping of setting: action")
        profile = {}
    for k, v in profile.items():
        if str(v).strip().lower() not in ("keep", "remove", "si", "ip"):
            problems.append(f"profile.{k} must be keep, remove, si or ip (got {v!r})")

    rules: list[Rule] = []
    seen: set[str] = set()
    raw_rules = d.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        problems.append("rules must be a non-empty list")
        raw_rules = []
    for i, r in enumerate(raw_rules):
        if not isinstance(r, dict):
            problems.append(f"rules[{i}] must be a mapping")
            continue
        rid = str(r.get("id") or f"rules[{i}]")
        if not r.get("id"):
            problems.append(f"rules[{i}]: id is required")
        elif rid in seen:
            problems.append(f"duplicate rule id {rid!r}")
        seen.add(rid)
        for k in sorted(set(r) - _RULE):
            problems.append(f"{rid}: unknown key {k!r}")
        t = r.get("target")
        if not isinstance(t, dict):
            problems.append(f"{rid}: target is required")
            t = {}
        else:
            for k in sorted(set(t) - _TARGET):
                problems.append(f"{rid}: unknown target key {k!r}")
            if not isinstance(t.get("path"), str) or not t.get("path"):
                problems.append(f"{rid}: target.path is required")
            if t.get("kind") not in KINDS:
                problems.append(f"{rid}: target.kind must be one of {', '.join(KINDS)}")
            if "options" in t and not (
                isinstance(t["options"], list) and t["options"]
                and all(isinstance(o, str) for o in t["options"])
            ):
                problems.append(f"{rid}: target.options must be a list of option texts")
            if "nth" in t and not (isinstance(t["nth"], int) and t["nth"] >= 1):
                problems.append(f"{rid}: target.nth must be a whole number from 1")
        acts = [a for a in ACTIONS if a in r]
        if len(acts) != 1:
            problems.append(f"{rid}: exactly one of choose, fill, remove_unless")
            continue
        act = acts[0]
        if t.get("kind") in KINDS and t["kind"] not in ACTIONS[act]:
            problems.append(f"{rid}: {act} needs kind {' or '.join(ACTIONS[act])}")
        arg = r[act]
        if act == "choose":
            if not isinstance(arg, dict) or set(arg) != {"match"}:
                problems.append(f"{rid}: choose must be {{match: <text>}}")
            else:
                _check_template(f"{rid}.choose.match", arg["match"], problems)
        elif act == "fill":
            _check_template(f"{rid}.fill", arg, problems)
        else:
            try:
                validate(arg, f"{rid}.remove_unless")
            except ConditionError as e:
                problems.append(str(e))
        req = r.get("requires", [])
        if not isinstance(req, list) or not all(
            isinstance(x, str) and _REQUIRES_RE.match(x) for x in req
        ):
            problems.append(
                f"{rid}: requires entries are bod.<field>, project.<field> or equipment.<field>"
            )
            req = []
        rules.append(Rule(rid, t, act, arg, req))

    if problems:
        where = f"{path}: " if path else ""
        raise AnnotationError(where + "invalid annotation:\n  - " + "\n  - ".join(problems))
    return Annotation(
        section=section, schedule=schedule, rules=rules,
        derive=d.get("derive") or {}, profile=profile, path=path,
    )


def load_annotation(path: Path | str) -> Annotation:
    import yaml  # PyYAML; only annotation loading needs it

    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise AnnotationError(f"{path}: not valid YAML: {e}") from e
    return from_dict(data, path)


# --- target resolution -------------------------------------------------------

def _norm(t: str) -> str:
    return _WS_RE.sub(" ", t).strip().casefold()


def _path_matches(pattern: str, path: str) -> bool:
    pats = [norm_title(p) for p in pattern.split("/")]
    segs = path.split("/")
    return len(pats) == len(segs) and all(
        fnmatch.fnmatchcase(s, p) for p, s in zip(pats, segs)
    )


def _candidates(manifest: dict) -> list[dict]:
    out = []
    for d in manifest["decisions"]:
        if d["in_note"]:
            continue
        path, rest = d["anchor"].split("#", 1)
        out.append({"id": d["id"], "kind": rest.split(":", 1)[0], "path": path,
                    "anchor": d["anchor"], "offset": d["offset"],
                    "options": d["options"], "label": " | ".join(d["options"])})
    for s in manifest.get("subsections", []):
        out.append({"id": s["id"], "kind": "spt", "path": s["anchor"].split("#", 1)[0],
                    "anchor": s["anchor"], "offset": s["src"][0],
                    "options": [s["title"]], "label": f"{s['num']} {s['title']}"})
    return sorted(out, key=lambda c: c["offset"])


def _all_matches(rule: Rule, cands: list[dict]) -> list[dict]:
    t = rule.target
    want = [_norm(o) for o in t["options"]] if "options" in t else None
    return [
        c for c in cands
        if c["kind"] == t["kind"] and _path_matches(t["path"], c["path"])
        and (want is None or [_norm(o) for o in c["options"]] == want)
    ]


def resolve_targets(ann: Annotation, manifest: dict) -> dict[str, list[dict]]:
    """rule id -> matched decisions/subsections, in document order. With
    nth, the single nth match (or nothing if there are fewer)."""
    cands = _candidates(manifest)
    out = {}
    for r in ann.rules:
        hits = _all_matches(r, cands)
        n = r.target.get("nth")
        out[r.id] = (hits[n - 1 : n] if n else hits)
    return out


def section_number(manifest: dict) -> str:
    return re.sub(r"^SECTION\s+", "", manifest.get("section", ""), flags=re.I).strip()


def check_targets(ann: Annotation, manifest: dict) -> list[str]:
    problems = []
    if _norm(ann.section) != _norm(section_number(manifest)):
        problems.append(
            f"annotation is for section {ann.section}, master is {section_number(manifest)}"
        )
    cands = _candidates(manifest)
    for r in ann.rules:
        hits = _all_matches(r, cands)
        n = r.target.get("nth")
        if not hits:
            problems.append(
                f"{r.id}: 0 matches for {r.target['kind']} at {r.target['path']!r}"
            )
        elif n and n > len(hits):
            problems.append(f"{r.id}: nth {n} but only {len(hits)} matches")
        elif len(hits) > 1 and not n:
            ids = ", ".join(h["id"] for h in hits)
            problems.append(f"{r.id}: {len(hits)} matches ({ids}); add options or nth")
    return problems
