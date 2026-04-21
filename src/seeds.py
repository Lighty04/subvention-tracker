from .models import WatchedAssociation, RiskLevel

DEFAULT_WATCHED = [
    {
        "nom": "Association pour le renouvellement de la vie politique",
        "reason": "Macron-era political foundation, high profile funding",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "La France est en marche",
        "reason": "Political movement association",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "Mouvement des jeunes socialistes",
        "reason": "Youth wing of Socialist Party",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "Les Jeunes Républicains",
        "reason": "Youth wing of Les Républicains",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "Generation.s",
        "reason": "Benoît Hamon political movement",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "Place Publique",
        "reason": "Raphaël Glucksmann political think tank",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "La Courneuve en commun",
        "reason": "Local political association",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "Fondation Jean Jaurès",
        "reason": "Socialist think tank with public funding",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "Fondation Abbé Pierre",
        "reason": "Major housing NGO with large subventions",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "Emmaüs France",
        "reason": "Major solidarity NGO",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "Les Restos du Cœur",
        "reason": "Coluche association, significant public funding",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "Médecins du Monde",
        "reason": "International solidarity NGO",
        "risk_level": RiskLevel.LOW,
    },
]

def seed_watched_associations(db):
    from sqlalchemy.orm import Session
    existing = {w.nom for w in db.query(WatchedAssociation).all()}
    added = 0
    for data in DEFAULT_WATCHED:
        if data["nom"] not in existing:
            db.add(WatchedAssociation(**data))
            added += 1
    if added:
        db.commit()
    return added
