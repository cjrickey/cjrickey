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
    # Sonnet 5 runs adaptive thinking by default -- even though we never
    # pass a `thinking` param -- and that reasoning eats into max_tokens
    # before a single word of visible text is written. On a large schedule
    # with several bolt-on sections enabled (e.g. the full remaining
    # critical path chain, which must cover every not-yet-completed
    # critical activity to project completion, not just a windowed few),
    # 16384 total tokens could be entirely consumed by thinking, leaving
    # zero text blocks. Sized well above realistic worst-case need instead;
    # max_tokens this large requires streaming (the SDK refuses a
    # non-streaming request it estimates could run past ~10 minutes).
    with client.messages.stream(
        model="claude-sonnet-5",
        max_tokens=64000,
        system=system_prompt,
        messages=[
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
    ) as stream:
        message = stream.get_final_message()

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
