"""
Wires a filtered activity payload (from filter_engine.py) to a prompt
template (from prompt_templates.py) and calls the Claude API to produce
the final narrative text. This is the only module in the whole pipeline
that makes a non-deterministic call -- everything upstream is pure code.
"""
import json
import os

from prompt_templates import build_weekly_oac_prompt, build_monthly_executive_prompt, OptionalSections


def generate_weekly_oac_narrative(
    filtered_payload: dict,
    include_schedule_metrics: bool = True,
    steer: str | None = None,
    sections: OptionalSections | None = None,
) -> str:
    system_prompt = build_weekly_oac_prompt(include_schedule_metrics, sections)
    if steer:
        system_prompt += f"\n\nAdditional guidance from the requester, to apply without contradicting the rules above: {steer}"
    return _call_claude(system_prompt, filtered_payload)


def generate_monthly_executive_narrative(
    filtered_payload: dict,
    include_schedule_metrics: bool = True,
    steer: str | None = None,
    sections: OptionalSections | None = None,
) -> str:
    system_prompt = build_monthly_executive_prompt(include_schedule_metrics, sections)
    if steer:
        system_prompt += f"\n\nAdditional guidance from the requester, to apply without contradicting the rules above: {steer}"
    return _call_claude(system_prompt, filtered_payload)


def _call_claude(system_prompt: str, payload: dict) -> str:
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-5",
        # Sonnet 5's adaptive thinking spends part of this budget reasoning
        # before it writes anything -- on larger schedules (more activities
        # to weigh, more area groups to rank by severity) it can exhaust the
        # budget entirely while thinking, leaving zero text blocks. Real
        # production schedules can carry 100+ activities in a single window,
        # well past what 4096 leaves room for on top of thinking.
        max_tokens=16384,
        system=system_prompt,
        messages=[
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
    )
    # content[0] isn't reliably the text block -- a ThinkingBlock can precede
    # it -- so pull out the text block(s) by type instead of assuming position.
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text.strip():
        raise ValueError(f"Claude returned no text (stop_reason={message.stop_reason!r})")
    return text


if __name__ == "__main__":
    with open("weekly_payload.json") as f:
        payload = json.load(f)
    narrative = generate_weekly_oac_narrative(payload, include_schedule_metrics=True)
    print(narrative)
