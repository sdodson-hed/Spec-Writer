"""Project design data (spec 2026-10-13, section 4).

One JSON file per project, written by an engineer today and by the Hedral
platform later:

    {"schema": "specgen.design-data/1",
     "project": {"name": ..., "agency": "AIR FORCE", "units": "IP"},
     "sources": {"acc-sched-35": {"kind": "schedule", ...}},
     "equipment": [{"mark": "ACC-1", "schedule": "air_cooled_chiller",
                    "source": "acc-sched-35", ...schedule fields...}],
     "bod": {...basis-of-design fields not on a schedule...}}

Field names come from the schedules, lowercased with underscores. Loading
checks the structure and reports every problem at once; it never fills in
a missing value (a missing field is how prefill knows to leave a decision
unresolved).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "specgen.design-data/1"
_TOP_KEYS = {"schema", "project", "sources", "equipment", "bod"}


class DesignDataError(Exception):
    pass


@dataclass
class DesignData:
    project: dict
    sources: dict
    equipment: list[dict]
    bod: dict = field(default_factory=dict)
    path: Path | None = None

    def rows(self, schedule: str) -> list[dict]:
        """Equipment rows on one schedule, in file order."""
        return [r for r in self.equipment if r["schedule"] == schedule]

    def source(self, mark: str) -> dict:
        """The source document a row came from, with its id."""
        row = next(r for r in self.equipment if r["mark"] == mark)
        return {**self.sources[row["source"]], "id": row["source"]}


def from_dict(data: dict, path: Path | None = None) -> DesignData:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise DesignDataError("design data must be a JSON object")
    if data.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r} (got {data.get('schema')!r})")
    for k in sorted(set(data) - _TOP_KEYS):
        problems.append(f"unknown top-level key {k!r}")

    project = data.get("project")
    if not isinstance(project, dict):
        problems.append("project must be an object")
        project = {}
    if not project.get("agency"):
        problems.append("project.agency is required")
    if project.get("units") not in ("IP", "SI"):
        problems.append(f"project.units must be IP or SI (got {project.get('units')!r})")

    sources = data.get("sources", {})
    if not isinstance(sources, dict) or not all(isinstance(v, dict) for v in sources.values()):
        problems.append("sources must be an object of objects")
        sources = {}

    equipment = data.get("equipment", [])
    if not isinstance(equipment, list):
        problems.append("equipment must be a list")
        equipment = []
    seen: set[str] = set()
    for i, row in enumerate(equipment):
        if not isinstance(row, dict):
            problems.append(f"equipment[{i}] must be an object")
            continue
        label = f"equipment[{i}]" + (f" ({row['mark']})" if row.get("mark") else "")
        for k in ("mark", "schedule", "source"):
            if not row.get(k):
                problems.append(f"{label}: {k} is required")
        if row.get("source") and row["source"] not in sources:
            problems.append(f"{label}: source {row['source']!r} is not in sources")
        if row.get("mark"):
            if row["mark"] in seen:
                problems.append(f"duplicate mark {row['mark']!r}")
            seen.add(row["mark"])

    bod = data.get("bod", {})
    if not isinstance(bod, dict):
        problems.append("bod must be an object")
        bod = {}

    if problems:
        where = f"{path}: " if path else ""
        raise DesignDataError(where + "invalid design data:\n  - " + "\n  - ".join(problems))
    return DesignData(project=project, sources=sources, equipment=equipment, bod=bod, path=path)


def load_design_data(path: Path | str) -> DesignData:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DesignDataError(f"{path}: not valid JSON: {e}") from e
    return from_dict(data, path)
