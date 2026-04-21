# Subvention Tracker

Micro-SaaS that alerts users to new public subventions (grants) awarded to French associations, with automatic conflict-of-interest flagging.

## Data Source

- Paris Open Data API v2.1: `subventions-associations-votees-`
  - 106,463 records (1990–present)
  - Fields: numero_de_dossier, annee_budgetaire, collectivite, nom_beneficiaire, numero_siret, objet_du_dossier, montant_vote, direction, nature_de_la_subvention, secteurs_d_activites
  - Endpoint: `https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/subventions-associations-votees-/records`

## Tech Stack

- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL (production) / SQLite (dev)
- **Frontend:** HTML + HTMX
- **Scraping:** httpx + direct API calls
- **Deployment:** Docker + VPS

## Quick Start

```bash
cd subvention-tracker
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## Project Status

- [x] Git repo initialized
- [x] Data source identified (Paris Open Data API)
- [ ] Database schema
- [ ] Scraper prototype
- [ ] FastAPI MVP
- [ ] Conflict-of-interest flagging
- [ ] Alert system
- [ ] Web dashboard
