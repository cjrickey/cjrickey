# Schedule Narrative Generator

Turns a P6 XER schedule export into a filtered, narrative status report
(weekly OAC or monthly executive), grounded strictly in the schedule's
own data -- no invented facts, no cross-schedule diffing in v1.

## Status

Built and validated against two real XER exports (a 5,440-activity
messy schedule and a 348-activity clean one). Every module below has
been run against real data, not just synthetic samples.

## Files

- `xer_parser.py` -- generic XER table parser (tab-delimited %T/%F/%R format)
- `activity_extractor.py` -- turns parsed tables into a flat, corrected
  activity list. Handles real P6 quirks found during testing:
  - completed tasks collapse early_start/early_end to the data date --
    uses target_start/target_end instead for those
  - driving_path_flag can be stale/unreliable -- is_critical is computed
    fresh from total_float_days <= 0
  - milestones are detected via task_type (TT_Mile/TT_FinMile), not a
    date heuristic
  - filters out external linked projects that share the same XER file
    (proj_id scoping)
- `filter_engine.py` -- pure, deterministic filtering. No LLM involved.
  - WBS scope matches at any tree depth, with cascading parent-to-child
    selection (matches the checkbox-tree UI behavior)
  - date windows anchor to the schedule's own data date, never system clock
  - max_float_days is an explicit user-set filter, not a hidden default
- `prompt_templates.py` -- weekly OAC + monthly executive system prompts.
  Single `include_schedule_metrics` toggle controls whether variance/float/
  critical-path language appears at all, or the narrative stays pure
  description.
- `narrative_generator.py` -- calls the Claude API (Sonnet) with the
  filtered payload. Requires `ANTHROPIC_API_KEY` in the environment --
  not included here, supply your own.
- `api.py` -- FastAPI service. `POST /schedules/upload` (multipart XER
  file) and `POST /schedules/{id}/narrative` (filter spec -> narrative).
  Tested end-to-end over real HTTP against a real file; upload path is
  fully verified, narrative path is verified up to the LLM call itself
  (needs your API key to go further).

## Not yet built

- Frontend (Next.js + the WBS tree / filter panel UI designs)
- Persistent storage (currently an in-memory dict keyed by schedule_id --
  fine for local dev, not for anything real)
- Auth, billing, usage caps

## Running locally

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
uvicorn api:app --reload
```

Then `POST /schedules/upload` with a `.xer` file, take the returned
`schedule_id`, and `POST /schedules/{schedule_id}/narrative` with a
filter spec to get a narrative back.
