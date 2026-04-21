from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Boolean, Text, ForeignKey, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import enum

Base = declarative_base()

class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class Subvention(Base):
    __tablename__ = "subventions"
    
    id = Column(Integer, primary_key=True)
    numero_dossier = Column(String(50), index=True)
    annee_budgetaire = Column(Integer, index=True)
    collectivite = Column(String(100))
    nom_beneficiaire = Column(String(500), index=True)
    numero_siret = Column(String(14), index=True)
    objet_dossier = Column(Text)
    montant_vote = Column(Integer)
    direction = Column(String(20), index=True)
    nature_subvention = Column(String(50))
    secteurs_activites = Column(JSON)
    date_import = Column(DateTime, default=datetime.utcnow)
    source_url = Column(String(500))
    
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)
    risk_reasons = Column(JSON, default=list)
    
    alerts = relationship("Alert", back_populates="subvention")

class WatchedAssociation(Base):
    __tablename__ = "watched_associations"
    
    id = Column(Integer, primary_key=True)
    nom = Column(String(500), index=True)
    numero_siret = Column(String(14), index=True, unique=True, nullable=True)
    reason = Column(Text)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.HIGH)
    date_added = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True)
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_premium = Column(Boolean, default=False)
    alert_email = Column(Boolean, default=True)
    alert_webhook = Column(String(500), nullable=True)
    api_key = Column(String(64), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    alerts = relationship("Alert", back_populates="user")
    alert_configs = relationship("AlertConfig", back_populates="user")

class AlertConfig(Base):
    __tablename__ = "alert_configs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    email = Column(String(255), nullable=True)
    webhook_url = Column(String(500), nullable=True)
    enabled = Column(Boolean, default=True)
    min_risk_level = Column(Enum(RiskLevel), default=RiskLevel.HIGH)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="alert_configs")

class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subvention_id = Column(Integer, ForeignKey("subventions.id"))
    sent_at = Column(DateTime, default=datetime.utcnow)
    channel = Column(String(20))
    status = Column(String(20), default="pending")
    
    user = relationship("User", back_populates="alerts")
    subvention = relationship("Subvention", back_populates="alerts")

class Person(Base):
    __tablename__ = "persons"
    
    id = Column(Integer, primary_key=True)
    nom = Column(String(500), index=True)
    roles = Column(JSON, default=list)  # [{"association": "...", "role": "President", "date_debut": "..."}]
    is_elected_official = Column(Boolean, default=False)
    elected_role = Column(String(200), nullable=True)  # e.g. "Deputy Mayor, 12th arr."
    total_controlled = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class AssociationProfile(Base):
    __tablename__ = "association_profiles"
    
    id = Column(Integer, primary_key=True)
    nom = Column(String(500), index=True)
    numero_siret = Column(String(14), unique=True, index=True, nullable=True)
    rna = Column(String(20), nullable=True)  # RNA number
    adresse = Column(Text, nullable=True)
    date_creation = Column(DateTime, nullable=True)
    objetsocial = Column(Text, nullable=True)
    total_subventions_received = Column(Integer, default=0)
    subvention_count = Column(Integer, default=0)
    board_members = Column(JSON, default=list)  # [{"nom": "...", "role": "...", "is_elected": false}]
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)
    last_enriched = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ImportLog(Base):
    __tablename__ = "import_logs"
    
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    records_imported = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    status = Column(String(20), default="running")
    error_message = Column(Text, nullable=True)

import os

_database_url = None
_engine = None

def get_engine():
    global _database_url, _engine
    current_url = os.environ.get("DATABASE_URL", "sqlite:///./subvention_tracker.db")
    if _engine is None or current_url != _database_url:
        _database_url = current_url
        _engine = create_engine(current_url, echo=False)
    return _engine

def get_session_local():
    engine = get_engine()
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)

SessionLocal = get_session_local()

def init_db():
    Base.metadata.create_all(bind=get_engine())

def get_db():
    Session = get_session_local()
    db = Session()
    try:
        yield db
    finally:
        db.close()
