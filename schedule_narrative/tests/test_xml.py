"""XML extraction across the schema variants that broke this pipeline before:
direct TotalFloat/IsCritical, Remaining*-only with calendar-aware float,
embedded baseline variance, LOE exclusion, and safe degradation + warning
on an unrecognized field-naming convention."""
from xml_parser import parse_p6_xml, pick_primary_project
from activity_extractor import (
    extract_activities_from_xml,
    get_data_date_xml,
    critical_status_coverage_warning,
)


def _extract(path):
    p6 = parse_p6_xml(path)
    return extract_activities_from_xml(p6.root)


def _by_id(activities):
    return {a.activity_id: a for a in activities}


def test_totalfloat_and_iscritical_read_directly(totalfloat_xml_path):
    by_id = _by_id(_extract(totalfloat_xml_path))
    # -16 hr / 8 = -2 days, IsCritical true
    assert by_id["A1000"].total_float_days == -2
    assert by_id["A1000"].is_critical is True
    # 80 hr / 8 = 10 days, IsCritical false
    assert by_id["A1010"].total_float_days == 10
    assert by_id["A1010"].is_critical is False


def test_loe_excluded_in_xml(totalfloat_xml_path):
    ids = {a.activity_id for a in _extract(totalfloat_xml_path)}
    assert "LOE1" not in ids


def test_data_date_xml(totalfloat_xml_path):
    p6 = parse_p6_xml(totalfloat_xml_path)
    project = pick_primary_project(p6.root)
    data_date = get_data_date_xml(project)
    assert data_date.strftime("%Y-%m-%d") == "2026-07-10"


def test_remaining_dates_calendar_aware_float(remaining_xml_path):
    by_id = _by_id(_extract(remaining_xml_path))
    a = by_id["A1000"]
    # 2026-07-06 (Mon) -> 2026-07-20 (Mon): 10 workdays minus one holiday
    # (2026-07-13) inside the span = 9 business days. Critically, this must
    # NOT be the raw 14-calendar-day / naive count.
    assert a.total_float_days == 9
    # forecast date comes from RemainingEarlyStartDate, not the stale Planned date
    assert a.planned_start == "2026-07-06 00:00"


def test_baseline_variance(baseline_xml_path):
    by_id = _by_id(_extract(baseline_xml_path))
    a = by_id["A1000"]
    # actual finish 2026-07-08 vs baseline target 2026-07-01 = 7 days late
    assert a.target_finish == "2026-07-01 00:00"
    assert a.variance_days == 7


def test_unrecognized_schema_degrades_safely(unrecognized_xml_path):
    activities = _extract(unrecognized_xml_path)
    assert len(activities) == 6
    # No recognized float field -> None float, not critical, and no crash /
    # no fabricated values.
    assert all(a.total_float_days is None for a in activities)
    assert all(a.is_critical is False for a in activities)


def test_unrecognized_schema_triggers_warning(unrecognized_xml_path):
    activities = _extract(unrecognized_xml_path)
    warning = critical_status_coverage_warning(activities)
    assert warning is not None
    assert "critical" in warning.lower()


def test_healthy_file_produces_no_warning(totalfloat_xml_path):
    activities = _extract(totalfloat_xml_path)
    assert critical_status_coverage_warning(activities) is None
