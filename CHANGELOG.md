# Changelog

All notable changes to OpenConstructionERP are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-03-30

### Added
- **BOQ Editor** — Hierarchical Bill of Quantities with AG Grid, inline editing, keyboard navigation
- **Resource Management** — Material, labor, equipment resources per position with Catalog Picker
- **Cost Database** — CWICR 55,000+ cost items across 11 regional databases (US, UK, DE, FR, ES, PT, RU, AE, CN, IN, CA)
- **Resource Catalog** — Searchable catalog with materials, labor, equipment, operators
- **20 Regional Standards** — DIN 276, NRM, MasterFormat, GAEB, DPGF, GESN, GB/T 50500, CPWD, Birim Fiyat, Sekisan, Computo Metrico, STABU, KNR, Korean Standard, NS 3420, URS, ACMM, CSI/CIQS, FIDIC, PBC
- **42 Validation Rules** — 13 rule sets: boq_quality, din276, gaeb, nrm, masterformat, sinapi, gesn, dpgf, onorm, gbt50500, cpwd, birimfiyat, sekisan
- **4D Schedule** — Gantt chart with CPM, dependencies, resource assignment
- **5D Cost Model** — Earned Value Management (SPI, CPI, EAC), S-curve, budget tracking
- **Risk Register** — Risk matrix (probability x impact), mitigation strategies
- **Change Orders** — Scope changes with cost/schedule impact, approval workflow
- **Tendering** — Bid packages, subcontractor management, bid comparison
- **Reports** — 12 report templates (PDF, Excel, GAEB XML, CSV)
- **Document Management** — Upload, categorize, search project files
- **AI Quick Estimate** — Generate BOQ from text, photo, PDF, Excel, CAD/BIM
- **AI Cost Advisor** — Chat interface for cost questions with database context
- **AI Smart Actions** — Enhance descriptions, suggest prerequisites, escalate rates, check scope
- **7 AI Providers** — Anthropic, OpenAI, Gemini, OpenRouter, Mistral, Groq, DeepSeek
- **20+ Languages** — Full i18n: EN, DE, FR, ES, PT, RU, ZH, AR, HI, TR, IT, NL, PL, CS, JA, KO, SV, NO, DA, FI
- **Dark Mode** — Full dark theme with system preference detection
- **Onboarding Wizard** — 7-step setup: Language, Cost DB, Catalog, Demo Projects, AI, Finish
- **5 Demo Projects** — Berlin (DIN 276), London (NRM), Houston (MasterFormat), Paris (DPGF), Dubai (FIDIC)
- **Backup & Restore** — Export/import user data as ZIP with manifest
- **Version Updates** — Automatic GitHub release checking with sidebar notification
- **SQLite Auto-Migration** — Seamless schema upgrades without data loss
- **Error Logging** — Anonymized error reports with PII scrubbing
- **Command Palette** — Ctrl+K search across pages, projects, BOQs
- **Keyboard Shortcuts** — Full keyboard navigation (?, Ctrl+N, Ctrl+Shift+N, etc.)
- **Locale-Aware Units** — Language-specific measurement units (Stk, sht, ge, etc.)

### Infrastructure
- FastAPI backend with 17 auto-discovered modules
- React 18 + TypeScript + Vite frontend
- SQLite (dev) / PostgreSQL (prod)
- LanceDB vector search (168K+ vectors)
- Modular plugin architecture
- AGPL-3.0 license

### Security
- JWT authentication with bcrypt password hashing
- Role-based access control (RBAC)
- CORS middleware with configurable origins
- Input validation via Pydantic v2
