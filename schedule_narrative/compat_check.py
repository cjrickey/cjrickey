"""
Standalone compatibility check for a schedule export from a tool other
than desktop P6 -- Asta Powerproject, Microsoft Project, Oracle
Primavera Cloud, etc. Doesn't touch the real pipeline or upload
anything; just reports which tables/fields (XER) or elements (XML) are
actually present in the file, against what activity_extractor.py
requires, so compatibility can be verified instead of assumed.

Usage:
    python3 compat_check.py path/to/export.xer
    python3 compat_check.py path/to/export.xml
"""
import sys
import xml.etree.ElementTree as ET

from xer_parser import parse_xer

# Fields activity_extractor.extract_activities() actually reads off TASK rows.
EXPECTED_XER_TASK_FIELDS = [
    "task_code", "task_name", "proj_id", "wbs_id", "status_code",
    "task_type", "total_float_hr_cnt", "early_start_date", "early_end_date",
    "target_start_date", "target_end_date", "act_start_date", "act_end_date",
]
EXPECTED_XER_TABLES = ["TASK", "PROJECT", "PROJWBS", "TASKPRED"]

# Fields activity_extractor.extract_activities_from_xml() actually reads
# off <Activity> elements.
EXPECTED_XML_ACTIVITY_FIELDS = [
    "Id", "Name", "Status", "Type", "EarlyStartDate", "EarlyFinishDate",
    "PlannedStartDate", "PlannedFinishDate", "ActualStartDate", "ActualFinishDate",
    "LateStartDate", "WBSObjectId",
]


def check_xer(path: str) -> None:
    xer = parse_xer(path)
    print(f"Header: {xer.header}\n")
    print("Tables found:")
    for name, rows in xer.tables.items():
        print(f"  {name}: {len(rows)} rows")

    print("\nTable coverage (what activity_extractor.py needs):")
    for table in EXPECTED_XER_TABLES:
        rows = xer.get(table)
        print(f"  [{'OK' if rows else 'MISSING'}] {table} ({len(rows)} rows)")

    task_rows = xer.get("TASK")
    if not task_rows:
        print("\nNo TASK rows -- this file cannot be read by our XER parser as-is.")
        return

    print("\nTASK field coverage (based on the first row):")
    sample = task_rows[0]
    for field in EXPECTED_XER_TASK_FIELDS:
        print(f"  [{'OK' if field in sample else 'MISSING'}] {field}")


def check_xml(path: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]

    print(f"Root tag: <{root.tag}>")
    print(f"Root's direct child tags: {sorted(set(c.tag for c in root))}\n")

    # P6 PMXML wraps everything in <APIBusinessObjects><Project>..., but
    # some other tools' XML export uses <Project> as the root itself --
    # check both so the diagnosis is accurate either way.
    projects = root.findall("Project")
    if not projects and root.tag == "Project":
        projects = [root]
    print(f"<Project> element(s) found: {len(projects)}")
    if not projects:
        print(
            "\nNo <Project> element anywhere -- doesn't match the P6 PMXML schema "
            "our xml_parser.py expects. This format likely needs its own dedicated "
            "parser, not a field-name tweak."
        )
        return

    project = max(projects, key=lambda p: len(p.findall("Activity")))
    activities = project.findall("Activity")
    print(f"<Activity> elements directly under the primary <Project>: {len(activities)}")
    if not activities:
        print(
            "\nNo <Activity> elements directly under <Project> -- check the child tag "
            "names printed above for what this format actually calls its tasks (e.g. "
            "Microsoft Project XML nests them under <Tasks><Task> instead, which this "
            "parser will not find)."
        )
        return

    print("\nActivity field coverage (based on the first activity):")
    sample_fields = {c.tag for c in activities[0]}
    for field in EXPECTED_XML_ACTIVITY_FIELDS:
        print(f"  [{'OK' if field in sample_fields else 'MISSING'}] {field}")

    relationships = project.findall("Relationship")
    print(f"\n<Relationship> elements (predecessor/successor logic): {len(relationships)}")

    baselines = root.findall("BaselineProject")
    print(f"<BaselineProject> elements (P6 Baseline data): {len(baselines)}")


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 compat_check.py path/to/export.(xer|xml)")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "rb") as f:
        head = f.read(200).lstrip(b"\xef\xbb\xbf").lstrip()

    if head.startswith(b"ERMHDR"):
        print("Detected: XER\n")
        check_xer(path)
    elif head.startswith(b"<?xml") or head.startswith(b"<APIBusinessObjects"):
        print("Detected: XML\n")
        check_xml(path)
    else:
        print("Doesn't look like XER or XML. First 200 bytes:")
        print(head)


if __name__ == "__main__":
    main()
