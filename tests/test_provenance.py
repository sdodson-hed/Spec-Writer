"""Merging a prefill re-run into an existing answers file (spec 2026-10-13,
section 6; plan 2026-10-20 provenance, Task 1, decisions D3-D5)."""

import copy
import json

from specgen.provenance import merge

K = "PART 2/X#choice:abc"  # an anchor


def src(value, ref="ACC-1.compressor_type"):
    return {"kind": "schedule", "ref": ref, "rule": "compressor-type",
            "data_source": "acc-sched-35", "value": value}


def auto(answer, value):
    return {"answer": answer, "notes": "", "id": "BRK-0023",
            "options": ["Scroll", "Reciprocating", "Rotary Screw"],
            "source": src(value), "state": "auto"}


def overridden(answer, was_answer, was_value):
    return {"answer": answer, "notes": "", "id": "BRK-0023",
            "source": {"kind": "manual", "was": {**src(was_value), "answer": was_answer}},
            "state": "overridden"}


def payload(answers, profile=None, meta=None, fp="fresh"):
    return {"schema": "specgen.answers/2", "fingerprint": fp, "answers": answers,
            "profile": profile or {}, "profile_meta": meta or {}, "prefill": {"report": []}}


def m(existing, fresh):
    merged, report = merge(payload(existing, fp="old"), payload(fresh))
    return merged["answers"], {r["key"]: r for r in report}


# --- auto answers follow the data ----------------------------------------------

def test_auto_replaced_by_new_auto():
    a, r = m({K: auto("1", "SCROLL")}, {K: auto("3", "ROTARY SCREW")})
    assert a[K] == auto("3", "ROTARY SCREW") and r[K]["outcome"] == "updated"


def test_auto_replaced_by_unresolved_note():
    note = {"answer": "", "notes": "prefill (compressor-type): needs ACC-1.compressor_type",
            "id": "BRK-0023"}
    a, r = m({K: auto("1", "SCROLL")}, {K: note})
    assert a[K] == note and r[K]["outcome"] == "updated"


def test_auto_dropped_when_no_rule_produces_it():
    a, r = m({K: auto("1", "SCROLL")}, {})
    assert K not in a and r[K]["outcome"] == "dropped"


def test_unchanged_auto_is_silent():
    a, r = m({K: auto("1", "SCROLL")}, {K: auto("1", "SCROLL")})
    assert a[K] == auto("1", "SCROLL") and K not in r


def test_same_answer_new_source_refreshes_silently():
    # e.g. "remove centrifugal" holds for SCROLL and for ROTARY SCREW alike
    a, r = m({K: auto("1", "SCROLL")}, {K: auto("1", "ROTARY SCREW")})
    assert a[K]["source"]["value"] == "ROTARY SCREW" and K not in r


# --- overrides survive; changed data makes a conflict --------------------------

def test_override_kept_when_data_unchanged():
    o = overridden("2", "1", "SCROLL")
    a, r = m({K: o}, {K: auto("1", "SCROLL")})
    assert a[K] == o and r[K]["outcome"] == "kept override"


def test_override_becomes_conflict_when_data_changes():
    a, r = m({K: overridden("2", "1", "SCROLL")}, {K: auto("3", "ROTARY SCREW")})
    assert a[K]["answer"] == "2" and a[K]["state"] == "conflict"
    assert a[K]["source"]["was"]["answer"] == "1"
    assert a[K]["source"]["now"] == {**src("ROTARY SCREW"), "answer": "3"}
    assert r[K]["outcome"] == "conflict"
    assert r[K]["detail"] == "engineer answer '2'; prefill now '3' from ACC-1.compressor_type = 'ROTARY SCREW'"


def test_conflict_returns_to_overridden_when_data_reverts():
    c, _ = m({K: overridden("2", "1", "SCROLL")}, {K: auto("3", "ROTARY SCREW")})
    a, r = m(c, {K: auto("1", "SCROLL")})
    assert a[K]["state"] == "overridden" and "now" not in a[K]["source"]
    assert r[K]["outcome"] == "resolved"


def test_conflict_updates_now_on_a_second_change():
    c, _ = m({K: overridden("2", "1", "SCROLL")}, {K: auto("3", "ROTARY SCREW")})
    a, _ = m(c, {K: auto("3", "SCREW")})
    assert a[K]["state"] == "conflict" and a[K]["source"]["now"]["value"] == "SCREW"


def test_data_catching_up_with_the_override_is_not_a_conflict():
    # engineer said Rotary Screw before the schedule did; now the schedule agrees
    a, r = m({K: overridden("3", "1", "SCROLL")}, {K: auto("3", "ROTARY SCREW")})
    assert a[K]["state"] == "overridden" and a[K]["answer"] == "3"
    assert a[K]["source"]["was"] == {**src("ROTARY SCREW"), "answer": "3"}
    assert r[K]["outcome"] == "agrees"


def test_override_kept_when_prefill_goes_silent():
    o = overridden("2", "1", "SCROLL")
    a, _ = m({K: o}, {})
    assert a[K] == o


# --- a duplicate's first instance (same_as) follows its decision ---------------

F = "PART 1/SUBMITTALS#choice:abc"


def mirror(answer, value, **extra):
    return {**auto(answer, value), "id": "BRK-0002", "same_as": "BRK-0023",
            "notes": "prefill (compressor-type): same decision as BRK-0023", **extra}


def test_mirror_is_replaced_quietly_and_reports_one_conflict():
    # the page copied the override onto the mirror; the data then changed
    over = overridden("2", "1", "SCROLL")
    existing = {K: over, F: {**mirror("2", "SCROLL"), "source": over["source"], "state": "overridden"}}
    a, r = m(existing, {K: auto("3", "ROTARY SCREW"), F: mirror("3", "ROTARY SCREW")})
    assert a[F] == mirror("3", "ROTARY SCREW")      # generate makes it follow K
    assert list(r) == [K] and r[K]["outcome"] == "conflict"


def test_mirror_taken_over_by_the_engineer_merges_as_theirs():
    mine = {**overridden("2", "1", "SCROLL"), "id": "BRK-0002"}   # same_as dropped
    a, r = m({F: mine}, {F: mirror("1", "SCROLL")})
    assert a[F]["answer"] == "2" and "same_as" not in a[F] and r[F]["outcome"] == "kept override"


# --- manual answers (D3) ---------------------------------------------------------

def test_manual_answer_equal_to_new_value_is_kept():
    man = {"answer": "1", "notes": "chosen at kickoff", "id": "BRK-0023", "source": {"kind": "manual"}}
    a, r = m({K: man}, {K: auto("1", "SCROLL")})
    assert a[K] == man and r[K]["outcome"] == "agrees"


def test_manual_answer_that_differs_is_a_conflict():
    man = {"answer": "2", "notes": "", "id": "BRK-0023"}   # no source: answered by hand
    a, r = m({K: man}, {K: auto("1", "SCROLL")})
    assert a[K]["state"] == "conflict" and a[K]["answer"] == "2"
    assert a[K]["source"] == {"kind": "manual", "now": {**src("SCROLL"), "answer": "1"}}


def test_manual_answers_and_text_edits_kept_when_prefill_is_silent():
    man = {"answer": "keep", "notes": "", "id": "BRK-0050"}
    edit = {"start": 10, "end": 14, "before": "text", "after": "word", "notes": ""}
    a, _ = m({K: man, "ME@10": edit}, {})
    assert a[K] == man and a["ME@10"] == edit


def test_engineer_note_survives_an_unanswered_record():
    a, _ = m({K: {"answer": "", "notes": "ask the owner", "id": "BRK-0023"}},
             {K: auto("1", "SCROLL")})
    assert a[K]["answer"] == "1" and a[K]["notes"] == "ask the owner"


# --- project settings (D5) ---------------------------------------------------------

def _meta(value, ref="project.agency"):
    return {"source": {"kind": "rule", "ref": ref, "value": value}, "state": "auto"}


def test_profile_follows_the_same_rules():
    old_meta = {"ARMY": {"source": {"kind": "manual", "was": {"kind": "rule", "ref": "project.agency",
                                                              "value": "AIR FORCE", "answer": "remove"}},
                         "state": "overridden"},
                "NAVY": _meta("AIR FORCE")}
    existing = payload({}, {"ARMY": "keep", "NAVY": "remove"}, old_meta, fp="old")
    fresh = payload({}, {"ARMY": "keep", "NAVY": "keep"}, {"ARMY": _meta("ARMY"), "NAVY": _meta("ARMY")})
    merged, report = merge(existing, fresh)
    # NAVY was auto: follows the data
    assert merged["profile"]["NAVY"] == "keep" and merged["profile_meta"]["NAVY"]["state"] == "auto"
    # ARMY: engineer kept it under AIR FORCE; now agency ARMY also keeps it -> agrees
    assert merged["profile"]["ARMY"] == "keep"
    assert merged["profile_meta"]["ARMY"]["state"] == "overridden"
    assert {r["key"]: r["outcome"] for r in report} == {"profile:NAVY": "updated", "profile:ARMY": "agrees"}


def test_profile_conflict_leaves_the_setting_unanswered():
    old_meta = {"ARMY": {"source": {"kind": "manual", "was": {"kind": "rule", "ref": "project.agency",
                                                              "value": "AIR FORCE", "answer": "remove"}},
                         "state": "overridden"}}
    existing = payload({}, {"ARMY": "keep"}, old_meta, fp="old")
    fresh = payload({}, {"ARMY": "remove"}, {"ARMY": _meta("NAVY")})
    merged, report = merge(existing, fresh)
    assert "ARMY" not in merged["profile"]                     # neither applied
    meta = merged["profile_meta"]["ARMY"]
    assert meta["state"] == "conflict" and meta["answer"] == "keep"
    assert meta["source"]["now"] == {"kind": "rule", "ref": "project.agency", "value": "NAVY",
                                     "answer": "remove"}


def test_settings_set_by_hand_count_as_manual():
    existing = payload({}, {"SOME OPTION": "remove"}, {}, fp="old")
    merged, _ = merge(existing, payload({}, {}, {}))
    assert merged["profile"] == {"SOME OPTION": "remove"}


# --- the payload -------------------------------------------------------------------

def test_fresh_metadata_wins_and_output_is_deterministic():
    existing = payload({K: overridden("2", "1", "SCROLL")}, fp="old")
    fresh = payload({K: auto("3", "ROTARY SCREW")})
    a = merge(copy.deepcopy(existing), copy.deepcopy(fresh))
    b = merge(copy.deepcopy(existing), copy.deepcopy(fresh))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a[0]["fingerprint"] == "fresh"
    assert a[0]["prefill"]["merge"] == a[1]
