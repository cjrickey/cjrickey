"""
Filter engine -- pure, deterministic functions that turn a filter
specification into a filtered activity list. No LLM involved anywhere
in this module. Every date window is computed relative to the
schedule's data date, never the system clock.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import timedelta
from typing import Optional

from xer_parser import parse_p6_datetime
from activity_extractor import Activity


@dataclass
class FilterSpec:
    report_type: str  # "weekly_oac" | "monthly_executive"
    lookback_days: int = 7
    lookahead_days: int = 7
    wbs_node_names: Optional[list[str]] = None  # match if ANY of these appear as a full path segment, any depth
    critical_only: bool = False
    milestones_only: bool = False
    include_variance: bool = True
    max_float_days: Optional[float] = None  # explicit user-set filter, off by default. Activities with no
    # float value (e.g. completed activities) are never excluded by this -- it only applies where float exists.


def _matches_wbs_scope(wbs_path: str, node_names: list[str]) -> bool:
    # A selected node includes itself and everything beneath it in the
    # tree -- matching the cascading-checkbox UI behavior. Since wbs_path
    # is an ordered "Root > Branch > Leaf" string, this means: does any
    # selected node name appear anywhere in this activity's path, at any
    # position (not just as the final segment).
    segments = wbs_path.split(" > ")
    return any(node in segments for node in node_names)


def apply_filters(
    activities: list[Activity],
    data_date,
    spec: FilterSpec,
) -> dict:
    lookback_start = data_date - timedelta(days=spec.lookback_days)
    lookahead_end = data_date + timedelta(days=spec.lookahead_days)

    completed = []
    upcoming = []

    for a in activities:
        if spec.wbs_node_names and not _matches_wbs_scope(a.wbs_path, spec.wbs_node_names):
            continue
        # NOTE: driving_path_flag from the XER can be stale (not recomputed
        # before export) or ambiguous under multiple-longest-path scheduling.
        # "Critical" is defined here as total_float_days <= 0, computed fresh
        # from the data, not the stored flag. critical_only is effectively a
        # shortcut for max_float_days=0, and the two compose: if both are
        # set, the tighter constraint wins naturally.
        if spec.critical_only and not (a.total_float_days is not None and a.total_float_days <= 0):
            continue
        if spec.milestones_only and not a.is_milestone:
            continue
        if (
            spec.max_float_days is not None
            and a.total_float_days is not None
            and a.total_float_days > spec.max_float_days
        ):
            continue

        if a.status == "completed" and a.actual_finish:
            af = parse_p6_datetime(a.actual_finish)
            if af and lookback_start <= af <= data_date:
                completed.append(a)

        elif a.status in ("not_started", "in_progress") and a.planned_start:
            ps = parse_p6_datetime(a.planned_start)
            if ps and data_date <= ps <= lookahead_end:
                upcoming.append(a)

    def serialize(a: Activity) -> dict:
        d = a.to_dict()
        if not spec.include_variance:
            d.pop("variance_days", None)
        return d

    return {
        "report_type": spec.report_type,
        "data_date": data_date.strftime("%Y-%m-%d"),
        "date_window": {
            "completed_start": lookback_start.strftime("%Y-%m-%d"),
            "completed_end": data_date.strftime("%Y-%m-%d"),
            "upcoming_start": data_date.strftime("%Y-%m-%d"),
            "upcoming_end": lookahead_end.strftime("%Y-%m-%d"),
        },
        "scope": {
            "wbs_node_names": spec.wbs_node_names,
            "critical_only": spec.critical_only,
            "milestones_only": spec.milestones_only,
            "max_float_days": spec.max_float_days,
        },
        "completed_activities": [serialize(a) for a in completed],
        "upcoming_activities": [serialize(a) for a in upcoming],
    }


def build_monthly_executive_payload(
    activities: list[Activity],
    data_date,
    wbs_node_names: Optional[list[str]] = None,
    lookback_days: int = 30,
) -> dict:
    """Monthly executive payload has a different shape than the weekly
    report: a flat list of milestones (with variance vs. target) plus a
    critical-path summary, rather than a date-windowed completed/upcoming
    split. No second schedule snapshot is used -- milestone variance is
    current forecast (or actual) vs. this file's own target dates.

    completed_this_period is the one date-windowed piece here -- named
    activities/milestones actually finished in roughly the last month
    relative to data_date -- so the executive summary has real names to
    cite instead of only aggregate counts (milestones/critical_path_summary
    cover overall status, not "what happened this period")."""
    scoped = [
        a for a in activities
        if not wbs_node_names or _matches_wbs_scope(a.wbs_path, wbs_node_names)
    ]

    milestones = [a for a in scoped if a.is_milestone]
    critical = [a for a in scoped if a.is_critical and not a.is_milestone]
    # Only populated for the optional bolt-on sections (near_critical_discussion,
    # critical_path_narrative, etc.) that ask about individual activities --
    # the core monthly narrative itself stays at the milestone/aggregate level
    # described above. Without this, those sections have no per-activity float
    # data to draw from at all for a monthly report and the model has nothing
    # truthful to say but "no such data is present."
    near_critical = [
        a for a in scoped
        if not a.is_milestone and not a.is_critical
        and a.total_float_days is not None and 0 < a.total_float_days <= 10
    ]

    period_start = data_date - timedelta(days=lookback_days)
    completed_this_period = []
    for a in scoped:
        if a.status == "completed" and a.actual_finish:
            af = parse_p6_datetime(a.actual_finish)
            if af and period_start <= af <= data_date:
                completed_this_period.append({
                    "name": a.name,
                    "is_milestone": a.is_milestone,
                    "actual_finish": a.actual_finish,
                })

    def milestone_dict(a: Activity) -> dict:
        return {
            "name": a.name,
            "status": a.status,
            "target_finish": a.target_finish,
            "current_finish": a.actual_finish or a.planned_finish,
            "variance_days": a.variance_days,
        }

    most_behind = min(
        (a for a in critical if a.total_float_days is not None),
        key=lambda a: a.total_float_days,
        default=None,
    )

    def activity_float_dict(a: Activity) -> dict:
        return {"name": a.name, "wbs_path": a.wbs_path, "float_days": a.total_float_days}

    return {
        "report_type": "monthly_executive",
        "data_date": data_date.strftime("%Y-%m-%d"),
        "period_start": period_start.strftime("%Y-%m-%d"),
        "completed_this_period": completed_this_period,
        "milestones": [milestone_dict(a) for a in milestones],
        "critical_path_summary": {
            "critical_activity_count": len(critical),
            "most_behind_activity": (
                {"name": most_behind.name, "float_days": most_behind.total_float_days}
                if most_behind else None
            ),
        },
        "critical_activities": [activity_float_dict(a) for a in critical],
        "near_critical_activities": [activity_float_dict(a) for a in near_critical],
    }


if __name__ == "__main__":
    import sys
    import json
    from xer_parser import parse_xer
    from activity_extractor import extract_activities, pick_primary_proj_id, get_data_date

    xer = parse_xer(sys.argv[1])
    proj_id = pick_primary_proj_id(xer)
    data_date = get_data_date(xer, proj_id)
    activities = extract_activities(xer, proj_id)

    # No WBS scope, no float filter -- shows the raw "riding the data date" mess
    print("=== Unscoped, no float filter (the mess) ===")
    spec_raw = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7)
    result_raw = apply_filters(activities, data_date, spec_raw)
    print(f"Completed: {len(result_raw['completed_activities'])} | Upcoming: {len(result_raw['upcoming_activities'])}")
    print()

    # Same scope, user sets max float = 10 days
    print("=== Unscoped, max_float_days=10 ===")
    spec_float = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7, max_float_days=10)
    result_float = apply_filters(activities, data_date, spec_float)
    print(f"Completed: {len(result_float['completed_activities'])} | Upcoming: {len(result_float['upcoming_activities'])}")
    print()

    # WBS-scoped to one area, no float filter
    print("=== WBS scoped to 'B1 -- Core E', no float filter ===")
    spec_wbs = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7, wbs_node_names=["B1 -- Core E"])
    result_wbs = apply_filters(activities, data_date, spec_wbs)
    print(f"Completed: {len(result_wbs['completed_activities'])} | Upcoming: {len(result_wbs['upcoming_activities'])}")
