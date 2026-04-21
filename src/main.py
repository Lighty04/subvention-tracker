from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlalchemy.orm import Session
from typing import Optional, List
import os
import asyncio

from .models import init_db, get_db, Subvention, User, WatchedAssociation, ImportLog, RiskLevel
from .scraper import import_recent_subventions

app = FastAPI(title="Subvention Tracker", version="0.1.0")

# Create tables on startup
@app.on_event("startup")
async def startup():
    init_db()

# HTML + HTMX frontend
templates = Jinja2Templates(directory="src/templates")

# API endpoints
@app.get("/api/subventions")
def list_subventions(
    risk: Optional[RiskLevel] = None,
    year: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    query = db.query(Subvention)
    if risk:
        query = query.filter(Subvention.risk_level == risk)
    if year:
        query = query.filter(Subvention.annee_budgetaire == year)
    if search:
        query = query.filter(Subvention.nom_beneficiaire.ilike(f"%{search}%"))
    
    total = query.count()
    items = query.order_by(Subvention.annee_budgetaire.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [s.__dict__ for s in items]}

@app.get("/api/subventions/{subvention_id}")
def get_subvention(subvention_id: int, db: Session = Depends(get_db)):
    sub = db.query(Subvention).get(subvention_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    return sub.__dict__

@app.post("/api/import")
def trigger_import(background_tasks: BackgroundTasks, max_records: int = 100, db: Session = Depends(get_db)):
    background_tasks.add_task(lambda: asyncio.run(import_recent_subventions(db, max_records)))
    return {"status": "started", "max_records": max_records}

@app.get("/api/import/status")
def import_status(db: Session = Depends(get_db)):
    log = db.query(ImportLog).order_by(ImportLog.started_at.desc()).first()
    if not log:
        return {"status": "no imports yet"}
    return {
        "status": log.status,
        "records_imported": log.records_imported,
        "records_updated": log.records_updated,
        "started_at": log.started_at,
        "finished_at": log.finished_at
    }

@app.get("/api/watched")
def list_watched(db: Session = Depends(get_db)):
    return db.query(WatchedAssociation).all()

@app.post("/api/watched")
def add_watched(assoc: dict, db: Session = Depends(get_db)):
    a = WatchedAssociation(**assoc)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a

@app.delete("/api/watched/{watched_id}")
def remove_watched(watched_id: int, db: Session = Depends(get_db)):
    a = db.query(WatchedAssociation).get(watched_id)
    if not a:
        raise HTTPException(status_code=404, detail="Not found")
    a.active = False
    db.commit()
    return {"deleted": True}

# Dashboard (HTMX)
@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    recent = db.query(Subvention).order_by(Subvention.date_import.desc()).limit(20).all()
    high_risk = db.query(Subvention).filter(Subvention.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL])).count()
    total = db.query(Subvention).count()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "recent": recent,
        "high_risk": high_risk,
        "total": total
    })

# Static files
if os.path.exists("src/static"):
    app.mount("/static", StaticFiles(directory="src/static"), name="static")
