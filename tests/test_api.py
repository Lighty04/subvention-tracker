import pytest
import sys
import os
import tempfile

# Set test DB path BEFORE any imports
TEST_DB_PATH = tempfile.mktemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

sys.path.insert(0, '/home/openclaw/.openclaw/workspace/subvention-tracker')

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.models import Base, get_db
from src.main import app

# Create engine matching the models module
models_engine = create_engine(os.environ["DATABASE_URL"])
TestSessionLocal = sessionmaker(bind=models_engine)

def setup_module(module):
    """Create all tables before running tests."""
    Base.metadata.create_all(bind=models_engine)

def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture
def client():
    # Clean state: drop and recreate tables for each test
    Base.metadata.drop_all(bind=models_engine)
    Base.metadata.create_all(bind=models_engine)
    with TestClient(app) as c:
        yield c

class TestSubventions:
    def test_list_empty(self, client):
        resp = client.get("/api/subventions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []
    
    def test_search_no_results(self, client):
        resp = client.get("/api/search?q=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

class TestAuth:
    def test_register(self, client):
        resp = client.post("/api/register", json={"email": "test@example.com", "password": "secretpassword123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert "id" in data
    
    def test_register_duplicate(self, client):
        client.post("/api/register", json={"email": "dup@example.com", "password": "secretpassword123"})
        resp = client.post("/api/register", json={"email": "dup@example.com", "password": "secretpassword123"})
        assert resp.status_code == 400
    
    def test_login(self, client):
        client.post("/api/register", json={"email": "login@example.com", "password": "secretpassword123"})
        resp = client.post("/api/login", json={"email": "login@example.com", "password": "secretpassword123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "api_key" in data
    
    def test_login_wrong_password(self, client):
        client.post("/api/register", json={"email": "bad@example.com", "password": "secretpassword123"})
        resp = client.post("/api/login", json={"email": "bad@example.com", "password": "wrongpassword"})
        assert resp.status_code == 401
    
    def test_me_unauthorized(self, client):
        resp = client.get("/api/me")
        assert resp.status_code == 401
    
    def test_me_with_key(self, client):
        reg = client.post("/api/register", json={"email": "me@example.com", "password": "secretpassword123"})
        api_key = reg.json().get("api_key")
        resp = client.get(f"/api/me?api_key={api_key}")
        assert resp.status_code == 200
        assert resp.json()["email"] == "me@example.com"

class TestWatched:
    def test_list_watched(self, client):
        resp = client.get("/api/watched")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
    
    def test_add_watched(self, client):
        resp = client.post("/api/watched", json={"nom": "Test Assoc", "reason": "Test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["nom"] == "Test Assoc"
    
    def test_delete_watched(self, client):
        create = client.post("/api/watched", json={"nom": "To Delete"})
        wid = create.json()["id"]
        resp = client.delete(f"/api/watched/{wid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == True

class TestImport:
    def test_import_unauthorized(self, client):
        resp = client.post("/api/import?max_records=10")
        assert resp.status_code == 401
    
    def test_import_status(self, client):
        resp = client.get("/api/import/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no imports yet"

class TestDashboard:
    def test_dashboard(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Subvention Tracker" in resp.text

# Cleanup
def teardown_module(module):
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
