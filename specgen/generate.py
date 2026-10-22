"""Generator: apply an answer workbook to a master section.

Order of operations:
  1. Resolve bracket decisions (reverse document order, so earlier source
     offsets stay valid while splicing).
  2. Remove tailoring blocks whose every OPT name is marked "remove"
     (spans recomputed on the already-edited source).
  3. Remove the unchosen <MET>/<ENG> unit elements per the project-level
     SI/IP profile answer (spans recomputed on the already-edited source).
  4. Verify: re-parse, byte round-trip, well-formed XML — before writing.

Outputs: the tailored .sec, a redline log (every change, machine-readable),
and an unresolved-decisions report for engineer review.
"""

from __future__ import annotations

import difflib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from . import secfile
from .anchors import section_anchors
from .answers import PLURAL_KEY, UNITS_KEY, resolve_answer_keys
from .errors import GenerateError  # noqa: F401  (re-exported for callers)
from .cleanup import plan_cleanup
from .manifest import build_manifest, section_subsections
from .scan import (
    additive_join,
    connector_runs,
    connector_word,
    context_excerpt,
    duplicate_map,
    is_additive,
    is_connector,
    is_plural,
    scan_groups,
    strip_connector,
)

_WS_RE = re.compile(r"\s+")

# Temporary attribute generate puts on every <SPT> open tag to track
# subsections through the edit passes. Never present in a master (checked
# across the WBDG corpus) and never in any output (verified before writing).
_SPT_MARK = "sg-spt"
# Same idea for removal cleanup targets (submittal items, reference entries,
# SD headings, organization blocks): value is the index into the plan.
_CLN_MARK = "sg-cln"
_SPT_MARK_RE = re.compile(r' sg-(?:spt|cln)="[^"]*"')
_CLEANUP_TAG = {
    "submittal-item": "<ITM", "reference": "<RID",
    "sd-heading": "<LST", "reference-org": "<REF",
}
_TRAIL_RE = re.compile(r"(?:\s|<BRK/>)*")
# redline kinds that are consequences, not bracket decisions: kept out of
# the "resolved" count and the per-decision section of .redline.md
_CLEANUP_KINDS = ("submittal-item", "reference", "sd-heading", "reference-org")
_NOT_DECISIONS = ("tailoring", "subsection", *_CLEANUP_KINDS)


def _removed_ancestor(spts: dict, sid: str, removed: set) -> str | None:
    p = spts[sid]["parent"]
    while p:
        if p in removed:
            return p
        p = spts[p]["parent"]
    return None


def _cleanup_entry(act: dict, action: str, before: str = "") -> dict:
    entry = {
        "id": act["id"],
        "kind": act["kind"],
        "name": act["name"],
        "action": action,
        "answer": "",
        "notes": "",
        "source": {"kind": "cleanup"},
        "caused_by": act["caused_by"],
        "before": before,
        "after": "",
    }
    if act.get("reviewer"):
        entry["reviewer"] = act["reviewer"]
    if act.get("rids"):
        entry["rids"] = act["rids"]
    return entry


def _provenance(rec: dict | None, default_kind: str) -> dict:
    """source/state for a redline entry (spec section 6): the answer's own
    provenance when it has one, else {"kind": default_kind}."""
    rec = rec or {}
    out = {"source": rec["source"] if isinstance(rec.get("source"), dict)
           else {"kind": default_kind}}
    if rec.get("state"):
        out["state"] = rec["state"]
    return out


def _spt_entry(s: dict, action: str, rec: dict | None, source: str, **extra) -> dict:
    # source: "default" for an unanswered keep (spec: source.kind default),
    # otherwise the answer's provenance (manual when it has none)
    prov = {"source": {"kind": "default"}} if source == "default" else _provenance(rec, "manual")
    return {
        "id": s["id"],
        "kind": "subsection",
        "action": action,
        "answer": (rec or {}).get("answer", ""),
        "notes": (rec or {}).get("notes", ""),
        **prov,
        "num": s["num"],
        "title": s["title"],
        "before": "",
        "after": "",
        **extra,
    }


def _strip_revisions(source: str, drop: str, unwrap: str) -> str:
    """Serialize with <drop> elements removed and <unwrap> elements replaced
    by their children. Both are only ever wrapped around balanced spans."""
    sec = secfile.parse_source(source, tolerant=True)

    def emit(node) -> str:
        if not isinstance(node, secfile.Element):
            return node.serialize()
        if node.name == drop:
            return ""
        if node.name == unwrap:
            return "".join(emit(c) for c in node.children)
        if node.self_closing:
            return node.open_raw
        inner = "".join(emit(c) for c in node.children)
        return f"{node.open_raw}{inner}{node.close_raw}"

    parts = [n.serialize() for n in sec.prolog]
    parts.append(emit(sec.root))
    parts.extend(n.serialize() for n in sec.epilog)
    return "".join(parts)


def _check_well_formed(
    sec: secfile.SecFile, master_defects: list[dict], what: str
) -> None:
    """Well-formed XML check that tolerates the master's own source defects
    (tolerant-parse stray close tags) and nothing else. The output may carry
    fewer defects (a removed block can take one with it), never a new one."""
    allowed = Counter(d["raw"] for d in master_defects)
    found = Counter(d["raw"] for d in sec.defects)
    if found - allowed:
        raise GenerateError(
            f"internal error: {what} has source defects the master does not: "
            f"{sorted((found - allowed).elements())}"
        )
    text = sec.source
    for d in sorted(sec.defects, key=lambda d: -d["offset"]):
        off, raw = d["offset"], d["raw"]
        text = text[:off] + " " * len(raw) + text[off + len(raw) :]
    ET.fromstring(text.encode(secfile.ENCODING))  # raises if not well-formed


def resolve_revisions(source: str) -> str:
    """Accept all changes: drop <DEL> content, keep <ADD> content.

    Assumes the DEL/ADD markup was produced by this generator (masters with
    pre-existing revision markup are rejected by generate)."""
    return _strip_revisions(source, drop="DEL", unwrap="ADD")


def revert_revisions(source: str) -> str:
    """Reject all changes: keep <DEL> content, drop <ADD> content.

    Assumes the DEL/ADD markup was produced by this generator (masters with
    pre-existing revision markup are rejected by generate)."""
    return _strip_revisions(source, drop="ADD", unwrap="DEL")


def _plural_case(marker: str, prev: str) -> str:
    """A kept plural marker written in capitals after a lowercase letter
    ("Chiller[S]" in 23 64 10) would read "ChillerS": match the word's case.
    "CHILLER[S]" in an all-caps title keeps its capital."""
    if marker.isupper() and prev.isalpha() and prev.islower():
        return marker.lower()
    return marker


def _rev_wrap(g, src: str, low: str, after: str, picked, office: str) -> str:
    before = src[g.src_start : g.src_end]
    if low == "delete":
        return f"<DEL>{before}</DEL>"
    if low == "keep":
        content = src[g.options[0].src_start : g.options[0].src_end]
        if office:
            content = re.sub(
                r"\[[^][]*\]",
                lambda m: f"<DEL>{m.group(0)}</DEL><ADD>{office}</ADD>",
                content,
                count=1,
            )
        return f"<DEL>[</DEL>{content}<DEL>]</DEL>"
    if picked is not None:
        parts, keep = [], set(picked)
        for i, o in enumerate(g.options):
            body = src[o.src_start : o.src_end]
            if i in keep:
                parts.append(f"<DEL>[</DEL>{body}<DEL>]</DEL>")
            else:
                parts.append(f"<DEL>[{body}]</DEL>")
        # Inter-option gaps are DEL-wrapped so resolve() joins picked bodies
        # exactly like the clean output does. Gaps are whitespace-only here:
        # markup-gap groups are always safe=False and never reach the splicer.
        out, pos = [], g.src_start
        for i, o in enumerate(g.options):
            gap = src[pos : o.src_start - 1]  # up to the '['
            if gap:
                out.append(f"<DEL>{gap}</DEL>")
            out.append(parts[i])
            pos = o.src_end + 1  # past the ']'
        tail = src[pos : g.src_end]
        if tail:
            out.append(f"<DEL>{tail}</DEL>")
        return "".join(out)
    return f"<DEL>{before}</DEL><ADD>{after}</ADD>"  # custom / fill-in


def _match_option(groups_options: list, ans: str) -> list[int] | None:
    """Interpret an answer against a choice group's options.
    Returns list of 0-based option indices, or None if not an option ref."""
    parts = [p.strip() for p in ans.split(",") if p.strip()]
    if parts and all(p.isdigit() for p in parts):
        idx = sorted({int(p) - 1 for p in parts})  # document order, deduped
        if all(0 <= i < len(groups_options) for i in idx):
            return idx
        return None  # out of range: fall through to custom-text handling
    # exact (whitespace-normalized) text match against a single option
    norm = _WS_RE.sub(" ", ans).strip().lower()
    matches = [
        i
        for i, o in enumerate(groups_options)
        if _WS_RE.sub(" ", o.text).strip().lower() == norm
    ]
    # also accept the workbook-dropdown variant where "," was shown as " /"
    if not matches and " /" in ans:
        norm2 = norm.replace(" /", ",")
        matches = [
            i
            for i, o in enumerate(groups_options)
            if _WS_RE.sub(" ", o.text).strip().lower() == norm2
        ]
    return matches if matches else None


def _escape_manual_edit_text(text: str) -> str:
    """Escape plain replacement text before splicing into SEC/XML source."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _invalid_edit_reason(
    edit: dict, src: str, stream: str, offs: list[int], groups: list
) -> str:
    """Validate a manual text edit (an ``ME@`` answer) against the ORIGINAL
    scan. Returns "" if valid, else a human-readable rejection reason."""
    try:
        start, end = int(edit.get("start")), int(edit.get("end"))
    except (TypeError, ValueError):
        return "manual edit has a non-numeric start/end"
    if not (0 <= start <= end <= len(stream)):
        return "manual edit start/end is out of range for this master"
    if start == end and str(edit.get("before", "")):
        return "zero-length manual edit carries deleted text"
    before = str(edit.get("before", ""))
    if stream[start:end] != before:
        return "selected text no longer matches this master (before mismatch)"
    if end > start and offs[end - 1] - offs[start] != end - 1 - start:
        return "selection crosses structural markup"
    # Synthetic layout chars (<BRK/> newline, list-indent tab) map to their
    # originating TAG's offset, not to a text char — splicing over one would
    # cut into markup bytes. A one-char edit on such a char passes the
    # contiguity check above, so test each char explicitly: real stream
    # chars always equal their source char; synthetic ones sit on a '<'.
    for k in range(start, end):
        if src[offs[k]] != stream[k]:
            return (
                "selection covers a layout character produced by markup "
                "(line break or list indent), which has no editable text"
            )
    # Only SAFE groups lock their spans: unsafe groups (options crossing
    # structural markup) are answered by editing their literal text, and the
    # contiguity check above already keeps any edit tag-free.
    for g in groups:
        if start < g.char_end and end > g.char_start and g.safe:
            return f"selection overlaps decision {g.gid}"
    return ""


def generate(
    master: Path | str,
    profile: dict[str, str],
    answers: dict[str, dict],
    out_sec: Path | str,
    revisions: bool = False,
    fingerprint: str | None = None,
    force_stale: bool = False,
    strict: bool = False,
    profile_conflicts: dict[str, str] | None = None,
) -> dict:
    # Project settings in conflict (step 7, D2/D5) are already out of
    # `profile` (unanswered: their tailoring stays); they are listed for review
    profile_conflicts = profile_conflicts or {}
    if strict and profile_conflicts:
        raise GenerateError(
            f"{len(profile_conflicts)} conflict(s) in project settings "
            f"({', '.join(sorted(profile_conflicts))}); resolve them on the decision page"
        )
    master = Path(master)
    master_sec = secfile.parse(master, tolerant=True)
    src = master_sec.source
    # Answer keys -> this master's BRK ids. Anchor keys resolve by anchor
    # (orphans are reported, applied to nothing); BRK keys still go through
    # the stale-fingerprint gate (issue #23). See answers.resolve_answer_keys.
    groups0 = scan_groups(src)[0]
    subsections = section_subsections(master_sec)
    answers, orphans, fp_status = resolve_answer_keys(
        answers, groups0, section_anchors(master_sec), fingerprint,
        force_stale=force_stale, strict=strict, subsections=subsections,
    )
    # subsection keep/remove answers (SPT-NNNN); governed ones were already
    # turned into their bracket's answer by resolve_answer_keys
    spt_answers = {k: v for k, v in answers.items() if k.startswith("SPT-")}
    answers = {k: v for k, v in answers.items() if not k.startswith("SPT-")}
    if revisions and re.search(r"<(?:DEL|ADD)[\s>/]", src):
        raise GenerateError(
            "master already contains <DEL>/<ADD> revision markup; "
            "accept or reject its revisions in SI Editor before generating "
            "with --revisions"
        )
    # Subsection decisions (step 3). Answers on subsections inside a removed
    # ancestor are ignored and logged. Then EVERY <SPT> gets a tracking
    # attribute on its open tag; the bracket, tailoring and units passes
    # below move it along with the tag, so after them the structural pass
    # can see exactly which subsections survived, remove the answered ones,
    # and log the rest. All markers are stripped before verification.
    spts = {s["id"]: s for s in subsections}
    structure_log: list[dict] = []
    asked_remove = {sid for sid, r in spt_answers.items() if r["answer"] == "remove"}
    spt_effective: dict[str, dict] = {}
    for sid, rec in spt_answers.items():
        anc = _removed_ancestor(spts, sid, asked_remove)
        if anc:
            structure_log.append(
                _spt_entry(spts[sid], f"ignored: inside removed {anc}", rec, "answer")
            )
        else:
            spt_effective[sid] = rec

    # Removal cleanup (step 4): submittal items, reference entries, emptied
    # SD headings and organization blocks whose only body uses sit inside
    # the subsections being removed. Planned in master coordinates; each
    # target gets its own tracking marker, removed in the structural pass.
    removing = {
        sid: tuple(spts[sid]["src"]) for sid, rec in spt_effective.items()
        if rec["answer"] == "remove"
    }
    for s in subsections:  # governed: removed through its bracket's delete
        brk = s.get("governed_by")
        if brk and str(answers.get(brk, {}).get("answer", "")).strip().lower() == "delete":
            removing[s["id"]] = tuple(s["src"])
    removing = {
        sid: sp for sid, sp in removing.items()
        if not any(o[0] <= sp[0] and sp[1] <= o[1] and o != sp for o in removing.values())
    }
    cleanup = (
        plan_cleanup(master_sec, build_manifest(master_sec), removing)
        if removing else {"remove": [], "blocked": [], "section_refs_dropped": []}
    )

    marks = [(s["src"][0], "<SPT", f' {_SPT_MARK}="{s["id"]}"') for s in subsections]
    for i, act in enumerate(cleanup["remove"]):
        tag = _CLEANUP_TAG[act["kind"]]
        marks.append((act["src"][0], tag, f' {_CLN_MARK}="{i}"'))
    for at, tag, attr in sorted(marks, key=lambda t: -t[0]):
        if not src.startswith(tag, at):
            raise GenerateError(f"internal error: marker target at {at} is not {tag}")
        src = src[: at + len(tag)] + attr + src[at + len(tag) :]

    rev = src
    groups, stream, offs = scan_groups(src)
    if len(groups) != len(groups0):
        raise GenerateError("internal error: subsection markers changed the bracket scan")
    by_id = {g.gid: g for g in groups}

    me_edits_in = {k: v for k, v in answers.items() if k.startswith("ME@")}
    bracket_answers = {k: v for k, v in answers.items() if not k.startswith("ME@")}

    unknown = sorted(set(bracket_answers) - set(by_id))
    if unknown:
        raise GenerateError(f"answer IDs not in section: {unknown}")

    dups = duplicate_map(groups)
    plural_action = profile.get(PLURAL_KEY, "")

    redline: list[dict] = []
    unresolved: list[dict] = []
    unresolved_edits: list[dict] = []
    valid_edits: list[dict] = []
    accepted_spans: list[tuple[int, int, str]] = []  # (start, end, key)

    def _edit_sort_key(item):
        # Deterministic acceptance order: ascending start (first edit wins on
        # overlap); malformed starts sort last, then by key for stability.
        try:
            return (0, int(item[1].get("start")), item[0])
        except (TypeError, ValueError):
            return (1, 0, item[0])

    for key, edit in sorted(me_edits_in.items(), key=_edit_sort_key):
        reason = _invalid_edit_reason(edit, src, stream, offs, groups)
        if not reason:
            start, end = int(edit["start"]), int(edit["end"])
            for a_start, a_end, a_key in accepted_spans:
                if start < a_end and end > a_start:
                    reason = f"overlaps another text edit ({a_key})"
                    break
        if reason:
            unresolved_edits.append(
                {
                    "id": key,
                    "kind": "manual-edit",
                    "options": [],
                    "note": f"{reason}; re-open the decision page against "
                    "this master",
                }
            )
            continue
        accepted_spans.append((start, end, key))
        after_plain = str(edit.get("after", ""))
        # A zero-width insertion (end == start) must splice a zero-width source
        # range at offs[start]; the old src_end = offs[end-1]+1 = offs[start-1]+1
        # inverts the range (duplicating stripped markup) whenever stream chars
        # start-1 and start are not source-contiguous, and points at end-of-text
        # when start == 0. At end-of-text (start == len(stream)) offs[start] is
        # out of range, so splice just past the last stream char (before any
        # trailing markup) — the source position analogous to offs[start].
        src_at_start = (
            offs[start]
            if start < len(offs)
            else (offs[-1] + 1 if offs else len(src))
        )
        valid_edits.append(
            {
                "id": key,
                "src_start": src_at_start,
                "src_end": src_at_start if end == start else offs[end - 1] + 1,
                "before": str(edit.get("before", "")),
                "after_plain": after_plain,
                "after_esc": _escape_manual_edit_text(after_plain),
                "notes": str(edit.get("notes", "")),
            }
        )

    worklist = sorted(
        [*groups, *valid_edits],
        key=lambda x: -(x["src_start"] if isinstance(x, dict) else x.src_start),
    )
    for item in worklist:
        if isinstance(item, dict):
            e = item
            if revisions:
                wrapped = f"<DEL>{e['before']}</DEL><ADD>{e['after_esc']}</ADD>"
                rev = rev[: e["src_start"]] + wrapped + rev[e["src_end"] :]
            src = src[: e["src_start"]] + e["after_esc"] + src[e["src_end"] :]
            redline.append(
                {
                    "id": e["id"],
                    "kind": "manual-edit",
                    "action": "text edited",
                    "answer": e["after_plain"],
                    "notes": e["notes"],
                    "before": e["before"],
                    "after": e["after_esc"],
                }
            )
            continue
        g = item
        if g.in_note:
            continue  # designer-note text is never edited
        entry = bracket_answers.get(g.gid, {})
        propagated = ""
        if (
            not entry.get("answer")
            and not entry.get("conflict")  # a conflict is never filled in
            and g.gid in dups
            and dups[g.gid] in bracket_answers
        ):
            entry = bracket_answers[dups[g.gid]]
            propagated = dups[g.gid]
        if not entry.get("answer") and is_plural(g) and plural_action:
            entry = {
                "answer": "keep" if plural_action == "keep" else "delete",
                "notes": "",
            }
            propagated = PLURAL_KEY
        ans = entry.get("answer", "")
        notes = entry.get("notes", "")
        before = src[g.src_start : g.src_end]
        low = ans.lower()
        picked_for_rev = None
        case_fixed = False  # plural marker lowercased: revisions show DEL/ADD

        if not ans or (
            low == "keep" and g.kind not in ("optional", "submittal-review")
        ):
            u = {"id": g.gid, "kind": g.kind, "options": [o.text for o in g.options]}
            if entry.get("conflict"):
                u["note"] = entry["conflict"]
            elif not ans and entry.get("notes"):
                u["note"] = entry["notes"]  # e.g. why prefill could not answer it
            unresolved.append(u)
            continue

        if not g.safe:
            unresolved.append(
                {
                    "id": g.gid,
                    "kind": g.kind,
                    "options": [o.text for o in g.options],
                    "note": "answer given but group spans markup unevenly; "
                    "needs manual edit in SI Editor",
                }
            )
            continue

        if low == "delete":
            after = ""
            action = "deleted"
        elif low == "keep":  # optional: keep text, drop brackets
            after = src[g.options[0].src_start : g.options[0].src_end]
            action = "kept (brackets removed)"
            if is_plural(g):
                fixed = _plural_case(after, stream[g.char_start - 1] if g.char_start else "")
                if fixed != after:
                    action = (f"kept plural; lowercased {after!r} to match the "
                              f"word before it")
                    after = fixed
                    case_fixed = True
            if g.kind == "submittal-review" and entry.get("office"):
                filled = re.sub(
                    r"\[[^][]*\]", lambda _m: entry["office"], after, count=1
                )
                if filled != after:  # only claim the fill if a blank existed
                    after = filled
                    action = f"kept; reviewer office = {entry['office']}"
        else:
            picked = _match_option(g.options, ans) if g.kind == "choice" else None
            if picked is not None:
                if is_additive(g):
                    # Additive list: recompose kept cores with fresh
                    # separators ("a", "a and b", "a, b, and c"). Interior
                    # connector-only spans are joiners, never kept on their
                    # own; connector spans at the group's EDGES join it to
                    # the surrounding sentence and are kept verbatim.
                    lo, hi = connector_runs(g)

                    def _body(i: int) -> str:
                        return src[g.options[i].src_start : g.options[i].src_end]

                    cores = [
                        strip_connector(_body(i))
                        for i in picked
                        if lo <= i < hi and not is_connector(g.options[i].text)
                    ]
                    joined = additive_join(cores, connector_word(g))
                    if cores:
                        prefix = "".join(_body(i) for i in range(lo))
                        suffix = "".join(_body(i) for i in range(hi, len(g.options)))
                        first = _body(lo)
                        lead = first[: len(first) - len(first.lstrip())]
                        if prefix and not lead and not prefix[-1].isspace():
                            lead = " "
                        after = prefix + lead + joined + suffix
                    else:
                        after = ""
                    action = f"kept items {[i + 1 for i in picked]}"
                    # revisions fall back to DEL/ADD: the joined text is not a
                    # plain concatenation of the kept bodies
                else:
                    after = "".join(
                        src[g.options[i].src_start : g.options[i].src_end]
                        for i in picked
                    )
                    action = f"chose option {[i + 1 for i in picked]}"
                    picked_for_rev = picked
            else:
                after = ans  # custom / fill-in text (plain text, no markup)
                action = "filled custom value" if g.kind == "blank" else "custom text"
        if revisions:
            office = (
                entry.get("office", "") if g.kind == "submittal-review" else ""
            )
            wrapped = _rev_wrap(
                g, rev, "replace" if case_fixed else low, after, picked_for_rev, office
            )
            rev = rev[: g.src_start] + wrapped + rev[g.src_end :]
        src = src[: g.src_start] + after + src[g.src_end :]
        if propagated:
            action += f" (propagated from {propagated})"
        if entry.get("via"):  # answered on its governed subsection row
            action += f" (via {entry['via']})"
        redline.append(
            {
                "id": g.gid,
                "kind": g.kind,
                "action": action,
                "answer": ans,
                "notes": notes,
                "before": before,
                "after": after,
                # provenance (spec section 6): only in .redline.json, never
                # in the issued .sec
                **(_provenance(entry, "manual") if entry.get("source") or entry.get("state")
                   else {}),
            }
        )

    # --- tailoring removal (on the edited source) ---
    removed_tai = 0
    if any(v == "remove" for v in profile.values()):

        def removable(opt_attr: str) -> bool:
            names = [n.strip() for n in opt_attr.split(",")]
            return all(profile.get(n) == "remove" for n in names)

        tmp = master.parent / (master.name + ".gen.tmp")
        while True:
            tmp.write_bytes(src.encode(secfile.ENCODING))
            tree = secfile.parse(tmp, tolerant=True)
            spans = [
                (t.src_start, t.src_end, t.attrs.get("OPT", ""))
                for t in tree.root.iter("TAI")
                if removable(t.attrs.get("OPT", ""))
            ]
            # outermost only; nested removable blocks go with their parent
            spans = [
                s
                for s in spans
                if not any(o[0] < s[0] and s[1] <= o[1] for o in spans if o != s)
            ]
            if not spans:
                break
            for start, end, opt in sorted(spans, key=lambda s: -s[0]):
                redline.append(
                    {
                        "id": f"TAI@{start}",
                        "kind": "tailoring",
                        "action": "removed block",
                        "answer": f"remove {opt}",
                        "notes": "",
                        "before": src[start:end][:200],
                        "after": "",
                    }
                )
                src = src[:start] + src[end:]
                removed_tai += 1
            if revisions:
                rtmp = master.parent / (master.name + ".rev.tmp")
                rtmp.write_bytes(rev.encode(secfile.ENCODING))
                rtree = secfile.parse(rtmp, tolerant=True)
                rspans = [
                    (t.src_start, t.src_end)
                    for t in rtree.root.iter("TAI")
                    if removable(t.attrs.get("OPT", ""))
                    and not any(a.name == "DEL" for a in t.ancestors())
                ]
                rspans = [
                    s for s in rspans
                    if not any(o[0] < s[0] and s[1] <= o[1] for o in rspans if o != s)
                ]
                for start, end in sorted(rspans, key=lambda s: -s[0]):
                    rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
                rtmp.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)

    # --- unit-system resolution (on the edited source) ---
    units = profile.get(UNITS_KEY, "")
    removed_units = 0
    if units in ("si", "ip"):
        drop = "ENG" if units == "si" else "MET"
        tmp = master.parent / (master.name + ".gen.tmp")
        tmp.write_bytes(src.encode(secfile.ENCODING))
        tree = secfile.parse(tmp, tolerant=True)
        spans = sorted(
            (
                (el.src_start, el.src_end)
                for el in tree.root.iter(drop)
                # designer-note text is never edited
                if not any(a.name == "NTE" for a in el.ancestors())
            ),
            key=lambda s: -s[0],
        )
        for start, end in spans:
            src = src[:start] + src[end:]
            removed_units += 1
        if revisions:
            rtmp = master.parent / (master.name + ".rev.tmp")
            rtmp.write_bytes(rev.encode(secfile.ENCODING))
            rtree = secfile.parse(rtmp, tolerant=True)
            rspans = sorted(
                (
                    (el.src_start, el.src_end)
                    for el in rtree.root.iter(drop)
                    if not any(a.name == "NTE" for a in el.ancestors())
                    and not any(a.name == "DEL" for a in el.ancestors())
                ),
                key=lambda s: -s[0],
            )
            for start, end in rspans:
                rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
            rtmp.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
        if removed_units:
            redline.append(
                {
                    "id": "UNITS",
                    "kind": "units",
                    "action": f"kept {'SI' if units == 'si' else 'IP'} units; "
                    f"removed {removed_units} <{drop}> elements",
                    "answer": units,
                    "notes": "",
                    "before": "",
                    "after": "",
                }
            )

    # --- subsection removal (on the edited source, spec 2026-10-13 sec. 3) ---
    tree = secfile.parse_source(src, tolerant=True)
    present = {
        el.attrs[_SPT_MARK]: (el.src_start, el.src_end)
        for el in tree.root.iter("SPT")
        if _SPT_MARK in el.attrs
    }
    to_remove = sorted(
        (present[sid], sid)
        for sid, rec in spt_effective.items()
        if rec["answer"] == "remove" and sid in present
    )
    removed_ids = {sid for _span, sid in to_remove}

    def _gone_reason(s: dict) -> str:
        # what removed a subsection before the structural pass ran
        tai = s.get("tailoring")
        if tai and all(profile.get(n.strip()) == "remove" for n in tai.split(",")):
            return f"tailoring {tai}"
        enclosing = [
            g for g in groups0
            if g.src_start < s["src"][0] and s["src"][1] <= g.src_end
        ]
        for g in sorted(enclosing, key=lambda g: g.src_end - g.src_start):
            # a bracket that kept its text did not remove the subsection
            if any(c["id"] == g.gid and not c["action"].startswith("kept")
                   for c in redline):
                return g.gid
        return "an enclosing edit"

    superseded: dict[str, str] = {}  # BRK id -> SPT that removed its text
    for (start, end), sid in sorted(to_remove, key=lambda t: -t[0][0]):
        s = spts[sid]
        inside = [
            g.gid for g in groups0
            if s["src"][0] <= g.src_start and g.src_end <= s["src"][1] and not g.in_note
        ]
        for gid in inside:
            superseded[gid] = sid
        structure_log.append(
            _spt_entry(s, "removed subsection", spt_effective[sid], "answer",
                       before=src[start:end][:200], brackets_removed=inside)
        )
        src = src[:start] + src[end:]
    for c in redline:
        if c["id"] in superseded:
            c["action"] += f" (then removed with {superseded[c['id']]})"
    if revisions:
        rtree = secfile.parse_source(rev, tolerant=True)
        rspans = [
            (el.src_start, el.src_end)
            for el in rtree.root.iter("SPT")
            if el.attrs.get(_SPT_MARK) in removed_ids
            and not any(a.name == "DEL" for a in el.ancestors())
        ]
        rspans = [
            sp for sp in rspans
            if not any(o[0] < sp[0] and sp[1] <= o[1] for o in rspans if o != sp)
        ]
        for start, end in sorted(rspans, key=lambda sp: -sp[0]):
            rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]

    # --- removal cleanup (step 4): remove the marked targets that are still
    # present, with the <BRK/>/whitespace run after each; DEL in revisions ---
    def _cln_spans(text: str) -> dict[int, tuple[int, int, bool]]:
        t = secfile.parse_source(text, tolerant=True)
        found: dict[int, tuple[int, int, bool]] = {}
        for el in t.root.iter():
            idx = el.attrs.get(_CLN_MARK)
            if idx is None:
                continue
            end = el.src_end
            if el.name == "RID":  # a reference entry is <RID> plus its <RTL>
                kids = [c for c in el.parent.children if isinstance(c, secfile.Element)]
                nxt = kids.index(el) + 1
                if nxt < len(kids) and kids[nxt].name == "RTL":
                    end = kids[nxt].src_end
            in_del = any(a.name == "DEL" for a in el.ancestors())
            found[int(idx)] = (el.src_start, _TRAIL_RE.match(text, end).end(), in_del)
        return found

    cleanup_log: list[dict] = []
    cleanup_unresolved: list[dict] = []
    cleaned: set[int] = set()
    if cleanup["remove"]:
        present_cln = _cln_spans(src)
        for idx in sorted(present_cln, key=lambda i: -present_cln[i][0]):
            start, end, _ = present_cln[idx]
            act = cleanup["remove"][idx]
            causes = ", ".join(act["caused_by"])
            what = {
                "sd-heading": f"removed: every item under it went with {causes}",
                "reference-org": f"removed: none of its references is used outside {causes}",
            }.get(act["kind"], f"removed: its only uses were in {causes}")
            cleanup_log.append(_cleanup_entry(act, what, before=src[start:end][:200]))
            src = src[:start] + src[end:]
            cleaned.add(idx)
        cleanup_log.reverse()  # removed back to front; log in document order
        for idx, act in enumerate(cleanup["remove"]):
            if idx not in present_cln:
                cleanup_log.append(_cleanup_entry(act, "already removed (bracket or tailoring)"))
        if revisions:
            rfound = _cln_spans(rev)
            for idx in sorted((i for i in cleaned if i in rfound and not rfound[i][2]),
                              key=lambda i: -rfound[i][0]):
                start, end, _ = rfound[idx]
                rev = rev[:start] + "<DEL>" + rev[start:end] + "</DEL>" + rev[end:]
    for b in cleanup["blocked"]:
        brk = b["in_bracket"]
        given = str(bracket_answers.get(brk, {}).get("answer", "")).strip().lower()
        causes = ", ".join(b["caused_by"])
        if given == "delete":
            continue  # the bracket answer already removed it
        if given:
            cleanup_log.append(_cleanup_entry(
                b, f"kept by answer on {brk} although its only references were removed"))
            continue
        note = f"its only references were removed with {causes}; consider delete ({brk})"
        cleanup_log.append(_cleanup_entry(b, f"kept: inside {brk}; {note}"))
        cleanup_unresolved.append(
            {"id": b["id"], "kind": b["kind"], "options": [b["name"]], "note": note}
        )
    redline.extend(cleanup_log)
    done = [cleanup["remove"][i] for i in cleaned]
    cleanup_counts = {
        "submittal_items_removed": sum(a["kind"] == "submittal-item" for a in done),
        "references_removed": sum(
            1 if a["kind"] == "reference" else len(a.get("rids", []))
            for a in done if a["kind"] in ("reference", "reference-org")
        ),
        "reference_orgs_removed": sum(a["kind"] == "reference-org" for a in done),
        "sd_headings_removed": sum(a["kind"] == "sd-heading" for a in done),
        "section_refs_dropped": cleanup["section_refs_dropped"],
    }

    kept_default = 0
    spt_unresolved: list[dict] = []
    for s in subsections:
        sid, rec = s["id"], spt_effective.get(s["id"])
        answered = bool(rec and rec["answer"])
        if sid in removed_ids or _removed_ancestor(spts, sid, removed_ids):
            continue
        if sid not in present:
            if answered and rec["answer"] == "remove":
                structure_log.append(
                    _spt_entry(s, f"already removed with {_gone_reason(s)}", rec, "answer"))
            elif answered:
                structure_log.append(_spt_entry(
                    s, f"keep had no effect: removed with {_gone_reason(s)}", rec, "answer"))
            continue
        if answered:
            structure_log.append(_spt_entry(s, "kept", rec, "answer"))
        else:
            # unanswered: kept by default; a note (e.g. prefill's reason) also
            # puts it on the unresolved list for the engineer
            structure_log.append(_spt_entry(s, "kept by default", rec, "default"))
            kept_default += 1
            if rec and rec.get("notes"):
                spt_unresolved.append({
                    "id": sid, "kind": "subsection", "options": [f"{s['num']} {s['title']}"],
                    "note": f"{rec['notes']}; kept by default until answered",
                })
    redline.extend(structure_log)

    # strip the tracking markers; nothing below may see them
    src = _SPT_MARK_RE.sub("", src)
    rev = _SPT_MARK_RE.sub("", rev)
    for c in redline:
        for k in ("before", "after"):
            if isinstance(c.get(k), str):
                c[k] = _SPT_MARK_RE.sub("", c[k])
    if any(mk in text for mk in (_SPT_MARK, _CLN_MARK) for text in (src, rev)):
        raise GenerateError("internal error: subsection marker left in output")

    # --- rescan the OUTPUT: the unresolved report is defined by what
    # actually remains bracketed, so choices that carried nested brackets
    # (e.g. picking a paragraph that itself contains [copper][aluminum])
    # surface as new open decisions instead of slipping through ---
    def _sig(opts: list[str]) -> tuple:
        return tuple(_WS_RE.sub(" ", o).strip() for o in opts)

    pool: dict[tuple, list[dict]] = {}
    for u in unresolved:
        pool.setdefault(_sig(u["options"]), []).append(u)
    final_groups, final_stream, _ = scan_groups(src)
    open_groups = [fg for fg in final_groups if not fg.in_note]
    origins: dict[int, dict] = {}
    for i, fg in enumerate(open_groups):
        bucket = pool.get(_sig([o.text for o in fg.options]))
        if bucket:
            origins[i] = bucket.pop(0)
    # An edit inside a still-open bracket (units or tailoring removed from its
    # text) changes its options, so the exact match above misses it. Pair it
    # with a leftover original only when the kind and option count agree and
    # the text is clearly the closest (>= 0.8 similar, 0.05 ahead of the next
    # candidate). This names the decision and keeps its note; it applies no
    # answer. Anything less certain stays OPEN@.
    leftover = [u for b in pool.values() for u in b]
    for i, fg in enumerate(open_groups):
        if i in origins:
            continue
        text = " | ".join(_sig([o.text for o in fg.options]))
        scored = sorted(
            ((difflib.SequenceMatcher(None, " | ".join(_sig(u["options"])), text,
                                      autojunk=False).ratio(), n, u)
             for n, u in enumerate(leftover)
             if u.get("kind") == fg.kind and len(u["options"]) == len(fg.options)),
            key=lambda t: (-t[0], t[1]),
        )
        if scored and scored[0][0] >= 0.8 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.05):
            origins[i] = scored[0][2]
            leftover.remove(scored[0][2])
    unresolved = []
    for i, fg in enumerate(open_groups):
        opts = [o.text for o in fg.options]
        origin = origins.get(i)
        entry = {
            "id": origin["id"] if origin else f"OPEN@{fg.src_start}",
            "kind": fg.kind,
            "options": opts,
            "context": context_excerpt(final_stream, fg.char_start, fg.char_end),
        }
        if origin and origin.get("note"):
            entry["note"] = origin["note"]
        if origin is None:
            entry["note"] = (
                "not one of the original decision IDs — it was nested inside "
                "a resolved choice or reshaped by neighboring edits; answer "
                "in a follow-up pass or in SI Editor"
            )
        unresolved.append(entry)
    unresolved.extend(orphans)
    unresolved.extend(cleanup_unresolved)
    unresolved.extend(spt_unresolved)
    unresolved.extend(
        {"id": name, "kind": "profile setting", "options": [], "note": note}
        for name, note in sorted(profile_conflicts.items())
    )
    unresolved.extend(unresolved_edits)

    # --- verify before writing ---
    out_sec = Path(out_sec)
    out_sec.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_sec.with_suffix(out_sec.suffix + ".tmp")
    tmp.write_bytes(src.encode(secfile.ENCODING))
    parsed = secfile.parse(tmp, tolerant=True)
    if not parsed.roundtrips():
        raise GenerateError("internal error: output does not round-trip")
    _check_well_formed(parsed, master_sec.defects, "output")
    tmp.replace(out_sec)

    summary = {
        "master": str(master),
        "output": str(out_sec),
        "answers_fingerprint": fp_status,
        "answers_carried": len(bracket_answers),
        "answers_orphaned": len(orphans),
        "subsections_answered": sum(1 for r in spt_answers.values() if r["answer"]),
        "decisions_total": len(groups),
        "resolved": len(
            [r for r in redline if r["kind"] not in _NOT_DECISIONS]
        ),
        "unresolved": len(unresolved),
        "tailoring_blocks_removed": removed_tai,
        "subsections_removed": len(removed_ids),
        "subsections_kept_default": kept_default,
        **cleanup_counts,
        "units_removed": removed_units,
        "bracket_chars_remaining": src.count("[") + src.count("]"),
        "source_defects": len(master_sec.defects),
    }

    if revisions:
        original = master_sec.source
        if resolve_revisions(rev) != src:
            raise GenerateError("revisions do not resolve to the clean output")
        if revert_revisions(rev) != original:
            raise GenerateError("revisions do not revert to the master")
        _check_well_formed(
            secfile.parse_source(rev, tolerant=True), master_sec.defects,
            "revisions output",
        )
        rev_path = out_sec.with_suffix(".revisions.sec")
        rev_path.write_bytes(rev.encode(secfile.ENCODING))
        summary["revisions_output"] = str(rev_path)

    out_sec.with_suffix(".redline.json").write_text(
        json.dumps({"summary": summary, "changes": redline}, indent=2),
        encoding="utf-8",
    )

    def _plain(raw: str, limit: int = 300) -> str:
        txt = _WS_RE.sub(" ", re.sub(r"<[^>]+>", " ", raw)).strip()
        return (txt[: limit - 1] + "…") if len(txt) > limit else (txt or "(nothing)")

    md = [
        f"# Redline — {out_sec.name}",
        "",
        f"{summary['resolved']} decisions applied, "
        f"{summary['tailoring_blocks_removed']} tailoring blocks removed, "
        f"{summary['unresolved']} left for engineer review.",
        "",
    ]
    plural = [
        c for c in redline if PLURAL_KEY in c["action"] and c["kind"] != "tailoring"
    ]
    brk = [
        c
        for c in redline
        if c["kind"] not in ("units", *_NOT_DECISIONS)
        and PLURAL_KEY not in c["action"]
    ]
    tai = [c for c in redline if c["kind"] == "tailoring"]
    spt_c = [c for c in redline if c["kind"] == "subsection"]
    if plural:
        verb = "kept (plural)" if plural[0]["answer"] == "keep" else "made singular"
        md += [f"_{len(plural)} plural [s] markers {verb} — profile setting._", ""]
    units_c = [c for c in redline if c["kind"] == "units"]
    if units_c:
        md += [f"_{units_c[0]['action']}._", ""]
    for c in sorted(brk, key=lambda c: c["id"]):
        md += [
            f"## {c['id']} — {c['action']}",
            "",
            f"- **Was:** {_plain(c['before'])}",
            f"- **Now:** {_plain(c['after'])}",
        ]
        if c.get("notes"):
            md.append(f"- Note: {c['notes']}")
        md.append("")
    if tai:
        md += ["## Tailoring blocks removed", ""]
        for c in tai:
            md.append(f"- {c['answer']}: {_plain(c['before'], 120)}")
        md.append("")
    if spt_c:
        md += ["## Subsections", ""]
        for c in spt_c:
            if c["action"] == "removed subsection":
                md += [
                    f"## {c['id']} — removed subsection {c['num']} {c['title']}",
                    "",
                    f"- **Was:** {_plain(c['before'], 200)}",
                ]
                if c.get("brackets_removed"):
                    md.append(f"- Decisions removed with it: {', '.join(c['brackets_removed'])}")
                if c.get("notes"):
                    md.append(f"- Note: {c['notes']}")
                md.append("")
        others = [c for c in spt_c
                  if c["action"] not in ("removed subsection", "kept by default")]
        for c in others:
            md.append(f"- {c['id']} {c['num']} {c['title']}: {c['action']}")
        if summary["subsections_kept_default"]:
            md.append(
                f"- {summary['subsections_kept_default']} subsections kept by default (no answer)"
            )
        md.append("")
    cln_c = [c for c in redline if c["kind"] in _CLEANUP_KINDS]
    if cln_c or summary["section_refs_dropped"]:
        md += ["## Cleanup", "",
               "_Submittal items and references whose only uses were in removed "
               "subsections._", ""]
        kind_label = {"submittal-item": "Submittal item", "reference": "Reference",
                      "sd-heading": "SD heading", "reference-org": "Reference organization"}
        for c in cln_c:
            label = c["name"] + (f" (reviewer {c['reviewer']})" if c.get("reviewer") else "")
            if c.get("rids"):
                label += f" [{', '.join(c['rids'])}]"
            where = ", ".join(spts[x]["num"] for x in c["caused_by"])
            if c["action"].startswith("removed"):
                md.append(f"- {kind_label[c['kind']]} {label}: removed, only used in {where}")
            else:
                md.append(f"- {kind_label[c['kind']]} {label}: {c['action']}")
        if summary["section_refs_dropped"]:
            md.append(
                "- section references no longer cited: "
                + ", ".join(summary["section_refs_dropped"])
            )
        md.append("")
    out_sec.with_suffix(".redline.md").write_text("\n".join(md), encoding="utf-8")
    unresolved_md = [
        f"# Unresolved decisions — {out_sec.name}",
        "",
        f"{len(unresolved)} decision(s) need engineer input:",
        "",
    ]
    for u in unresolved:
        opts = " | ".join(u["options"]) if u["kind"] != "blank" else "(fill in)"
        unresolved_md += [f"## {u['id']} · {u['kind']}", f"- Options: {opts}"]
        if "context" in u:
            unresolved_md.append(f"- Context: {u['context']}")
        if u.get("note"):
            unresolved_md.append(f"- **Note:** {u['note']}")
        unresolved_md.append("")
    out_sec.with_suffix(".unresolved.md").write_text(
        "\n".join(unresolved_md), encoding="utf-8"
    )
    return summary
