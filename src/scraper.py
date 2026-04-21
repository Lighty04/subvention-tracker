import httpx
from sqlalchemy.orm import Session
from .models import Subvention, ImportLog, RiskLevel, WatchedAssociation, Alert, AlertConfig, User
from typing import List
from datetime import datetime

PARIS_API_URL = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/subventions-associations-votees-/records"
BATCH_SIZE = 100

async def fetch_subventions(offset: int = 0, limit: int = BATCH_SIZE, year: int = None) -> List[dict]:
    async with httpx.AsyncClient() as client:
        params = {
            "limit": limit,
            "offset": offset,
            "order_by": "annee_budgetaire DESC"
        }
        if year:
            params["refine"] = f"annee_budgetaire:{year}"
        resp = await client.get(PARIS_API_URL, params=params, timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])

async def import_recent_subventions(db: Session, max_records: int = 500) -> ImportLog:
    log = ImportLog(status="running")
    db.add(log)
    db.commit()
    db.refresh(log)
    
    imported = 0
    updated = 0
    
    try:
        # Import by year to avoid 10k offset limit
        # Start from most recent year
        current_year = datetime.utcnow().year
        for year in range(current_year, 2010, -1):
            if imported >= max_records:
                break
            
            year_imported = 0
            offset = 0
            while imported < max_records:
                batch = await fetch_subventions(offset=offset, limit=BATCH_SIZE, year=year)
                if not batch:
                    break
                
                for record in batch:
                    dossier = record.get("numero_de_dossier")
                    if not dossier:
                        continue
                    existing = db.query(Subvention).filter_by(numero_dossier=dossier).first()
                    
                    subvention_data = {
                        "numero_dossier": dossier,
                        "annee_budgetaire": int(record.get("annee_budgetaire", 0)) if record.get("annee_budgetaire") else None,
                        "collectivite": record.get("collectivite"),
                        "nom_beneficiaire": record.get("nom_beneficiaire"),
                        "numero_siret": record.get("numero_siret"),
                        "objet_dossier": record.get("objet_du_dossier"),
                        "montant_vote": record.get("montant_vote"),
                        "direction": record.get("direction"),
                        "nature_subvention": record.get("nature_de_la_subvention"),
                        "secteurs_activites": record.get("secteurs_d_activites_definies_par_l_association", [])
                    }
                    
                    if existing:
                        for key, value in subvention_data.items():
                            setattr(existing, key, value)
                        updated += 1
                    else:
                        db.add(Subvention(**subvention_data))
                        imported += 1
                        year_imported += 1
                
                db.commit()
                offset += len(batch)
                if len(batch) < BATCH_SIZE:
                    break
            
            print(f"  Year {year}: {year_imported} records")
        
        score_conflicts(db)
        generate_alerts(db)
        
        log.records_imported = imported
        log.records_updated = updated
        log.status = "success"
        
    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
    
    log.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(log)
    return log

import unicodedata

def normalize_text(text: str) -> str:
    """Strip accents and lowercase for fuzzy matching."""
    text = text.lower()
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if unicodedata.category(c) != 'Mn')
    return text

def score_conflicts(db: Session) -> None:
    watched = db.query(WatchedAssociation).filter_by(active=True).all()
    watched_sirets = {w.numero_siret for w in watched if w.numero_siret}
    
    # Normalize watched names for substring matching
    watched_norms = [(w, normalize_text(w.nom)) for w in watched]
    
    # Reset all scores first
    db.execute(Subvention.__table__.update().values(risk_level=RiskLevel.LOW, risk_reasons=[]))
    db.commit()
    
    subventions = db.query(Subvention).all()
    
    for sub in subventions:
        reasons = []
        max_risk = RiskLevel.LOW
        
        if sub.numero_siret and sub.numero_siret in watched_sirets:
            reasons.append(f"SIRET {sub.numero_siret} matches watched association")
            max_risk = RiskLevel.CRITICAL
        
        if sub.nom_beneficiaire:
            sub_norm = normalize_text(sub.nom_beneficiaire)
            
            for w, w_norm in watched_norms:
                # Check if the full watched name (normalized) appears as a substring
                if w_norm in sub_norm or sub_norm in w_norm:
                    reasons.append(f"Name matches watched association: {w.nom}")
                    if w.risk_level == RiskLevel.CRITICAL:
                        max_risk = RiskLevel.CRITICAL
                    elif w.risk_level == RiskLevel.HIGH and max_risk != RiskLevel.CRITICAL:
                        max_risk = RiskLevel.HIGH
                    elif w.risk_level == RiskLevel.MEDIUM and max_risk not in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                        max_risk = RiskLevel.MEDIUM
        
        if reasons:
            sub.risk_level = max_risk
            sub.risk_reasons = reasons
    
    db.commit()

def generate_alerts(db: Session) -> int:
    configs = db.query(AlertConfig).filter_by(enabled=True).all()
    if not configs:
        return 0
    
    high_risk = db.query(Subvention).filter(
        Subvention.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]),
        Subvention.date_import >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    ).all()
    
    created = 0
    for sub in high_risk:
        for cfg in configs:
            existing = db.query(Alert).filter_by(
                user_id=cfg.user_id,
                subvention_id=sub.id
            ).first()
            if existing:
                continue
            
            min_risk = cfg.min_risk_level or RiskLevel.HIGH
            if sub.risk_level.value not in ["high", "critical"] and sub.risk_level != min_risk:
                continue
            
            alert = Alert(
                user_id=cfg.user_id,
                subvention_id=sub.id,
                channel="email" if cfg.email else "webhook",
                status="pending"
            )
            db.add(alert)
            created += 1
    
    db.commit()
    return created
