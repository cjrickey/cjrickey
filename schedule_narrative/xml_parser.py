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


def parse_p6_xml(path: str) -> P6XmlFile:
    tree = ET.parse(path)
    root = tree.getroot()
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
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


def find_matching_baseline(root: ET.Element, project_object_id: str) -> Optional[ET.Element]:
    """The <BaselineProject> whose OriginalProjectObjectId points back to
    the given live project, if one was included in this export."""
    for baseline in root.findall("BaselineProject"):
        if baseline.findtext("OriginalProjectObjectId") == project_object_id:
            return baseline
    return None
