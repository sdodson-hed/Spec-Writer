"""Provenance: merging a prefill re-run into an answers file the engineer has
worked on (spec 2026-10-13, section 6).

Record states:
  auto        written by prefill: follows the data on every re-run
  overridden  the engineer changed a prefilled answer; source.kind is
              "manual" and source.was keeps the original source and answer
  conflict    the data changed under an override (or under a hand answer):
              source.now holds what prefill says now; the engineer decides,
              and until then generate applies neither
  (none)      answered by hand where prefill had nothing (source.kind
              "manual" or no source at all)

merge(existing, fresh) applies those rules per answer and per project
setting (profile + profile_meta) and returns the merged payload and a
report of everything that changed. Deterministic.
"""

from __future__ import annotations

import copy


def _txt(v) -> str:
    return str(v if v is not None else "").strip().casefold()


def _answered(rec: dict | None) -> bool:
    return bool(rec) and bool(str(rec.get("answer", "")).strip())


def _merge_record(e: dict | None, n: dict | None) -> tuple[dict | None, str | None, str]:
    """(result or None to drop, outcome or None if nothing worth reporting, detail)."""
    if e is None:
        return copy.deepcopy(n), None, ""
    if not _answered(e):
        notes = str(e.get("notes", "")).strip()
        engineer_note = notes and not notes.startswith("prefill (")
        if n is None:
            return (copy.deepcopy(e) if engineer_note else None), None, ""
        res = copy.deepcopy(n)
        if engineer_note:
            res["notes"] = notes + (f"; {n['notes']}" if n.get("notes") else "")
        return res, None, ""
    if e.get("state") == "auto":
        if n is None:
            return None, "dropped", f"no rule answers it now (was {e['answer']!r})"
        if n == e:
            return copy.deepcopy(e), None, ""
        return copy.deepcopy(n), "updated", f"{e['answer']!r} -> {n.get('answer', '')!r}"

    # the engineer's answer (overridden, conflict, or by hand)
    res = copy.deepcopy(e)
    src = dict(res.get("source") or {})
    was = src.get("was")
    if not _answered(n):
        if res.get("state") == "conflict":  # prefill went silent: nothing to compare
            src.pop("now", None)
            res["source"] = {**src, "kind": "manual"}
            if was:
                res["state"] = "overridden"
            else:
                res.pop("state", None)
        return res, None, ""
    now = {**n.get("source", {}), "answer": n["answer"]}
    if _txt(n["answer"]) == _txt(e["answer"]):
        if was or e.get("state") in ("overridden", "conflict"):
            res["source"] = {"kind": "manual", "was": now}
            res["state"] = "overridden"
        else:
            src.pop("now", None)
            if src:
                res["source"] = src
            res.pop("state", None)
        return res, "agrees", f"prefill now agrees: {n['answer']!r}"
    if (was and _txt(n["answer"]) == _txt(was.get("answer"))
            and _txt(n.get("source", {}).get("value")) == _txt(was.get("value"))):
        res["source"] = {"kind": "manual", "was": was}
        res["state"] = "overridden"
        outcome = "resolved" if e.get("state") == "conflict" else "kept override"
        return res, outcome, f"engineer answer {e['answer']!r} stands; data unchanged"
    res["source"] = {"kind": "manual", **({"was": was} if was else {}), "now": now}
    res["state"] = "conflict"
    ns = n.get("source", {})
    detail = (f"engineer answer {e['answer']!r}; prefill now {n['answer']!r} "
              f"from {ns.get('ref', '?')} = {ns.get('value')!r}")
    return res, "conflict", detail


def _profile_record(value, meta: dict | None) -> dict | None:
    meta = meta or {}
    answer = value if value is not None else meta.get("answer")
    if answer is None:
        return None
    rec = {"answer": answer}
    for k in ("source", "state"):
        if k in meta:
            rec[k] = copy.deepcopy(meta[k])
    return rec


def merge(existing: dict, fresh: dict) -> tuple[dict, list[dict]]:
    out = copy.deepcopy(fresh)
    report: list[dict] = []
    old, new = existing.get("answers") or {}, fresh.get("answers") or {}
    answers: dict[str, dict] = {}
    for key in [*new, *(k for k in old if k not in new)]:
        if key.startswith("ME@"):  # text edits are the engineer's
            answers[key] = copy.deepcopy(old.get(key, new.get(key)))
            continue
        res, outcome, detail = _merge_record(old.get(key), new.get(key))
        if res is not None:
            answers[key] = res
        if outcome:
            ref = old.get(key) or new.get(key) or {}
            report.append({"key": key, "id": ref.get("id"), "outcome": outcome, "detail": detail})
    out["answers"] = answers

    oprof, ometa = existing.get("profile") or {}, existing.get("profile_meta") or {}
    nprof, nmeta = fresh.get("profile") or {}, fresh.get("profile_meta") or {}
    profile, meta = {}, {}
    names = [*nprof, *(k for k in [*oprof, *ometa] if k not in nprof)]
    for name in dict.fromkeys(names):
        e = _profile_record(oprof.get(name), ometa.get(name))
        n = _profile_record(nprof.get(name), nmeta.get(name)) if name in nprof else None
        res, outcome, detail = _merge_record(e, n)
        if res is not None:
            if res.get("state") == "conflict":
                meta[name] = {"source": res["source"], "state": "conflict", "answer": res["answer"]}
            else:
                profile[name] = res["answer"]
                if "source" in res:
                    meta[name] = {k: res[k] for k in ("source", "state") if k in res}
        if outcome:
            report.append({"key": f"profile:{name}", "id": name, "outcome": outcome, "detail": detail})
    out["profile"], out["profile_meta"] = profile, meta
    out.setdefault("prefill", {})["merge"] = report
    return out, report
