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


def _build_critical_graph(scoped_activities: list[Activity]):
    """All not-yet-completed critical activities across the *entire*
    remaining schedule -- not windowed to a report period -- plus the
    driving predecessor/successor graph between them. Shared by
    _top_critical_paths; not used directly outside this module.

    predecessors/successors here are real P6 logic links (TASKPRED/
    Relationship, see activity_extractor.py) -- never inferred from names
    or date adjacency -- narrowed to only the driving tie(s) via
    _driving_predecessor_ids, not every logic link that happens to exist
    between two critical activities."""
    remaining = [a for a in scoped_activities if a.is_critical and a.status != "completed"]
    remaining.sort(key=lambda a: parse_p6_datetime(a.planned_start) or datetime.max)
    by_id = {a.activity_id: a for a in remaining}

    driving_preds = {a.activity_id: _driving_predecessor_ids(a, by_id) for a in remaining}
    driving_succs: dict[str, list[tuple[str, str]]] = {a.activity_id: [] for a in remaining}
    for succ_id, preds in driving_preds.items():
        for pred_id, rel_type in preds:
            driving_succs.setdefault(pred_id, []).append((succ_id, rel_type))

    return remaining, by_id, driving_preds, driving_succs


def _worst_branch(
    candidates: list[tuple[str, str]],
    by_id: dict[str, Activity],
) -> str:
    def float_of(link: tuple[str, str]) -> float:
        f = by_id[link[0]].total_float_days
        return f if f is not None else 0

    return min(candidates, key=float_of)[0]


def _full_chain_through(
    activity_id: str,
    by_id: dict[str, Activity],
    driving_preds: dict[str, list[tuple[str, str]]],
    driving_succs: dict[str, list[tuple[str, str]]],
) -> list[str]:
    """Trace the one full chain (true source to true sink) that passes
    through activity_id, picking the more negative-float branch at any
    fork or merge along the way. Walking backward AND forward from every
    activity (not just from a shared endpoint) is what actually recovers
    distinct parallel paths: when several branches converge into the same
    downstream activity or milestone, tracing backward from that shared
    point alone would only ever find the single worst branch and silently
    drop the others. Tracing from every activity and de-duplicating by
    the resulting activity set (done by the caller) recovers each
    genuinely distinct branch instead."""
    backward = []
    seen_back = {activity_id}
    current = activity_id
    while True:
        preds = [p for p in driving_preds.get(current, []) if p[0] not in seen_back]
        if not preds:
            break
        current = _worst_branch(preds, by_id)
        backward.append(current)
        seen_back.add(current)
    backward.reverse()

    forward = []
    seen_fwd = {activity_id}
    current = activity_id
    while True:
        succs = [s for s in driving_succs.get(current, []) if s[0] not in seen_fwd]
        if not succs:
            break
        current = _worst_branch(succs, by_id)
        forward.append(current)
        seen_fwd.add(current)

    return backward + [activity_id] + forward


def _top_critical_paths(scoped_activities: list[Activity], max_paths: int = 3) -> list[dict]:
    """When a schedule is badly behind, many activities can be critical at
    once -- not one critical path but several parallel ones (e.g.
    structural, MEP, and envelope work each independently behind,
    possibly converging on the same final milestone). Traces the full
    chain through every critical activity, de-duplicates identical
    chains, and ranks the distinct ones by their worst (most negative)
    float -- since that's what actually makes one chain more critical
    than another. Returns up to max_paths chains, most negative first --
    "primary" is the worst, down to "tertiary." A schedule with fewer
    than max_paths distinct chains just returns however many exist; none
    are invented to fill out three."""
    remaining, by_id, driving_preds, driving_succs = _build_critical_graph(scoped_activities)
    if not remaining:
        return []

    def worst_float(chain: list[str]) -> float:
        floats = [by_id[aid].total_float_days for aid in chain if by_id[aid].total_float_days is not None]
        return min(floats) if floats else 0

    unique_chains: dict[frozenset, list[str]] = {}
    for a in remaining:
        chain = _full_chain_through(a.activity_id, by_id, driving_preds, driving_succs)
        key = frozenset(chain)
        if key not in unique_chains:
            unique_chains[key] = chain

    chains = sorted(unique_chains.values(), key=worst_float)

    def named(links: list[tuple[str, str]]) -> list[dict]:
        return [{"name": by_id[activity_id].name, "relationship_type": rel_type} for activity_id, rel_type in links]

    def activity_dict(activity_id: str) -> dict:
        a = by_id[activity_id]
        return {
            "name": a.name,
            "wbs_path": a.wbs_path,
            "is_milestone": a.is_milestone,
            "status": a.status,
            "planned_start": a.planned_start,
            "planned_finish": a.planned_finish,
            "float_days": a.total_float_days,
            "predecessors": named(driving_preds.get(activity_id, [])),
            "successors": named(driving_succs.get(activity_id, [])),
        }

    ranks = ["primary", "secondary", "tertiary"]
    return [
        {
            "rank": ranks[i],
            "worst_float_days": worst_float(chain),
            "activities": [activity_dict(aid) for aid in chain],
        }
        for i, chain in enumerate(chains[:max_paths])
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
        "critical_paths": _top_critical_paths(scoped_for_chain),
    }


def build_monthly_executive_payload(
    activities: list[Activity],
    data_date,
    wbs_node_names: Optional[list[str]] = None,
    lookback_days: int = 30,
    lookahead_days: int = 30,
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
    status, not "what happened this period"). critical_paths is explicitly
    NOT windowed -- see _top_critical_paths."""
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
    period_end = data_date + timedelta(days=lookahead_days)
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
        "critical_paths": _top_critical_paths(scoped),
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
