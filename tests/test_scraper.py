import pytest
import sys
sys.path.insert(0, '/home/openclaw/.openclaw/workspace/subvention-tracker')

import asyncio
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Base, Subvention, WatchedAssociation, RiskLevel
from src.scraper import score_conflicts, fetch_subventions

# In-memory test DB
TEST_DB = "sqlite:///:memory:"
engine = create_engine(TEST_DB)
TestSessionLocal = sessionmaker(bind=engine)

@pytest.fixture
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@pytest.mark.asyncio
async def test_fetch_subventions_mock():
    mock_data = {
        "results": [
            {"numero_de_dossier": "D-2024-001", "annee_budgetaire": "2024", "nom_beneficiaire": "Test Assoc"}
        ]
    }
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_data
        mock_get.return_value = mock_resp
        
        result = await fetch_subventions(limit=1)
        assert len(result) == 1
        assert result[0]["numero_de_dossier"] == "D-2024-001"

def test_score_conflicts_exact_match(db):
    # Add a watched association
    watched = WatchedAssociation(nom="Test Association", risk_level=RiskLevel.HIGH, active=True)
    db.add(watched)
    db.commit()
    
    # Add a subvention with matching name
    sub = Subvention(numero_dossier="D-001", nom_beneficiaire="Test Association", risk_level=RiskLevel.LOW)
    db.add(sub)
    db.commit()
    
    score_conflicts(db)
    
    updated = db.query(Subvention).get(sub.id)
    assert updated.risk_level == RiskLevel.HIGH
    assert len(updated.risk_reasons) > 0

def test_score_conflicts_no_match(db):
    watched = WatchedAssociation(nom="XYZ Corp", risk_level=RiskLevel.HIGH, active=True)
    db.add(watched)
    
    sub = Subvention(numero_dossier="D-002", nom_beneficiaire="ABC Org", risk_level=RiskLevel.LOW)
    db.add(sub)
    db.commit()
    
    score_conflicts(db)
    
    updated = db.query(Subvention).get(sub.id)
    assert updated.risk_level == RiskLevel.LOW

def test_score_conflicts_siret_match(db):
    watched = WatchedAssociation(nom="SIRET Corp", numero_siret="12345678901234", risk_level=RiskLevel.HIGH, active=True)
    db.add(watched)
    
    sub = Subvention(numero_dossier="D-003", nom_beneficiaire="Other Corp", numero_siret="12345678901234", risk_level=RiskLevel.LOW)
    db.add(sub)
    db.commit()
    
    score_conflicts(db)
    
    updated = db.query(Subvention).get(sub.id)
    assert updated.risk_level == RiskLevel.CRITICAL
