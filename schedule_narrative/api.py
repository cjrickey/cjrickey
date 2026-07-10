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
    kind = _sniff_file_kind(contents)
    if kind == "unknown":
        raise HTTPException(400, "Only P6 XER or XML exports are supported")

    tmp_path = f"/tmp/{uuid.uuid4()}.{kind}"
    with open(tmp_path, "wb") as f:
        f.write(contents)

    try:
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
    finally:
        os.remove(tmp_path)

    schedule_id = str(uuid.uuid4())
    storage.save_schedule(schedule_id, user_id, data_date, activities, wbs_tree)

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
        generate = lambda: generate_weekly_oac_narrative(payload, req.include_schedule_metrics, req.steer, sections)

    elif req.report_type == "monthly_executive":
        payload = build_monthly_executive_payload(
            activities, data_date, req.wbs_node_names, req.lookback_days, req.lookahead_days
        )
        generate = lambda: generate_monthly_executive_narrative(payload, req.include_schedule_metrics, req.steer, sections)

    else:
        raise HTTPException(400, f"Unknown report_type: {req.report_type}")

    try:
        narrative = generate()
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
