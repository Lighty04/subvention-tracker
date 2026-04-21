from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Boolean, Text, ForeignKey, JSON, Enum, BigInteger
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
    numero_dossier = Column(String(50), index=True, unique=True)
    annee_budgetaire = Column(Integer, index=True)
    collectivite = Column(String(100))
    nom_beneficiaire = Column(String(500), index=True)
    numero_siret = Column(String(14), index=True)
    objet_dossier = Column(Text)
    montant_vote = Column(Integer)  # cents / whole euros
    direction = Column(String(20), index=True)
    nature_subvention = Column(String(50))
    secteurs_activites = Column(JSON)
    date_import = Column(DateTime, default=datetime.utcnow)
    source_url = Column(String(500))
    
    # Conflict of interest scoring
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)
    risk_reasons = Column(JSON, default=list)
    
    alerts = relationship("Alert", back_populates="subvention")

class WatchedAssociation(Base):
    __tablename__ = "watched_associations"
    
    id = Column(Integer, primary_key=True)
    nom = Column(String(500), index=True)
    numero_siret = Column(String(14), index=True, unique=True, nullable=True)
    reason = Column(Text)  # Why this association is watched (conflict details)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.HIGH)
    date_added = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True)
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_premium = Column(Boolean, default=False)  # free vs €29/mo
    alert_email = Column(Boolean, default=True)
    alert_webhook = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    alerts = relationship("Alert", back_populates="user")

class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    subvention_id = Column(Integer, ForeignKey("subventions.id"))
    sent_at = Column(DateTime, default=datetime.utcnow)
    channel = Column(String(20))  # email, webhook
    status = Column(String(20), default="pending")  # pending, sent, failed
    
    user = relationship("User", back_populates="alerts")
    subvention = relationship("Subvention", back_populates="alerts")

class ImportLog(Base):
    __tablename__ = "import_logs"
    
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    records_imported = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    status = Column(String(20), default="running")  # running, success, failed
    error_message = Column(Text, nullable=True)

# SQLite for dev
engine = create_engine("sqlite:///./subvention_tracker.db", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
