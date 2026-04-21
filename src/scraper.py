import httpx
from sqlalchemy.orm import Session
from .models import Subvention, ImportLog, RiskLevel, WatchedAssociation, Alert, AlertConfig, User
from typing import List
from datetime import datetime
import csv
import io

PARIS_API_URL = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/subventions-associations-votees-/records"
PARIS_CSV_URL = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/subventions-associations-votees-/exports/csv"
BATCH_SIZE = 100
MAX_API_OFFSET = 9900  # API limit

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

async def download_full_csv() -> List[dict]:
    """Download full dataset as CSV (bypasses 10k API limit)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(PARIS_CSV_URL, timeout=300.0)  # No params, default export
        resp.raise_for_status()
        
        # Parse CSV (semicolon-separated, strip BOM)
        content = resp.text.lstrip('\ufeff')
        reader = csv.DictReader(io.StringIO(content), delimiter=';')
        records = []
        for row in reader:
            records.append({
                "numero_de_dossier": row.get("numero_de_dossier"),
                "annee_budgetaire": row.get("annee_budgetaire"),
                "collectivite": row.get("collectivite"),
                "nom_beneficiaire": row.get("nom_beneficiaire"),
                "numero_siret": row.get("numero_siret"),
                "objet_du_dossier": row.get("objet_du_dossier"),
                "montant_vote": row.get("montant_vote"),
                "direction": row.get("direction"),
                "nature_de_la_subvention": row.get("nature_de_la_subvention"),
                "secteurs_d_activites_definies_par_l_association": row.get("secteurs_d_activites_definies_par_l_association", "")
            })
        return records

def _import_record(db: Session, record: dict, imported: list, updated: list):
    """Import a single record. Returns True if imported/updated."""
    # Strip BOM from keys
    record = {k.lstrip('\ufeff'): v for k, v in record.items()}
    dossier = record.get("numero_de_dossier")
    if not dossier:
        return False
    
    existing = db.query(Subvention).filter_by(numero_dossier=dossier).first()
    
    # Parse amount - CSV amounts are plain integers as strings
    amount_str = record.get("montant_vote", "")
    amount = None
    if amount_str and amount_str.strip():
        try:
            amount = int(float(amount_str.strip()))
        except (ValueError, TypeError):
            amount = None
    
    subvention_data = {
        "numero_dossier": dossier,
        "annee_budgetaire": int(record.get("annee_budgetaire", 0)) if record.get("annee_budgetaire") else None,
        "collectivite": record.get("collectivite"),
        "nom_beneficiaire": record.get("nom_beneficiaire"),
        "numero_siret": record.get("numero_siret"),
        "objet_dossier": record.get("objet_du_dossier"),
        "montant_vote": amount,
        "direction": record.get("direction"),
        "nature_subvention": record.get("nature_de_la_subvention"),
        "secteurs_activites": record.get("secteurs_d_activites_definies_par_l_association", [])
    }
    
    if existing:
        for key, value in subvention_data.items():
            setattr(existing, key, value)
        updated.append(1)
    else:
        db.add(Subvention(**subvention_data))
        imported.append(1)
    
    return True

async def import_recent_subventions(db: Session, max_records: int = 500, use_csv: bool = False) -> ImportLog:
    log = ImportLog(status="running")
    db.add(log)
    db.commit()
    db.refresh(log)
    
    imported = []
    updated = []
    
    try:
        if use_csv:
            print("Downloading full dataset as CSV (this may take a minute)...")
            records = await download_full_csv()
            print(f"  Downloaded {len(records)} records from CSV")
            
            for i, record in enumerate(records):
                if max_records > 0 and len(imported) >= max_records:
                    break
                _import_record(db, record, imported, updated)
                if i % 1000 == 0:
                    db.commit()
                    print(f"  Progress: {len(imported)} imported, {len(updated)} updated")
            
            db.commit()
            print(f"  CSV import: {len(imported)} imported, {len(updated)} updated")
            
        else:
            # API-based import (year-by-year, up to 10k per year)
            current_year = datetime.utcnow().year
            for year in range(current_year, 2010, -1):
                if max_records > 0 and len(imported) >= max_records:
                    break
                
                year_imported = 0
                offset = 0
                while (max_records <= 0 or len(imported) < max_records) and offset < MAX_API_OFFSET:
                    batch = await fetch_subventions(offset=offset, limit=BATCH_SIZE, year=year)
                    if not batch:
                        break
                    
                    for record in batch:
                        if _import_record(db, record, imported, updated):
                            year_imported += 1
                        if max_records > 0 and len(imported) >= max_records:
                            break
                    
                    db.commit()
                    offset += len(batch)
                    if len(batch) < BATCH_SIZE:
                        break
                
                if year_imported > 0:
                    print(f"  Year {year}: {year_imported} records")
        
        score_conflicts(db)
        generate_alerts(db)
        
        log.records_imported = len(imported)
        log.records_updated = len(updated)
        log.status = "success"
        
    except Exception as e:
        log.status = "failed"
        log.error_message = str(e)
        print(f"Import failed: {e}")
    
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
    
    # Normalize watched names + extract key identifying tokens
    stopwords = {"association", "fondation", "pour", "les", "des", "de", "la", "le", "du", "et", "en", "paris", "france", "ville", "communaute", "communauté"}
    
    watched_entries = []
    for w in watched:
        norm = normalize_text(w.nom)
        tokens = [t for t in norm.split() if len(t) >= 3 and t not in stopwords]
        watched_entries.append((w, norm, tokens))
    
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
            sub_tokens = [t for t in sub_norm.split() if len(t) >= 3 and t not in stopwords]
            
            for w, w_norm, w_tokens in watched_entries:
                # Strict matching: only match if the FULL watched name (or a close variant) appears
                # in the association name. NOT individual tokens.
                matched = False
                
                # 1. Full name substring (both directions)
                if w_norm in sub_norm or sub_norm in w_norm:
                    matched = True
                # 2. For multi-word watched names: check if ALL key tokens appear in order
                elif len(w_tokens) >= 2 and sub_tokens:
                    # All tokens must be present AND in relative order
                    idx = 0
                    found_count = 0
                    for token in w_tokens:
                        try:
                            new_idx = sub_tokens.index(token, idx)
                            idx = new_idx + 1
                            found_count += 1
                        except ValueError:
                            pass
                    if found_count >= len(w_tokens):
                        matched = True
                # 3. Single distinctive token (only if it's a unique/identifying word, min 5 chars)
                elif len(w_tokens) == 1 and len(w_tokens[0]) >= 5 and sub_tokens:
                    if w_tokens[0] in sub_tokens:
                        matched = True
                
                if matched:
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
