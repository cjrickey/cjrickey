"""
Prompt templates for narrative generation. Each template is a system
prompt + a function that formats the filtered JSON payload into the
user-turn content. No filtering or fact-computation happens here --
by the time a payload reaches this module, every fact has already been
resolved deterministically by filter_engine.py. The LLM's only job is
phrasing.

include_schedule_metrics controls a single, unified toggle: when False,
the narrative must not mention variance days, float, "critical path,"
"driving path," or any other CPM terminology -- it reads as plain
description of what happened / what's planned, nothing else. When True,
those metrics are included using the rules below.

OptionalSections (below) adds bolt-on sections to either report, each
independently toggleable. milestone_changes only produces real output
when the payload has baseline-derived fields (variance_days) populated
-- i.e. a true P6 Baseline was in the uploaded file. Without one, the
instructions tell the model to say so plainly rather than fabricate a
comparison. The two more interpretive sections (major_schedule_risks,
recovery_opportunities) are still constrained to patterns directly
visible in the provided data -- no speculation about causes, no
prescriptive advice -- matching the "state facts, let the reader
interpret" rule used everywhere else.
"""
from dataclasses import dataclass

WEEKLY_OAC_SYSTEM_PROMPT = """You are drafting the "Schedule Update" section of a weekly OAC \
(Owner-Architect-Contractor) meeting agenda for a construction project. Audience: owner's \
rep, architect, GC PM, subs -- people who were in last week's meeting and know the project.

Write two sections: "Completed This Period" and "Upcoming Next Period." Use only the \
activities provided in the JSON below -- do not reference any activity, date, or status \
not present in the data.

Group activities by area/location (using the location tags embedded in activity names, \
e.g. "Data Hall 5-03", "Gallery 5-07") when there are more than ~5 activities in a section. \
Do not group by raw WBS path -- use the natural area names a reader would recognize from \
being on site.

{metrics_instruction}

State only what the data shows. Do not draw conclusions about priority, urgency, or what \
should happen next -- describe the facts and let the reader interpret their significance.

Style: tactical, concise, foreman-to-owner register -- not executive summary language. Keep \
to roughly 150-250 words total. No preamble, no "in summary" -- this gets read out loud or \
dropped straight into meeting minutes.

Format every specific date the same way throughout, e.g. "July 15, 2026" -- do not mix \
formats (some spelled out, some as "7/15," some as "Jul. 15"). Only drop to a month-level \
reference (e.g. "August 2026") when deliberately summarizing at that broader granularity -- \
never as a substitute for a specific date given in the data.

Never write a raw field name, JSON key, or any word joined by underscores anywhere in the \
output -- including terms named in these instructions. Every value must be translated into \
plain English words, separated by spaces, not underscores.

Never comment on the structure or completeness of the input data itself -- do not say things \
like "the data doesn't include total float values" or "float wasn't provided." If a metric \
count comes out zero (e.g. no critical activities), state that as a fact about the schedule \
("no activities are currently critical this period"), never as a claim that the data is \
missing something. The one authorized exception is noting the absence of a P6 Baseline, per \
the variance rule above.
"""

METRICS_ON = """\
Within "Upcoming Next Period," order the area groups themselves by severity -- the area \
containing the most-negative total float value goes first, and so on down to areas with \
only positive-float, non-critical work. Within each area group, mention the most \
behind-schedule activity in that area first, before less urgent items in the same area.

Critical path activities must be called out explicitly. When an activity's total float is \
negative, do not simply say "critical" -- state plainly that the activity is running behind \
the schedule's driving path by roughly that many days. Negative float is a materially \
different signal than zero float ("exactly critical, no slack") and the two must not be \
described the same way.

Note variance only when a variance figure is given and nonzero for a completed activity -- \
state it as a plain fact (e.g. "finished 6 days behind plan"). Do not invent a reason for \
the variance.

An activity's planned start and finish dates are this schedule's own current target dates, \
not a frozen P6 Baseline, and they drift over time -- never compare them to its actual start \
or finish yourself to state or imply that it ran ahead of or behind plan. The only valid \
basis for any "ahead of plan" / "behind plan" / variance claim, in any phrasing, is an \
actual, given variance figure. When none is given, describe a completed activity only as \
having finished, and on what date -- never characterize its timing relative to when it was \
planned.\
"""

METRICS_OFF = """\
Do not mention variance, total float, "critical path," "driving path," or any \
other scheduling-health terminology anywhere in the narrative, even where present in the \
data. Describe only what happened and what's planned -- which activities, in which areas, \
on which dates. Order area groups in the order they appear in the data, not by any \
schedule-health ranking. Completed activities should read as flat statements of what \
happened, with no comparison to plan.\
"""


def build_weekly_oac_prompt(include_schedule_metrics: bool, sections: "OptionalSections | None" = None) -> str:
    instruction = METRICS_ON if include_schedule_metrics else METRICS_OFF
    prompt = WEEKLY_OAC_SYSTEM_PROMPT.format(metrics_instruction=instruction)
    return prompt + build_optional_sections_block(sections)


MONTHLY_EXECUTIVE_SYSTEM_PROMPT = """You are drafting the schedule section of a monthly \
executive project status report. Audience: senior leadership and ownership who are not in \
weekly meetings and don't track activity-level detail -- they want milestone health and \
overall trajectory.

Using only the data provided in the JSON below, write a single narrative paragraph (not \
bulleted sections) covering milestone status this period. The list of what's completed this \
period gives the specific activities and milestones actually finished between the reporting \
period's start date and the schedule's data date -- name at least the most significant of \
these (favor milestones, and any others that stand out) rather than only giving aggregate \
counts. Do not speculate on causes for date movement beyond what's in the data -- state \
variance as fact, where included per the instruction below.

{metrics_instruction}

State only what the data shows. Do not draw conclusions about priority, risk, or what \
should happen next -- describe the facts and let the reader interpret their significance.

Style: executive register -- confident, plain, no jargon, no hedging language ("it appears," \
"seems to"). Lead with the overall status in one sentence, then specifics. Target 100-150 \
words. This will be read by people who skim, so the first sentence must stand alone as the \
takeaway.

Format every specific date the same way throughout, e.g. "July 15, 2026" -- do not mix \
formats (some spelled out, some as "7/15," some as "Jul. 15"). Only drop to a month-level \
reference (e.g. "August 2026") when deliberately summarizing at that broader granularity -- \
never as a substitute for a specific date given in the data.

Never write a raw field name, JSON key, or any word joined by underscores anywhere in the \
output -- including terms named in these instructions. Every value must be translated into \
plain English words, separated by spaces, not underscores.

Never comment on the structure or completeness of the input data itself -- do not say things \
like "the data doesn't include total float values" or "float wasn't provided." If no \
activities are currently critical, state that as a fact about the schedule ("no activities \
are currently critical this period"), never as a claim that the data is missing something. \
The one authorized exception is noting the absence of a P6 Baseline, per the milestone \
changes rule below.
"""

MONTHLY_METRICS_ON = """\
Name each milestone along with its status and current/target finish date. Cover any \
milestone whose variance is given and nonzero, stating the number of days ahead or behind \
target as a plain fact. Cover overall critical-path status: how many activities are \
currently critical, and name the most-behind activity with how many days of float it \
carries -- if none are currently critical, state plainly that no activities are currently \
critical this period.\
"""

MONTHLY_METRICS_OFF = """\
Do not mention variance, float, "critical path," "driving path," or any other \
scheduling-health terminology anywhere in the narrative, even where present in the data. \
Ignore critical-path status entirely. For each milestone, state only its name, status, and \
current target/finish date -- no comparison to a prior date or plan.\
"""


def build_monthly_executive_prompt(include_schedule_metrics: bool, sections: "OptionalSections | None" = None) -> str:
    instruction = MONTHLY_METRICS_ON if include_schedule_metrics else MONTHLY_METRICS_OFF
    prompt = MONTHLY_EXECUTIVE_SYSTEM_PROMPT.format(metrics_instruction=instruction)
    return prompt + build_optional_sections_block(sections)


@dataclass
class OptionalSections:
    executive_summary: bool = False
    critical_path_narrative: bool = False
    milestone_changes: bool = False  # baseline-only
    near_critical_discussion: bool = False
    major_schedule_risks: bool = False
    procurement_impacts: bool = False
    recovery_opportunities: bool = False
    owner_talking_points: bool = False
    pm_talking_points: bool = False

    def any_enabled(self) -> bool:
        return any(
            (
                self.executive_summary,
                self.critical_path_narrative,
                self.milestone_changes,
                self.near_critical_discussion,
                self.major_schedule_risks,
                self.procurement_impacts,
                self.recovery_opportunities,
                self.owner_talking_points,
                self.pm_talking_points,
            )
        )


_SECTION_INSTRUCTIONS: dict[str, str] = {
    "executive_summary": """\
Add an "Executive Summary" section at the very top of the narrative, before any other \
section: 2-3 sentences giving the overall status in plain terms -- name at least one or two \
specific activities or milestones completed this period (when any are given) rather than \
only citing counts, whether the critical path is holding, and any milestone-level takeaway \
visible in the data. This previews what the rest of the narrative covers; do not introduce \
any fact not also covered elsewhere in the narrative.\
""",
    "critical_path_narrative": """\
Add a "Critical Path Narrative" section with two subsections:

"This Period": cover only the critical activities among what's completed or upcoming this \
period -- which finished, which are underway, which are due to start.

"Remaining Critical Path to Completion": cover the full remaining critical path data given, \
regardless of the report's own date window -- this is the entire chain of not-yet-completed \
critical work still standing between now and project completion, and must never be trimmed \
to only what falls inside the reporting period.

Both subsections must read as connected narrative prose describing what the work is and how \
it flows from one activity to the next -- not a list of float-status facts. Do not state or \
restate float/criticality as its own sentence (e.g. "both activities sit at zero float," "this \
activity has no slack") -- criticality is already established by an activity's presence in this \
section, so spend the prose on the work itself and its sequencing instead.

In "Remaining Critical Path to Completion," each entry's predecessor/successor links are the \
real, driving P6 schedule logic ties (actual relationships from the file, already narrowed to \
the one(s) that actually constrain that activity's date -- not every logic tie in the file) \
-- use these, and only these, to state how activities connect: a "Finish to Start" link means \
the predecessor must finish before the successor starts; "Start to Start" means they start \
together; "Finish to Finish" means they finish together; "Start to Finish" means the \
predecessor's start drives the successor's finish. Phrase each link according to its actual \
type -- do not default to "leads to" or "enables" phrasing for a non-Finish-to-Start link. If \
an activity has no predecessor or successor link given, state only that it is critical and \
when it's due, without implying a connection to any other activity. Never assert that one \
activity's completion triggers, causes, or enables another based on their names, order, or \
timing alone -- only a given predecessor/successor link is a valid basis for a sequencing \
claim.

Focus specifically on critical-path continuity and risk rather than repeating other sections \
verbatim.\
""",
    "milestone_changes": """\
Add a "Milestone Changes" section: for each milestone where a baseline variance figure is \
given and nonzero, state how many days it has moved from its P6 Baseline target and whether \
that's an improvement or slippage. If no milestone has a baseline variance figure given, \
state plainly that no baseline-based milestone comparison is available for this schedule -- \
never describe a non-baseline planned or forecast date as if it were baseline movement.\
""",
    "near_critical_discussion": """\
Add a "Near-Critical Path Discussion" section: describe activities with low but positive \
total float (roughly 1-10 days, not already critical) that could become critical if upstream \
work slips. Base this only on total float values given in the data.\
""",
    "major_schedule_risks": """\
Add a "Major Schedule Risks" section: identify only risk patterns directly visible in the \
provided activity data -- for example, multiple critical or near-critical activities \
converging in the same narrow date window, or a cluster of behind-plan activities in the \
same area. Do not speculate about causes (weather, subcontractor performance, staffing, \
etc.) and do not describe any risk not evidenced by the activity data itself.\
""",
    "procurement_impacts": """\
Add a "Procurement Impacts" section: identify activities whose name or WBS path indicates \
procurement, fabrication, shop drawings, or delivery work (e.g. containing "Procure," "Fab," \
"Deliver," "Submit," "Shop Drawing"), and describe their status and any effect on downstream \
critical-path work visible in the data. If none are present among the filtered activities, \
state that plainly.\
""",
    "recovery_opportunities": """\
Add a "Recovery Opportunities" section: identify only non-critical activities with \
meaningfully higher total float in the same area/WBS as whatever is described in Major \
Schedule Risks, that could plausibly absorb resequencing. State only which activities have \
float available -- do not recommend specific actions (adding crews, changing means and \
methods, expediting, etc.).\
""",
    "owner_talking_points": """\
Add a "Talking Points for the Owner" section: exactly three bullet points, each one sentence, \
written for someone who wants the bottom line -- overall status, the single most \
consequential risk or milestone, and one thing worth asking about. Derive these only from \
data already covered elsewhere in the narrative.\
""",
    "pm_talking_points": """\
Add a "Talking Points for the PM" section: exactly three bullet points, each one sentence, \
written for the project manager driving day-to-day execution -- specific activities or areas \
needing near-term attention. Derive these only from data already covered elsewhere in the \
narrative.\
""",
}


def build_optional_sections_block(sections: "OptionalSections | None") -> str:
    if sections is None or not sections.any_enabled():
        return ""

    enabled = [
        _SECTION_INSTRUCTIONS[name]
        for name in _SECTION_INSTRUCTIONS
        if getattr(sections, name)
    ]
    preamble = (
        "\n\nAdditionally, include the following section(s) in the narrative. The word-count "
        "target given above applies only to the core section(s) described before this point -- "
        "each additional section below should still be concise (roughly the length its own "
        "instruction implies), but do not compress or drop them to fit the original target:\n\n"
    )
    return preamble + "\n\n".join(enabled)
