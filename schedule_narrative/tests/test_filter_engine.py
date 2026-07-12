"""filter_engine: date windowing, the default 'important activities' narrowing,
critical_only, monthly payload, multi-path critical-path detection, the nearest
near-critical chain, and driving-relationship selection (explicit Driving flag
overriding the heuristic, and the heuristic being lag-aware)."""
from xer_parser import parse_xer
from activity_extractor import Activity, extract_activities
from filter_engine import (
    FilterSpec,
    apply_filters,
    build_monthly_executive_payload,
    _driving_predecessor_ids,
)


def _load(xer_path):
    xer = parse_xer(xer_path)
    return extract_activities(xer)


def _ids(rows):
    return {r["activity_id"] for r in rows}


# --------------------------------------------------------------------------
# apply_filters (weekly)
# --------------------------------------------------------------------------
def test_weekly_default_importance_filter(xer_path):
    activities = _load(xer_path)
    spec = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7)
    payload = apply_filters(activities, _data_date(), spec)
    # A1000 completed in window and critical -> in; A0990 completed in window
    # but 30-day float -> dropped by the default importance filter.
    assert _ids(payload["completed_activities"]) == {"A1000"}
    assert _ids(payload["upcoming_activities"]) == {"A1020", "A1040", "A2020"}


def test_weekly_critical_only(xer_path):
    activities = _load(xer_path)
    spec = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7, critical_only=True)
    payload = apply_filters(activities, _data_date(), spec)
    # A1040 (float 10, not critical) drops out under critical_only
    assert _ids(payload["upcoming_activities"]) == {"A1020", "A2020"}


def test_weekly_scope_dict_has_no_float_control(xer_path):
    # The user-facing max-float control was removed; the scope block must not
    # advertise one.
    activities = _load(xer_path)
    spec = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7)
    payload = apply_filters(activities, _data_date(), spec)
    assert "max_float_days" not in payload["scope"]


# --------------------------------------------------------------------------
# critical paths + near-critical (whole-scope, not windowed)
# --------------------------------------------------------------------------
def test_multiple_distinct_critical_paths(xer_path):
    activities = _load(xer_path)
    spec = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7)
    payload = apply_filters(activities, _data_date(), spec)
    paths = payload["critical_paths"]
    # Two genuinely distinct parallel critical chains must both be found.
    assert len(paths) == 2
    primary, secondary = paths[0], paths[1]
    assert primary["rank"] == "primary"
    assert secondary["rank"] == "secondary"
    # Ranked most-negative-worst-float first.
    assert primary["worst_float_days"] == -40
    assert secondary["worst_float_days"] == -3
    primary_names = {a["name"] for a in primary["activities"]}
    assert {"Pour footings", "Frame walls", "Foundation milestone"} <= primary_names
    secondary_names = {a["name"] for a in secondary["activities"]}
    assert {"Electrical rough-in", "Electrical trim"} == secondary_names


def test_nearest_near_critical_path(xer_path):
    activities = _load(xer_path)
    spec = FilterSpec(report_type="weekly_oac", lookback_days=7, lookahead_days=7)
    payload = apply_filters(activities, _data_date(), spec)
    near = payload["nearest_near_critical_path"]
    assert len(near) == 1
    assert near[0]["rank"] == "nearest"
    names = {a["name"] for a in near[0]["activities"]}
    assert "Order steel" in names  # float 10, not yet critical


# --------------------------------------------------------------------------
# monthly executive payload
# --------------------------------------------------------------------------
def test_monthly_payload_named_periods_and_importance(xer_path):
    activities = _load(xer_path)
    payload = build_monthly_executive_payload(activities, _data_date())
    completed_names = {a["name"] for a in payload["completed_this_period"]}
    assert "Excavate foundation" in completed_names
    assert "Landscaping prep" not in completed_names  # not important -> dropped
    starting_names = {a["name"] for a in payload["starting_this_period"]}
    assert {"Frame walls", "Order steel", "Electrical trim"} <= starting_names


def test_monthly_critical_path_summary(xer_path):
    activities = _load(xer_path)
    payload = build_monthly_executive_payload(activities, _data_date())
    summary = payload["critical_path_summary"]
    # critical, non-milestone: A1000, A1010, A1020, A2010, A2020
    assert summary["critical_activity_count"] == 5
    assert summary["most_behind_activity"]["name"] == "Pour footings"  # -5 days


def test_monthly_finds_critical_paths(xer_path):
    activities = _load(xer_path)
    payload = build_monthly_executive_payload(activities, _data_date())
    assert len(payload["critical_paths"]) == 2


# --------------------------------------------------------------------------
# driving-relationship selection (unit-level, synthetic)
# --------------------------------------------------------------------------
def _mk(aid, start, finish, preds=None):
    return Activity(
        activity_id=aid, name=aid, wbs_path="Root", status="not_started",
        is_critical=False, total_float_days=None, planned_start=start,
        planned_finish=finish, actual_start=None, actual_finish=None,
        target_finish=None, variance_days=None, predecessors=preds or [],
    )


def test_explicit_driving_flag_overrides_heuristic():
    a = _mk("A", "2026-07-15 08:00", "2026-07-20 08:00", preds=[
        # dates align (heuristic would call this driving) but P6 says NOT driving
        {"activity_id": "P1", "type": "Finish to Start", "lag_days": None, "driving": False},
        # dates don't align but P6 says driving
        {"activity_id": "P2", "type": "Finish to Start", "lag_days": None, "driving": True},
    ])
    by_id = {
        "P1": _mk("P1", "2026-07-01 08:00", "2026-07-15 08:00"),
        "P2": _mk("P2", "2026-07-01 08:00", "2026-07-10 08:00"),
    }
    assert _driving_predecessor_ids(a, by_id) == [("P2", "Finish to Start")]


def test_heuristic_is_lag_aware():
    # A starts 07-15; P1 finishes 07-10 with 5 days lag -> lands exactly on A's
    # start, so it's driving once lag is accounted for.
    a = _mk("A", "2026-07-15 08:00", "2026-07-20 08:00", preds=[
        {"activity_id": "P1", "type": "Finish to Start", "lag_days": 5, "driving": None},
    ])
    by_id = {"P1": _mk("P1", "2026-07-01 08:00", "2026-07-10 08:00")}
    assert _driving_predecessor_ids(a, by_id) == [("P1", "Finish to Start")]


def test_heuristic_backward_compatible_without_new_keys():
    # Links lacking lag_days/driving keys entirely must still work.
    a = _mk("A", "2026-07-10 08:00", "2026-07-15 08:00", preds=[
        {"activity_id": "P1", "type": "Finish to Start"},
    ])
    by_id = {"P1": _mk("P1", "2026-07-01 08:00", "2026-07-10 08:00")}
    assert _driving_predecessor_ids(a, by_id) == [("P1", "Finish to Start")]


# --------------------------------------------------------------------------
# shared
# --------------------------------------------------------------------------
def _data_date():
    from datetime import datetime
    return datetime(2026, 7, 10)
