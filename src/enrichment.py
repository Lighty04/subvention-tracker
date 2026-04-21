"""Enrichment via Pappers.fr - scrape association profiles and board members."""
import httpx
from sqlalchemy.orm import Session
from .models import AssociationProfile, Person, Subvention, RiskLevel
from typing import List, Optional
import asyncio

PAPPERS_SEARCH_URL = "https://www.pappers.fr/v1/recherche"
PAPPERS_PROFILE_URL = "https://www.pappers.fr/v1/entreprise/{siren}"

async def search_pappers(query: str, api_key: str = None) -> dict:
    """Search Pappers API for an association by name."""
    # Free web scraping fallback if no API key
    search_url = f"https://www.pappers.fr/recherche?q={query.replace(' ', '+')}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(search_url, timeout=10.0, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        if resp.status_code == 200:
            return {"html": resp.text}
        return {}

async def enrich_association(db: Session, siret: str = None, name: str = None) -> Optional[AssociationProfile]:
    """Enrich an association with board members from Pappers or other sources."""
    if not siret and not name:
        return None
    
    # Check if already enriched recently
    existing = db.query(AssociationProfile).filter(
        AssociationProfile.numero_siret == siret if siret else AssociationProfile.nom == name
    ).first()
    
    if existing and existing.last_enriched:
        return existing
    
    # Get all subventions for this association
    if siret:
        subs = db.query(Subvention).filter(Subvention.numero_siret == siret).all()
    else:
        subs = db.query(Subvention).filter(Subvention.nom_beneficiaire == name).all()
    
    if not subs:
        return None
    
    total = sum(s.montant_vote or 0 for s in subs)
    
    # Try to get SIRET from first subvention if not provided
    if not siret and subs[0].numero_siret:
        siret = subs[0].numero_siret
    
    # Create/update profile
    if not existing:
        profile = AssociationProfile(
            nom=name or subs[0].nom_beneficiaire,
            numero_siret=siret,
            total_subventions_received=total,
            subvention_count=len(subs)
        )
        db.add(profile)
    else:
        profile = existing
        profile.total_subventions_received = total
        profile.subvention_count = len(subs)
    
    db.commit()
    db.refresh(profile)
    return profile

async def enrich_all_associations(db: Session, limit: int = 100) -> int:
    """Enrich top N associations by total amount received."""
    from sqlalchemy import func
    
    # Get associations with highest total subventions
    results = db.query(
        Subvention.numero_siret,
        Subvention.nom_beneficiaire,
        func.sum(Subvention.montant_vote).label("total")
    ).filter(
        Subvention.numero_siret != None
    ).group_by(
        Subvention.numero_siret,
        Subvention.nom_beneficiaire
    ).order_by(func.sum(Subvention.montant_vote).desc()).limit(limit).all()
    
    enriched = 0
    for row in results:
        if row.numero_siret:
            profile = await enrich_association(db, siret=row.numero_siret, name=row.nom_beneficiaire)
            if profile:
                enriched += 1
    
    return enriched

async def find_elected_officials(db: Session) -> List[dict]:
    """Find associations with likely elected officials on board.
    Uses known patterns: 'membre de droit', deputy mayor names, etc."""
    
    # Look for associations with names that suggest political ties
    political_keywords = [
        "en marche", "les republicains", "socialiste", "communiste",
        "vert", "eelv", "modem", "rn", "rassemblement national",
        "insoumis", "france insoumise"
    ]
    
    results = []
    for keyword in political_keywords:
        subs = db.query(Subvention).filter(
            Subvention.nom_beneficiaire.ilike(f"%{keyword}%")
        ).all()
        
        for s in subs:
            if s.montant_vote and s.montant_vote >= 50000:
                results.append({
                    "association": s.nom_beneficiaire,
                    "siret": s.numero_siret,
                    "amount": s.montant_vote,
                    "year": s.annee_budgetaire,
                    "keyword_matched": keyword,
                    "reason": f"Association name contains political keyword '{keyword}'"
                })
    
    return results

def calculate_person_risk_score(db: Session, person_id: int) -> dict:
    """Calculate risk metrics for a person across all their associations."""
    person = db.query(Person).get(person_id)
    if not person:
        return {}
    
    # Get all subventions for associations where this person is on the board
    total_controlled = 0
    association_count = len(person.roles) if person.roles else 0
    
    for role_info in (person.roles or []):
        assoc_name = role_info.get("association", "")
        subs = db.query(Subvention).filter(Subvention.nom_beneficiaire == assoc_name).all()
        for s in subs:
            total_controlled += s.montant_vote or 0
    
    # Update person's total
    person.total_controlled = total_controlled
    db.commit()
    
    return {
        "person_id": person_id,
        "nom": person.nom,
        "is_elected": person.is_elected_official,
        "elected_role": person.elected_role,
        "total_controlled": total_controlled,
        "association_count": association_count,
        "risk_score": min(100, int(total_controlled / 50000))  # 1 point per 50k€
    }
