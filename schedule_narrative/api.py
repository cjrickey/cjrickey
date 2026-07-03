"""
FastAPI service exposing the schedule narrative pipeline.

Endpoints:
  POST /schedules/upload   -- upload an XER, get back data date + WBS tree + activity count
  POST /schedules/{id}/narrative -- given a filter spec, return the generated narrative

The uploaded XER is parsed once and persisted to SQLite (storage.py) so
schedules survive a backend restart. See storage.py for the schema.

Auth is a single shared bearer token (API_AUTH_TOKEN) rather than
per-user accounts -- this is a single-operator tool, not a multi-tenant
product, so there's no user model to authenticate against. If
API_AUTH_TOKEN isn't set, auth is skipped entirely (plain localhost dev).
Usage caps are a daily narrative-generation limit (MAX_NARRATIVES_PER_DAY)
to bound Anthropic API spend; unset means unlimited.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from xer_parser import parse_xer
from activity_extractor import extract_activities, pick_primary_proj_id, get_data_date
from filter_engine import FilterSpec, apply_filters, build_monthly_executive_payload
from narrative_generator import generate_weekly_oac_narrative, generate_monthly_executive_narrative
import storage

app = FastAPI(title="Schedule Narrative API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

API_AUTH_TOKEN = os.environ.get("API_AUTH_TOKEN")
_max_narratives_env = os.environ.get("MAX_NARRATIVES_PER_DAY")
MAX_NARRATIVES_PER_DAY = int(_max_narratives_env) if _max_narratives_env else None


def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    if API_AUTH_TOKEN is None:
        return
    if authorization != f"Bearer {API_AUTH_TOKEN}":
        raise HTTPException(401, "Missing or invalid API token")


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


@app.post("/schedules/upload", dependencies=[Depends(require_auth)])
async def upload_schedule(file: UploadFile):
    if not file.filename.lower().endswith(".xer"):
        raise HTTPException(400, "Only .xer files are supported")

    contents = await file.read()
    tmp_path = f"/tmp/{uuid.uuid4()}.xer"
    with open(tmp_path, "wb") as f:
        f.write(contents)

    try:
        xer = parse_xer(tmp_path)
        proj_id = pick_primary_proj_id(xer)
        data_date = get_data_date(xer, proj_id)
        activities = extract_activities(xer, proj_id)
        wbs_tree = _build_wbs_tree(xer, proj_id)
    finally:
        os.remove(tmp_path)

    schedule_id = str(uuid.uuid4())
    storage.save_schedule(schedule_id, data_date, activities, wbs_tree)

    return {
        "schedule_id": schedule_id,
        "data_date": data_date.strftime("%Y-%m-%d"),
        "activity_count": len(activities),
        "wbs_tree": wbs_tree,
    }


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


@app.post("/schedules/{schedule_id}/narrative", dependencies=[Depends(require_auth)])
async def generate_narrative(schedule_id: str, req: NarrativeRequest):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if MAX_NARRATIVES_PER_DAY is not None and storage.get_usage_count(today) >= MAX_NARRATIVES_PER_DAY:
        raise HTTPException(429, f"Daily narrative generation limit of {MAX_NARRATIVES_PER_DAY} reached")

    cached = storage.load_schedule(schedule_id)
    if not cached:
        raise HTTPException(404, "Schedule not found -- upload it again")

    activities = cached["activities"]
    data_date = cached["data_date"]

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
        generate = lambda: generate_weekly_oac_narrative(payload, req.include_schedule_metrics, req.steer)

    elif req.report_type == "monthly_executive":
        payload = build_monthly_executive_payload(activities, data_date, req.wbs_node_names)
        generate = lambda: generate_monthly_executive_narrative(payload, req.include_schedule_metrics, req.steer)

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
        raise HTTPException(502, f"Narrative generation failed: {exc}") from exc

    if MAX_NARRATIVES_PER_DAY is not None:
        storage.increment_usage(today)

    return {
        "narrative": narrative,
        "filtered_payload": payload,  # returned so the frontend can show "here's the underlying data" per the trust/provenance design
    }
