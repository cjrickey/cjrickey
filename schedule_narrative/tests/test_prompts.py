"""prompt_templates: the guarantees that must hold in the instructions we send
Claude -- never authorize a specific float number, never leak raw field names,
suppress all metrics when asked, include rollup guidance, and assemble every
optional section cleanly. (Output-level checks that need an actual model call
belong in the live smoke test, not here.)"""
import re

from prompt_templates import (
    build_weekly_oac_prompt,
    build_monthly_executive_prompt,
    OptionalSections,
)

ALL_SECTIONS = OptionalSections(
    executive_summary=True,
    critical_path_narrative=True,
    show_relationship_types=True,
    milestone_changes=True,
    near_critical_discussion=True,
    major_schedule_risks=True,
    procurement_impacts=True,
    owner_talking_points=True,
    pm_talking_points=True,
)


def _weekly(metrics=True, sections=None):
    return build_weekly_oac_prompt(metrics, sections)


def _monthly(metrics=True, sections=None):
    return build_monthly_executive_prompt(metrics, sections)


def test_float_number_prohibition_present_weekly():
    p = _weekly(metrics=True)
    assert "never state or imply a specific total float" in p.lower()


def test_float_number_prohibition_present_monthly():
    p = _monthly(metrics=True)
    assert "without citing a specific float" in p.lower()


def test_removed_float_magnitude_examples_absent():
    # These concrete "N days behind" examples were deliberately removed so the
    # model is never shown a float number as an acceptable thing to write.
    for build in (_weekly, _monthly):
        p = build(metrics=True, sections=ALL_SECTIONS)
        assert "roughly 12 days behind" not in p
        assert "how many days of float it carries" not in p


def test_metrics_off_suppresses_terminology_instruction():
    p = _weekly(metrics=False)
    assert "do not mention" in p.lower()
    # and the "metrics on" ordering instruction should not be present
    assert "never state or imply a specific total float" not in p.lower()


def test_rollup_guidance_present():
    # Caps were removed in favor of prompt-level rollup; that guidance must be
    # present so huge schedules summarize instead of enumerating everything.
    p = _weekly(metrics=True, sections=ALL_SECTIONS)
    assert "roll the rest into a plain count" in p


def test_all_optional_sections_assemble():
    p = _weekly(metrics=True, sections=ALL_SECTIONS)
    for heading in (
        "Executive Summary",
        "Critical Path Narrative",
        "Milestone Changes",
        "Near-Critical Path Discussion",
        "Major Schedule Risks",
        "Procurement",
        "Talking Points for the Owner",
        "Talking Points for the PM",
    ):
        assert heading in p, f"missing section: {heading}"


def test_relationship_type_variant_selection():
    with_types = _weekly(metrics=True, sections=OptionalSections(
        critical_path_narrative=True, show_relationship_types=True))
    generic = _weekly(metrics=True, sections=OptionalSections(
        critical_path_narrative=True, show_relationship_types=False))
    # WITH_TYPES tells the model to phrase each link by its actual P6 type;
    # GENERIC forbids naming the type at all. (Both mention the type names --
    # GENERIC only to prohibit them -- so distinguish on the instruction, not
    # on the mere presence of "Finish to Start".)
    assert "Phrase each link according to its actual type" in with_types
    assert "Phrase each link according to its actual type" not in generic
    assert "never name or reveal the formal" in generic.lower()


def test_no_raw_field_names_leak_into_prompts():
    # snake_case tokens (raw JSON keys / Python field names) must never reach
    # the narrative instructions -- they'd risk surfacing in output.
    pattern = re.compile(r"\b[a-z]{2,}_[a-z_]{2,}\b")
    for build in (_weekly, _monthly):
        p = build(metrics=True, sections=ALL_SECTIONS)
        leaks = set(pattern.findall(p))
        assert not leaks, f"raw field-name tokens leaked into prompt: {sorted(leaks)}"
