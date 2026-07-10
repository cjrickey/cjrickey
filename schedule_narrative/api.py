"""
FastAPI service exposing the schedule narrative pipeline.

Endpoints:
  POST /schedules/upload   -- upload an XER, get back data date + WBS tree + activity count
  POST /schedules/{id}/narrative -- given a filter spec, return the generated narrative

The uploaded XER is parsed once and persisted (storage.py, SQLite locally
/ Postgres in production) so schedules survive a backend restart. See
storage.py for the schema.

Auth is per-user: the frontend signs users in via Clerk and attaches
their session token as a bearer token; clerk_auth.require_user verifies
it and returns the Clerk user id, which scopes every schedule and usage
row. Uploading only requires being signed in (it's free); generating a
narrative additionally requires either an active Stripe subscription or
remaining free-trial narratives (billing.require_narrative_access) --
this is a paid product, not a single-operator tool with a shared secret
anymore.

Usage caps are a daily per-user narrative-generation limit
(MAX_NARRATIVES_PER_DAY) to bound Anthropic API spend on top of the
trial/subscription gate; unset means unlimited.
"""
import os
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, UploadFile, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from xer_parser import parse_xer
from xml_parser import parse_p6_xml, pick_primary_project, find_matching_baseline
from activity_extractor import (
    extract_activities,
    pick_primary_proj_id,
    get_data_date,
    extract_activities_from_xml,
    get_data_date_xml,
)
from filter_engine import FilterSpec, apply_filters, build_monthly_executive_payload
from narrative_generator import generate_weekly_oac_narrative, generate_monthly_executive_narrative
from prompt_templates import OptionalSections
from clerk_auth import require_user
from billing import require_narrative_access, router as billing_router
import storage

app = FastAPI(title="Schedule Narrative API")

_frontend_origins = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    # Comma-separated so apex and www variants (which browsers treat as
    # distinct origins) can both be listed without picking one to break.
    allow_origins=[origin.strip() for origin in _frontend_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(billing_router)

_max_narratives_env = os.environ.get("MAX_NARRATIVES_PER_DAY")
MAX_NARRATIVES_PER_DAY = int(_max_narratives_env) if _max_narratives_env else None

# Generous safety ceiling, well above real-world schedules (up to ~40k
# activities) -- exists to fail cleanly on a pathological/corrupted file
# rather than let parsing balloon unboundedly.
MAX_ACTIVITIES_PER_SCHEDULE = int(os.environ.get("MAX_ACTIVITIES_PER_SCHEDULE", "150000"))

# A real P6 export can be much larger than its activity count alone
# suggests -- resource assignments, UDFs, activity codes, and notes this
# app never reads can bloat a file to 50+ MB for a couple thousand
# activities. This is a safety net against a truly extreme file
# exhausting the instance's memory (see the Render OOM incident this was
# added for), set comfortably above real observed exports, not a
# business limit -- upgrading the Render instance's memory tier is the
# durable fix if this ever needs to be legitimately raised.
MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024

# Critical/near-critical path data is meant to read as a paragraph or two
# of connected prose per path (see prompt_templates.py), not an
# enumeration -- but a real project's critical path from start to finish
# can easily run past 40 activities, so the cap needs real headroom above
# that, not a pure "short chain" assumption. critical_paths is NOT
# windowed by date (deliberately, so it always covers the full remaining
# chain to completion) -- only WBS scope shrinks it, so the message below
# must say that, not "narrow the date range," which wouldn't do anything
# for this one.
MAX_PATH_NARRATIVE_ACTIVITIES = int(os.environ.get("MAX_PATH_NARRATIVE_ACTIVITIES", "100"))

# The main report body groups activities by area and can reasonably
# summarize a few hundred -- still much less than a "monster" schedule's
# full activity count, since both date range and WBS scope narrow this.
MAX_REPORT_ACTIVITIES = int(os.environ.get("MAX_REPORT_ACTIVITIES", "500"))


def _check_payload_size(payload: dict, report_type: str) -> None:
    critical_path_activities = sum(len(p["activities"]) for p in payload.get("critical_paths", []))
    path_lists = {
        "critical path": critical_path_activities,
        "near-critical": len(payload.get("near_critical_activities", [])),
        "critical": len(payload.get("critical_activities", [])),
    }
    for label, count in path_lists.items():
        if count > MAX_PATH_NARRATIVE_ACTIVITIES:
            raise HTTPException(
                400,
                f"This schedule has {count} {label} activities in scope -- too many to "
                f"narrate as a short critical-path narrative (limit {MAX_PATH_NARRATIVE_ACTIVITIES}). "
                "Narrow the WBS scope to a smaller area of the project and try again.",
            )

    if report_type == "weekly_oac":
        total = len(payload.get("completed_activities", [])) + len(payload.get("upcoming_activities", []))
    else:
        total = (
            len(payload.get("completed_this_period", []))
            + len(payload.get("starting_this_period", []))
            + len(payload.get("milestones", []))
        )
    if total > MAX_REPORT_ACTIVITIES:
        raise HTTPException(
            400,
            f"This report would cover {total} activities, too many to narrate well "
            f"(limit {MAX_REPORT_ACTIVITIES}). Narrow the date range and/or WBS scope and try again.",
        )


def _build_wbs_tree(xer, proj_id: str) -> list[dict]:
    """Nested tree structure the frontend WBS selector consumes directly."""
    nodes = {r["wbs_id"]: r for r in xer.get("PROJWBS") if r.get("proj_id") == proj_id}
    children_map: dict[str, list[str]] = {}
    for wbs_id, node in nodes.items():
        parent = node.get("parent_wbs_id")
        children_map.setdefault(parent, []).append(wbs_id)

    def build(wbs_id: str) -> dict:
        node = nodes[wbs_id]
        child_ids = sorted(
            children_map.get(wbs_id, []),
            key=lambda x: nodes[x].get("seq_num", "0"),
        )
        result = {"name": node.get("wbs_name") or node.get("wbs_short_name") or ""}
        if child_ids:
            result["children"] = [build(cid) for cid in child_ids]
        return result

    roots = [wid for wid, n in nodes.items() if n.get("parent_wbs_id") not in nodes]
    return [build(r) for r in roots]


def _build_wbs_tree_xml(project) -> list[dict]:
    """Same nested shape as _build_wbs_tree, from a P6 XML <Project>'s WBS children."""
    nodes = {wbs.findtext("ObjectId"): wbs for wbs in project.findall("WBS")}
    children_map: dict[str, list[str]] = {}
    for object_id, node in nodes.items():
        parent = node.findtext("ParentObjectId")
        children_map.setdefault(parent, []).append(object_id)

    def build(object_id: str) -> dict:
        node = nodes[object_id]
        child_ids = sorted(
            children_map.get(object_id, []),
            key=lambda x: nodes[x].findtext("SequenceNumber") or "0",
        )
        result = {"name": node.findtext("Name") or ""}
        if child_ids:
            result["children"] = [build(cid) for cid in child_ids]
        return result

    roots = [oid for oid, n in nodes.items() if n.findtext("ParentObjectId") not in nodes]
    return [build(r) for r in roots]


def _sniff_file_kind(contents: bytes) -> str:
    """XER and P6 XML have no reliable file extension convention users
    actually follow, so detect from content instead of trusting the
    filename: XER always starts with the ERMHDR line; XML starts with an
    XML declaration or the root element, allowing for a UTF-8 BOM."""
    head = contents.lstrip(b"\xef\xbb\xbf")[:200].lstrip()
    if head.startswith(b"ERMHDR"):
        return "xer"
    if head.startswith(b"<?xml") or head.startswith(b"<APIBusinessObjects"):
        return "xml"
    return "unknown"


@app.post("/schedules/upload")
async def upload_schedule(file: UploadFile, user_id: str = Depends(require_user)):
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            400,
            f"This file is {len(contents) / 1024 / 1024:.0f} MB, above the "
            f"{MAX_UPLOAD_SIZE_BYTES // 1024 // 1024} MB we currently support. P6 exports carry a lot "
            "of data this app never reads (resource assignments, UDFs, activity codes, notes) -- "
            "re-exporting with those options unchecked usually shrinks the file a lot without "
            "losing anything this app uses.",
        )

    kind = _sniff_file_kind(contents)
    if kind == "unknown":
        raise HTTPException(400, "Only P6 XER or XML exports are supported")

    tmp_path = f"/tmp/{uuid.uuid4()}.{kind}"
    with open(tmp_path, "wb") as f:
        f.write(contents)
    # Free the in-memory copy now that it's on disk -- parsing reads from
    # tmp_path, not this variable, and there's no reason to hold both the
    # raw bytes and the parsed structure in memory at once.
    del contents

    def _parse():
        if kind == "xer":
            xer = parse_xer(tmp_path)
            proj_id = pick_primary_proj_id(xer)
            data_date = get_data_date(xer, proj_id)
            activities = extract_activities(xer, proj_id)
            wbs_tree = _build_wbs_tree(xer, proj_id)
            has_baseline = False
        else:
            xml_file = parse_p6_xml(tmp_path)
            project = pick_primary_project(xml_file.root)
            has_baseline = find_matching_baseline(xml_file.root, project.findtext("ObjectId")) is not None
            data_date = get_data_date_xml(project)
            activities = extract_activities_from_xml(xml_file.root)
            wbs_tree = _build_wbs_tree_xml(project)
        return data_date, activities, wbs_tree, has_baseline

    try:
        try:
            # A large schedule (tens of thousands of activities) can take a
            # few real seconds to parse -- run_in_threadpool keeps that off
            # the event loop, same reasoning as narrative generation below.
            data_date, activities, wbs_tree, has_baseline = await run_in_threadpool(_parse)
        except Exception as exc:
            # A malformed/corrupted export, a truncated upload, or a file
            # from an unsupported tool that happened to sniff as XER/XML --
            # must never surface as a raw 500/traceback. One clean, honest
            # reason instead, whatever actually went wrong.
            raise HTTPException(400, f"Couldn't read this file as a P6 export: {exc}") from exc
    finally:
        os.remove(tmp_path)

    if data_date is None:
        raise HTTPException(
            400,
            "Couldn't determine this schedule's data date -- the export may be missing "
            "required project information.",
        )
    if not activities:
        raise HTTPException(
            400,
            "No activities were found in this file. It may be from a tool this app doesn't "
            "support yet (only P6 XER and XML exports are read), or the project may be empty.",
        )
    if len(activities) > MAX_ACTIVITIES_PER_SCHEDULE:
        raise HTTPException(
            400,
            f"This schedule has {len(activities)} activities, above the "
            f"{MAX_ACTIVITIES_PER_SCHEDULE} we currently support in one upload. Contact us if "
            "you need this raised.",
        )

    schedule_id = str(uuid.uuid4())
    # Also threadpooled -- JSON-serializing tens of thousands of activities
    # plus the DB write is real, measurable synchronous work too.
    await run_in_threadpool(storage.save_schedule, schedule_id, user_id, data_date, activities, wbs_tree)

    return {
        "schedule_id": schedule_id,
        "data_date": data_date.strftime("%Y-%m-%d"),
        "activity_count": len(activities),
        "wbs_tree": wbs_tree,
        # XER never carries baseline data; XML does only if a matching
        # BaselineProject was included at export time. The frontend uses
        # this to tell the user upfront whether variance/narration against
        # a real P6 Baseline will be available for this upload.
        "has_baseline": has_baseline,
    }


class NarrativeSections(BaseModel):
    """Bolt-on report sections, each independently toggleable. See
    prompt_templates.OptionalSections for what each one does;
    milestone_changes requires a P6 Baseline."""
    executive_summary: bool = False
    critical_path_narrative: bool = False
    show_relationship_types: bool = True  # only meaningful when critical_path_narrative is on
    milestone_changes: bool = False
    near_critical_discussion: bool = False
    major_schedule_risks: bool = False
    procurement_impacts: bool = False
    owner_talking_points: bool = False
    pm_talking_points: bool = False


class NarrativeRequest(BaseModel):
    report_type: str  # "weekly_oac" | "monthly_executive"
    lookback_days: int = 7
    lookahead_days: int = 7
    wbs_node_names: Optional[list[str]] = None
    critical_only: bool = False
    milestones_only: bool = False
    max_float_days: Optional[float] = None
    include_schedule_metrics: bool = True
    steer: Optional[str] = None  # optional freeform tone instruction, narrative only
    sections: NarrativeSections = NarrativeSections()


@app.post("/schedules/{schedule_id}/narrative")
async def generate_narrative(
    schedule_id: str, req: NarrativeRequest, user_id: str = Depends(require_narrative_access)
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if MAX_NARRATIVES_PER_DAY is not None and storage.get_usage_count(user_id, today) >= MAX_NARRATIVES_PER_DAY:
        raise HTTPException(429, f"Daily narrative generation limit of {MAX_NARRATIVES_PER_DAY} reached")

    cached = storage.load_schedule(schedule_id, user_id)
    if not cached:
        raise HTTPException(404, "Schedule not found -- upload it again")

    activities = cached["activities"]
    data_date = cached["data_date"]
    sections = OptionalSections(**req.sections.model_dump())

    if req.report_type == "weekly_oac":
        spec = FilterSpec(
            report_type="weekly_oac",
            lookback_days=req.lookback_days,
            lookahead_days=req.lookahead_days,
            wbs_node_names=req.wbs_node_names,
            critical_only=req.critical_only,
            milestones_only=req.milestones_only,
            max_float_days=req.max_float_days,
        )
        payload = apply_filters(activities, data_date, spec)
        _check_payload_size(payload, "weekly_oac")
        generate = lambda: generate_weekly_oac_narrative(payload, req.include_schedule_metrics, req.steer, sections)

    elif req.report_type == "monthly_executive":
        payload = build_monthly_executive_payload(
            activities, data_date, req.wbs_node_names, req.lookback_days, req.lookahead_days
        )
        _check_payload_size(payload, "monthly_executive")
        generate = lambda: generate_monthly_executive_narrative(payload, req.include_schedule_metrics, req.steer, sections)

    else:
        raise HTTPException(400, f"Unknown report_type: {req.report_type}")

    try:
        # generate() makes a blocking, several-minutes-possible Anthropic
        # call (see narrative_generator._call_claude). This endpoint is
        # async def, and Render runs a single Uvicorn worker (no --workers
        # flag) -- calling generate() directly would block that worker's
        # entire event loop for the whole generation, freezing the backend
        # for every other request (including Render's own health check)
        # until it finished. run_in_threadpool hands it to a worker thread
        # instead, so the event loop stays free to serve everyone else.
        narrative = await run_in_threadpool(generate)
    except KeyError:
        # Unhandled exceptions bypass CORSMiddleware in Starlette's default
        # middleware stack, so the browser reports an opaque CORS failure
        # instead of the real error -- raise HTTPException instead so
        # ExceptionMiddleware (inside CORSMiddleware) handles it properly.
        raise HTTPException(500, "Server is missing ANTHROPIC_API_KEY")
    except Exception as exc:
        if "credit balance is too low" in str(exc):
            # Our Anthropic account is out of credit, not something the user
            # did -- don't expose our billing plumbing to a paying customer,
            # and don't burn one of their trial narratives on it (nothing was
            # generated, so we never reach storage.increment_usage below).
            raise HTTPException(
                503,
                "Narrative generation is temporarily unavailable on our end -- "
                "this isn't something you did. Please try again in a few minutes.",
            ) from exc
        raise HTTPException(502, f"Narrative generation failed: {exc}") from exc

    # Always tracked (not just when MAX_NARRATIVES_PER_DAY is set) -- the
    # free trial counts lifetime narratives against this same table via
    # storage.get_total_narrative_count().
    storage.increment_usage(user_id, today)

    return {
        "narrative": narrative,
        "filtered_payload": payload,  # returned so the frontend can show "here's the underlying data" per the trust/provenance design
    }
