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
    constrain a's own date.

    P6's own Driving flag (see activity_extractor.py's XML relationship
    parsing) is used when the export carries it -- it reflects whatever
    lag, calendars, and scheduling method P6 actually used, which this
    pipeline has no way to fully replicate. Only falls back to the
    date-gap heuristic below when Driving isn't present on any of a's
    predecessor links (true for XER always, and for XML exports that
    don't carry it).

    The heuristic approximates the driving link(s) by matching each
    predecessor's implied constraint date (offset by that link's lag,
    when given) against a's own start/finish -- still not a full CPM
    forward pass, but lag-aware where the data allows it. A Finish to
    Start or Start to Start link constrains a's start; Finish to Finish
    or Start to Finish constrains a's finish. Ties within a day both
    count as driving (e.g. two predecessors converging the same day)."""
    if any(link.get("driving") is not None for link in a.predecessors):
        return [
            (link["activity_id"], link["type"])
            for link in a.predecessors
            if link.get("driving") is True
        ]

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
        lag_days = link.get("lag_days")
        if lag_days:
            ref = ref + timedelta(days=lag_days)
        candidates.append((abs((target - ref).days), link["activity_id"], rel_type))

    if not candidates:
        return []
    best_gap = min(c[0] for c in candidates)
    return [(activity_id, rel_type) for gap, activity_id, rel_type in candidates if gap <= best_gap + 1]


def _build_activity_graph(remaining: list[Activity]):
    """Given an already-filtered, chronologically-sorted activity list,
    builds the driving predecessor/successor graph among them. Shared by
    _top_critical_paths and _nearest_near_critical_path.

    predecessors/successors here are real P6 logic links (TASKPRED/
    Relationship, see activity_extractor.py) -- never inferred from names
    or date adjacency -- narrowed to only the driving tie(s) via
    _driving_predecessor_ids, not every logic link that happens to exist
    between two activities in the set."""
    by_id = {a.activity_id: a for a in remaining}

    driving_preds = {a.activity_id: _driving_predecessor_ids(a, by_id) for a in remaining}
    driving_succs: dict[str, list[tuple[str, str]]] = {a.activity_id: [] for a in remaining}
    for succ_id, preds in driving_preds.items():
        for pred_id, rel_type in preds:
            driving_succs.setdefault(pred_id, []).append((succ_id, rel_type))

    return by_id, driving_preds, driving_succs


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


def _top_distinct_paths(remaining: list[Activity], max_paths: int, rank_labels: list[str]) -> list[dict]:
    """Shared engine behind _top_critical_paths and
    _nearest_near_critical_path: traces the full chain through every
    activity in `remaining` (already filtered to whatever criticality
    condition and chronologically sorted), de-duplicates identical
    resulting chains, ranks the distinct ones by their worst (lowest)
    float, and returns up to max_paths of them labeled by rank_labels.
    No cap on how many activities `remaining` itself may contain --
    de-duplication and the max_paths slice are what keep the *output*
    bounded, not a count check on the input."""
    if not remaining:
        return []
    by_id, driving_preds, driving_succs = _build_activity_graph(remaining)

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

    return [
        {
            "rank": rank_labels[i],
            "worst_float_days": worst_float(chain),
            "activities": [activity_dict(aid) for aid in chain],
        }
        for i, chain in enumerate(chains[:max_paths])
    ]


def _top_critical_paths(scoped_activities: list[Activity], max_paths: int = 3) -> list[dict]:
    """When a schedule is badly behind, many activities can be critical at
    once -- not one critical path but several parallel ones (e.g.
    structural, MEP, and envelope work each independently behind,
    possibly converging on the same final milestone). Ranked by worst
    (most negative) float -- "primary" is the worst, down to "tertiary."
    A schedule with fewer than max_paths distinct chains just returns
    however many exist; none are invented to fill out three."""
    remaining = [a for a in scoped_activities if a.is_critical and a.status != "completed"]
    remaining.sort(key=lambda a: parse_p6_datetime(a.planned_start) or datetime.max)
    return _top_distinct_paths(remaining, max_paths, ["primary", "secondary", "tertiary"])


def _nearest_near_critical_path(scoped_activities: list[Activity]) -> list[dict]:
    """The single chain of near-critical activities (positive float, not
    yet critical, 0 < float <= 10 days, not milestones) closest to
    becoming critical -- i.e. with the lowest float. Same chain-tracing
    approach as _top_critical_paths, narrowed to just the one nearest
    chain rather than three, since "near-critical" isn't already a
    narrow category the way "critical" (float <= 0) is -- a badly behind
    schedule can have hundreds of activities sitting at a few days of
    float, and a flat list of all of them isn't a short discussion."""
    remaining = [
        a for a in scoped_activities
        if not a.is_milestone and not a.is_critical
        and a.total_float_days is not None and 0 < a.total_float_days <= 10
        and a.status != "completed"
    ]
    remaining.sort(key=lambda a: parse_p6_datetime(a.planned_start) or datetime.max)
    return _top_distinct_paths(remaining, max_paths=1, rank_labels=["nearest"])


@dataclass
class FilterSpec:
    report_type: str  # "weekly_oac" | "monthly_executive"
    lookback_days: int = 7
    lookahead_days: int = 7
    wbs_node_names: Optional[list[str]] = None  # match if ANY of these appear as a full path segment, any depth
    critical_only: bool = False
    milestones_only: bool = False
    include_variance: bool = True


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
        # from the data, not the stored flag.
        if spec.critical_only and not (a.total_float_days is not None and a.total_float_days <= 0):
            continue
        if spec.milestones_only and not a.is_milestone:
            continue
        elif not spec.milestones_only:
            # Not an explicit "milestones only" request (which means show
            # every milestone in the window, not just the important-looking
            # ones) -- default to "important" activities only: critical, or
            # comfortably close to it (float < 25 days), so an unscoped
            # report on a huge schedule doesn't try to narrate every single
            # activity in the window. An activity with no float value at all
            # (e.g. missing data) still passes here; only a real float >= 25
            # excludes it. No user-facing float threshold is exposed here --
            # this pipeline can't guarantee derived float values match P6
            # exactly (see activity_extractor.py), so float only ever drives
            # this internal narrowing, never a number a user sets or sees.
            if not a.is_critical and not (a.total_float_days is not None and a.total_float_days < 25):
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
        },
        "completed_activities": [serialize(a) for a in completed],
        "upcoming_activities": [serialize(a) for a in upcoming],
        "critical_paths": _top_critical_paths(scoped_for_chain),
        "nearest_near_critical_path": _nearest_near_critical_path(scoped_for_chain),
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

    def is_important(a: Activity) -> bool:
        # Milestones are always worth citing regardless of float. Otherwise,
        # default to "important" only -- critical, or comfortably close to
        # it (float < 25 days) -- so an unscoped report on a huge schedule
        # doesn't try to cite every single activity in the period. No
        # user-facing float threshold is exposed here -- this pipeline can't
        # guarantee derived float values match P6 exactly (see
        # activity_extractor.py), so float only ever drives this internal
        # narrowing, never a number a user sets or sees.
        if a.is_milestone:
            return True
        return a.is_critical or (a.total_float_days is not None and a.total_float_days < 25)

    period_start = data_date - timedelta(days=lookback_days)
    period_end = data_date + timedelta(days=lookahead_days)
    completed_this_period = []
    starting_this_period = []
    for a in scoped:
        if not is_important(a):
            continue
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
        "critical_paths": _top_critical_paths(scoped),
        "nearest_near_critical_path": _nearest_near_critical_path(scoped),
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

    # No WBS scope -- shows the raw "riding the data date" mess
    print("=== Unscoped (the mess) ===")
    spec_raw = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7)
    result_raw = apply_filters(activities, data_date, spec_raw)
    print(f"Completed: {len(result_raw['completed_activities'])} | Upcoming: {len(result_raw['upcoming_activities'])}")
    print()

    # WBS-scoped to one area
    print("=== WBS scoped to 'B1 -- Core E' ===")
    spec_wbs = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7, wbs_node_names=["B1 -- Core E"])
    result_wbs = apply_filters(activities, data_date, spec_wbs)
    print(f"Completed: {len(result_wbs['completed_activities'])} | Upcoming: {len(result_wbs['upcoming_activities'])}")
