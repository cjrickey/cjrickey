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
from datetime import datetime
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
    # filter_engine._remaining_critical_path for the critical path narrative.
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
    schedule (see pick_primary_proj_id)."""
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
        successors.setdefault(pred_id, []).append({"activity_id": succ_id, "type": rel_type})
        predecessors.setdefault(succ_id, []).append({"activity_id": pred_id, "type": rel_type})
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


def _xml_total_float_days(activity: ET.Element) -> Optional[float]:
    """Total float isn't always its own field in a P6 XML export (an
    export-option choice); derive it from LateStartDate - EarlyStartDate
    instead, mirroring the /8-hour-workday approximation the XER path uses.
    Used for both the live project's activities and the baseline's."""
    early_start = _normalize_xml_date(activity.findtext("EarlyStartDate"))
    late_start = _normalize_xml_date(activity.findtext("LateStartDate"))
    if not (early_start and late_start):
        return None
    es = parse_p6_datetime(early_start)
    ls = parse_p6_datetime(late_start)
    if not (es and ls):
        return None
    return round((ls - es).total_seconds() / 3600 / 8)  # whole days for the narrative


def _build_xml_relationships(project: ET.Element) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Real P6 logic links from <Relationship> elements, keyed by activity
    Id -- relationships reference activities by ObjectId (an internal id
    distinct from the human-readable Id used everywhere else in this
    module), so this joins through an ObjectId -> Id map first, the same
    pattern used for baseline linkage above."""
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
        successors.setdefault(pred_id, []).append({"activity_id": succ_id, "type": rel_type})
        predecessors.setdefault(succ_id, []).append({"activity_id": pred_id, "type": rel_type})
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

    Total float isn't always present as its own field in a P6 XML export
    (an export-option choice); it's derived here from
    LateStartDate - EarlyStartDate instead, mirroring the /8-hour-workday
    approximation the XER path already uses.
    """
    from xml_parser import pick_primary_project, find_matching_baseline

    project = pick_primary_project(root)
    project_object_id = project.findtext("ObjectId")
    baseline = find_matching_baseline(root, project_object_id)

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

        early_start = _normalize_xml_date(a.findtext("EarlyStartDate"))
        total_float_days = _xml_total_float_days(a)

        is_critical = total_float_days is not None and total_float_days <= 0
        is_milestone = a.findtext("Type") in ("Start Milestone", "Finish Milestone")

        planned_start_field = _normalize_xml_date(a.findtext("PlannedStartDate"))
        planned_finish_field = _normalize_xml_date(a.findtext("PlannedFinishDate"))
        early_finish = _normalize_xml_date(a.findtext("EarlyFinishDate"))

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
