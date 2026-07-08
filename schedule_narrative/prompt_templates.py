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
independently toggleable. Two of them (milestone_changes, float_changes)
only produce real output when the payload has baseline-derived fields
(variance_days / float_change_days) populated -- i.e. a true P6 Baseline
was in the uploaded file. Without one, the instructions tell the model
to say so plainly rather than fabricate a comparison. The two more
interpretive sections (major_schedule_risks, recovery_opportunities) are
still constrained to patterns directly visible in the provided data --
no speculation about causes, no prescriptive advice -- matching the
"state facts, let the reader interpret" rule used everywhere else.
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
"""

METRICS_ON = """\
Within "Upcoming Next Period," order the area groups themselves by severity -- the area \
containing the most-negative total_float_days value goes first, and so on down to areas \
with only positive-float, non-critical work. Within each area group, mention the most \
behind-schedule activity in that area first, before less urgent items in the same area.

Critical path activities (is_critical: true) must be called out explicitly. When \
total_float_days is negative, do not simply say "critical" -- state plainly that the \
activity is running behind the schedule's driving path by roughly that many days. Negative \
float is a materially different signal than zero float ("exactly critical, no slack") and \
the two must not be described the same way.

Note variance only when variance_days is present and nonzero for a completed activity -- \
state it as a plain fact (e.g. "finished 6 days behind plan"). Do not invent a reason for \
the variance.\
"""

METRICS_OFF = """\
Do not mention variance_days, total_float_days, "critical path," "driving path," or any \
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
bulleted sections) covering milestone status this period. Do not speculate on causes for \
date movement beyond what's in the data -- state variance as fact, where included per the \
instruction below.

{metrics_instruction}

State only what the data shows. Do not draw conclusions about priority, risk, or what \
should happen next -- describe the facts and let the reader interpret their significance.

Style: executive register -- confident, plain, no jargon, no hedging language ("it appears," \
"seems to"). Lead with the overall status in one sentence, then specifics. Target 100-150 \
words. This will be read by people who skim, so the first sentence must stand alone as the \
takeaway.
"""

MONTHLY_METRICS_ON = """\
Cover any milestone whose variance_days is nonzero, stating the number of days ahead or \
behind target as a plain fact. Cover the critical_path_summary: how many activities are \
currently critical, and name the most-behind activity with its float_days value.\
"""

MONTHLY_METRICS_OFF = """\
Do not mention variance_days, float_days, "critical path," "driving path," or any other \
scheduling-health terminology anywhere in the narrative, even where present in the data. \
Ignore the critical_path_summary section of the JSON entirely. For each milestone, state \
only its name, status, and current target/finish date -- no comparison to a prior date or \
plan.\
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
    float_changes: bool = False  # baseline-only
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
                self.float_changes,
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
section: 2-3 sentences giving the overall status in plain terms -- how much is complete vs. \
upcoming, whether the critical path is holding, and any milestone-level takeaway visible in \
the data. This previews what the rest of the narrative covers; do not introduce any fact not \
also covered elsewhere in the narrative.\
""",
    "critical_path_narrative": """\
Add a "Critical Path Narrative" section: describe which activities are currently on the \
critical path (is_critical: true), their float status, and how they sequence in the near \
term. Focus specifically on critical-path continuity and risk rather than repeating other \
sections verbatim.\
""",
    "milestone_changes": """\
Add a "Milestone Changes" section: for each milestone (is_milestone: true) where \
variance_days is present and nonzero, state how many days it has moved from its P6 Baseline \
target and whether that's an improvement or slippage. If no milestone in the payload has \
variance_days present, state plainly that no baseline-based milestone comparison is \
available for this schedule -- never describe a non-baseline planned or forecast date as if \
it were baseline movement.\
""",
    "float_changes": """\
Add a "Float Changes" section: for activities where float_change_days is present, describe \
which activities have gained or lost float relative to the P6 Baseline and by roughly how \
many days. If no activity in the payload has float_change_days present, state plainly that \
baseline float comparison is not available for this schedule.\
""",
    "near_critical_discussion": """\
Add a "Near-Critical Path Discussion" section: describe activities with low but positive \
total_float_days (roughly 1-10 days, not already critical) that could become critical if \
upstream work slips. Base this only on total_float_days values present in the data.\
""",
    "major_schedule_risks": """\
Add a "Major Schedule Risks" section: identify only risk patterns directly visible in the \
provided activity data -- for example, multiple critical or near-critical activities \
converging in the same narrow date window, or a cluster of behind-plan activities in the \
same area. Do not speculate about causes (weather, subcontractor performance, staffing, \
etc.) and do not describe any risk not evidenced by the activity data itself.\
""",
    "procurement_impacts": """\
Add a "Procurement Impacts" section: identify activities whose name or wbs_path indicates \
procurement, fabrication, shop drawings, or delivery work (e.g. containing "Procure," "Fab," \
"Deliver," "Submit," "Shop Drawing"), and describe their status and any effect on downstream \
critical-path work visible in the data. If none are present among the filtered activities, \
state that plainly.\
""",
    "recovery_opportunities": """\
Add a "Recovery Opportunities" section: identify only non-critical activities with \
meaningfully higher total_float_days in the same area/WBS as whatever is described in Major \
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
