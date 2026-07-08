# Schedule Narrative Generator

Turns a P6 schedule export (XER or XML) into a filtered, narrative
status report (weekly OAC or monthly executive), grounded strictly in
the schedule's own data -- no invented facts.

Variance ("X days ahead/behind plan") is only ever computed against a
true P6 Baseline -- the one set via Project > Maintain/Assign Baselines
-- never against a schedule's own current Planned Dates, which drift
over time and aren't a frozen comparison point. XER cannot carry
baseline data at all (P6 only exports baselines via XML), so **XER
uploads never produce variance**, only critical-path status. XML
uploads produce variance only if the export included the assigned
baseline as an embedded `<BaselineProject>`; the app tells you which
case you're in immediately after upload.

## Status

Built and validated against two real XER exports (a 5,440-activity
messy schedule and a 348-activity clean one). Every module below has
been run against real data, not just synthetic samples.

## Files

- `xer_parser.py` -- generic XER table parser (tab-delimited %T/%F/%R format)
- `xml_parser.py` -- parser for P6 XML exports (the `APIBusinessObjects`
  schema). Strips the P6-version-specific XML namespace so it works
  across client versions. Finds the primary `<Project>` (most `Activity`
  children, excluding `<Project external="true">` cross-project
  relationship stubs) and, if present, the matching `<BaselineProject>`
  -- linked back via `OriginalProjectObjectId` -- regardless of which
  P6 baseline "slot" (Project Baseline vs. a named user baseline) it
  occupies; whichever baseline was actually embedded at export time is
  the one used.
- `activity_extractor.py` -- turns parsed tables/XML into a flat,
  corrected activity list. Handles real P6 quirks found during testing:
  - completed tasks collapse early_start/early_end to the data date --
    uses target_start/target_end (XER) or Planned Dates (XML) instead
    for those
  - driving_path_flag can be stale/unreliable -- is_critical is computed
    fresh from total_float_days <= 0 (from `total_float_hr_cnt` in XER;
    derived from `LateStartDate - EarlyStartDate` in XML, since total
    float isn't always its own field in an XML export)
  - milestones are detected via task_type/Type (XER: TT_Mile/TT_FinMile;
    XML: "Start Milestone"/"Finish Milestone"), not a date heuristic
  - filters out external linked projects that share the same file
    (proj_id scoping for XER; the `external="true"` stub check for XML)
  - XML dates are normalized from ISO-8601 to XER's "YYYY-MM-DD HH:MM"
    string convention on extraction, so the rest of the pipeline
    (filter_engine.py, variance math) stays format-agnostic
  - baseline join is by activity `Id` (task code), never `ObjectId` --
    P6 assigns a new ObjectId to every activity in a baseline copy, so
    only the code is a stable key across the live/baseline pair
  - an activity present in the live schedule but missing from the
    baseline (scope added since baselining), or vice versa, gets
    `target_finish: null` and thus `variance_days: null` -- no invented
    numbers for unmatched scope
  - `baseline_total_float_days` / `float_change_days` (current float
    minus baseline float, both derived from Early/Late dates the same
    way) are computed the same baseline-join way, for the Float Changes
    section
- `filter_engine.py` -- pure, deterministic filtering. No LLM involved.
  - WBS scope matches at any tree depth, with cascading parent-to-child
    selection (matches the checkbox-tree UI behavior)
  - date windows anchor to the schedule's own data date, never system clock
  - max_float_days is an explicit user-set filter, not a hidden default
- `prompt_templates.py` -- weekly OAC + monthly executive system prompts.
  Single `include_schedule_metrics` toggle controls whether variance/float/
  critical-path language appears at all, or the narrative stays pure
  description. `OptionalSections` adds ten independently-toggleable
  bolt-on sections (executive summary, critical path narrative, milestone
  changes, float changes, near-critical path discussion, major schedule
  risks, procurement impacts, recovery opportunities, owner talking
  points, PM talking points). `milestone_changes`/`float_changes` only
  produce real content when the payload has baseline-derived fields
  populated -- otherwise the instructions tell the model to say so \
  plainly rather than fabricate a comparison. `major_schedule_risks`/
  `recovery_opportunities` stay constrained to patterns directly visible
  in the provided activity data (e.g. several critical activities
  converging in the same date window) -- no speculation about causes,
  no prescriptive advice, matching the "state facts, let the reader
  interpret" rule used everywhere else.
- `narrative_generator.py` -- calls the Claude API (Sonnet) with the
  filtered payload, plus an optional `steer` freeform tone instruction.
  Requires `ANTHROPIC_API_KEY` in the environment -- not included here,
  supply your own.
- `storage.py` -- SQLite-backed persistence for parsed schedules
  (`schedules.db` by default, override with `SCHEDULE_DB_PATH`), so an
  uploaded schedule survives a backend restart. `Activity` round-trips
  through JSON via `to_dict()` / `Activity(**dict)`.
- `api.py` -- FastAPI service. `POST /schedules/upload` (multipart XER
  or XML file -- auto-detected by content, not filename extension) and
  `POST /schedules/{id}/narrative` (filter spec -> narrative). The
  upload response includes `has_baseline` so the frontend can tell the
  user upfront whether this file will produce variance narration.
  CORS-enabled for the frontend's origin (`FRONTEND_ORIGIN`, defaults to
  `http://localhost:3000`). Verified end-to-end over real HTTP, including
  a real Claude API call and a real generated narrative.
  - Auth: a single shared bearer token (`API_AUTH_TOKEN`), checked on
    both endpoints. Unset means no auth (plain localhost dev). There's
    no per-user account model since this is a single-operator tool, not
    a multi-tenant product -- if that changes, this needs real accounts,
    not a bigger shared secret.
  - Usage cap: `MAX_NARRATIVES_PER_DAY` bounds narrative generations
    (the Anthropic-API-calling, cost-bearing endpoint) per UTC day,
    tracked in SQLite. Unset means unlimited. Returns 429 once hit.
- `frontend/` -- Next.js app: upload panel, cascading-checkbox WBS tree,
  filter panel (report type, lookback/lookahead, critical/milestone
  filters, max float, metrics toggle, ten optional-section checkboxes,
  steering note), and a narrative view with a collapsible "underlying
  data" panel for provenance. The two baseline-only optional sections
  (Milestone changes, Float changes) are greyed out and labeled
  "(requires baseline)" whenever the uploaded file has no baseline.
  Verified end-to-end in a real browser against the real API. Set
  `NEXT_PUBLIC_API_TOKEN` to match the backend's `API_AUTH_TOKEN` if set.

## Not yet built

- **Billing.** Deliberately not implemented: there's no pricing model,
  payment processor, or plan tiers decided anywhere in this project, and
  building a Stripe integration against invented numbers would just be
  scaffolding to rip out later. What's here (bearer-token auth + a daily
  generation cap) covers the actual near-term risk -- an exposed backend
  burning your Anthropic API budget -- without presuming this is a
  billed multi-tenant product yet.

## Running locally

Backend:

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
# optional:
# export API_AUTH_TOKEN=some-shared-secret
# export MAX_NARRATIVES_PER_DAY=50
uvicorn api:app --reload
```

Frontend:

```
cd frontend
npm install
# if API_AUTH_TOKEN is set on the backend:
# echo "NEXT_PUBLIC_API_TOKEN=some-shared-secret" >> .env.local
npm run dev
```

Then open `http://localhost:3000`, upload a `.xer` or `.xml` file, and generate a narrative. Only a `.xml` export with the Project Baseline included will show variance vs. baseline -- the app tells you which case you're in right after upload.
