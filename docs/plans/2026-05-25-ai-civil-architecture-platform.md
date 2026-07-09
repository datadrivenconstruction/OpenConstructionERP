# AI Civil Architecture Platform — Brainstorm

**Date:** 2026-05-25
**Owner:** Ali Sadikin
**Status:** Design locked — ready for `gaspol-plan`
**Skill:** gaspol-brainstorm v1.2

---

## Context & Motivation

Ali baru beli **rumah 2nd hand 2 lantai di Batam** dan mau renovasi total (arsitektur + interior). Butuh satu platform yang:

1. AI bantuin **design layout** bangunan (2D floor plan editor)
2. AI generate **3D visualization** (real-time + photoreal render)
3. AI susun **RAB (Rencana Anggaran Biaya)** dengan harga material market Batam
4. Reusable jadi **multi-tenant platform** (orang lain bisa pakai)

## Design (locked via AskUserQuestion)

| Decision | Choice | Rationale |
|---|---|---|
| **Architecture base** | Fork [OpenConstructionERP](https://github.com/datadrivenconstruction/OpenConstructionERP) | 264★, last commit 2026-05-24, BIM-to-BOQ built-in, 55k cost DB, AI takeoff, APAC supported, pip install. Saves 6-12 months of foundation work. |
| **Scope** | Platform-Ready Multi-Tenant | Built untuk multi-user dari awal — auth, project switcher, region selector. Heavier upfront tapi reusable. |
| **Pricing data** | Hybrid SNI coefficient + scraped Batam | SNI 2835/2836/2837/7395 + AHSP 2022 untuk coefficient; harga unit di-scrape weekly dari arsiteqi.or.id, sobatbangun.com, mbdkontraktor.com. AI fallback. |
| **License** | AGPL-3.0 (comply, public repo) | OpenConstructionERP AGPL-3.0 copyleft kuat — fork harus open-source. Cocok untuk commodity tool industri konstruksi Indonesia. |
| **AI stack** | Multi-provider: Claude + Gemini + local | Claude Opus = reasoning + BOQ. Gemini 3 Image (Nano Banana Pro) = photoreal render. Local PaddleOCR + YOLOv11 = PDF takeoff. Multi-vendor risk hedge. |
| **Deployment** | Self-hosted Docker Compose | Server Ali di Batam (atau VPS). Traefik + Postgres + FastAPI + React + Qdrant dalam 1 docker-compose.yml. |

## Architecture Blueprint

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React 18 + TS)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Floor Editor │  │  3D Viewer   │  │  RAB Editor (BOQ)    │  │
│  │ (embed       │  │ (IFC.js +    │  │  - Hierarchical      │  │
│  │  open3d-     │  │  Three.js)   │  │  - SNI/AHSP coef     │  │
│  │  Floorplan)  │  │              │  │  - Batam unit price  │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  AI Render Studio (embed AIStudioFloorPlan + Gemini)     │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ REST + WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND (Python 3.12 + FastAPI)               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  Auth + Tenant  │  │  Project Mgmt   │  │  BOQ Engine    │  │
│  │  (Supabase or   │  │  (OpenConstr-   │  │  (forked from  │  │
│  │   built-in)     │  │   uctionERP)    │  │   OpenConstr.) │  │
│  └─────────────────┘  └─────────────────┘  └────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  CAD/BIM Parser │  │  AI Takeoff     │  │  RAB Generator │  │
│  │  (cad2data,     │  │  (PaddleOCR +   │  │  (Claude Opus  │  │
│  │   IFC/RVT/DWG)  │  │   YOLOv11)      │  │   + SNI rules) │  │
│  └─────────────────┘  └─────────────────┘  └────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │  Batam Scraper  │  │  3D Renderer    │  │  Export PDF    │  │
│  │  (weekly cron)  │  │  (Gemini Image  │  │  (BOQ + 3D)    │  │
│  │                 │  │   Pro / Nano    │  │                │  │
│  │                 │  │   Banana)       │  │                │  │
│  └─────────────────┘  └─────────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐ │
│  │  PostgreSQL  │ │  LanceDB     │ │  Qdrant      │ │  S3 /  │ │
│  │  (relational │ │  (BIM        │ │  (vector     │ │  MinIO │ │
│  │   + tenant)  │ │   indexing)  │ │   search     │ │  files │ │
│  │              │ │              │ │   for cost   │ │        │ │
│  │              │ │              │ │   matching)  │ │        │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ └────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Module Inventory (Fork + Build)

### Forked from OpenConstructionERP (keep as-is or extend)

| Module | Status | Action |
|---|---|---|
| BOQ editor (hierarchical) | ✅ Keep | Use as-is |
| Multi-currency | ✅ Keep | Default IDR + lock to Batam locale |
| BIM ingest (IFC/RVT/DWG/DGN) | ✅ Keep | Use as-is via `cad2data` |
| PDF takeoff (PaddleOCR) | ✅ Keep | Use as-is |
| AI Estimate (Photo→BOQ) | ✅ Keep | Swap upstream LLM to Claude Opus |
| Cost DB (55k items, global) | 🔄 Replace | Strip → seed with SNI-AHSP Indonesia + Batam |
| 4D/5D cost planning | ✅ Keep | Use as-is |
| Real-time collaboration | ✅ Keep | Multi-tenant friendly |

### New modules (build)

| Module | Why | Tech |
|---|---|---|
| **2D Floor Plan Editor** | OpenConstructionERP fokus ke importing existing BIM, bukan menggambar dari nol. Ali butuh draw layout rumahnya dari scratch. | Embed [open3dFloorplan](https://github.com/theLodgeBots/open3dFloorplan) (SvelteKit + Three.js, MIT) as iframe atau port React |
| **AI Photoreal Render** | OpenConstructionERP fokus engineering, bukan interior visualization. | Adapt [AIStudioFloorPlan](https://github.com/dseditor/AIStudioFloorPlan) pattern + Gemini 3 Image Pro |
| **Batam Price Scraper** | OpenConstructionERP cost DB global. Butuh harga riil Batam mingguan. | FastAPI scheduler + Playwright/Firecrawl → scrape arsiteqi.or.id, sobatbangun.com, mbdkontraktor.com. Store ke Postgres + Qdrant. |
| **SNI/AHSP Coefficient DB** | Methodology Indonesia official. | Seed manual dari PDF SNI 2835/2836/2837/7395 + AHSP 2022. Format: `{pekerjaan_id, material[], upah[], alat[]}`. |
| **RAB Generator (AI)** | Bridge antara floor plan + cost DB. | Claude Opus tool-use: input floor plan IFC → output BOQ items + qty + total. Verify via PaddleOCR cross-check. |
| **Multi-tenant Auth** | Built-in OpenConstructionERP minim. | Supabase Auth + Row Level Security di Postgres. Tenant per project. |
| **Region Selector** | Default Batam, extensible. | DB table `regions` + per-region cost multiplier. |

## Data Integration Map

| Component | Data Source | Existing? | Notes |
|---|---|---|---|
| BOQ items | PostgreSQL `boq_items` table | ✅ (in fork) | Hierarchical, fork schema as-is |
| Cost DB (coefficient) | PostgreSQL `cost_coefficients` | 🔨 New seed | From SNI 2835/2836/2837/7395 + AHSP 2022 PDFs (manual parse) |
| Cost DB (unit price Batam) | PostgreSQL `material_prices` + Qdrant index | 🔨 New | Weekly scraper from arsiteqi.or.id, sobatbangun.com, mbdkontraktor.com |
| Floor plan geometry | LanceDB (vectorized) + JSON in Postgres | ✅ + 🔨 | LanceDB exists in fork. JSON schema custom for open3dFloorplan export |
| 3D model (IFC/RVT/DWG) | S3/MinIO file storage | ✅ (in fork) | `cad2data` parser already present |
| AI render images | S3/MinIO + Postgres `renders` metadata | 🔨 New | Gemini 3 Image Pro output |
| Auth + tenants | Supabase or built-in Postgres `users`/`tenants` | 🔨 Decision pending | Recommend Supabase (faster) |
| Audit log | Postgres `audit_log` | ✅ (in fork) | Use as-is for compliance |

## Implementation Feasibility — No Placeholders

| Risk | Real implementation path | Fallback if stuck |
|---|---|---|
| AGPL-3.0 obligation | Public repo from day 1 (`github.com/alisadikinma/ai-civil-architecture`). README discloses AGPL-3.0. | None needed — AGPL is friendly to personal + open commercial use |
| Batam scraper site changes | Use Firecrawl extract mode (JSON schema). Per-site adapter pattern. Weekly cron monitors success rate, alerts via Telegram bot. | LLM-based extraction fallback (Claude reads HTML → JSON) |
| OpenConstructionERP upstream changes | Fork from specific tag (v3.0). Cherry-pick critical updates monthly. Document divergence ADRs. | Freeze at v3.0 + add patches locally |
| Gemini 3 Image API cost | Cache renders aggressively (Qdrant lookup by prompt hash). Limit free tier to N renders/user. | Local ComfyUI + Stable Diffusion XL as fallback |
| Claude Opus reasoning cost | Use Sonnet 4.6 for routine BOQ generation. Reserve Opus for complex multi-room reasoning. | Self-host Llama 3.3 70B on Ali's GPU server |
| SNI PDF parsing | Manual seed (one-time, ~1 week effort). Document each pekerjaan as YAML. Version-controlled. | Crowdsource later (open repo accepts PRs) |
| IFC export from open3dFloorplan | Repo has Three.js geometry — write custom IFC exporter using `web-ifc` library (BimEdit). | Use STL/glTF intermediate, OpenConstructionERP imports gltf too |

## Tech Stack Summary

**Backend**
- Python 3.12 + FastAPI (fork OpenConstructionERP)
- PostgreSQL 16 + LanceDB + Qdrant
- PaddleOCR + YOLOv11 (PDF + image takeoff)
- Playwright/Firecrawl (Batam scraper)
- APScheduler (cron jobs)

**Frontend**
- React 18 + TypeScript + Vite (fork OpenConstructionERP)
- Three.js + IFC.js (3D viewer)
- open3dFloorplan port atau iframe (2D editor)
- TanStack Query + Zustand (state)

**AI Layer**
- Claude Opus 4.7 (reasoning, BOQ generation)
- Claude Sonnet 4.6 (routine takeoff parsing)
- Gemini 3 Image Pro / Nano Banana Pro (photoreal render)
- PaddleOCR + YOLOv11 local (CV)
- Anthropic SDK + Google Gen AI SDK + Ollama fallback

**Deployment**
- Docker Compose (single `docker-compose.yml`)
- Traefik (auto HTTPS via Let's Encrypt)
- Postgres + LanceDB + Qdrant + MinIO containers
- Self-hosted di server Batam atau VPS

**License**
- AGPL-3.0 (mandatory karena fork OpenConstructionERP)

## Sources & Citations

### Primary GitHub repos
- [datadrivenconstruction/OpenConstructionERP](https://github.com/datadrivenconstruction/OpenConstructionERP) — fork base
- [theLodgeBots/open3dFloorplan](https://github.com/theLodgeBots/open3dFloorplan) — 2D editor (MIT)
- [dseditor/AIStudioFloorPlan](https://github.com/dseditor/AIStudioFloorPlan) — AI render pattern
- [ThatOpen/web-ifc-viewer](https://github.com/ThatOpen/web-ifc-viewer) — IFC.js BIM viewer (MIT)
- [furnishup/blueprint3d](https://github.com/furnishup/blueprint3d) — interior 3D models reference
- [aboen/rab](https://github.com/aboen/rab) — Indonesia RAB schema reference

### Indonesia construction standards
- SNI 2835:2008 (pekerjaan tanah)
- SNI 2836:2008 (pondasi)
- SNI 2837:2008 (plesteran)
- SNI 7395:2008 (lantai & dinding)
- AHSP 2022 (Analisa Harga Satuan Pekerjaan, Kemen-PUPR)

### Batam pricing sources (scraper targets)
- [arsiteqi.or.id/upah/tukang-bangunan-batam](https://arsiteqi.or.id/upah/tukang-bangunan-batam/) — upah tukang Batam
- [sobatbangun.com](https://sobatbangun.com/) — harga material updated bulanan
- [mbdkontraktor.com](https://www.mbdkontraktor.com/) — daftar material
- [sutindosurya.com](https://sutindosurya.com/) — estimasi 2026

### Reference (commercial RAB tools — competitive analysis)
- estimator.id, rabestimator.id, ScaleOcean, Daksasoft, RAB xPro — domestic competitors
- OpenConstructionERP, [Maket.ai](https://www.maket.ai/), Plan7Architect — global competitors

## Next Step

→ Hand off ke `/gaspol-dev:gaspol-plan` untuk break down ke phases dengan Data Integration Map per-phase, criteria verification, dan parallelization decisions.

**Recommended initial phase order:**
1. Phase 0: Fork OpenConstructionERP + local Docker stack running
2. Phase 1: Strip global cost DB + seed SNI/AHSP Indonesia
3. Phase 2: Batam scraper (3 sites, weekly cron)
4. Phase 3: Multi-tenant auth (Supabase or built-in)
5. Phase 4: Embed open3dFloorplan as 2D editor module
6. Phase 5: AI render integration (Gemini 3 Image)
7. Phase 6: RAB Generator (Claude Opus tool-use, floor plan → BOQ)
8. Phase 7: Deploy to Ali's Batam server + Traefik SSL
9. Phase 8: Use it for actual rumah Ali renovation (end-to-end test)
