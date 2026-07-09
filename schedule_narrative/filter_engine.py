"""
Filter engine -- pure, deterministic functions that turn a filter
specification into a filtered activity list. No LLM involved anywhere
in this module. Every date window is computed relative to the
schedule's data date, never the system clock.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

from xer_parser import parse_p6_datetime
from activity_extractor import Activity


def _reference_date(a: Activity, which: str) -> Optional[datetime]:
    """which is 'start' or 'finish' -- prefers the actual date (if the
    activity has started/finished) over the planned one, since that's the
    real date the relationship played out against."""
    raw = (a.actual_start or a.planned_start) if which == "start" else (a.actual_finish or a.planned_finish)
    return parse_p6_datetime(raw) if raw else None


def _driving_predecessor_ids(a: Activity, by_id: dict[str, Activity]) -> list[tuple[str, str]]:
    """Of a's real predecessor links, keep only the one(s) that actually
    constrain a's own date -- approximated by matching each predecessor's
    implied constraint date against a's own start/finish, since this
    pipeline doesn't model lag or run a full CPM forward pass. A Finish to
    Start or Start to Start link constrains a's start; Finish to Finish or
    Start to Finish constrains a's finish. Ties within a day both count as
    driving (e.g. two predecessors converging the same day)."""
    my_start = _reference_date(a, "start")
    my_finish = _reference_date(a, "finish")

    candidates = []
    for link in a.predecessors:
        pred = by_id.get(link["activity_id"])
        if pred is None:
            continue
        rel_type = link["type"]
        if rel_type in ("Finish to Start", "Start to Start"):
            target = my_start
            ref = _reference_date(pred, "finish" if rel_type == "Finish to Start" else "start")
        else:  # Finish to Finish, Start to Finish
            target = my_finish
            ref = _reference_date(pred, "finish" if rel_type == "Finish to Finish" else "start")
        if ref is None or target is None:
            continue
        candidates.append((abs((target - ref).days), link["activity_id"], rel_type))

    if not candidates:
        return []
    best_gap = min(c[0] for c in candidates)
    return [(activity_id, rel_type) for gap, activity_id, rel_type in candidates if gap <= best_gap + 1]


def _remaining_critical_path(scoped_activities: list[Activity]) -> list[dict]:
    """All not-yet-completed critical activities/milestones across the
    *entire* remaining schedule -- not windowed to a report period -- in
    chronological order: the actual chain of critical work still standing
    between now and project completion. Used by the critical_path_narrative
    bolt-on section, which must always cover this in full regardless of the
    report's own lookback/lookahead window (weekly) or reporting period
    (monthly).

    predecessors/successors here are real P6 logic links (TASKPRED/
    Relationship, see activity_extractor.py) -- never inferred from names
    or date adjacency -- narrowed to only the driving tie(s) via
    _driving_predecessor_ids, not every logic link that happens to exist
    between two critical activities. An activity with no driving link
    simply has empty lists; that's a fact about this schedule's logic, not
    a gap to paper over."""
    remaining = [a for a in scoped_activities if a.is_critical and a.status != "completed"]
    remaining.sort(key=lambda a: parse_p6_datetime(a.planned_start) or datetime.max)
    by_id = {a.activity_id: a for a in remaining}

    driving_preds = {a.activity_id: _driving_predecessor_ids(a, by_id) for a in remaining}
    driving_succs: dict[str, list[tuple[str, str]]] = {a.activity_id: [] for a in remaining}
    for succ_id, preds in driving_preds.items():
        for pred_id, rel_type in preds:
            driving_succs.setdefault(pred_id, []).append((succ_id, rel_type))

    def named(links: list[tuple[str, str]]) -> list[dict]:
        return [{"name": by_id[activity_id].name, "relationship_type": rel_type} for activity_id, rel_type in links]

    return [
        {
            "name": a.name,
            "wbs_path": a.wbs_path,
            "is_milestone": a.is_milestone,
            "status": a.status,
            "planned_start": a.planned_start,
            "planned_finish": a.planned_finish,
            "float_days": a.total_float_days,
            "predecessors": named(driving_preds.get(a.activity_id, [])),
            "successors": named(driving_succs.get(a.activity_id, [])),
        }
        for a in remaining
    ]


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

    # Independent of critical_only/milestones_only -- those are user-set
    # filters on the windowed completed/upcoming lists above, but the
    # remaining critical path chain always reflects the true, whole-schedule
    # critical path regardless of what the user chose to filter this report to.
    scoped_for_chain = [
        a for a in activities
        if not spec.wbs_node_names or _matches_wbs_scope(a.wbs_path, spec.wbs_node_names)
    ]

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
        "remaining_critical_path": _remaining_critical_path(scoped_for_chain),
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

    completed_this_period / starting_this_period are the date-windowed
    pieces here -- named activities/milestones finished or due to start in
    roughly the last/next month relative to data_date -- so the executive
    summary and critical_path_narrative have real names to cite instead of
    only aggregate counts (milestones/critical_path_summary cover overall
    status, not "what happened this period"). remaining_critical_path is
    explicitly NOT windowed -- see _remaining_critical_path."""
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
    period_end = data_date + timedelta(days=lookback_days)
    completed_this_period = []
    starting_this_period = []
    for a in scoped:
        if a.status == "completed" and a.actual_finish:
            af = parse_p6_datetime(a.actual_finish)
            if af and period_start <= af <= data_date:
                completed_this_period.append({
                    "name": a.name,
                    "is_milestone": a.is_milestone,
                    "is_critical": a.is_critical,
                    "actual_finish": a.actual_finish,
                })
        elif a.status in ("not_started", "in_progress") and a.planned_start:
            ps = parse_p6_datetime(a.planned_start)
            if ps and data_date <= ps <= period_end:
                starting_this_period.append({
                    "name": a.name,
                    "is_milestone": a.is_milestone,
                    "is_critical": a.is_critical,
                    "planned_start": a.planned_start,
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
        "period_end": period_end.strftime("%Y-%m-%d"),
        "completed_this_period": completed_this_period,
        "starting_this_period": starting_this_period,
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
        "remaining_critical_path": _remaining_critical_path(scoped),
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
