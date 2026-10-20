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

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from . import secfile
from .anchors import section_anchors
from .answers import PLURAL_KEY, UNITS_KEY, resolve_answer_keys
from .errors import GenerateError  # noqa: F401  (re-exported for callers)
from .manifest import section_subsections
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
_SPT_MARK_RE = re.compile(r' sg-spt="SPT-\d+"')


def _removed_ancestor(spts: dict, sid: str, removed: set) -> str | None:
    p = spts[sid]["parent"]
    while p:
        if p in removed:
            return p
        p = spts[p]["parent"]
    return None


def _spt_entry(s: dict, action: str, rec: dict | None, source: str, **extra) -> dict:
    return {
        "id": s["id"],
        "kind": "subsection",
        "action": action,
        "answer": (rec or {}).get("answer", ""),
        "notes": (rec or {}).get("notes", ""),
        "source": source,
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
) -> dict:
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
    for s in sorted(subsections, key=lambda s: -s["src"][0]):
        at = s["src"][0]
        if not src.startswith("<SPT", at):
            raise GenerateError(f"internal error: {s['id']} span does not start at <SPT")
        src = src[: at + 4] + f' {_SPT_MARK}="{s["id"]}"' + src[at + 4 :]

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

        if not ans or (
            low == "keep" and g.kind not in ("optional", "submittal-review")
        ):
            u = {"id": g.gid, "kind": g.kind, "options": [o.text for o in g.options]}
            if entry.get("conflict"):
                u["note"] = entry["conflict"]
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
            wrapped = _rev_wrap(g, rev, low, after, picked_for_rev, office)
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

    kept_default = 0
    for s in subsections:
        sid, rec = s["id"], spt_effective.get(s["id"])
        if sid in removed_ids or _removed_ancestor(spts, sid, removed_ids):
            continue
        if sid not in present:
            if rec and rec["answer"] == "remove":
                structure_log.append(
                    _spt_entry(s, f"already removed with {_gone_reason(s)}", rec, "answer"))
            elif rec:
                structure_log.append(_spt_entry(
                    s, f"keep had no effect: removed with {_gone_reason(s)}", rec, "answer"))
            continue
        if rec:
            structure_log.append(_spt_entry(s, "kept", rec, "answer"))
        else:
            structure_log.append(_spt_entry(s, "kept by default", None, "default"))
            kept_default += 1
    redline.extend(structure_log)

    # strip the tracking markers; nothing below may see them
    src = _SPT_MARK_RE.sub("", src)
    rev = _SPT_MARK_RE.sub("", rev)
    for c in redline:
        for k in ("before", "after"):
            if isinstance(c.get(k), str):
                c[k] = _SPT_MARK_RE.sub("", c[k])
    if _SPT_MARK in src or _SPT_MARK in rev:
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
    unresolved = []
    for fg in final_groups:
        if fg.in_note:
            continue
        opts = [o.text for o in fg.options]
        bucket = pool.get(_sig(opts))
        origin = bucket.pop(0) if bucket else None
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
        "subsections_answered": len(spt_answers),
        "decisions_total": len(groups),
        "resolved": len(
            [r for r in redline if r["kind"] not in ("tailoring", "subsection")]
        ),
        "unresolved": len(unresolved),
        "tailoring_blocks_removed": removed_tai,
        "subsections_removed": len(removed_ids),
        "subsections_kept_default": kept_default,
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
        if c["kind"] not in ("tailoring", "units", "subsection")
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
