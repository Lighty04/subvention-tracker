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
from .enrichment import enrich_association, enrich_all_associations, find_elected_officials, calculate_person_risk_score

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

async def _run_import(max_records: int, use_csv: bool = False):
    from .models import SessionLocal
    db = SessionLocal()
    try:
        await import_recent_subventions(db, max_records, use_csv=use_csv)
    finally:
        db.close()

@app.post("/api/import")
def trigger_import(
    background_tasks: BackgroundTasks,
    max_records: int = Query(100, le=500000),
    csv: bool = Query(False),
    user: User = Depends(require_user)
):
    background_tasks.add_task(_run_import, max_records, use_csv=csv)
    return {"status": "started", "max_records": max_records, "mode": "csv" if csv else "api"}

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
# MONETIZATION: PERSON / ASSOCIATION PROFILES
# ====================================================================

@app.get("/api/persons/search")
def search_persons(q: str = Query(..., min_length=2), db: Session = Depends(get_db)):
    """Search persons by name."""
    from .models import Person
    like = f"%{q}%"
    persons = db.query(Person).filter(Person.nom.ilike(like)).order_by(Person.total_controlled.desc()).limit(20).all()
    return {
        "total": len(persons),
        "items": [{
            "id": p.id,
            "nom": p.nom,
            "is_elected_official": p.is_elected_official,
            "elected_role": p.elected_role,
            "total_controlled": p.total_controlled,
            "association_count": len(p.roles) if p.roles else 0,
            "risk_score": min(100, int((p.total_controlled or 0) / 50000))
        } for p in persons]
    }

@app.get("/api/persons/{person_id}")
def get_person_profile(person_id: int, db: Session = Depends(get_db)):
    """Get detailed profile for a person."""
    from .models import Person
    person = db.query(Person).get(person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    
    # Calculate risk score
    risk_data = calculate_person_risk_score(db, person_id)
    
    return {
        "id": person.id,
        "nom": person.nom,
        "is_elected_official": person.is_elected_official,
        "elected_role": person.elected_role,
        "total_controlled": person.total_controlled,
        "roles": person.roles,
        "risk_score": risk_data.get("risk_score", 0),
        "created_at": person.created_at.isoformat() if person.created_at else None
    }

@app.get("/api/associations/search")
def search_associations(q: str = Query(..., min_length=2), db: Session = Depends(get_db)):
    """Search associations by name or SIRET."""
    from .models import AssociationProfile
    like = f"%{q}%"
    profiles = db.query(AssociationProfile).filter(
        or_(AssociationProfile.nom.ilike(like), AssociationProfile.numero_siret.ilike(like))
    ).order_by(AssociationProfile.total_subventions_received.desc()).limit(20).all()
    
    # Also search in raw subventions for SIRET matches
    if not profiles:
        subs = db.query(Subvention).filter(Subvention.nom_beneficiaire.ilike(like)).limit(20).all()
        return {
            "total": len(subs),
            "items": [{
                "nom": s.nom_beneficiaire,
                "siret": s.numero_siret,
                "total_received": s.montant_vote,
                "subvention_count": 1,
                "risk_level": s.risk_level.value
            } for s in subs]
        }
    
    return {
        "total": len(profiles),
        "items": [{
            "id": p.id,
            "nom": p.nom,
            "siret": p.numero_siret,
            "total_received": p.total_subventions_received,
            "subvention_count": p.subvention_count,
            "board_members": p.board_members,
            "risk_level": p.risk_level.value if p.risk_level else "low"
        } for p in profiles]
    }

@app.get("/api/associations/{siret}/profile")
def get_association_profile(siret: str, db: Session = Depends(get_db)):
    """Get full profile for an association."""
    from .models import AssociationProfile
    profile = db.query(AssociationProfile).filter(AssociationProfile.numero_siret == siret).first()
    
    if not profile:
        # Build from subventions
        subs = db.query(Subvention).filter(Subvention.numero_siret == siret).all()
        if not subs:
            raise HTTPException(status_code=404, detail="Association not found")
        
        total = sum(s.montant_vote or 0 for s in subs)
        return {
            "nom": subs[0].nom_beneficiaire,
            "siret": siret,
            "total_received": total,
            "subvention_count": len(subs),
            "years": sorted(set(s.annee_budgetaire for s in subs if s.annee_budgetaire)),
            "board_members": [],
            "risk_level": "low"
        }
    
    return {
        "id": profile.id,
        "nom": profile.nom,
        "siret": profile.numero_siret,
        "rna": profile.rna,
        "adresse": profile.adresse,
        "objetsocial": profile.objetsocial,
        "total_received": profile.total_subventions_received,
        "subvention_count": profile.subvention_count,
        "board_members": profile.board_members,
        "risk_level": profile.risk_level.value if profile.risk_level else "low",
        "last_enriched": profile.last_enriched.isoformat() if profile.last_enriched else None
    }

# ====================================================================
# MONETIZATION: ENRICHMENT ENDPOINTS
# ====================================================================

@app.post("/api/enrich/association/{siret}")
def enrich_assoc_endpoint(siret: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Trigger enrichment for a specific association."""
    import asyncio
    profile = asyncio.run(enrich_association(db, siret=siret))
    if not profile:
        raise HTTPException(status_code=404, detail="Association not found")
    return {
        "status": "enriched",
        "association": profile.nom,
        "siret": profile.numero_siret,
        "total_subventions": profile.total_subventions_received
    }

@app.get("/api/enrich/elected-officials")
def find_elected(db: Session = Depends(get_db)):
    """Find associations with likely elected officials."""
    import asyncio
    results = asyncio.run(find_elected_officials(db))
    return {"total": len(results), "items": results}

# ====================================================================
# MONETIZATION: SUBSCRIPTION TIERS
# ====================================================================

@app.get("/api/subscription")
def get_subscription(user: User = Depends(require_user)):
    """Get current subscription info."""
    return {
        "tier": "pro" if user.is_premium else "free",
        "is_premium": user.is_premium,
        "features": {
            "max_alerts": 10 if user.is_premium else 3,
            "max_exports": 50 if user.is_premium else 5,
            "full_history": user.is_premium,
            "api_calls": 1000 if user.is_premium else 100,
            "email_alerts": user.is_premium
        },
        "upgrade_url": "/api/subscription/upgrade"
    }

@app.post("/api/subscription/upgrade")
def upgrade_subscription(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Upgrade to Pro (placeholder - would integrate with Stripe)."""
    # In production: integrate Stripe checkout
    user.is_premium = True
    db.commit()
    return {
        "status": "upgraded",
        "tier": "pro",
        "message": "Upgraded to Pro! Enjoy unlimited alerts, full history, and priority email alerts."
    }

@app.post("/api/subscription/downgrade")
def downgrade_subscription(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Downgrade to Free."""
    user.is_premium = False
    db.commit()
    return {"status": "downgraded", "tier": "free"}

# ====================================================================
# MONETIZATION: EMAIL ALERTS (SMTP)
# ====================================================================

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_alert_email(to_email: str, subject: str, html_content: str, smtp_host: str = None, smtp_user: str = None, smtp_pass: str = None) -> bool:
    """Send email alert via SMTP."""
    smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = smtp_user or os.environ.get("SMTP_USER")
    smtp_pass = smtp_pass or os.environ.get("SMTP_PASS")
    
    if not smtp_user or not smtp_pass:
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email send failed: {e}")
        return False

@app.post("/api/alerts/send-test")
def send_test_alert(
    email: str = Query(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Send a test alert email."""
    html = f"""
    <html>
    <body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>🚨 SubventionTracker Test Alert</h2>
        <p>This is a test email from SubventionTracker.</p>
        <p>Your account: {user.email}</p>
        <p>You're receiving this because you configured email alerts.</p>
        <hr>
        <p><a href="http://192.168.0.16:8002/daily">View Daily Dashboard</a></p>
    </body>
    </html>
    """
    success = send_alert_email(email, "Test Alert from SubventionTracker", html)
    return {"sent": success, "email": email}

@app.post("/api/alerts/send-digest")
def send_digest_email(
    email: str = Query(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Send conflict digest email."""
    summary = get_daily_summary(db)
    
    conflicts_html = ""
    for s in summary["top_conflicts"][:5]:
        conflicts_html += f"""
        <tr>
            <td>{s.nom_beneficiaire}</td>
            <td>€{s.montant_vote:,}</td>
            <td>{s.risk_level.value.upper()}</td>
        </tr>"""
    
    html = f"""
    <html>
    <body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2>🚨 SubventionTracker Daily Digest</h2>
        <p><strong>New subventions:</strong> {summary['alert_summary']['new_count']}</p>
        <p><strong>New conflicts:</strong> {summary['alert_summary']['conflict_count']}</p>
        <p><strong>First-ever subventions:</strong> {summary['alert_summary']['first_ever']}</p>
        
        <h3>Top Conflicts</h3>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="background: #f0f0f0;">
                <th style="text-align: left; padding: 10px;">Beneficiary</th>
                <th style="text-align: left; padding: 10px;">Amount</th>
                <th style="text-align: left; padding: 10px;">Risk</th>
            </tr>
            {conflicts_html}
        </table>
        
        <p><a href="http://192.168.0.16:8002/daily" style="background: #1976d2; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px;">View Full Dashboard</a></p>
    </body>
    </html>
    """
    
    success = send_alert_email(email, f"SubventionTracker Daily Digest — {summary['alert_summary']['conflict_count']} conflicts", html)
    return {"sent": success, "email": email, "conflicts_count": summary['alert_summary']['conflict_count']}

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
