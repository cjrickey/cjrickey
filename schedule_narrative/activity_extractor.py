"""
Turns a parsed XerFile (or P6 XML file) into a flat list of activity
dicts, scoped to the "primary" project in the file (the one matching the
filename / the one with the most tasks -- P6 exports often carry in
external linked projects for cross-project relationships, which must NOT
be treated as part of this project's schedule).
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import xml.etree.ElementTree as ET

from xer_parser import XerFile, parse_p6_datetime

# P6's internal relationship-type codes/labels, normalized to plain English
# so both the XER and XML paths produce the same values downstream.
XER_PRED_TYPE_MAP = {
    "PR_FS": "Finish to Start",
    "PR_SS": "Start to Start",
    "PR_FF": "Finish to Finish",
    "PR_SF": "Start to Finish",
}


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
    target_finish: Optional[str] = None  # baseline target date; only ever set from a true P6 Baseline (XML)
    variance_days: Optional[int] = None
    is_milestone: bool = False
    # Real P6 logic links -- from TASKPRED (XER) or <Relationship> (XML),
    # never inferred from names/dates. Each entry: {"activity_id": str, "type": str}.
    # Deliberately excluded from to_dict()/serialize() for the main
    # completed/upcoming lists (would bloat every activity's JSON); only
    # surfaced, filtered to critical-to-critical links, by
    # filter_engine._top_critical_paths for the critical path narrative.
    predecessors: list[dict] = field(default_factory=list)
    successors: list[dict] = field(default_factory=list)

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

    def to_storage_dict(self) -> dict:
        """Full round-trip representation for storage.py -- unlike to_dict(),
        includes predecessors/successors. Those are left out of to_dict()
        to keep the per-activity narrative payload lean (only
        filter_engine._top_critical_paths needs them, already filtered
        down to the handful of critical activities), but storage.py persists
        whatever this returns, so leaving them out here would silently
        drop real P6 relationship data the moment a schedule is saved --
        it would never reach narrative generation even on a fresh upload."""
        return {**self.to_dict(), "predecessors": self.predecessors, "successors": self.successors}


STATUS_MAP = {
    "TK_Complete": "completed",
    "TK_Active": "in_progress",
    "TK_NotStart": "not_started",
}


def _build_xer_relationships(xer: XerFile, proj_id: str) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Real P6 logic links from TASKPRED, keyed by task_code (activity_id)
    rather than TASK's internal task_id -- TASKPRED references task_id, so
    this joins through a task_id -> task_code map first. Cross-project
    predecessor links (pred_proj_id != proj_id) are dropped -- those point
    at external/linked-project stub tasks, not real activities in this
    schedule (see pick_primary_proj_id).

    lag_hr_cnt is a standard TASKPRED field (confirmed on a real export),
    included so filter_engine.py's driving-relationship heuristic can
    account for lag instead of assuming zero. TASKPRED has no equivalent
    of XML's direct Driving flag -- driving is always None here, which
    just means the heuristic is always used for XER (same as XML exports
    that don't carry Driving either)."""
    task_id_to_code = {
        row.get("task_id"): row.get("task_code")
        for row in xer.get("TASK")
        if row.get("proj_id") == proj_id
    }

    predecessors: dict[str, list[dict]] = {}
    successors: dict[str, list[dict]] = {}
    for row in xer.get("TASKPRED"):
        if row.get("proj_id") != proj_id or row.get("pred_proj_id") != proj_id:
            continue
        succ_id = task_id_to_code.get(row.get("task_id"))
        pred_id = task_id_to_code.get(row.get("pred_task_id"))
        if not succ_id or not pred_id:
            continue
        rel_type = XER_PRED_TYPE_MAP.get(row.get("pred_type"), "Finish to Start")
        lag_raw = (row.get("lag_hr_cnt") or "").strip()
        try:
            lag_days = float(lag_raw) / 8 if lag_raw else None
        except ValueError:
            lag_days = None
        successors.setdefault(pred_id, []).append(
            {"activity_id": succ_id, "type": rel_type, "lag_days": lag_days, "driving": None}
        )
        predecessors.setdefault(succ_id, []).append(
            {"activity_id": pred_id, "type": rel_type, "lag_days": lag_days, "driving": None}
        )
    return predecessors, successors


def extract_activities(xer: XerFile, proj_id: Optional[str] = None) -> list[Activity]:
    if proj_id is None:
        proj_id = pick_primary_proj_id(xer)

    wbs_paths = build_wbs_path_map(xer, proj_id)
    predecessors_by_id, successors_by_id = _build_xer_relationships(xer, proj_id)

    activities = []
    for row in xer.get("TASK"):
        if row.get("proj_id") != proj_id:
            continue
        # Level of Effort activities (e.g. "Project Management," "Site
        # Supervision") span other activities' durations rather than
        # representing real, sequenced work -- they carry no meaningful
        # float/critical-path status and must never appear anywhere in a
        # narrative, critical path callouts included. Drop them here, at
        # the source, rather than filtering downstream.
        if row.get("task_type") == "TT_LOE":
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
                total_float_days = round(float(total_float_hr) / 8)  # 8hr workday, whole days for the narrative
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

        # XER cannot carry a P6 Baseline -- baselines only export via XML
        # (see xml_parser.py / extract_activities_from_xml). target_end_date
        # here is just the live project's own Planned Dates, which drift
        # over time and aren't a frozen snapshot; treating it as "the plan"
        # for variance purposes was the very confusion this was built to
        # fix. So XER uploads never produce variance_days -- only a true,
        # embedded P6 Baseline (XML) does.
        target_finish = None
        variance_days = None

        activity_id = row.get("task_code", "")
        activities.append(Activity(
            activity_id=activity_id,
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
            predecessors=predecessors_by_id.get(activity_id, []),
            successors=successors_by_id.get(activity_id, []),
        ))

    return activities


def _normalize_xml_date(value: Optional[str]) -> Optional[str]:
    """P6 XML dates are ISO-8601 ('2025-03-09T00:00:00'); normalize to the
    same 'YYYY-MM-DD HH:MM' string convention XER uses, so every downstream
    consumer (variance math here, filter_engine.py's date-window logic)
    can stay format-agnostic and just call parse_p6_datetime uniformly."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d %H:%M")


def build_wbs_path_map_xml(project: ET.Element) -> dict[str, str]:
    """ObjectId -> full path string, walking WBS elements that are direct
    children of the given <Project> (or <BaselineProject>) element."""
    nodes = {wbs.findtext("ObjectId"): wbs for wbs in project.findall("WBS")}
    path_cache: dict[str, str] = {}

    def resolve(object_id: str, _seen: Optional[set] = None) -> str:
        if object_id in path_cache:
            return path_cache[object_id]
        if _seen is None:
            _seen = set()
        if object_id in _seen or object_id not in nodes:
            return ""
        _seen.add(object_id)
        node = nodes[object_id]
        name = node.findtext("Name") or ""
        parent_id = node.findtext("ParentObjectId")
        if parent_id and parent_id in nodes:
            parent_path = resolve(parent_id, _seen)
            full = f"{parent_path} > {name}" if parent_path else name
        else:
            full = name
        path_cache[object_id] = full
        return full

    return {object_id: resolve(object_id) for object_id in nodes}


_XML_STATUS_MAP = {
    "Completed": "completed",
    "In Progress": "in_progress",
    "Not Started": "not_started",
}


_WEEKDAY_INDEX = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
    "Friday": 4, "Saturday": 5, "Sunday": 6,
}
_DEFAULT_CALENDAR = {"workdays": {0, 1, 2, 3, 4}, "holidays": set()}  # plain Mon-Fri, no holidays


def _has_work_time(parent: ET.Element) -> bool:
    """A P6 Calendar represents a non-working day/date as a <WorkTime
    xsi:nil="true" /> child with no Start/Finish -- checking for real
    Start content (rather than the nil attribute, whose namespace prefix
    survives root-tag-stripping unpredictably) works regardless of how
    the export happens to serialize it."""
    return any((wt.findtext("Start") or "").strip() for wt in parent.findall("WorkTime"))


def _parse_calendars(root: ET.Element) -> dict[str, dict]:
    """P6's own float calculation is calendar-aware -- a project can mix
    5-day, 6-day, and 24-hour calendars, each with its own holiday list,
    and an activity's Calendar assignment determines which one applies.
    This pipeline has no CPM engine, but replicating just the working-
    day pattern turns a raw date gap (see _xml_total_float_days) into a
    reasonable whole-workday count instead of counting weekends and
    holidays as work time, which wildly overstates float/behind-schedule
    magnitude on any gap spanning more than a few days. Confirmed on a
    real export that <Calendar> is a root-level element (project
    calendars shared, not nested under <Project>) -- but exports vary
    (see the two different float-field conventions already found in
    this app's history), so this searches at any depth rather than
    assuming root-level is universal; a project-scoped export that
    nests calendars under <Project> is found the same way. Looked up
    per-activity by CalendarObjectId. Returns
    {calendar_object_id: {"workdays": {0..6}, "holidays": {date}}}."""
    calendars: dict[str, dict] = {}
    for cal in root.findall(".//Calendar"):
        object_id = cal.findtext("ObjectId")
        if not object_id:
            continue
        workdays = set()
        week = cal.find("StandardWorkWeek")
        if week is not None:
            for day in week.findall("StandardWorkHours"):
                name = day.findtext("DayOfWeek")
                if name in _WEEKDAY_INDEX and _has_work_time(day):
                    workdays.add(_WEEKDAY_INDEX[name])

        holidays = set()
        exceptions = cal.find("HolidayOrExceptions")
        if exceptions is not None:
            for exc in exceptions.findall("HolidayOrException"):
                if _has_work_time(exc):
                    continue  # modified hours that day, still a working day
                normalized = _normalize_xml_date(exc.findtext("Date"))
                parsed = parse_p6_datetime(normalized) if normalized else None
                if parsed:
                    holidays.add(parsed.date())

        calendars[object_id] = {"workdays": workdays or {0, 1, 2, 3, 4}, "holidays": holidays}
    return calendars


def _business_days_between(start: datetime, end: datetime, calendar: dict) -> int:
    """Signed whole-workday count between two datetimes under the given
    calendar's work week + holiday pattern. Time-of-day is ignored (this
    pipeline works in whole days everywhere else too); only which
    calendar days fall strictly between the two dates counts."""
    sign = 1
    lo, hi = start, end
    if lo > hi:
        lo, hi = hi, lo
        sign = -1

    count = 0
    current = lo.date()
    end_date = hi.date()
    while current < end_date:
        if current.weekday() in calendar["workdays"] and current not in calendar["holidays"]:
            count += 1
        current += timedelta(days=1)
    return sign * count


def _xml_date_gap_days(activity: ET.Element, start_tag: str, end_tag: str, calendar: dict) -> Optional[float]:
    start = _normalize_xml_date(activity.findtext(start_tag))
    end = _normalize_xml_date(activity.findtext(end_tag))
    if not (start and end):
        return None
    s = parse_p6_datetime(start)
    e = parse_p6_datetime(end)
    if not (s and e):
        return None
    return _business_days_between(s, e, calendar)


def _xml_total_float_days(activity: ET.Element, calendars: dict[str, dict]) -> Optional[float]:
    """P6's XML schema carries TotalFloat as its own field (hours, same
    convention as the XER TASK table's total_float_hr_cnt) on some
    exports -- read it directly when present, rather than deriving it.
    Different P6 versions/export settings name the early/late date pair
    differently, though: some use plain EarlyStartDate/LateStartDate,
    others (confirmed on a real export, no TotalFloat/IsCritical/
    EarlyStartDate/LateStartDate fields at all) only carry
    RemainingEarlyStartDate/RemainingLateStartDate -- the correct pair
    for an in-progress or not-started activity's float from the data
    date forward. Tries each in order and uses the first that yields a
    value, so an export missing one naming convention still works via
    another. When deriving from dates, counts actual working days under
    the activity's own Calendar (falling back to a plain Mon-Fri week if
    the export carries no calendar data or this activity's
    CalendarObjectId doesn't match one) rather than raw elapsed hours,
    which otherwise overstates float by roughly 3x-5x on any gap of more
    than a few days by counting nights, weekends, and holidays as work
    time. Used for both the live project's activities and the
    baseline's."""
    raw = (activity.findtext("TotalFloat") or "").strip()
    if raw:
        try:
            return round(float(raw) / 8)  # 8hr workday, whole days for the narrative
        except ValueError:
            pass

    calendar = calendars.get(activity.findtext("CalendarObjectId"), _DEFAULT_CALENDAR)

    gap = _xml_date_gap_days(activity, "RemainingEarlyStartDate", "RemainingLateStartDate", calendar)
    if gap is not None:
        return gap

    return _xml_date_gap_days(activity, "EarlyStartDate", "LateStartDate", calendar)


def _xml_relationship_lag_days(rel: ET.Element) -> Optional[float]:
    raw = (rel.findtext("Lag") or "").strip()
    if not raw:
        return None
    try:
        return float(raw) / 8  # same hours-per-workday convention as float/duration fields
    except ValueError:
        return None


def _xml_relationship_driving(rel: ET.Element) -> Optional[bool]:
    raw = (rel.findtext("Driving") or "").strip().lower()
    return {"true": True, "false": False}.get(raw)


def _build_xml_relationships(project: ET.Element) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Real P6 logic links from <Relationship> elements, keyed by activity
    Id -- relationships reference activities by ObjectId (an internal id
    distinct from the human-readable Id used everywhere else in this
    module), so this joins through an ObjectId -> Id map first, the same
    pattern used for baseline linkage above.

    Driving and lag_days are P6's own computed/entered values, included
    when the export carries them (confirmed present in the schema, not
    populated in every real export seen so far -- same situation as
    TotalFloat/IsCritical) so filter_engine.py's driving-relationship
    determination can prefer them over its own date-gap heuristic, which
    can't account for lag or P6's own scheduling calculation at all."""
    objid_to_id = {
        a.findtext("ObjectId"): a.findtext("Id")
        for a in project.findall("Activity")
        if a.findtext("ObjectId") and a.findtext("Id")
    }

    predecessors: dict[str, list[dict]] = {}
    successors: dict[str, list[dict]] = {}
    for rel in project.findall("Relationship"):
        pred_id = objid_to_id.get(rel.findtext("PredecessorActivityObjectId"))
        succ_id = objid_to_id.get(rel.findtext("SuccessorActivityObjectId"))
        if not pred_id or not succ_id:
            continue
        rel_type = rel.findtext("Type") or "Finish to Start"
        lag_days = _xml_relationship_lag_days(rel)
        driving = _xml_relationship_driving(rel)
        successors.setdefault(pred_id, []).append(
            {"activity_id": succ_id, "type": rel_type, "lag_days": lag_days, "driving": driving}
        )
        predecessors.setdefault(succ_id, []).append(
            {"activity_id": pred_id, "type": rel_type, "lag_days": lag_days, "driving": driving}
        )
    return predecessors, successors


def extract_activities_from_xml(root: ET.Element) -> list[Activity]:
    """Same Activity shape as extract_activities(), sourced from a P6 XML
    export instead of XER. If the export embeds a matching <BaselineProject>
    (linked via OriginalProjectObjectId -- the true P6 Baseline set via
    Project > Maintain/Assign Baselines, not just the live project's own
    Planned Dates), target_finish/variance_days are computed against that
    baseline's PlannedFinishDate, joined by activity Id (ObjectId differs
    between the live project and its baseline copy, so Id is the only
    stable join key). No baseline embedded -- or an activity added since
    the baseline was taken -- means target_finish stays None, so
    variance_days comes out None too: no invented facts.

    Total float and criticality are read from P6's own TotalFloat/
    IsCritical fields (present directly in the XML schema, same as the
    XER TASK table's total_float_hr_cnt) rather than derived, since P6's
    own computed values reflect whatever critical-path definition and
    calendar/lag modeling the schedule actually uses -- this pipeline has
    no CPM engine of its own. Falls back to deriving float from date
    gaps (see _xml_total_float_days) only if an export omits the direct
    fields, using each activity's own Calendar to count real working
    days rather than raw elapsed time.
    """
    from xml_parser import pick_primary_project, find_matching_baseline

    project = pick_primary_project(root)
    project_object_id = project.findtext("ObjectId")
    baseline = find_matching_baseline(root, project_object_id)
    calendars = _parse_calendars(root)

    baseline_target_finish: dict[str, str] = {}
    if baseline is not None:
        for a in baseline.findall("Activity"):
            activity_id = a.findtext("Id")
            if not activity_id:
                continue
            target = _normalize_xml_date(a.findtext("PlannedFinishDate"))
            if target:
                baseline_target_finish[activity_id] = target

    wbs_paths = build_wbs_path_map_xml(project)
    predecessors_by_id, successors_by_id = _build_xml_relationships(project)

    activities = []
    for a in project.findall("Activity"):
        # Same exclusion as the XER path -- Level of Effort activities carry
        # no meaningful float/critical-path status and must never appear in
        # a narrative.
        if a.findtext("Type") == "Level of Effort":
            continue

        raw_status = a.findtext("Status") or ""
        status = _XML_STATUS_MAP.get(raw_status, raw_status.lower().replace(" ", "_"))

        # EarlyStartDate isn't universal either -- some exports only carry
        # RemainingEarlyStartDate (see _xml_total_float_days above).
        early_start = (
            _normalize_xml_date(a.findtext("EarlyStartDate"))
            or _normalize_xml_date(a.findtext("RemainingEarlyStartDate"))
        )
        total_float_days = _xml_total_float_days(a, calendars)

        # IsCritical is P6's own computed flag -- it reflects whatever
        # critical-path definition the project's schedule options actually
        # use (total float <= a threshold, or true Longest Path, which
        # isn't always identical to float <= 0), so it's more trustworthy
        # than re-deriving criticality from total_float_days here. Only
        # fall back to the float-based definition when this export omits
        # the field entirely.
        raw_is_critical = (a.findtext("IsCritical") or "").strip().lower()
        if raw_is_critical in ("true", "false"):
            is_critical = raw_is_critical == "true"
        else:
            is_critical = total_float_days is not None and total_float_days <= 0
        is_milestone = a.findtext("Type") in ("Start Milestone", "Finish Milestone")

        planned_start_field = _normalize_xml_date(a.findtext("PlannedStartDate"))
        planned_finish_field = _normalize_xml_date(a.findtext("PlannedFinishDate"))
        early_finish = (
            _normalize_xml_date(a.findtext("EarlyFinishDate"))
            or _normalize_xml_date(a.findtext("RemainingEarlyFinishDate"))
        )

        # Same completed-vs-not split as the XER path: once complete, P6's
        # forward-pass Early dates are stale (collapsed to the data date),
        # so Planned Dates are the meaningful ones; for anything not yet
        # finished, Early dates are the live forecast.
        if status == "completed":
            planned_start = planned_start_field
            planned_finish = planned_finish_field
        else:
            planned_start = early_start or planned_start_field
            planned_finish = early_finish or planned_finish_field

        activity_id = a.findtext("Id") or ""
        actual_finish = _normalize_xml_date(a.findtext("ActualFinishDate"))
        target_finish = baseline_target_finish.get(activity_id)

        variance_days = None
        if actual_finish and target_finish:
            af = parse_p6_datetime(actual_finish)
            tf = parse_p6_datetime(target_finish)
            if af and tf:
                variance_days = (af - tf).days
        elif planned_finish and target_finish and status != "completed":
            pf = parse_p6_datetime(planned_finish)
            tf = parse_p6_datetime(target_finish)
            if pf and tf:
                variance_days = (pf - tf).days

        activities.append(Activity(
            activity_id=activity_id,
            name=a.findtext("Name") or "",
            wbs_path=wbs_paths.get(a.findtext("WBSObjectId") or "", ""),
            status=status,
            is_critical=is_critical,
            is_milestone=is_milestone,
            total_float_days=total_float_days,
            actual_start=_normalize_xml_date(a.findtext("ActualStartDate")),
            actual_finish=actual_finish,
            planned_start=planned_start,
            planned_finish=planned_finish,
            target_finish=target_finish,
            variance_days=variance_days,
            predecessors=predecessors_by_id.get(activity_id, []),
            successors=successors_by_id.get(activity_id, []),
        ))

    return activities


def critical_status_coverage_warning(activities: list[Activity]) -> Optional[str]:
    """P6/PMXML exports vary by version and export settings in ways this
    app has already been caught out by twice (see xml_parser.py /
    activity_extractor.py history: one variant carries TotalFloat/
    IsCritical directly, another only RemainingEarlyStartDate/
    RemainingLateStartDate, and there's no guarantee a not-yet-seen
    variant won't use a third naming convention this pipeline doesn't
    recognize). Rather than let that surface only as a confusing "zero
    critical activities" narrative days later, checked at upload time so
    it's diagnosable immediately: if most not-yet-finished activities
    have no determinable total float, something about this specific
    export's field names likely isn't recognized. Deliberately says
    nothing about a specific float number (never surfaced to users at
    all -- see prompt_templates.py) -- only that determination itself
    may have failed for this file."""
    relevant = [a for a in activities if a.status != "completed"]
    if not relevant:
        return None
    determined = sum(1 for a in relevant if a.total_float_days is not None)
    if determined / len(relevant) >= 0.5:
        return None
    return (
        "Critical path status could not be determined for most activities in this file. "
        "This can happen with certain P6 export settings or versions -- results involving "
        "critical or near-critical activities may be incomplete. Contact us if this persists."
    )


def extraction_diagnostics(activities: list[Activity]) -> dict:
    """A compact health readout of what extraction actually pulled out of a
    file, returned on every upload. Its point is variant-robustness: P6
    exports vary by version/settings in ways we can't fully anticipate, so
    rather than only handle the variants we've seen, this surfaces the
    numbers that make a mis-parse obvious at a glance (e.g. "6,500
    activities, 0 relationships parsed" screams that this file's logic-link
    naming isn't recognized) instead of it surfacing days later as a
    confusing narrative. Pure counts -- no schedule content."""
    total = len(activities)
    non_completed = [a for a in activities if a.status != "completed"]
    with_float = sum(1 for a in non_completed if a.total_float_days is not None)
    with_dates = sum(
        1 for a in activities
        if a.planned_start or a.planned_finish or a.actual_start or a.actual_finish
    )
    return {
        "activity_count": total,
        "critical_count": sum(1 for a in activities if a.is_critical),
        "milestone_count": sum(1 for a in activities if a.is_milestone),
        "relationships_parsed": sum(len(a.predecessors) for a in activities),
        "float_coverage_pct": round(100 * with_float / len(non_completed)) if non_completed else 100,
        "date_coverage_pct": round(100 * with_dates / total) if total else 0,
        "status_breakdown": {
            "completed": sum(1 for a in activities if a.status == "completed"),
            "in_progress": sum(1 for a in activities if a.status == "in_progress"),
            "not_started": sum(1 for a in activities if a.status == "not_started"),
        },
    }


def extraction_warnings(activities: list[Activity]) -> list[str]:
    """All plain-language data-quality warnings for a file, generalizing the
    float-coverage check (critical_status_coverage_warning) to the other
    fields a variant export could name differently: dates and logic links.
    Each is a "did most activities come through with X?" test, so it flags
    an unrecognized field-naming convention without having to know the
    specific convention. Returns [] for a clean file."""
    warnings: list[str] = []

    float_warning = critical_status_coverage_warning(activities)
    if float_warning:
        warnings.append(float_warning)

    diag = extraction_diagnostics(activities)

    if diag["activity_count"] > 0 and diag["date_coverage_pct"] < 50:
        warnings.append(
            "Start/finish dates could not be read for most activities in this file. "
            "This can happen with certain P6 export settings or versions -- the report's "
            "dates may be incomplete. Contact us if this persists."
        )

    # Zero logic links across a non-trivial schedule almost always means the
    # relationship data didn't parse (a variant naming), not that the
    # schedule genuinely has none. Threshold avoids false alarms on small,
    # legitimately link-sparse schedules.
    if diag["activity_count"] >= 25 and diag["relationships_parsed"] == 0:
        warnings.append(
            "No predecessor/successor logic could be read from this file, so critical-path "
            "sequencing may be limited. This can happen with certain P6 export settings or "
            "versions. Contact us if this persists."
        )

    return warnings


def get_data_date_xml(project: ET.Element) -> Optional[datetime]:
    return parse_p6_datetime(_normalize_xml_date(project.findtext("DataDate")))


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
