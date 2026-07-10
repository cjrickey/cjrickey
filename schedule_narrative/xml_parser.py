"""
Parser for Primavera P6 XML exports (the APIBusinessObjects schema).

Unlike XER, a P6 XML export can embed a full assigned Baseline alongside
the live project -- a <BaselineProject> element, linked back to the live
project via <OriginalProjectObjectId>. This is the only way to get a true
P6 Baseline (the one set via Project > Maintain/Assign Baselines) rather
than the live project's own current Planned Dates, which can shift over
time and aren't a frozen snapshot.

The namespace URI embeds the P6 version (e.g. .../V22.12/...), which
varies by client version -- so tags are stripped of their namespace
right after parsing rather than hardcoding a version, letting the rest
of the code match plain local tag names regardless of source version.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import xml.etree.ElementTree as ET


@dataclass
class P6XmlFile:
    root: ET.Element


# Real P6/PMXML exports can carry far more than the schedule data this
# app reads -- resource assignments, UDFs, activity codes, notes, risks,
# S-curve spread data, etc. -- and a plain ET.parse() keeps all of it in
# memory for the whole request regardless of whether any of it is ever
# looked at (verified: none of these tags are referenced anywhere in
# xml_parser.py or activity_extractor.py). Cleared the instant each
# one's closing tag is parsed, so memory stays roughly proportional to
# what this app actually uses, not to whatever the export happens to
# include. Calendar is deliberately NOT in this set -- when an export
# doesn't carry a direct TotalFloat field, activity_extractor.py needs
# each Calendar's work week + holiday list to turn a raw date gap into
# a real business-day count instead of treating every calendar day
# (including weekends and holidays) as work time.
_UNUSED_HEAVY_TAGS = {
    "ResourceAssignment", "UDF", "UDFType", "ActivityCode", "ActivityCodeType",
    "ActivityCodeTypeValue", "Expense", "Step", "Risk", "Role", "Resource",
    "WorkTimeException", "ResourceCode", "ResourceCodeType",
    "ProjectCode", "ProjectCodeType", "Currency", "FinancialPeriod",
    "ScheduleOptions", "ProjectSpread", "ResourceAssignmentSpread",
    "Notebook", "ActivityNote", "WBSNote", "ProjectNote",
}


def parse_p6_xml(path: str) -> P6XmlFile:
    root = None
    # iterparse still builds the full tree as it goes -- the memory win
    # comes from clearing unused elements the moment they're complete,
    # not from avoiding tree-building itself. events=("end",) means each
    # element arrives once, fully parsed; the last one is always the
    # document root.
    for _, elem in ET.iterparse(path, events=("end",)):
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
        if elem.tag in _UNUSED_HEAVY_TAGS:
            elem.clear()
        root = elem
    return P6XmlFile(root=root)


def find_real_projects(root: ET.Element) -> list[ET.Element]:
    """Root-level <Project> elements that are the live schedule itself --
    excludes <Project external="true"> stubs, which only carry minimal
    cross-project relationship placeholders for predecessor/successor
    links into other, unrelated projects."""
    return [p for p in root.findall("Project") if p.get("external") != "true"]


def pick_primary_project(root: ET.Element) -> ET.Element:
    """The primary project is the one with the most Activity children --
    mirrors pick_primary_proj_id in activity_extractor.py for XER."""
    projects = find_real_projects(root)
    if not projects:
        raise ValueError("No project found in XML file")
    return max(projects, key=lambda p: len(p.findall("Activity")))


def _project_list_baseline_object_id(root: ET.Element, project_object_id: str) -> Optional[str]:
    """<ProjectList><Project ObjectId="X"><BaselineProject ObjectId="Y"> names
    the specific baseline P6 associates with this project in the export --
    this is the deterministic signal for "which one," since a file can embed
    more than one <BaselineProject> that all point back to the same live
    project (e.g. several named baselines selected at export time)."""
    for project in root.find("ProjectList").findall("Project") if root.find("ProjectList") is not None else []:
        if project.get("ObjectId") == project_object_id:
            baseline_ref = project.find("BaselineProject")
            if baseline_ref is not None:
                return baseline_ref.get("ObjectId")
    return None


def find_matching_baseline(root: ET.Element, project_object_id: str) -> Optional[ET.Element]:
    """The <BaselineProject> P6 actually associates with the given live
    project. Prefers the specific one named in <ProjectList> (see above);
    falls back to matching by OriginalProjectObjectId only if that
    reference isn't present, and only when there's exactly one candidate --
    picking arbitrarily among several would silently use the wrong
    baseline, which is worse than reporting none."""
    named_id = _project_list_baseline_object_id(root, project_object_id)
    if named_id is not None:
        for baseline in root.findall("BaselineProject"):
            if baseline.findtext("ObjectId") == named_id:
                return baseline
        return None

    candidates = [
        baseline
        for baseline in root.findall("BaselineProject")
        if baseline.findtext("OriginalProjectObjectId") == project_object_id
    ]
    return candidates[0] if len(candidates) == 1 else None
