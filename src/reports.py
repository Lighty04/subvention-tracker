"""Report generation: CSV, PDF, daily digest, newsletter."""
import csv
import io
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from .models import Subvention, RiskLevel


def export_subventions_csv(db: Session, subventions: list) -> str:
    """Export subventions to CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "numero_dossier", "annee_budgetaire", "nom_beneficiaire",
        "numero_siret", "montant_vote", "direction",
        "nature_subvention", "objet_dossier", "risk_level"
    ])
    for s in subventions:
        writer.writerow([
            s.numero_dossier, s.annee_budgetaire, s.nom_beneficiaire,
            s.numero_siret, s.montant_vote, s.direction,
            s.nature_subvention, s.objet_dossier, s.risk_level.value
        ])
    return output.getvalue()


def export_subventions_pdf(db: Session, subventions: list, title: str = "Subvention Report") -> str:
    """Export subventions to simple HTML (for PDF conversion)."""
    rows = ""
    total = 0
    for s in subventions:
        rows += f"""
        <tr>
            <td>{s.nom_beneficiaire or ''}</td>
            <td>{s.annee_budgetaire or ''}</td>
            <td>{s.montant_vote or 0}</td>
            <td>{s.risk_level.value}</td>
            <td>{s.objet_dossier or ''}</td>
        </tr>"""
        total += s.montant_vote or 0

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>{title}</title><style>
        body {{ font-family: sans-serif; padding: 20px; max-width: 1000px; margin: 0 auto; }}
        h1 {{ color: #333; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }}
        th {{ background: #f0f0f0; }}
        .summary {{ background: #e8f5e9; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
    </style></head>
    <body>
        <h1>🚨 {title}</h1>
        <div class="summary">
            <p><strong>Generated:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
            <p><strong>Records:</strong> {len(subventions)}</p>
            <p><strong>Total Amount:</strong> €{total:,}</p>
        </div>
        <table>
            <tr>
                <th>Beneficiary</th>
                <th>Year</th>
                <th>Amount (€)</th>
                <th>Risk</th>
                <th>Object</th>
            </tr>
            {rows}
        </table>
    </body>
    </html>
    """
    return html


def get_daily_summary(db: Session) -> dict:
    """Generate daily summary data."""
    yesterday = datetime.utcnow() - timedelta(days=1)

    new_subventions = db.query(Subvention).filter(
        Subvention.date_import >= yesterday
    ).order_by(Subvention.date_import.desc()).all()

    top_conflicts = db.query(Subvention).filter(
        Subvention.risk_level.in_([RiskLevel.HIGH, RiskLevel.CRITICAL]),
        Subvention.date_import >= yesterday
    ).order_by(Subvention.montant_vote.desc()).limit(5).all()

    # Trending: associations with unusually high amounts (2x+ their average)
    trending = []
    for sub in new_subventions[:20]:
        if sub.nom_beneficiaire and sub.montant_vote:
            avg = db.query(func.avg(Subvention.montant_vote)).filter(
                Subvention.nom_beneficiaire == sub.nom_beneficiaire,
                Subvention.id != sub.id
            ).scalar() or 0
            if sub.montant_vote >= 2 * avg and avg > 0:
                trending.append({
                    "subvention": sub,
                    "average": int(avg),
                    "multiplier": round(sub.montant_vote / avg, 1)
                })

    # Alert summary
    first_ever = 0
    high_amount = 0
    for sub in new_subventions:
        if sub.nom_beneficiaire:
            existing = db.query(Subvention).filter(
                Subvention.nom_beneficiaire == sub.nom_beneficiaire,
                Subvention.id < sub.id
            ).count()
            if existing == 0:
                first_ever += 1
        if sub.montant_vote and sub.montant_vote >= 100000:
            high_amount += 1

    return {
        "new_subventions": new_subventions,
        "top_conflicts": top_conflicts,
        "trending": trending,
        "alert_summary": {
            "new_count": len(new_subventions),
            "conflict_count": len(top_conflicts),
            "first_ever": first_ever,
            "high_amount": high_amount,
            "trending_count": len(trending)
        }
    }


def get_sector_analysis(db: Session) -> list:
    """Analyze subventions by sector."""
    results = db.query(
        Subvention.nature_subvention,
        func.count(Subvention.id).label("count"),
        func.sum(Subvention.montant_vote).label("total")
    ).group_by(Subvention.nature_subvention).order_by(func.sum(Subvention.montant_vote).desc()).all()

    sectors = []
    for row in results:
        if row.nature_subvention:
            sectors.append({
                "sector": row.nature_subvention,
                "count": row.count,
                "total": int(row.total or 0)
            })
    return sectors


def get_association_trends(db: Session, siret: str = None, name: str = None) -> dict:
    """Get year-over-year trends for an association."""
    query = db.query(Subvention)
    if siret:
        query = query.filter(Subvention.numero_siret == siret)
    elif name:
        query = query.filter(Subvention.nom_beneficiaire == name)
    else:
        return {"error": "Need siret or name"}

    yearly = query.with_entities(
        Subvention.annee_budgetaire,
        func.count(Subvention.id).label("count"),
        func.sum(Subvention.montant_vote).label("total")
    ).group_by(Subvention.annee_budgetaire).order_by(Subvention.annee_budgetaire).all()

    total_received = sum(y.total or 0 for y in yearly)
    total_count = sum(y.count for y in yearly)
    avg = total_received / total_count if total_count else 0

    return {
        "yearly": [{"year": y.annee_budgetaire, "count": y.count, "total": int(y.total or 0)} for y in yearly],
        "total_received": int(total_received),
        "total_count": total_count,
        "average": int(avg)
    }


def get_newsletter_preview(db: Session) -> dict:
    """Generate 'Subvention of the Week' preview."""
    # Find most interesting subvention this week (highest risk + highest amount)
    week_ago = datetime.utcnow() - timedelta(days=7)

    candidate = db.query(Subvention).filter(
        Subvention.date_import >= week_ago
    ).order_by(
        Subvention.montant_vote.desc()
    ).first()

    if not candidate:
        candidate = db.query(Subvention).order_by(
            Subvention.montant_vote.desc()
        ).first()

    if not candidate:
        return {"message": "No data available yet"}

    # Check if it's unusual
    avg = db.query(func.avg(Subvention.montant_vote)).filter(
        Subvention.nom_beneficiaire == candidate.nom_beneficiaire,
        Subvention.id != candidate.id
    ).scalar() or 0

    is_unusual = candidate.montant_vote >= 2 * avg if avg > 0 else False

    return {
        "subvention": {
            "id": candidate.id,
            "beneficiary": candidate.nom_beneficiaire,
            "amount": candidate.montant_vote,
            "year": candidate.annee_budgetaire,
            "object": candidate.objet_dossier,
            "risk_level": candidate.risk_level.value,
            "risk_reasons": candidate.risk_reasons
        },
        "is_unusual": is_unusual,
        "average_for_beneficiary": int(avg),
        "multiplier": round(candidate.montant_vote / avg, 1) if avg > 0 else None
    }
