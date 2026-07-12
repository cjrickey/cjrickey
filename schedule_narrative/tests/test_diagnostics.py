"""extraction_diagnostics + extraction_warnings: the general variant-detection
layer. These generalize the float-coverage check to dates and logic links, so
an unrecognized field-naming convention surfaces at upload time instead of as a
confusing narrative later -- without having to anticipate the specific variant."""
from activity_extractor import (
    Activity,
    extract_activities,
    extract_activities_from_xml,
    extraction_diagnostics,
    extraction_warnings,
)
from xer_parser import parse_xer
from xml_parser import parse_p6_xml


def _mk(aid, *, status="not_started", float_days=None, critical=False, milestone=False,
        planned_start="2026-07-15 00:00", preds=None):
    return Activity(
        activity_id=aid, name=aid, wbs_path="Root", status=status,
        is_critical=critical, total_float_days=float_days, planned_start=planned_start,
        planned_finish=None, actual_start=None, actual_finish=None, target_finish=None,
        variance_days=None, is_milestone=milestone, predecessors=preds or [],
    )


# --------------------------------------------------------------------------
# diagnostics readout
# --------------------------------------------------------------------------
def test_diagnostics_on_real_xer(xer_path):
    diag = extraction_diagnostics(extract_activities(parse_xer(xer_path)))
    assert diag["activity_count"] == 8
    assert diag["milestone_count"] == 1
    assert diag["relationships_parsed"] >= 4
    assert diag["date_coverage_pct"] == 100
    # status breakdown sums back to the total
    sb = diag["status_breakdown"]
    assert sb["completed"] + sb["in_progress"] + sb["not_started"] == 8


def test_healthy_file_has_no_warnings(xer_path):
    assert extraction_warnings(extract_activities(parse_xer(xer_path))) == []


# --------------------------------------------------------------------------
# generalized variant detection
# --------------------------------------------------------------------------
def test_unrecognized_float_variant_warns(unrecognized_xml_path):
    activities = extract_activities_from_xml(parse_p6_xml(unrecognized_xml_path).root)
    warnings = extraction_warnings(activities)
    assert any("critical path status" in w.lower() for w in warnings)


def test_missing_dates_variant_warns():
    # A hypothetical variant where date fields didn't parse: activities exist
    # but carry no usable dates.
    activities = [_mk(f"A{i}", planned_start=None, float_days=5) for i in range(10)]
    warnings = extraction_warnings(activities)
    assert any("dates could not be read" in w.lower() for w in warnings)


def test_missing_relationships_variant_warns():
    # 25+ activities but zero logic links parsed -> almost certainly a variant
    # whose relationship naming wasn't recognized.
    activities = [_mk(f"A{i}", float_days=5) for i in range(30)]
    diag = extraction_diagnostics(activities)
    assert diag["relationships_parsed"] == 0
    warnings = extraction_warnings(activities)
    assert any("predecessor/successor logic" in w.lower() for w in warnings)


def test_small_link_sparse_schedule_does_not_false_alarm():
    # A small schedule legitimately having no links must NOT trip the
    # relationship warning (threshold guards against false positives).
    activities = [_mk(f"A{i}", float_days=5) for i in range(10)]
    warnings = extraction_warnings(activities)
    assert not any("predecessor/successor logic" in w.lower() for w in warnings)
