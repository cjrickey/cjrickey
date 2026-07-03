"""
Wires a filtered activity payload (from filter_engine.py) to a prompt
template (from prompt_templates.py) and calls the Claude API to produce
the final narrative text. This is the only module in the whole pipeline
that makes a non-deterministic call -- everything upstream is pure code.
"""
import json
import os

from prompt_templates import build_weekly_oac_prompt, build_monthly_executive_prompt


def generate_weekly_oac_narrative(filtered_payload: dict, include_schedule_metrics: bool = True) -> str:
    system_prompt = build_weekly_oac_prompt(include_schedule_metrics)
    return _call_claude(system_prompt, filtered_payload)


def generate_monthly_executive_narrative(filtered_payload: dict, include_schedule_metrics: bool = True) -> str:
    system_prompt = build_monthly_executive_prompt(include_schedule_metrics)
    return _call_claude(system_prompt, filtered_payload)


def _call_claude(system_prompt: str, payload: dict) -> str:
    import anthropic  # pip install anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=600,
        system=system_prompt,
        messages=[
            {"role": "user", "content": json.dumps(payload, indent=2)},
        ],
    )
    return message.content[0].text


if __name__ == "__main__":
    with open("weekly_payload.json") as f:
        payload = json.load(f)
    narrative = generate_weekly_oac_narrative(payload, include_schedule_metrics=True)
    print(narrative)
