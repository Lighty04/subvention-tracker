from .models import WatchedAssociation, RiskLevel

DEFAULT_WATCHED = [
    # Political foundations & movements
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
        "nom": "Fondation Jean Jaurès",
        "reason": "Socialist think tank with public funding",
        "risk_level": RiskLevel.MEDIUM,
    },
    # Major cultural institutions (high scrutiny due to membre de droit pattern)
    {
        "nom": "THEATRE MUSICAL DE PARIS",
        "reason": "Top recipient €200M+, known for political board appointments (membre de droit)",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "PHILHARMONIE DE PARIS",
        "reason": "Major cultural institution, €42M total, elected officials on board",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "THEATRE DE LA VILLE",
        "reason": "Top recipient €92M, political oversight via mairie de Paris",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "FORUM DES IMAGES",
        "reason": "Major cultural institution €83M, city-funded",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "ORCHESTRE DE CHAMBRE DE PARIS",
        "reason": "Top recipient €60M, cultural institution with political ties",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "MUSEE D'ART ET D'HISTOIRE DU JUDAISME",
        "reason": "Cultural institution with public board appointments",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "MEP - MAISON EUROPEENNE DE LA PHOTOGRAPHIE",
        "reason": "Cultural institution, potential political board members",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "ATELIER PARISIEN D'URBANISME",
        "reason": "APUR - urban planning think tank closely tied to mairie de Paris",
        "risk_level": RiskLevel.CRITICAL,
    },
    {
        "nom": "PARIS ATELIERS",
        "reason": "Arts institution with significant public funding €49M",
        "risk_level": RiskLevel.MEDIUM,
    },
    # Social services (membre de droit pattern: elected officials on boards)
    {
        "nom": "ASSOCIATION D'ACTION SOCIALE EN FAVEUR DES PERSONNELS DE LA VILLE DE PARIS",
        "reason": "ASPP - Social association for city employees, €95M, strong political ties",
        "risk_level": RiskLevel.CRITICAL,
    },
    {
        "nom": "MISSION LOCALE DE PARIS",
        "reason": "Public employment service €53M, political oversight",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "ABC PUERICULTURE",
        "reason": "Childcare association €53M, significant public funding",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "FONDATION OEUVRE DE LA CROIX SAINT-SIMON",
        "reason": "Social care foundation €52M, public funding",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "nom": "EMMAUS SOLIDARITE",
        "reason": "Major solidarity NGO €48M, significant public subventions",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "LA MAISON KANGOUROU",
        "reason": "Childcare association €48M",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "ENFANT PRESENT",
        "reason": "Child welfare association €21M",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "LA MAISON DES BOUT'CHOU",
        "reason": "Childcare association €37M",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "CRESCENDO",
        "reason": "Cultural association €72M, very high funding",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "ASSOCIATION POUR LA GESTION DES OEUVRES SOCIALES DU PERSONNEL DE LA VILLE",
        "reason": "AGOS - Social works for city employees €71M, strong political ties",
        "risk_level": RiskLevel.CRITICAL,
    },
    {
        "nom": "ASSOCIATION DU THEATRE DE LA VILLE",
        "reason": "Theater association €70M",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "OEUVRE DE SECOURS AUX ENFANTS",
        "reason": "Child welfare NGO €21M",
        "risk_level": RiskLevel.LOW,
    },
    {
        "nom": "OFFICE DU TOURISME ET DES CONGRES DE PARIS",
        "reason": "Tourism office €39M, politically controlled",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "nom": "SOCIETE DE RETRAITES DES CONSEILLERS DE PARIS",
        "reason": "Pension fund for Paris city councilors, direct political tie",
        "risk_level": RiskLevel.CRITICAL,
    },
    {
        "nom": "ASSOCIATION INTERNATIONALE DES MAIRES",
        "reason": "AIMF - International mayors association €1.4M/year, political organization",
        "risk_level": RiskLevel.CRITICAL,
    },
    # Sports (potential political patronage)
    {
        "nom": "FC SOLITAIRES PARIS EST",
        "reason": "Sports club with significant funding €35K",
        "risk_level": RiskLevel.LOW,
    },
    # NGOs
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

def update_watched_associations(db):
    """Add new watched associations without duplicating existing ones."""
    return seed_watched_associations(db)
