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
"""

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


def build_weekly_oac_prompt(include_schedule_metrics: bool) -> str:
    instruction = METRICS_ON if include_schedule_metrics else METRICS_OFF
    return WEEKLY_OAC_SYSTEM_PROMPT.format(metrics_instruction=instruction)


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


def build_monthly_executive_prompt(include_schedule_metrics: bool) -> str:
    instruction = MONTHLY_METRICS_ON if include_schedule_metrics else MONTHLY_METRICS_OFF
    return MONTHLY_EXECUTIVE_SYSTEM_PROMPT.format(metrics_instruction=instruction)
