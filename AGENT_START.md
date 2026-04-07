# AGENT_START.md — Read This First

> You are working on **OpenConstructionERP** — open-source construction cost estimation and project management platform.
> Owner: **Artem Boiko** (DataDrivenConstruction). Solo developer. 10+ years in construction estimation.

---

## Step 1: Read These Files (in order)

1. **This file** — you're here. Quick orientation.
2. **`CLAUDE.md`** (repo root) — architecture, conventions, code style, module structure. Authoritative.
3. **`OpenConstructionERP_APPLICATION_PLAN.md`** (in `~/Downloads/`) — full master plan: all 50 modules, phasing, data models, inter-module flows, QA process. Read when working on new modules or cross-module features.

Path to master plan:
```
C:\Users\Artem Boiko\Downloads\OpenConstructionERP_APPLICATION_PLAN.md
```

---

## Step 2: Know Where We Are

| Key | Value |
|-----|-------|
| Current version | **v0.8.0** (production) |
| Current phase | **Phase 0 complete** (CI green). Next: Phase 9 (i18n Foundation) per master plan |
| Production URL | https://openconstructionerp.com |
| Demo SPA | https://openconstructionerp.com/demo/ |
| API health | https://openconstructionerp.com/api/health |
| GitHub | https://github.com/datadrivenconstruction/OpenConstructionERP |
| Stack | Python 3.12 / FastAPI + React 18 / TypeScript / Vite + SQLite (dev) / PostgreSQL (prod optional) |
| Existing modules | 11 core (ai, assemblies, backup, boq, cad, catalog, costs, markups, punchlist, requirements, users, validation) + schedule, documents, fieldreports, risk, takeoff, reporting, changeorders, costmodel, tendering |
| Target | v1.0.0 — 50 modules (39 core + 11 regional/enterprise packs) |

### Phase Roadmap (from master plan)

```
Phase 0  ✅ CI fix (done — ruff clean, 512 backend + 515 frontend tests passing)
Phase 9     Internationalization Foundation (multi-currency, locale, calendars, taxes, RTL)
Phase 10    Module System v2 (install/uninstall/marketplace)
Phase 11    Shared Infrastructure (contacts, notifications, collaboration, teams, meetings, CDE, transmittals, OpenCDE)
Phase 12    Projects + BOQ polish (WBS, milestones, lock, revisions)
Phase 13    Schedule + CPM + own Gantt (SVG-based)
Phase 14    Finance + Procurement
Phase 15    Field + Quality + Safety + Tasks
Phase 16    Variations + Risk + RFI + Submittals + NCR
Phase 17    Documents + Takeoff polish
Phase 18    BIM Hub + own BIM Viewer (Three.js + glTF)
Phase 19    Reporting + Dashboards
Phase 20    Regional Packs (US/DACH/UK/RU/ME/AsiaPac/India/LatAm)
Phase 21    Enterprise + Feature Packs
Phase 22    v1.0.0 release
```

---

## Step 3: Hard Rules (violating any = rejected work)

### Code
- **English** for all code, comments, variable names, docs
- **Russian** for discussion (when Artem writes in Russian)
- **Conventional Commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `ci:`, `test:`
- **NO Claude/Anthropic references** in commits, code, or PR bodies — history was rewritten to remove them
- **NO hardcoded UI strings** — all via `useTranslation()` / i18n keys (20 languages)
- **NO IfcOpenShell, BCF libs, native IFC** — all CAD via ODA SDK + Rust reverse engineering
- **BIM viewer = own** — Three.js + glTF/GLB, NOT xeokit or third-party
- **Validation is mandatory** — no module without validation rules
- **AI = human-confirmed** — confidence scores, no auto-actions without review

### Process
- **Quality > Speed** — no TODOs in production, no "fix later", no "good enough"
- **One phase at a time** — don't jump ahead in the master plan
- **One module at a time** — complete fully (models → schemas → repo → service → router → tests → i18n) before next
- **Parallel agents within a phase** — backend + frontend + i18n can run simultaneously
- **BOQ regression test** — mandatory before every merge
- **Don't add features** beyond what's asked
- **Don't refactor** unrelated code
- **Don't create files** unless absolutely necessary
- **Don't skip versions** — every bump needs changelog entry + all version files updated

### Version Bump Checklist
1. `frontend/package.json` → `version`
2. `backend/pyproject.toml` → `version`
3. `backend/app/config.py` → verify `app_version` (reads from `importlib.metadata` now)
4. `CHANGELOG.md` → new entry (Keep-a-Changelog format)
5. `frontend/src/features/about/Changelog.tsx` → visible in-app entry
6. Git tag: `git tag -a v0.x.y -m "OpenConstructionERP v0.x.y — description"`

---

## Step 4: Local Development

### Backend
```bash
cd "C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/backend"
python -m uvicorn app.main:create_app --factory --port 8000 --host 0.0.0.0
```
- DB: SQLite at `./openestimate.db`
- Health: http://localhost:8000/api/health
- API docs: http://localhost:8000/docs
- Demo login: `demo@openestimator.io` / `DemoPass1234!`

### Frontend
```bash
cd "C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/frontend"
npm run dev
```
- http://localhost:5173 (Vite proxy: `/api` → backend)

### Lint & Test
```bash
# Backend
cd backend && ruff check . && ruff format --check . && python -m pytest

# Frontend
cd frontend && npx eslint src && npx tsc --noEmit && npx vitest run
```

---

## Step 5: Deploy to Production

```bash
# 1. Push both branches
git push origin master:master && git push origin master:main

# 2. SSH deploy
ssh root@openconstructionerp.com '
  cd /root/OpenConstructionERP && git fetch origin && git reset --hard origin/main
  source venv/bin/activate && pip install -e ./backend
  cd frontend && npm install --legacy-peer-deps && npx vite build
  systemctl restart openconstructionerp
  curl -s http://localhost:9090/api/health
'
```

- VPS: Hetzner Ubuntu 24.04, SSH key auth pre-configured
- Backend on port 9090, fronted by Caddy reverse proxy
- Frontend served via backend SPA fallback (`SERVE_FRONTEND=true`)

---

## Step 6: When Uncertain

- **Ambiguous task?** → Propose 2-3 options with trade-offs, wait for Artem's pick
- **Delete existing code?** → Explain why, get confirmation
- **Add dependency?** → Justify (check stdlib first)
- **Cross-module change?** → Read master plan §5 (inter-module flows) first
