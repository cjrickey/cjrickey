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
  - `total_float_days` rounds to a whole number of days (not `445.1`) --
    the narrative should never show a decimal
- `filter_engine.py` -- pure, deterministic filtering. No LLM involved.
  - WBS scope matches at any tree depth, with cascading parent-to-child
    selection (matches the checkbox-tree UI behavior)
  - date windows anchor to the schedule's own data date, never system clock
  - max_float_days is an explicit user-set filter, not a hidden default
- `prompt_templates.py` -- weekly OAC + monthly executive system prompts.
  Single `include_schedule_metrics` toggle controls whether variance/float/
  critical-path language appears at all, or the narrative stays pure
  description. `OptionalSections` adds nine independently-toggleable
  bolt-on sections (executive summary, critical path narrative, milestone
  changes, near-critical path discussion, major schedule risks,
  procurement impacts, recovery opportunities, owner talking points, PM
  talking points). `milestone_changes` only produces real content when
  the payload has baseline-derived fields populated -- otherwise the
  instructions tell the model to say so plainly rather than fabricate a
  comparison. `major_schedule_risks`/`recovery_opportunities` stay
  constrained to patterns directly visible in the provided activity data
  (e.g. several critical activities converging in the same date window)
  -- no speculation about causes, no prescriptive advice, matching the
  "state facts, let the reader interpret" rule used everywhere else.
  (A tenth section, float changes, was built and then removed -- too
  confusing in practice, and total_float_days already covers the
  present-day float picture.)
- `narrative_generator.py` -- calls the Claude API (Sonnet) with the
  filtered payload, plus an optional `steer` freeform tone instruction.
  Requires `ANTHROPIC_API_KEY` in the environment -- not included here,
  supply your own.
- `storage.py` -- persistence via SQLAlchemy Core, so the same code runs
  against local SQLite (`sqlite:///schedules.db`, the zero-setup default)
  or production Postgres (set `DATABASE_URL`). Schedules and narrative
  usage counts are scoped per user (`owner_user_id`, the Clerk user id)
  now that this is multi-tenant -- one user can never load another
  user's schedule by guessing a `schedule_id`. Also holds the
  `subscriptions` table (Clerk user id -> Stripe customer/subscription
  id + status). `Activity` round-trips through JSON via `to_dict()` /
  `Activity(**dict)`.
- `clerk_auth.py` -- verifies the Clerk session token the frontend
  attaches as `Authorization: Bearer <token>`, against Clerk's public
  JWKS (fetched once, cached in memory). Returns the Clerk user id (the
  `sub` claim). Requires `CLERK_ISSUER` (found in the Clerk dashboard).
- `billing.py` -- Stripe billing. Plans: a free trial (`TRIAL_NARRATIVE_LIMIT`,
  default 3, narratives with no card required), and Professional at
  $29/month or $290/year (two months free) for unlimited narratives.
  Checkout (`POST /billing/create-checkout-session`, body `{"plan":
  "monthly"|"annual"}`) picks the matching Stripe Price
  (`STRIPE_PRICE_ID_MONTHLY` / `STRIPE_PRICE_ID_ANNUAL`); the Stripe
  Customer Portal handles self-serve cancel/update-card (`POST
  /billing/create-portal-session`); a webhook (`POST /billing/webhook`)
  keeps the `subscriptions` table in sync with Stripe; `GET
  /billing/status` reports subscription status plus trial narratives
  used/remaining for the frontend. `require_narrative_access` is the
  FastAPI dependency that gates narrative generation -- allows an active
  subscriber through, or a user still under the trial limit, and 402s
  otherwise.
- `api.py` -- FastAPI service. `POST /schedules/upload` (multipart XER
  or XML file -- auto-detected by content, not filename extension) and
  `POST /schedules/{id}/narrative` (filter spec -> narrative). The
  upload response includes `has_baseline` so the frontend can tell the
  user upfront whether this file will produce variance narration.
  CORS-enabled for the frontend's origin (`FRONTEND_ORIGIN`, defaults to
  `http://localhost:3000`). Verified end-to-end over real HTTP, including
  a real Claude API call and a real generated narrative.
  - Auth: every request must carry a valid Clerk session token. Uploading
    only requires being signed in (parsing a schedule is free); generating
    a narrative additionally requires an active subscription or remaining
    free-trial narratives (`billing.require_narrative_access`, which
    itself depends on `clerk_auth.require_user`). There's no
    anonymous/shared-secret mode anymore -- this is a paid, multi-tenant
    product.
  - Usage cap: `MAX_NARRATIVES_PER_DAY` additionally bounds narrative
    generations (the Anthropic-API-calling, cost-bearing endpoint) per
    user per UTC day, on top of the trial/subscription gate. Unset means
    unlimited. Returns 429 once hit. Every successful generation is
    recorded regardless of this setting, since the free trial counts
    lifetime narratives against the same table.
- `frontend/` -- Next.js app: upload panel, cascading-checkbox WBS tree,
  filter panel (report type, lookback/lookahead, critical/milestone
  filters, max float, metrics toggle, nine optional-section checkboxes,
  steering note), and a narrative view with a collapsible "underlying
  data" panel for provenance. The baseline-only optional section
  (Milestone changes) is greyed out and labeled "(requires baseline)"
  whenever the uploaded file has no baseline. Verified end-to-end in a
  real browser against the real API.
  - Auth: `@clerk/nextjs` handles sign-in/sign-up (`/sign-in`, `/sign-up`)
    and session management. `src/proxy.ts` (Next.js 16 renamed
    `middleware.ts` to `proxy.ts`) just makes the session available on
    every request -- it doesn't gate access itself, since Clerk now
    recommends resource-based checks over route-matcher middleware.
    `SubscriptionGate` (wraps the main page) only redirects signed-out
    users to `/sign-in`; billing/trial status is exposed via
    `BillingContext` instead of a hard redirect, so a user who's used up
    their free trial can still browse the app -- generating a narrative
    is what's blocked, with an inline prompt to subscribe. This is a UX
    convenience only -- the backend never trusts it and re-checks
    everything itself.
  - `/pricing` -- monthly ($29) vs. annual ($290, two months free) plan
    picker; "Subscribe" creates a Stripe Checkout session for the chosen
    plan and redirects there. A "Manage billing" link in the main app
    (shown once subscribed) opens the Stripe Customer Portal (cancel,
    update card, view invoices) via a generated portal session.

## Accounts you'll need

- **Anthropic** (already required) -- API key for narrative generation.
- **Clerk** (clerk.com) -- free tier is enough to start. Create an
  application, grab the publishable + secret keys, and the Frontend API
  URL (this is `CLERK_ISSUER`).
- **Stripe** (stripe.com) -- create a "Professional" Product with two
  recurring Prices: $29/month and $290/year; note both Price ids
  (`price_...`). Use test-mode keys until you're ready to charge real
  cards.
- **Render** (render.com) -- hosts the FastAPI backend + a managed
  Postgres database. `render.yaml` at the repo root defines both as a
  Blueprint.
- **Vercel** (vercel.com) -- hosts the Next.js frontend. Point the
  project's Root Directory at `schedule_narrative/frontend`.

## Pricing model

- **Free**: 3 narratives, no credit card required.
- **Professional**: $29/month, or $290/year (two months free vs. paying
  monthly) -- unlimited narratives. Cancel any time via the Stripe
  Customer Portal.

## Environment variables

Backend (Render, or a local `.env`/exported shell vars):

| Variable | Required | Notes |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | yes | Claude API key |
| `CLERK_ISSUER` | yes | Clerk dashboard -> your app -> API Keys -> "Frontend API URL" |
| `STRIPE_SECRET_KEY` | yes | Stripe dashboard -> Developers -> API keys |
| `STRIPE_PRICE_ID_MONTHLY` | yes | the `price_...` id for the $29/month Price |
| `STRIPE_PRICE_ID_ANNUAL` | yes | the `price_...` id for the $290/year Price |
| `STRIPE_WEBHOOK_SECRET` | yes | from the Stripe webhook endpoint you create (see below) |
| `FRONTEND_ORIGIN` | yes | your deployed frontend URL, e.g. `https://schedule-narrative.vercel.app` (defaults to `http://localhost:3000`) |
| `DATABASE_URL` | production only | Render sets this automatically via the Blueprint; local dev falls back to SQLite (`schedules.db`) if unset |
| `TRIAL_NARRATIVE_LIMIT` | no | free narratives before requiring a subscription; default 3 |
| `MAX_NARRATIVES_PER_DAY` | no | per-user daily generation cap; unset = unlimited |

Frontend (Vercel, or `frontend/.env.local`):

| Variable | Required | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | yes | Clerk dashboard -> API Keys |
| `CLERK_SECRET_KEY` | yes | Clerk dashboard -> API Keys |
| `NEXT_PUBLIC_API_BASE_URL` | yes | your deployed backend URL, e.g. `https://schedule-narrative-api.onrender.com` (defaults to `http://localhost:8000`) |

## Running locally

Backend:

```
cd schedule_narrative
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
export CLERK_ISSUER=https://your-app.clerk.accounts.dev
export STRIPE_SECRET_KEY=sk_test_...
export STRIPE_PRICE_ID_MONTHLY=price_...
export STRIPE_PRICE_ID_ANNUAL=price_...
export STRIPE_WEBHOOK_SECRET=whsec_...   # from `stripe listen`, see below
uvicorn api:app --reload
```

For local Stripe webhook testing, install the [Stripe CLI](https://stripe.com/docs/stripe-cli) and run `stripe listen --forward-to localhost:8000/billing/webhook` in a separate terminal -- it prints a `whsec_...` value to use above.

Frontend:

```
cd schedule_narrative/frontend
npm install
echo "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_..." >> .env.local
echo "CLERK_SECRET_KEY=sk_test_..." >> .env.local
npm run dev
```

Then open `http://localhost:3000`. You'll be redirected to sign in, then straight to the tool -- no card needed for the first 3 narratives. Upload a `.xer` or `.xml` file and generate a narrative -- only a `.xml` export with the Project Baseline included will show variance vs. baseline; the app tells you which case you're in right after upload. After 3 narratives, generating is blocked with a prompt to visit `/pricing` and subscribe (use a [Stripe test card](https://stripe.com/docs/testing), e.g. `4242 4242 4242 4242`).

## Deploying to production

1. **Clerk**: create a production instance (separate from your dev instance), get its publishable/secret keys and Frontend API URL.
2. **Stripe**: switch to live-mode keys and create the live-mode Professional Product with its $29/month and $290/year Prices (test-mode and live-mode Products/Prices are separate).
3. **Render**: connect this repo, deploy via the `render.yaml` Blueprint (New -> Blueprint). Set the secret env vars listed above in the dashboard (they're marked `sync: false` in `render.yaml` so they're never committed).
4. **Vercel**: import this repo, set the Root Directory to `schedule_narrative/frontend`, set the frontend env vars above.
5. Set `FRONTEND_ORIGIN` on Render to your live Vercel URL, and `NEXT_PUBLIC_API_BASE_URL` on Vercel to your live Render URL.
6. **Stripe webhook**: in the Stripe dashboard, add an endpoint pointing to `https://<your-render-url>/billing/webhook`, subscribed to `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, and `invoice.payment_failed`. Copy its signing secret into `STRIPE_WEBHOOK_SECRET` on Render.
7. Redeploy both services after setting env vars, then run through the signup -> checkout -> upload -> generate flow once end-to-end with a real test card before switching Stripe to live mode.
