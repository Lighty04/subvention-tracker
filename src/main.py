from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request as FastAPIRequest
from sqlalchemy.orm import Session
from typing import Optional, List
import os
import secrets
import hashlib
import asyncio

from sqlalchemy import or_

from .models import init_db, get_db, Subvention, User, WatchedAssociation, ImportLog, RiskLevel, Alert, AlertConfig
from .schemas import (
    SubventionResponse, SubventionList, WatchedAssocCreate, WatchedAssocResponse,
    UserRegister, UserLogin, UserResponse, AlertConfigCreate, AlertResponse, ImportStatus
)
from .scraper import import_recent_subventions
from .seeds import seed_watched_associations

app = FastAPI(title="Subvention Tracker", version="0.1.0")

# Create tables on startup (disabled for testing)
# @app.on_event("startup")
# async def startup():
#     init_db()
#     seed_watched_associations(db)

templates = Jinja2Templates(directory="src/templates")

def get_current_user(db: Session = Depends(get_db), api_key: Optional[str] = Query(None)) -> Optional[User]:
    if not api_key:
        return None
    return db.query(User).filter(User.api_key == api_key).first()

def require_user(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="API key required")
    return user

@app.get("/api/subventions", response_model=SubventionList)
def list_subventions(
    risk: Optional[RiskLevel] = None,
    year: Optional[int] = None,
    search: Optional[str] = None,
    min_amount: Optional[int] = None,
    max_amount: Optional[int] = None,
    direction: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    query = db.query(Subvention)
    if risk:
        query = query.filter(Subvention.risk_level == risk)
    if year:
        query = query.filter(Subvention.annee_budgetaire == year)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Subvention.nom_beneficiaire.ilike(like),
                Subvention.objet_dossier.ilike(like)
            )
        )
    if min_amount is not None:
        query = query.filter(Subvention.montant_vote >= min_amount)
    if max_amount is not None:
        query = query.filter(Subvention.montant_vote <= max_amount)
    if direction:
        query = query.filter(Subvention.direction.ilike(f"%{direction}%"))
    
    total = query.count()
    items = query.order_by(Subvention.annee_budgetaire.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": items}

@app.get("/api/subventions/{subvention_id}", response_model=SubventionResponse)
def get_subvention(subvention_id: int, db: Session = Depends(get_db)):
    sub = db.query(Subvention).get(subvention_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Not found")
    return sub

@app.get("/api/search")
def search_subventions(
    q: str = Query(..., min_length=2),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    like = f"%{q}%"
    query = db.query(Subvention).filter(
        Subvention.nom_beneficiaire.ilike(like) |
        Subvention.objet_dossier.ilike(like) |
        Subvention.numero_siret.ilike(like) |
        Subvention.numero_dossier.ilike(like)
    )
    total = query.count()
    items = query.order_by(Subvention.annee_budgetaire.desc()).limit(limit).all()
    return {"total": total, "items": items}

async def _run_import(max_records: int):
    from .models import SessionLocal
    db = SessionLocal()
    try:
        await import_recent_subventions(db, max_records)
    finally:
        db.close()

@app.post("/api/import")
def trigger_import(
    background_tasks: BackgroundTasks,
    max_records: int = Query(100, le=5000),
    user: User = Depends(require_user)
):
    background_tasks.add_task(_run_import, max_records)
    return {"status": "started", "max_records": max_records}

@app.get("/api/import/status", response_model=ImportStatus)
def import_status(db: Session = Depends(get_db)):
    log = db.query(ImportLog).order_by(ImportLog.started_at.desc()).first()
    if not log:
        return {"status": "no imports yet", "records_imported": 0, "records_updated": 0, "started_at": None, "finished_at": None}
    return log

@app.get("/api/watched", response_model=List[WatchedAssocResponse])
def list_watched(db: Session = Depends(get_db)):
    return db.query(WatchedAssociation).filter_by(active=True).all()

@app.post("/api/watched", response_model=WatchedAssocResponse)
def add_watched(assoc: WatchedAssocCreate, db: Session = Depends(get_db)):
    a = WatchedAssociation(
        nom=assoc.nom,
        numero_siret=assoc.numero_siret,
        reason=assoc.reason,
        risk_level=RiskLevel(assoc.risk_level) if assoc.risk_level else RiskLevel.HIGH
    )
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

# Auth (bcrypt direct, no passlib)
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def generate_api_key() -> str:
    return secrets.token_urlsafe(32)

@app.post("/api/register", response_model=UserResponse)
def register(user: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    u = User(
        email=user.email,
        password_hash=hash_password(user.password),
        api_key=generate_api_key()
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u

@app.post("/api/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.email == user.email).first()
    if not u or not verify_password(user.password, u.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"email": u.email, "api_key": u.api_key, "is_premium": u.is_premium}

@app.get("/api/me", response_model=UserResponse)
def me(user: User = Depends(require_user)):
    return user

# Alerts
@app.get("/api/alerts", response_model=List[AlertResponse])
def list_alerts(
    status: Optional[str] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    query = db.query(Alert).filter(Alert.user_id == user.id)
    if status:
        query = query.filter(Alert.status == status)
    return query.order_by(Alert.sent_at.desc()).limit(100).all()

@app.post("/api/alerts/config")
def set_alert_config(
    config: AlertConfigCreate,
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    existing = db.query(AlertConfig).filter(AlertConfig.user_id == user.id).first()
    if existing:
        existing.email = config.email
        existing.webhook_url = config.webhook_url
        existing.enabled = config.enabled
        db.commit()
        return existing
    
    cfg = AlertConfig(
        user_id=user.id,
        email=config.email,
        webhook_url=config.webhook_url,
        enabled=config.enabled
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg

# Dashboard
@app.get("/")
def dashboard(request: FastAPIRequest, db: Session = Depends(get_db)):
    recent = db.query(Subvention).order_by(Subvention.date_import.desc()).limit(20).all()
    high_risk = db.query(Subvention).filter(Subvention.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL])).count()
    total = db.query(Subvention).count()
    critical = db.query(Subvention).filter(Subvention.risk_level == RiskLevel.CRITICAL).count()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "recent": recent,
        "high_risk": high_risk,
        "critical": critical,
        "total": total
    })

# Static files
if os.path.exists("src/static"):
    app.mount("/static", StaticFiles(directory="src/static"), name="static")
