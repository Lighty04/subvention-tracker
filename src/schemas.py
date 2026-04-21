from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from .models import RiskLevel

class SubventionResponse(BaseModel):
    id: int
    numero_dossier: Optional[str]
    annee_budgetaire: Optional[int]
    collectivite: Optional[str]
    nom_beneficiaire: Optional[str]
    numero_siret: Optional[str]
    objet_dossier: Optional[str]
    montant_vote: Optional[int]
    direction: Optional[str]
    nature_subvention: Optional[str]
    risk_level: str
    risk_reasons: list
    date_import: Optional[datetime]
    
    class Config:
        from_attributes = True

class SubventionList(BaseModel):
    total: int
    items: List[SubventionResponse]

class WatchedAssocCreate(BaseModel):
    nom: str
    numero_siret: Optional[str] = None
    reason: Optional[str] = None
    risk_level: str = "high"

class WatchedAssocResponse(BaseModel):
    id: int
    nom: str
    numero_siret: Optional[str]
    reason: Optional[str]
    risk_level: str
    active: bool
    date_added: datetime
    
    class Config:
        from_attributes = True

class UserRegister(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    is_active: bool
    is_premium: bool
    api_key: Optional[str] = None
    
    class Config:
        from_attributes = True

class AlertConfigCreate(BaseModel):
    email: Optional[str] = None
    webhook_url: Optional[str] = None
    enabled: bool = True

class AlertResponse(BaseModel):
    id: int
    subvention_id: int
    sent_at: datetime
    channel: str
    status: str
    
    class Config:
        from_attributes = True

class ImportStatus(BaseModel):
    status: str
    records_imported: int
    records_updated: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
