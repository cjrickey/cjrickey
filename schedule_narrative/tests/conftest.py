"""
Shared pytest fixtures: synthetic P6 exports that reproduce the real
schema variants this pipeline has to handle. Everything here is
hand-built, not derived from any real client schedule -- real customer
files are confidential and never committed.

Each builder returns file-content text; the pytest fixtures write it to
a temp file and hand back the path, so tests exercise the real parse
path end to end. To add a new variant to the corpus, add a builder and a
fixture here, then a test that asserts against it.
"""
import os
import sys
import textwrap

import pytest

# The app modules live one directory up (schedule_narrative/), imported
# flat (e.g. `import xer_parser`), so make that importable from tests/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TAB = "\t"


# --------------------------------------------------------------------------
# XER builder
# --------------------------------------------------------------------------
def _xer_table(name: str, fields: list[str], rows: list[list[str]]) -> str:
    lines = [f"%T{TAB}{name}", "%F" + TAB + TAB.join(fields)]
    for row in rows:
        lines.append("%R" + TAB + TAB.join(row))
    return "\n".join(lines)


def standard_xer() -> str:
    """A representative XER exercising: completed / in-progress / not-started
    statuses, a critical chain, a second parallel critical chain (for
    primary/secondary path detection), a near-critical activity, an LOE
    activity (must be excluded), a milestone, and a non-important completed
    activity (must be dropped by the default importance filter). Data date
    2026-07-10."""
    header = "ERMHDR\t22.12\t2026-07-10\tProject\tadmin\tadmin\tUSD"

    project = _xer_table(
        "PROJECT",
        ["proj_id", "last_recalc_date"],
        [["100", "2026-07-10 00:00"]],
    )
    projwbs = _xer_table(
        "PROJWBS",
        ["wbs_id", "proj_id", "parent_wbs_id", "wbs_name", "seq_num"],
        [
            ["200", "100", "", "Building A", "1"],
            ["201", "100", "200", "Structure", "1"],
        ],
    )

    task_fields = [
        "task_id", "proj_id", "wbs_id", "task_code", "task_name", "task_type",
        "status_code", "total_float_hr_cnt", "target_start_date", "target_end_date",
        "early_start_date", "early_end_date", "act_start_date", "act_end_date",
    ]
    # task_id, code, name, type, status, float_hr, tgt_start, tgt_end, early_start, early_end, act_start, act_end
    task_rows = [
        ["1", "100", "201", "A1000", "Excavate foundation", "TT_Task", "TK_Complete",
         "0", "2026-06-01 00:00", "2026-06-15 00:00", "", "", "2026-06-01 00:00", "2026-07-08 00:00"],
        ["2", "100", "201", "A1010", "Pour footings", "TT_Task", "TK_Active",
         "-40", "", "", "2026-06-16 00:00", "2026-07-20 00:00", "2026-06-20 00:00", ""],
        ["3", "100", "201", "A1020", "Frame walls", "TT_Task", "TK_NotStart",
         "-8", "", "", "2026-07-14 00:00", "2026-08-10 00:00", "", ""],
        ["4", "100", "201", "M1000", "Foundation milestone", "TT_Mile", "TK_NotStart",
         "-320", "", "", "2026-08-11 00:00", "2026-08-11 00:00", "", ""],
        ["5", "100", "201", "LOE1", "Project Management", "TT_LOE", "TK_Active",
         "0", "", "", "2026-06-01 00:00", "2026-08-01 00:00", "2026-06-01 00:00", ""],
        ["6", "100", "201", "A0990", "Landscaping prep", "TT_Task", "TK_Complete",
         "240", "2026-06-20 00:00", "2026-07-05 00:00", "", "", "2026-06-20 00:00", "2026-07-08 00:00"],
        ["7", "100", "201", "A1040", "Order steel", "TT_Task", "TK_NotStart",
         "80", "", "", "2026-07-15 00:00", "2026-07-30 00:00", "", ""],
        ["8", "100", "201", "A2010", "Electrical rough-in", "TT_Task", "TK_Active",
         "-24", "", "", "2026-06-20 00:00", "2026-07-25 00:00", "2026-06-25 00:00", ""],
        ["9", "100", "201", "A2020", "Electrical trim", "TT_Task", "TK_NotStart",
         "-16", "", "", "2026-07-16 00:00", "2026-08-05 00:00", "", ""],
    ]
    task = _xer_table("TASK", task_fields, task_rows)

    taskpred = _xer_table(
        "TASKPRED",
        ["task_pred_id", "task_id", "pred_task_id", "proj_id", "pred_proj_id", "pred_type", "lag_hr_cnt"],
        [
            ["1", "2", "1", "100", "100", "PR_FS", "0"],   # A1010 <- A1000
            ["2", "3", "2", "100", "100", "PR_FS", "0"],   # A1020 <- A1010
            ["3", "4", "3", "100", "100", "PR_FS", "0"],   # M1000 <- A1020
            ["4", "7", "1", "100", "100", "PR_FS", "0"],   # A1040 <- A1000
            ["5", "9", "8", "100", "100", "PR_FS", "0"],   # A2020 <- A2010
        ],
    )

    return "\n".join([header, project, projwbs, task, taskpred]) + "\n"


# --------------------------------------------------------------------------
# XML builders
# --------------------------------------------------------------------------
_XML_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<APIBusinessObjects '
    'xmlns="http://xmlns.oracle.com/Primavera/P6/V22.12/API/BusinessObjects" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
)
_XML_FOOTER = "</APIBusinessObjects>\n"


def totalfloat_xml() -> str:
    """XML variant that carries P6's own TotalFloat (hours) and IsCritical
    fields directly. Includes a Level of Effort activity that must be
    excluded."""
    return _XML_HEADER + textwrap.dedent("""\
      <Project>
        <ObjectId>1</ObjectId>
        <Id>PROJ</Id>
        <DataDate>2026-07-10T00:00:00</DataDate>
        <WBS><ObjectId>10</ObjectId><Name>Structure</Name></WBS>
        <Activity>
          <ObjectId>101</ObjectId><Id>A1000</Id><Name>Pour foundation</Name>
          <Type>Task Dependent</Type><Status>In Progress</Status>
          <WBSObjectId>10</WBSObjectId>
          <TotalFloat>-16</TotalFloat><IsCritical>true</IsCritical>
          <EarlyStartDate>2026-07-06T00:00:00</EarlyStartDate>
        </Activity>
        <Activity>
          <ObjectId>102</ObjectId><Id>A1010</Id><Name>Frame walls</Name>
          <Type>Task Dependent</Type><Status>Not Started</Status>
          <WBSObjectId>10</WBSObjectId>
          <TotalFloat>80</TotalFloat><IsCritical>false</IsCritical>
          <EarlyStartDate>2026-07-14T00:00:00</EarlyStartDate>
        </Activity>
        <Activity>
          <ObjectId>103</ObjectId><Id>LOE1</Id><Name>Project Management</Name>
          <Type>Level of Effort</Type><Status>In Progress</Status>
          <WBSObjectId>10</WBSObjectId>
          <TotalFloat>0</TotalFloat><IsCritical>true</IsCritical>
        </Activity>
      </Project>
    """) + _XML_FOOTER


def remaining_calendar_xml() -> str:
    """XML variant that carries neither TotalFloat nor plain Early/Late
    dates -- only RemainingEarlyStartDate / RemainingLateStartDate, plus a
    Calendar with a work week and a holiday. Float must be derived as a
    calendar-aware business-day count.

    The single activity spans RemainingEarlyStartDate 2026-07-06 (Mon) to
    RemainingLateStartDate 2026-07-20 (Mon): 14 calendar days, 2 weekends
    (10 workdays), minus one holiday inside the span (2026-07-13) -> 9."""
    return _XML_HEADER + textwrap.dedent("""\
      <Calendar>
        <ObjectId>500</ObjectId><Name>Standard 5-Day</Name>
        <StandardWorkWeek>
          <StandardWorkHours><DayOfWeek>Sunday</DayOfWeek><WorkTime xsi:nil="true"/></StandardWorkHours>
          <StandardWorkHours><DayOfWeek>Monday</DayOfWeek><WorkTime><Start>08:00:00</Start><Finish>17:00:00</Finish></WorkTime></StandardWorkHours>
          <StandardWorkHours><DayOfWeek>Tuesday</DayOfWeek><WorkTime><Start>08:00:00</Start><Finish>17:00:00</Finish></WorkTime></StandardWorkHours>
          <StandardWorkHours><DayOfWeek>Wednesday</DayOfWeek><WorkTime><Start>08:00:00</Start><Finish>17:00:00</Finish></WorkTime></StandardWorkHours>
          <StandardWorkHours><DayOfWeek>Thursday</DayOfWeek><WorkTime><Start>08:00:00</Start><Finish>17:00:00</Finish></WorkTime></StandardWorkHours>
          <StandardWorkHours><DayOfWeek>Friday</DayOfWeek><WorkTime><Start>08:00:00</Start><Finish>17:00:00</Finish></WorkTime></StandardWorkHours>
          <StandardWorkHours><DayOfWeek>Saturday</DayOfWeek><WorkTime xsi:nil="true"/></StandardWorkHours>
        </StandardWorkWeek>
        <HolidayOrExceptions>
          <HolidayOrException><Date>2026-07-13T00:00:00</Date><WorkTime xsi:nil="true"/></HolidayOrException>
        </HolidayOrExceptions>
      </Calendar>
      <Project>
        <ObjectId>1</ObjectId>
        <Id>PROJ</Id>
        <DataDate>2026-07-01T00:00:00</DataDate>
        <WBS><ObjectId>10</ObjectId><Name>Structure</Name></WBS>
        <Activity>
          <ObjectId>101</ObjectId><Id>A1000</Id><Name>Install curtain wall</Name>
          <Type>Task Dependent</Type><Status>Not Started</Status>
          <WBSObjectId>10</WBSObjectId>
          <CalendarObjectId>500</CalendarObjectId>
          <RemainingEarlyStartDate>2026-07-06T00:00:00</RemainingEarlyStartDate>
          <RemainingEarlyFinishDate>2026-07-10T00:00:00</RemainingEarlyFinishDate>
          <RemainingLateStartDate>2026-07-20T00:00:00</RemainingLateStartDate>
          <PlannedStartDate>2026-06-01T00:00:00</PlannedStartDate>
          <PlannedFinishDate>2026-06-05T00:00:00</PlannedFinishDate>
        </Activity>
      </Project>
    """) + _XML_FOOTER


def baseline_xml() -> str:
    """XML with an embedded BaselineProject linked by OriginalProjectObjectId,
    so variance_days is computed against the baseline's PlannedFinishDate.
    The completed activity finished 2026-07-08 vs. a baseline target of
    2026-07-01 -> 7 days late."""
    return _XML_HEADER + textwrap.dedent("""\
      <Project>
        <ObjectId>1</ObjectId>
        <Id>PROJ</Id>
        <DataDate>2026-07-10T00:00:00</DataDate>
        <WBS><ObjectId>10</ObjectId><Name>Structure</Name></WBS>
        <Activity>
          <ObjectId>101</ObjectId><Id>A1000</Id><Name>Pour foundation</Name>
          <Type>Task Dependent</Type><Status>Completed</Status>
          <WBSObjectId>10</WBSObjectId>
          <TotalFloat>0</TotalFloat><IsCritical>true</IsCritical>
          <ActualFinishDate>2026-07-08T00:00:00</ActualFinishDate>
          <PlannedStartDate>2026-06-01T00:00:00</PlannedStartDate>
          <PlannedFinishDate>2026-07-08T00:00:00</PlannedFinishDate>
        </Activity>
      </Project>
      <BaselineProject>
        <ObjectId>9</ObjectId>
        <OriginalProjectObjectId>1</OriginalProjectObjectId>
        <Activity>
          <ObjectId>901</ObjectId><Id>A1000</Id><Name>Pour foundation</Name>
          <PlannedFinishDate>2026-07-01T00:00:00</PlannedFinishDate>
        </Activity>
      </BaselineProject>
    """) + _XML_FOOTER


def unrecognized_xml() -> str:
    """XML from a hypothetical export whose float/criticality field naming
    this pipeline does not recognize -- no TotalFloat, IsCritical,
    Early/Late, or Remaining* fields. Extraction must degrade safely
    (float None, not critical, no crash) and the coverage check must warn."""
    activities = "\n".join(
        textwrap.dedent(f"""\
          <Activity>
            <ObjectId>{100 + i}</ObjectId><Id>A{1000 + i}</Id><Name>Activity {i}</Name>
            <Type>Task Dependent</Type><Status>Not Started</Status>
            <WBSObjectId>10</WBSObjectId>
            <SomeFutureFloatField>-5</SomeFutureFloatField>
            <PlannedStartDate>2026-07-15T00:00:00</PlannedStartDate>
            <PlannedFinishDate>2026-07-20T00:00:00</PlannedFinishDate>
          </Activity>""")
        for i in range(6)
    )
    return _XML_HEADER + textwrap.dedent("""\
      <Project>
        <ObjectId>1</ObjectId>
        <Id>PROJ</Id>
        <DataDate>2026-07-10T00:00:00</DataDate>
        <WBS><ObjectId>10</ObjectId><Name>Structure</Name></WBS>
    """) + activities + "\n  </Project>\n" + _XML_FOOTER


# --------------------------------------------------------------------------
# pytest fixtures -- write each builder's output to a temp file, return path
# --------------------------------------------------------------------------
def _write(tmp_path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.fixture
def xer_path(tmp_path):
    return _write(tmp_path, "standard.xer", standard_xer())


@pytest.fixture
def totalfloat_xml_path(tmp_path):
    return _write(tmp_path, "totalfloat.xml", totalfloat_xml())


@pytest.fixture
def remaining_xml_path(tmp_path):
    return _write(tmp_path, "remaining.xml", remaining_calendar_xml())


@pytest.fixture
def baseline_xml_path(tmp_path):
    return _write(tmp_path, "baseline.xml", baseline_xml())


@pytest.fixture
def unrecognized_xml_path(tmp_path):
    return _write(tmp_path, "unrecognized.xml", unrecognized_xml())
