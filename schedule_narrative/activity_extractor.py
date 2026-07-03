"""
Turns a parsed XerFile into a flat list of activity dicts, scoped to the
"primary" project in the file (the one matching the filename / the one
with the most tasks -- P6 exports often carry in external linked projects
for cross-project relationships, which must NOT be treated as part of
this project's schedule).
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from xer_parser import XerFile, parse_p6_datetime


def pick_primary_proj_id(xer: XerFile) -> str:
    """The primary project is the one with the most TASK rows.
    Linked/external projects brought in for cross-project relationships
    typically have far fewer (or zero) task rows relative to WBS nodes."""
    counts = Counter(row.get("proj_id") for row in xer.get("TASK"))
    if not counts:
        raise ValueError("No TASK rows found in file")
    return counts.most_common(1)[0][0]


def build_wbs_path_map(xer: XerFile, proj_id: str) -> dict[str, str]:
    """wbs_id -> full path string like 'B1 > Site Improvements > Utilities'"""
    nodes = {
        row["wbs_id"]: row
        for row in xer.get("PROJWBS")
        if row.get("proj_id") == proj_id
    }

    path_cache: dict[str, str] = {}

    def resolve(wbs_id: str, _seen: Optional[set] = None) -> str:
        if wbs_id in path_cache:
            return path_cache[wbs_id]
        if _seen is None:
            _seen = set()
        if wbs_id in _seen or wbs_id not in nodes:
            return ""
        _seen.add(wbs_id)
        node = nodes[wbs_id]
        name = node.get("wbs_name") or node.get("wbs_short_name") or ""
        parent_id = node.get("parent_wbs_id")
        if parent_id and parent_id in nodes:
            parent_path = resolve(parent_id, _seen)
            full = f"{parent_path} > {name}" if parent_path else name
        else:
            full = name
        path_cache[wbs_id] = full
        return full

    return {wbs_id: resolve(wbs_id) for wbs_id in nodes}


def get_data_date(xer: XerFile, proj_id: str):
    for row in xer.get("PROJECT"):
        if row.get("proj_id") == proj_id:
            return parse_p6_datetime(row.get("last_recalc_date"))
    return None


@dataclass
class Activity:
    activity_id: str
    name: str
    wbs_path: str
    status: str  # "completed" | "in_progress" | "not_started"
    is_critical: bool
    total_float_days: Optional[float]
    actual_start: Optional[str]
    actual_finish: Optional[str]
    planned_start: Optional[str]
    planned_finish: Optional[str]
    target_finish: Optional[str] = None  # always the baseline/target date, regardless of status
    variance_days: Optional[int] = None
    is_milestone: bool = False

    def to_dict(self) -> dict:
        return {
            "activity_id": self.activity_id,
            "name": self.name,
            "wbs_path": self.wbs_path,
            "status": self.status,
            "is_critical": self.is_critical,
            "is_milestone": self.is_milestone,
            "total_float_days": self.total_float_days,
            "actual_start": self.actual_start,
            "actual_finish": self.actual_finish,
            "planned_start": self.planned_start,
            "planned_finish": self.planned_finish,
            "target_finish": self.target_finish,
            "variance_days": self.variance_days,
        }


STATUS_MAP = {
    "TK_Complete": "completed",
    "TK_Active": "in_progress",
    "TK_NotStart": "not_started",
}


def extract_activities(xer: XerFile, proj_id: Optional[str] = None) -> list[Activity]:
    if proj_id is None:
        proj_id = pick_primary_proj_id(xer)

    wbs_paths = build_wbs_path_map(xer, proj_id)

    activities = []
    for row in xer.get("TASK"):
        if row.get("proj_id") != proj_id:
            continue

        status = STATUS_MAP.get(row.get("status_code"), row.get("status_code"))

        # NOTE: driving_path_flag can be stale (not recomputed before
        # export) or ambiguous under multiple-longest-path scheduling
        # settings. Cross-checked against a real file: 61 activities had
        # negative float but driving_path_flag=N, vs. only 12 correctly
        # flagged Y. Float-based is the trustworthy definition -- compute
        # it fresh rather than relying on the stored flag.
        total_float_hr = row.get("total_float_hr_cnt", "").strip()
        total_float_days = None
        if total_float_hr:
            try:
                total_float_days = round(float(total_float_hr) / 8, 1)  # 8hr workday
            except ValueError:
                pass

        is_critical = total_float_days is not None and total_float_days <= 0
        is_milestone = row.get("task_type") in ("TT_Mile", "TT_FinMile", "TT_StartMile")

        # IMPORTANT: once a task is 100% complete, P6 collapses its
        # early_start/early_end to the data date (an artifact of the
        # forward-pass recalculation, not a meaningful planned date).
        # For completed tasks we must use target_start/target_end instead
        # -- those hold the actual current-plan dates the task was
        # tracked against. For not-started/in-progress tasks, early_* is
        # the correct forward-looking forecast.
        if status == "completed":
            planned_start = row.get("target_start_date") or None
            planned_finish = row.get("target_end_date") or None
        else:
            planned_start = row.get("early_start_date") or row.get("target_start_date") or None
            planned_finish = row.get("early_end_date") or row.get("target_end_date") or None

        actual_finish = row.get("act_end_date") or None
        target_finish = row.get("target_end_date") or None

        variance_days = None
        if actual_finish and target_finish:
            # completed: actual vs. target
            af = parse_p6_datetime(actual_finish)
            tf = parse_p6_datetime(target_finish)
            if af and tf:
                variance_days = (af - tf).days
        elif planned_finish and target_finish and status != "completed":
            # not yet finished: current forecast (early dates) vs. target --
            # this is what lets a not-started milestone show slippage
            # without needing a second schedule snapshot to diff against.
            pf = parse_p6_datetime(planned_finish)
            tf = parse_p6_datetime(target_finish)
            if pf and tf:
                variance_days = (pf - tf).days

        activities.append(Activity(
            activity_id=row.get("task_code", ""),
            name=row.get("task_name", ""),
            wbs_path=wbs_paths.get(row.get("wbs_id", ""), ""),
            status=status,
            is_critical=is_critical,
            is_milestone=is_milestone,
            total_float_days=total_float_days,
            actual_start=row.get("act_start_date") or None,
            actual_finish=actual_finish,
            planned_start=planned_start,
            planned_finish=planned_finish,
            target_finish=target_finish,
            variance_days=variance_days,
        ))

    return activities


if __name__ == "__main__":
    import sys
    import json
    from xer_parser import parse_xer

    xer = parse_xer(sys.argv[1])
    proj_id = pick_primary_proj_id(xer)
    data_date = get_data_date(xer, proj_id)
    activities = extract_activities(xer, proj_id)

    print(f"Primary proj_id: {proj_id}")
    print(f"Data date: {data_date}")
    print(f"Activities extracted: {len(activities)}")
    print()
    print("Sample (first 3):")
    for a in activities[:3]:
        print(json.dumps(a.to_dict(), indent=2))
