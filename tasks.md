# SubventionTracker Atomic Tasks for Devclaw

## Task 1: Import Full Dataset + Conflict Detection
**Priority**: Critical
**Scope**: Run full import of 106k Paris Open Data records, verify conflict scoring works
**Files**: src/scraper.py, src/models.py
**Deliverable**: 100k+ subventions in DB with risk scores populated
**Test**: At least 1 high/critical risk match found
**Cmd**: cd ~/subvention-tracker && .venv/bin/python -m src.import_cli --max-records 50000
**Verify**: curl http://localhost:8002/api/subventions?risk=high or critical > 0

## Task 2: Leaderboard API Endpoints
**Priority**: High
**Scope**: Add /api/leaderboard?type=associations_by_amount|persons_by_amount|top_conflicts
**Files**: src/main.py, src/models.py (add computed properties if needed)
**Deliverable**: Working leaderboard API + HTMX dashboard section
**Test**: /api/leaderboard returns sorted data

## Task 3: Person + Association Profile Pages
**Priority**: High
**Scope**: Add Person and Association models, link them to Subventions
**Files**: src/models.py, src/main.py, src/templates/
**Deliverable**: /association/{siret} and /person/{id} pages with subvention history
**Test**: Profile pages render with real data

## Task 4: Alert Rules + Email Notifications
**Priority**: High
**Scope**: AlertRule model, alert matching after import, email sending via SMTP
**Files**: src/models.py, src/scraper.py (generate_alerts), new src/notifications.py
**Deliverable**: Users can create alert rules, get emails on new high-risk subventions
**Test**: Send test alert to configured email

## Task 5: Weekly Report Generator
**Priority**: Medium
**Scope**: Generate weekly email digest of new subventions + conflicts
**Files**: new src/reports.py, src/templates/weekly_report.html
**Deliverable**: CLI tool: python -m src.reports --send-weekly
**Test**: Report generates with correct stats

## Task 6: Docker + Nginx + Systemd Production Setup
**Priority**: Medium
**Scope**: Docker multi-stage build, nginx reverse proxy, systemd service, SSL
**Files**: Dockerfile, docker-compose.prod.yml, nginx.conf, systemd/
**Deliverable**: Full production deployment on decisionhelper@192.168.0.16
**Test**: HTTPS working, app accessible on standard port

## Task 7: Historical Analysis + Trend Detection
**Priority**: Low
**Scope**: Year-over-year trends per association/sector, budget comparison
**Files**: src/analytics.py
**Deliverable**: /api/analytics/trends endpoint
**Test**: Trend data matches imported dataset

## Task 8: Pappers.fr Enrichment Pipeline
**Priority**: Medium
**Scope**: Query Pappers.fr by SIRET, extract board members, store Person nodes
**Files**: new src/enrichment.py
**Deliverable**: Board member data for watched associations
**Test**: At least 5 associations enriched with board members

## Task 9: Frontend Polish + HTMX Dashboard v2
**Priority**: Medium
**Scope**: Search bar, pagination, filters, charts (simple HTML/HTMX)
**Files**: src/templates/dashboard.html, src/templates/leaderboard.html, src/static/
**Deliverable**: Full-featured dashboard with all features above
**Test**: Dashboard usable without JS framework

## Task 10: Stripe Payments + Subscription Tiers
**Priority**: Low
**Scope**: Stripe integration, free/premium tiers, subscription management
**Files**: src/payments.py
**Deliverable**: /api/subscribe endpoint, premium-only features gated
**Test**: Test subscription flow with Stripe test keys
