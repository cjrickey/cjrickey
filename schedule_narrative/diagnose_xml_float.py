"""
Standalone diagnostic -- run this locally against your own P6 XML export
to help pin down why critical activities aren't being detected. It never
prints activity names, dates, or any other schedule content -- only field
names and aggregate counts, safe to share.

Usage:
    python3 diagnose_xml_float.py path/to/your_export.xml
"""
import sys
import xml.etree.ElementTree as ET
from collections import Counter


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def main(path: str) -> None:
    root = None
    for _, elem in ET.iterparse(path, events=("end",)):
        elem.tag = strip_ns(elem.tag)
        root = elem

    projects = [p for p in root.findall("Project") if p.get("external") != "true"]
    if not projects:
        print("No non-external <Project> found -- can't proceed.")
        return
    project = max(projects, key=lambda p: len(p.findall("Activity")))
    activities = project.findall("Activity")
    print(f"Activities in primary project: {len(activities)}")

    # Every distinct child tag name seen under <Activity>, and how many
    # activities have it present with a non-empty value.
    tag_counts = Counter()
    nonempty_counts = Counter()
    for a in activities:
        seen_tags = set()
        for child in a:
            tag = strip_ns(child.tag)
            seen_tags.add(tag)
            if (child.text or "").strip():
                nonempty_counts[tag] += 1
        for tag in seen_tags:
            tag_counts[tag] += 1

    print("\nAll field names present under <Activity>, with counts (present / non-empty):")
    for tag in sorted(tag_counts):
        print(f"  {tag}: {tag_counts[tag]} present, {nonempty_counts[tag]} non-empty")

    # Specifically check the fields this app currently relies on.
    print("\n--- Fields this app currently uses for critical/float detection ---")
    total_float_present = sum(1 for a in activities if (a.findtext("TotalFloat") or "").strip())
    is_critical_present = sum(1 for a in activities if (a.findtext("IsCritical") or "").strip())
    early_present = sum(1 for a in activities if (a.findtext("EarlyStartDate") or "").strip())
    late_present = sum(1 for a in activities if (a.findtext("LateStartDate") or "").strip())
    both_present = sum(
        1 for a in activities
        if (a.findtext("EarlyStartDate") or "").strip() and (a.findtext("LateStartDate") or "").strip()
    )
    print(f"TotalFloat non-empty:     {total_float_present} / {len(activities)}  (primary source)")
    print(f"IsCritical non-empty:     {is_critical_present} / {len(activities)}  (primary source)")
    print(f"EarlyStartDate non-empty: {early_present} / {len(activities)}  (fallback only)")
    print(f"LateStartDate non-empty:  {late_present} / {len(activities)}  (fallback only)")
    print(f"Both Early+Late non-empty:{both_present} / {len(activities)}")

    # Any field whose name suggests it directly carries float/critical/
    # driving-path info -- if one of these exists, it's likely a more
    # reliable source than deriving float from date subtraction.
    print("\n--- Fields whose name suggests float/critical/driving-path info ---")
    candidate_keywords = ("float", "critical", "driv", "longestpath")
    candidate_tags = sorted(
        tag for tag in tag_counts
        if any(kw in tag.lower() for kw in candidate_keywords)
    )
    if not candidate_tags:
        print("  (none found)")
    else:
        for tag in candidate_tags:
            values = Counter((a.findtext(tag) or "").strip() for a in activities)
            values.pop("", None)
            sample_values = dict(values.most_common(5))
            print(f"  {tag}: {tag_counts[tag]} present, {nonempty_counts[tag]} non-empty, sample value counts: {sample_values}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 diagnose_xml_float.py path/to/your_export.xml")
        sys.exit(1)
    main(sys.argv[1])
