from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from nivvi.api.schemas import AnalyticsEventRequest, WaitlistRequest, WaitlistResponse
from nivvi.services.audit_service import AuditService
from nivvi.services.waitlist_service import WaitlistService
from nivvi.storage.in_memory import InMemoryStore
from nivvi.storage.relational_persistence import RelationalPersistence
from nivvi.storage.snapshot_persistence import SnapshotPersistence


STORE = InMemoryStore()
persistence = SnapshotPersistence()
persistence.load_into(STORE)
relational_persistence = RelationalPersistence()
relational_persistence.load_into(STORE)
audit_service = AuditService(STORE, relational_persistence=relational_persistence)
waitlist_service = WaitlistService(STORE, audit_service)


app = FastAPI(
    title="Nivvi Marketing",
    version="0.1.0",
    description="Landing, waitlist, and public marketing ingestion endpoints.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def persistence_snapshot_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 500:
        persistence.save(STORE)
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "marketing"}


@app.post("/v1/waitlist", response_model=WaitlistResponse)
def create_waitlist_lead(payload: WaitlistRequest) -> WaitlistResponse:
    try:
        result = waitlist_service.upsert_lead(
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=payload.email,
            phone_number=payload.phone_number,
            marketing_consent=payload.marketing_consent,
            source=payload.source,
            utm=payload.utm,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return WaitlistResponse(
        id=result.lead.id,
        status="created" if result.created else "already_exists",
        created_at=result.lead.created_at,
    )


@app.post("/v1/analytics/events")
def ingest_analytics_event(payload: AnalyticsEventRequest) -> dict:
    audit_service.log(
        household_id="system",
        event_type=f"analytics.{payload.event_name}",
        entity_id=payload.page,
        details={"page": payload.page, "properties": payload.properties or {}},
    )
    return {"status": "ok"}


def _require_admin_key(request: Request) -> None:
    expected_key = os.getenv("NIVVI_ADMIN_KEY", "").strip()
    if not expected_key:
        raise HTTPException(status_code=503, detail="Admin key is not configured")

    provided_key = request.headers.get("x-admin-key", "").strip()
    if not provided_key or provided_key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _serialize_waitlist_lead(lead) -> dict:
    full_name = " ".join(part for part in [lead.first_name, lead.last_name] if part).strip()
    return {
        "id": lead.id,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "full_name": full_name,
        "email": lead.email,
        "phone_number": lead.phone_number,
        "marketing_consent": lead.marketing_consent,
        "source": lead.source,
        "utm": lead.utm,
        "created_at": lead.created_at.isoformat(),
    }


@app.get("/v1/admin/waitlist/leads")
def list_waitlist_leads(
    request: Request,
    limit: int = Query(default=200, ge=1, le=5000),
    source: str | None = Query(default=None, max_length=64),
) -> dict:
    _require_admin_key(request)

    leads = sorted(
        STORE.waitlist_leads.values(),
        key=lambda item: item.created_at,
        reverse=True,
    )
    if source:
        leads = [lead for lead in leads if lead.source == source]

    rows = [_serialize_waitlist_lead(lead) for lead in leads[:limit]]
    return {"total_count": len(leads), "returned_count": len(rows), "items": rows}


@app.get("/v1/admin/waitlist/leads.csv")
def export_waitlist_leads_csv(
    request: Request,
    source: str | None = Query(default=None, max_length=64),
) -> Response:
    _require_admin_key(request)

    leads = sorted(
        STORE.waitlist_leads.values(),
        key=lambda item: item.created_at,
        reverse=True,
    )
    if source:
        leads = [lead for lead in leads if lead.source == source]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone_number",
            "marketing_consent",
            "source",
            "utm_json",
            "created_at",
        ]
    )
    for lead in leads:
        full_name = " ".join(part for part in [lead.first_name, lead.last_name] if part).strip()
        writer.writerow(
            [
                lead.id,
                lead.first_name,
                lead.last_name or "",
                full_name,
                lead.email,
                lead.phone_number or "",
                "true" if lead.marketing_consent else "false",
                lead.source or "",
                json.dumps(lead.utm, separators=(",", ":"), sort_keys=True),
                lead.created_at.isoformat(),
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nivvi-waitlist-leads.csv"'},
    )


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", response_model=None)
def root():
    landing = WEB_DIR / "landing.html"
    if landing.exists():
        return FileResponse(landing)
    return JSONResponse(status_code=404, content={"detail": "Landing page not found"})


@app.get("/waitlist", response_model=None)
def waitlist_page():
    page = WEB_DIR / "waitlist.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse(status_code=404, content={"detail": "Waitlist page not found"})


@app.get("/waitlist/success", response_model=None)
def waitlist_success_page():
    page = WEB_DIR / "waitlist-success.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse(status_code=404, content={"detail": "Waitlist success page not found"})


@app.get("/legal/privacy", response_model=None)
def privacy_page():
    page = WEB_DIR / "privacy.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse(status_code=404, content={"detail": "Privacy policy page not found"})


@app.get("/legal/terms", response_model=None)
def terms_page():
    page = WEB_DIR / "terms.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse(status_code=404, content={"detail": "Terms page not found"})


@app.get("/robots.txt", response_model=None)
def robots() -> PlainTextResponse | JSONResponse:
    page = WEB_DIR / "robots.txt"
    if page.exists():
        return FileResponse(page, media_type="text/plain; charset=utf-8")
    return JSONResponse(status_code=404, content={"detail": "robots.txt not found"})


@app.get("/sitemap.xml", response_model=None)
def sitemap() -> PlainTextResponse | JSONResponse:
    page = WEB_DIR / "sitemap.xml"
    if page.exists():
        return FileResponse(page, media_type="application/xml; charset=utf-8")
    return JSONResponse(status_code=404, content={"detail": "sitemap.xml not found"})
