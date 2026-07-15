"""CLI: python -m specgen <command> <file.SEC> [options]

Commands:
  roundtrip  Parse and re-serialize, verifying byte-identical output.
  manifest   Emit the decision manifest as JSON.
  report     Emit a human-readable markdown summary of the manifest.
  validate   Check well-formedness, and XSD-validate if lxml + schema exist.
  answers    Emit the engineer-facing answer workbook (.xlsx).
  generate   Apply a filled answer workbook -> tailored .sec + redline +
             unresolved report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import secfile
from .manifest import build_manifest

SCHEMA_DEFAULT = Path(__file__).resolve().parent.parent / "schema" / "specsintactSEC.xsd"


def cmd_roundtrip(args) -> int:
    sec = secfile.parse(args.file)
    out = sec.serialize()
    if out == sec.source:
        print(f"OK: {args.file} round-trips byte-identically "
              f"({len(sec.source.encode(secfile.ENCODING))} bytes)")
        return 0
    # locate first divergence for debugging
    for i, (a, b) in enumerate(zip(sec.source, out)):
        if a != b:
            print(f"FAIL: first divergence at char {i}:")
            print(f"  source: ...{sec.source[max(0,i-60):i+60]!r}...")
            print(f"  output: ...{out[max(0,i-60):i+60]!r}...")
            return 1
    print(f"FAIL: length mismatch (source {len(sec.source)}, output {len(out)})")
    return 1


def cmd_manifest(args) -> int:
    sec = secfile.parse(args.file)
    data = build_manifest(sec)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out} ({data['counts']['bracket_groups_total']} bracket groups)")
    else:
        print(text)
    return 0


def cmd_report(args) -> int:
    sec = secfile.parse(args.file)
    m = build_manifest(sec)
    c = m["counts"]
    lines = [
        f"# {m['section']} — {m['title']}",
        "",
        f"Revision: {m['revision'] or m['date_code']} · UMRL: {m['umrl_date'] or 'n/a'}",
        "",
        "## Decision workload",
        "",
        f"- Bracket groups: **{c['bracket_groups_total']}** "
        f"({c['bracket_groups_in_body']} in spec body, "
        f"{c['bracket_groups_in_notes']} inside notes to the specifier)",
        f"- Choices: {c['kind_choice']} · Blanks to fill: {c['kind_blank']} · "
        f"Optional phrases: {c['kind_optional']}",
        f"- Tailoring blocks: {c['tailoring_blocks']} across "
        f"{len(m['tailoring_options'])} options",
        f"- Notes to the specifier: {c['notes_to_specifier']}",
        f"- Submittal items: {c['submittal_items']} · References declared: "
        f"{c['references_declared']}",
        "",
        "## Tailoring options",
        "",
    ]
    for opt, v in m["tailoring_options"].items():
        lines.append(f"- `{opt}`: {v['blocks']} blocks, {v['chars']:,} chars governed")
    lines += ["", "## Submittals", ""]
    for s in m["submittals"]:
        flag = " *(bracketed)*" if s["has_brackets"] else ""
        lines.append(f"- [{s['sd_group']}] {s['name']}{flag}")
    ru, rd = c["references_used_but_undeclared"], c["references_declared_but_unused"]
    if ru or rd:
        lines += ["", "## Reference anomalies", ""]
        if ru:
            lines.append(f"- Used in body but not in Reference Article: {', '.join(ru)}")
        if rd:
            lines.append(f"- Declared but never used in body: {', '.join(rd)}")
    lines += ["", "## Decisions in spec body", ""]
    for d in m["decisions"]:
        if d["in_note"]:
            continue
        opts = " | ".join(d["options"]) if d["kind"] != "blank" else "(fill in)"
        lines.append(f"### {d['id']} · {d['kind']} · {d['location']}")
        lines.append("")
        lines.append(f"- Options: {opts}")
        lines.append(f"- Context: …{d['context']}…")
        lines.append("")
    text = "\n".join(lines)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_validate(args) -> int:
    import xml.etree.ElementTree as ET

    try:
        ET.parse(args.file)
        print(f"OK: {args.file} is well-formed XML")
    except ET.ParseError as e:
        print(f"FAIL: not well-formed: {e}")
        return 1
    schema_path = Path(args.schema) if args.schema else SCHEMA_DEFAULT
    if not schema_path.exists():
        print(f"NOTE: schema not found at {schema_path}; skipped XSD validation")
        return 0
    try:
        from lxml import etree
    except ImportError:
        print("NOTE: lxml not installed; skipped XSD validation (pip install lxml)")
        return 0
    schema = etree.XMLSchema(etree.parse(str(schema_path)))
    doc = etree.parse(args.file)
    if schema.validate(doc):
        print(f"OK: valid against {schema_path.name}")
        return 0
    print("FAIL: XSD validation errors:")
    for err in schema.error_log:
        print(f"  line {err.line}: {err.message}")
    return 1


def cmd_answers(args) -> int:
    from .answers import write_workbook

    sec = secfile.parse(args.file)
    m = build_manifest(sec)
    out = args.out or (Path(args.file).stem + ".answers.xlsx")
    write_workbook(m, out)
    ds = [d for d in m["decisions"] if not d["in_note"] and not d.get("plural")]
    uniq = len([d for d in ds if not d.get("duplicate_of")])
    print(
        f"Wrote {out} ({len(ds)} rows, {uniq} unique decisions, "
        f"{len(m['tailoring_options'])} tailoring options)"
    )
    return 0


def cmd_generate(args) -> int:
    from .answers import read_answers
    from .audit import audit_file
    from .generate import generate

    report = audit_file(args.file)
    if report["unknowns"]:
        for u in report["unknowns"]:
            print(f"UNKNOWN {u['type']} @ {u['offset']}: {u['context']}")
        if not args.force:
            print("Refusing: section has unattributed decision signals "
                  "(rerun with --force to proceed anyway)")
            return 1
        print("WARNING: proceeding despite unattributed signals (--force)")

    profile, ans = read_answers(args.answers)
    summary = generate(args.file, profile, ans, args.out, revisions=args.revisions)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_audit(args) -> int:
    from .audit import audit_file

    report = audit_file(args.file)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for sig, buckets in sorted(report["signals"].items()):
            row = " · ".join(f"{b}={n}" for b, n in sorted(buckets.items()))
            print(f"{sig:32s} {row}")
        for u in report["unknowns"]:
            print(f"UNKNOWN {u['type']} @ {u['offset']}: {u['context']}")
    if report["unknowns"]:
        print(f"FAIL: {len(report['unknowns'])} unattributed signal(s)")
        return 1
    print("OK: every decision signal attributed")
    return 0


def cmd_html(args) -> int:
    from .audit import audit_file
    from .htmlpage import write_html

    report = audit_file(args.file)
    if report["unknowns"]:
        for u in report["unknowns"]:
            print(f"UNKNOWN {u['type']} @ {u['offset']}: {u['context']}")
        if not args.force:
            print("Refusing: section has unattributed decision signals "
                  "(rerun with --force to proceed anyway)")
            return 1
        print("WARNING: proceeding despite unattributed signals (--force)")

    sec = secfile.parse(args.file)
    m = build_manifest(sec)
    out = args.out or (Path(args.file).stem + ".decisions.html")
    write_html(m, out)
    uniq = len(
        [d for d in m["decisions"]
         if not d["in_note"] and not d.get("plural") and not d.get("duplicate_of")]
    )
    print(f"Wrote {out} ({uniq} unique decisions)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="specgen", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn in [
        ("roundtrip", cmd_roundtrip),
        ("manifest", cmd_manifest),
        ("report", cmd_report),
        ("validate", cmd_validate),
        ("answers", cmd_answers),
        ("generate", cmd_generate),
        ("html", cmd_html),
        ("audit", cmd_audit),
    ]:
        sp = sub.add_parser(name)
        sp.add_argument("file")
        if name in ("manifest", "report", "answers", "html"):
            sp.add_argument("-o", "--out")
        if name == "validate":
            sp.add_argument("--schema")
        if name == "generate":
            sp.add_argument("--answers", required=True)
            sp.add_argument("-o", "--out", required=True)
            sp.add_argument("--revisions", action="store_true")
        if name in ("html", "generate"):
            sp.add_argument("--force", action="store_true")
        if name == "audit":
            sp.add_argument("--json", action="store_true")
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
