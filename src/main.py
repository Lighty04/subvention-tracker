from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request as FastAPIRequest
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional, List
import os
import secrets
import asyncio

from .models import init_db, get_db, Subvention, User, WatchedAssociation, ImportLog, RiskLevel, Alert, AlertConfig
from .schemas import (
    SubventionResponse, SubventionList, WatchedAssocCreate, WatchedAssocResponse,
    UserRegister, UserLogin, UserResponse, AlertConfigCreate, AlertResponse, ImportStatus
)
from .scraper import import_recent_subventions
from .seeds import seed_watched_associations
from .reports import (
    export_subventions_csv, export_subventions_pdf, get_daily_summary,
    get_sector_analysis, get_association_trends, get_newsletter_preview
)

app = FastAPI(title="Subvention Tracker", version="0.2.0")

# Auth
import bcrypt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def generate_api_key() -> str:
    return secrets.token_urlsafe(32)

def get_current_user(db: Session = Depends(get_db), api_key: Optional[str] = Query(None)) -> Optional[User]:
    if not api_key:
        return None
    return db.query(User).filter(User.api_key == api_key).first()

def require_user(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="API key required")
    return user

# Templates
templates = Jinja2Templates(directory="src/templates")

# ====================================================================
# CORE API
# ====================================================================

@app.get("/api/subventions", response_model=SubventionList)
def list_subventions(
    risk: Optional[RiskLevel] = None,
    year: Optional[int] = None,
    search: Optional[str] = None,
    min_amount: Optional[int] = None,
    max_amount: Optional[int] = None,
    direction: Optional[str] = None,
    limit: int = Query(50, le=500),
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
        query = query.filter(or_(Subvention.nom_beneficiaire.ilike(like), Subvention.objet_dossier.ilike(like)))
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
def search_subventions(q: str = Query(..., min_length=2), limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    like = f"%{q}%"
    query = db.query(Subvention).filter(
        Subvention.nom_beneficiaire.ilike(like) | Subvention.objet_dossier.ilike(like) |
        Subvention.numero_siret.ilike(like) | Subvention.numero_dossier.ilike(like)
    )
    total = query.count()
    items = query.order_by(Subvention.annee_budgetaire.desc()).limit(limit).all()
    return {"total": total, "items": items}

# ====================================================================
# IMPORT
# ====================================================================

async def _run_import(max_records: int):
    from .models import SessionLocal
    db = SessionLocal()
    try:
        await import_recent_subventions(db, max_records)
    finally:
        db.close()

@app.post("/api/import")
def trigger_import(background_tasks: BackgroundTasks, max_records: int = Query(100, le=5000), user: User = Depends(require_user)):
    background_tasks.add_task(_run_import, max_records)
    return {"status": "started", "max_records": max_records}

@app.get("/api/import/status", response_model=ImportStatus)
def import_status(db: Session = Depends(get_db)):
    log = db.query(ImportLog).order_by(ImportLog.started_at.desc()).first()
    if not log:
        return {"status": "no imports yet", "records_imported": 0, "records_updated": 0, "started_at": None, "finished_at": None}
    return log

# ====================================================================
# WATCHED ASSOCIATIONS
# ====================================================================

@app.get("/api/watched", response_model=List[WatchedAssocResponse])
def list_watched(db: Session = Depends(get_db)):
    return db.query(WatchedAssociation).filter_by(active=True).all()

@app.post("/api/watched", response_model=WatchedAssocResponse)
def add_watched(assoc: WatchedAssocCreate, db: Session = Depends(get_db)):
    a = WatchedAssociation(
        nom=assoc.nom, numero_siret=assoc.numero_siret,
        reason=assoc.reason, risk_level=RiskLevel(assoc.risk_level) if assoc.risk_level else RiskLevel.HIGH
    )
    db.add(a); db.commit(); db.refresh(a)
    return a

@app.delete("/api/watched/{watched_id}")
def remove_watched(watched_id: int, db: Session = Depends(get_db)):
    a = db.query(WatchedAssociation).get(watched_id)
    if not a: raise HTTPException(status_code=404, detail="Not found")
    a.active = False; db.commit()
    return {"deleted": True}

# ====================================================================
# AUTH
# ====================================================================

@app.post("/api/register", response_model=UserResponse)
def register(user: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing: raise HTTPException(status_code=400, detail="Email already registered")
    u = User(email=user.email, password_hash=hash_password(user.password), api_key=generate_api_key())
    db.add(u); db.commit(); db.refresh(u)
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

# ====================================================================
# ALERTS
# ====================================================================

@app.get("/api/alerts", response_model=List[AlertResponse])
def list_alerts(status: Optional[str] = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    query = db.query(Alert).filter(Alert.user_id == user.id)
    if status: query = query.filter(Alert.status == status)
    return query.order_by(Alert.sent_at.desc()).limit(100).all()

@app.post("/api/alerts/config")
def set_alert_config(config: AlertConfigCreate, user: User = Depends(require_user), db: Session = Depends(get_db)):
    existing = db.query(AlertConfig).filter(AlertConfig.user_id == user.id).first()
    if existing:
        existing.email = config.email; existing.webhook_url = config.webhook_url; existing.enabled = config.enabled
        db.commit(); return existing
    cfg = AlertConfig(user_id=user.id, email=config.email, webhook_url=config.webhook_url, enabled=config.enabled)
    db.add(cfg); db.commit(); db.refresh(cfg)
    return cfg

# ====================================================================
# MONETIZATION: DAILY DASHBOARD
# ====================================================================

@app.get("/daily")
def daily_dashboard(request: FastAPIRequest, db: Session = Depends(get_db)):
    summary = get_daily_summary(db)
    return templates.TemplateResponse("daily.html", {
        "request": request,
        "new_subventions": summary["new_subventions"],
        "top_conflicts": summary["top_conflicts"],
        "trending": summary["trending"],
        "alert_summary": summary["alert_summary"]
    })

@app.get("/api/daily")
def daily_data(db: Session = Depends(get_db)):
    return get_daily_summary(db)

# ====================================================================
# MONETIZATION: EXPORT
# ====================================================================

@app.get("/api/subventions/export")
def export_subventions(
    format: str = Query("csv", regex="^(csv|pdf)$"),
    risk: Optional[RiskLevel] = None,
    year: Optional[int] = None,
    search: Optional[str] = None,
    min_amount: Optional[int] = None,
    max_amount: Optional[int] = None,
    direction: Optional[str] = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db)
):
    """Export subventions as CSV or PDF."""
    query = db.query(Subvention)
    if risk: query = query.filter(Subvention.risk_level == risk)
    if year: query = query.filter(Subvention.annee_budgetaire == year)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Subvention.nom_beneficiaire.ilike(like), Subvention.objet_dossier.ilike(like)))
    if min_amount: query = query.filter(Subvention.montant_vote >= min_amount)
    if max_amount: query = query.filter(Subvention.montant_vote <= max_amount)
    if direction: query = query.filter(Subvention.direction.ilike(f"%{direction}%"))
    
    items = query.order_by(Subvention.annee_budgetaire.desc()).limit(limit).all()
    
    if format == "csv":
        content = export_subventions_csv(db, items)
        return PlainTextResponse(content=content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=subventions.csv"})
    else:
        content = export_subventions_pdf(db, items)
        return HTMLResponse(content=content)

# ====================================================================
# MONETIZATION: EMBED WIDGET
# ====================================================================

@app.get("/embed/association/{siret}")
def embed_association(siret: str, db: Session = Depends(get_db)):
    """Minimal embeddable widget for associations."""
    subventions = db.query(Subvention).filter(Subvention.numero_siret == siret).order_by(Subvention.annee_budgetaire.desc()).all()
    if not subventions:
        return HTMLResponse(content="<p style='font-family:sans-serif'>No data found</p>")
    
    total = sum(s.montant_vote or 0 for s in subventions)
    latest = subventions[0]
    
    html = f"""
    <div style="font-family:system-ui,sans-serif;padding:15px;border:1px solid #ddd;border-radius:8px;max-width:400px;">
        <h3 style="margin:0 0 10px">{latest.nom_beneficiaire or 'Association'}</h3>
        <p><strong>SIRET:</strong> {siret}</p>
        <p><strong>Total received:</strong> €{total:,}</p>
        <p><strong>Subventions:</strong> {len(subventions)}</p>
        <p><strong>Latest:</strong> €{latest.montant_vote or 0} ({latest.annee_budgetaire or 'N/A'})</p>
        <p><strong>Risk:</strong> <span style="color:{'red' if latest.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL] else 'green'}">{latest.risk_level.value.upper()}</span></p>
        <a href="http://192.168.0.16:8002/api/subventions?search={siret}" target="_blank" style="color:#1976d2">View full profile →</a>
    </div>
    """
    return HTMLResponse(content=html)

# ====================================================================
# MONETIZATION: ANALYTICS
# ====================================================================

@app.get("/api/analytics/sectors")
def sector_analysis(db: Session = Depends(get_db)):
    return get_sector_analysis(db)

@app.get("/api/associations/{siret}/trends")
def association_trends(siret: str, db: Session = Depends(get_db)):
    return get_association_trends(db, siret=siret)

# ====================================================================
# MONETIZATION: NEWSLETTER
# ====================================================================

@app.get("/api/newsletter/preview")
def newsletter_preview(db: Session = Depends(get_db)):
    return get_newsletter_preview(db)

# ====================================================================
# DASHBOARD
# ====================================================================

@app.get("/")
def dashboard(request: FastAPIRequest, db: Session = Depends(get_db)):
    recent = db.query(Subvention).order_by(Subvention.date_import.desc()).limit(20).all()
    high_risk = db.query(Subvention).filter(Subvention.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL])).count()
    total = db.query(Subvention).count()
    critical = db.query(Subvention).filter(Subvention.risk_level == RiskLevel.CRITICAL).count()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "recent": recent,
        "high_risk": high_risk, "critical": critical, "total": total
    })

# Static files
if os.path.exists("src/static"):
    app.mount("/static", StaticFiles(directory="src/static"), name="static")
