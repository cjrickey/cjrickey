"""XER parsing + activity extraction: the stable-field path (total_float_hr_cnt),
LOE exclusion, criticality, milestones, statuses, and real TASKPRED relationships."""
from xer_parser import parse_xer
from activity_extractor import (
    extract_activities,
    pick_primary_proj_id,
    get_data_date,
)


def _by_id(activities):
    return {a.activity_id: a for a in activities}


def test_data_date_and_project(xer_path):
    xer = parse_xer(xer_path)
    proj_id = pick_primary_proj_id(xer)
    assert proj_id == "100"
    data_date = get_data_date(xer, proj_id)
    assert data_date is not None
    assert data_date.strftime("%Y-%m-%d") == "2026-07-10"


def test_loe_activities_are_excluded(xer_path):
    xer = parse_xer(xer_path)
    activities = extract_activities(xer)
    ids = {a.activity_id for a in activities}
    assert "LOE1" not in ids, "Level of Effort activity must never be extracted"


def test_expected_activities_extracted(xer_path):
    xer = parse_xer(xer_path)
    activities = extract_activities(xer)
    ids = {a.activity_id for a in activities}
    # 9 rows minus the one LOE row = 8
    assert len(activities) == 8
    assert {"A1000", "A1010", "A1020", "M1000", "A0990", "A1040", "A2010", "A2020"} == ids


def test_float_and_criticality_from_xer(xer_path):
    xer = parse_xer(xer_path)
    by_id = _by_id(extract_activities(xer))
    # total_float_hr_cnt / 8, rounded to whole days
    assert by_id["A1010"].total_float_days == -5
    assert by_id["A1010"].is_critical is True
    assert by_id["A1040"].total_float_days == 10
    assert by_id["A1040"].is_critical is False
    # -320 hr / 8 = -40 days
    assert by_id["M1000"].total_float_days == -40


def test_statuses_and_milestone(xer_path):
    xer = parse_xer(xer_path)
    by_id = _by_id(extract_activities(xer))
    assert by_id["A1000"].status == "completed"
    assert by_id["A1010"].status == "in_progress"
    assert by_id["A1020"].status == "not_started"
    assert by_id["M1000"].is_milestone is True
    assert by_id["A1010"].is_milestone is False


def test_completed_activity_uses_target_dates(xer_path):
    xer = parse_xer(xer_path)
    by_id = _by_id(extract_activities(xer))
    # completed -> planned dates come from target_*, and actual_finish is set
    assert by_id["A1000"].actual_finish == "2026-07-08 00:00"
    assert by_id["A1000"].planned_finish == "2026-06-15 00:00"


def test_xer_relationships_parsed(xer_path):
    xer = parse_xer(xer_path)
    by_id = _by_id(extract_activities(xer))
    # A1020 <- A1010 (Finish to Start), keyed by activity code
    pred_ids = {p["activity_id"] for p in by_id["A1020"].predecessors}
    assert "A1010" in pred_ids
    a1010_to_a1020 = [p for p in by_id["A1020"].predecessors if p["activity_id"] == "A1010"][0]
    assert a1010_to_a1020["type"] == "Finish to Start"
    # XER carries no Driving flag
    assert a1010_to_a1020["driving"] is None
    # successor direction is populated too
    succ_ids = {s["activity_id"] for s in by_id["A1010"].successors}
    assert "A1020" in succ_ids


def test_xer_never_produces_variance(xer_path):
    # XER can't carry a P6 Baseline, so variance must always be None
    xer = parse_xer(xer_path)
    for a in extract_activities(xer):
        assert a.variance_days is None
        assert a.target_finish is None
