<div align="center">

# OpenConstructionERP

**Open-source ERP for construction estimation and project management**

Professional BOQ, 4D/5D planning, AI-powered estimation, CAD/BIM takeoff — all in one platform.

[Demo](https://openconstructionerp.com) · [Documentation](https://openconstructionerp.com/docs) · [Discussions](https://t.me/datadrivenconstruction) · [Report Bug](https://github.com/datadrivenconstruction/OpenConstructionERP/issues)

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.3.1-green)](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/tag/v2.3.1)
[![PyPI](https://img.shields.io/pypi/v/openconstructionerp?color=informational&label=pypi)](https://pypi.org/project/openconstructionerp/)
[![Downloads (pepy · per month)](https://static.pepy.tech/personalized-badge/openconstructionerp?period=month&units=international_system&left_color=grey&right_color=blue&left_text=downloads%20(pepy%20%C2%B7%20per%20month))](https://pepy.tech/project/openconstructionerp)
[![Stars](https://img.shields.io/github/stars/datadrivenconstruction/OpenConstructionERP?style=flat&logo=github)](https://github.com/datadrivenconstruction/OpenConstructionERP/stargazers)
<br/>
[![Last commit](https://img.shields.io/github/last-commit/datadrivenconstruction/OpenConstructionERP?color=informational)](https://github.com/datadrivenconstruction/OpenConstructionERP/commits/main)
![Languages](https://img.shields.io/badge/languages-21-orange)
![Cost Items](https://img.shields.io/badge/cost_items-55%2C000%2B-red)

[![▶ Play the full 12-minute walkthrough (with music)](docs/screenshots/hero-overview.jpg)](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/download/v2.0.0/oce_full_demo.mp4)

<sub>🎬 <b>Click the image above</b> to play the full 12-minute walkthrough (with music) — onboarding → BoQ → BIM → DWG → PDF → AI → dashboard</sub>

*100% open source · 55,000+ cost items · AI estimation · 21 languages · Self-hosted*

</div>

---

<details open>
<summary><h2>Table of Contents</h2></summary>

<table width="100%">
<colgroup>
<col width="33%"/>
<col width="34%"/>
<col width="33%"/>
</colgroup>
<tr>
<td valign="top">

**Getting Started**
- [Why OpenConstructionERP?](#why-openconstructionerp)
- [See It In Action](#see-it-in-action)
- [Quick Start](#quick-start)
- [Demo Accounts](#demo-accounts)

</td>
<td valign="top">

**Core Modules**
- [BOQ Management](#-bill-of-quantities-boq-management)
- [Cost Databases & Catalog](#%EF%B8%8F-cost-databases--resource-catalog)
- [CAD/BIM & AI Estimation](#%EF%B8%8F-cadbim-takeoff--ai-estimation)

</td>
<td valign="top">

**Planning & Delivery**
- [4D Scheduling & 5D Cost](#-4d-scheduling--5d-cost-model)
- [Tendering, Risk & Reports](#-tendering-risk--reporting)
- [Requirements & Quality](#-requirements--quality-gates)

</td>
</tr>
<tr>
<td valign="top">

**Field Tools**
- [PDF Markups & Annotations](#%EF%B8%8F-pdf-markups--annotations)
- [Punch List](#-punch-list)
- [Validation Engine](#%EF%B8%8F-validation--compliance-engine)

</td>
<td valign="top">

**Standards & Onboarding**
- [20 Regional Standards](#-20-regional-standards)
- [Guided Onboarding](#-guided-onboarding)
- [Key Features Overview](#key-features)

</td>
<td valign="top">

**Technical**
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Security](#security)

</td>
</tr>
<tr>
<td valign="top">

**Project & Community**
- [Support the Project](#support-the-project)

</td>
<td valign="top">

**Compliance**
- [AI Disclaimer](#ai-disclaimer)
- [Trademarks](#trademarks)
- [Export Control](#export-control)

</td>
<td valign="top">

**Legal & Privacy**
- [Star History](#star-history)
- [License](#license)
- [Privacy and Terms](#privacy-and-terms)

</td>
</tr>
</table>

</details>

---

⭐ <b>If you want to see new updates and database versions and if you find our tools useful please give our repositories a star to see more similar applications for the construction industry.</b>
Star OpenConstructionERP on GitHub and be instantly notified of new releases.
<p align="center">
  <br>
  <img src="https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto/blob/main/DDC_in_additon/DDC_readme_content/OCE%20star%20GitHub.gif" width="100%"/>
  <br></br>
</p>

---

## ✨ What's New in v2.0.0

The second stable release — shipped **April 20, 2026**. Supersedes the entire 1.x line.

<table>
<tr>
<td width="50%" valign="top">

**🔧 Reliability**
- AI Chat SSE streams survive middleware cancellation
- AI API keys survive backend restarts (absolute-path `.env` loading, Fernet decryption gating)
- DWG Takeoff respects DXF `$INSUNITS` end-to-end
- BIM Linked-BOQ panel populates via new aggregate endpoint
- 48 backend integration tests fixed — 61/61 green

**🧩 Module Developer Experience**
- `MODULES.md` at repo root — single entry point
- New in-app `/modules/developer-guide` page
- **"+ Add module"** CTA in the sidebar
- Covers backend Python + frontend React scaffolding

</td>
<td width="50%" valign="top">

**📊 CAD-BIM BI Explorer**
- Renamed from *CAD-BIM Explorer*
- KPI strip: Elements · Volume · Area · Length · Weight · Categories · Levels
- Power-BI-style data bars in pivot cells
- Slicers, saved views, drill-down from charts

**✨ UX Polish**
- Dashboard: Quick Start is now pure-navigation, explicit *New Estimate* button, Quality Score icon + click-through
- About page: Artem Boiko avatar, DDC logo, full-width clickable book banner, LinkedIn / Telegram / X community block
- Layered DDC provenance watermarks for copyright enforcement

</td>
</tr>
</table>

See the [full v2.0.0 changelog](CHANGELOG.md#200--2026-04-20) or the [v2.0.0 GitHub release](https://github.com/datadrivenconstruction/OpenConstructionERP/releases/tag/v2.0.0).

---

## Why OpenConstructionERP?

Construction cost estimation software is expensive, closed-source, and locked to specific regions. OpenConstructionERP changes that.

| What you get | How it works |
|-------------|-------------|
| **Free forever** | AGPL-3.0 license. No subscriptions, no per-seat fees, no vendor lock-in. |
| **Your data, your server** | Self-hosted. Everything runs on your machine — nothing leaves your network. |
| **21 languages** | Full UI translation: English, German, French, Spanish, Portuguese, Russian, Chinese, Arabic, Hindi, Japanese, Korean, and 10 more. |
| **20 regional standards** | DIN 276, NRM 1/2, CSI MasterFormat, GAEB, ГЭСН, DPGF, GB/T 50500, CPWD, and more. |
| **AI-powered** | Connect any LLM provider (Anthropic, OpenAI, Gemini, Mistral, Groq, DeepSeek) for smart estimation. |
| **55,000+ cost items** | CWICR database with 11 regional pricing databases (DACH, UK, US, France, Spain, Brazil, Russia, UAE, China, India, Canada). |

### How It Compares

<table>
<tr>
<th align="left">Capability</th>
<th align="center">OpenConstructionERP</th>
<th align="center">RIB iTWO</th>
<th align="center">Exactal CostX</th>
<th align="center">Sage Estimating</th>
<th align="center">Bluebeam</th>
</tr>
<tr><td><b>License</b></td><td align="center">AGPL-3.0 (free)</td><td align="center">Proprietary</td><td align="center">Proprietary</td><td align="center">Proprietary</td><td align="center">Proprietary</td></tr>
<tr><td><b>Self-hosted / offline</b></td><td align="center">&#10004;</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#9888; partial</td><td align="center">&#10006;</td></tr>
<tr><td><b>Price</b></td><td align="center"><b>Free forever</b></td><td align="center">~&#8364;500/mo</td><td align="center">~&#8364;300/mo</td><td align="center">~&#8364;200/mo</td><td align="center">~&#8364;30/mo</td></tr>
<tr><td><b>AI estimation</b></td><td align="center">&#10004; 7 LLM providers</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
<tr><td><b>UI languages</b></td><td align="center"><b>21</b></td><td align="center">5</td><td align="center">3</td><td align="center">2</td><td align="center">8</td></tr>
<tr><td><b>Regional standards</b></td><td align="center"><b>20</b></td><td align="center">4</td><td align="center">3</td><td align="center">2</td><td align="center">&mdash;</td></tr>
<tr><td><b>BOQ editor</b></td><td align="center">&#10004;</td><td align="center">&#10004;</td><td align="center">&#10004;</td><td align="center">&#10004;</td><td align="center">&#10006;</td></tr>
<tr><td><b>CAD/BIM takeoff</b></td><td align="center">&#10004; RVT IFC DWG DGN</td><td align="center">&#10004;</td><td align="center">&#10004;</td><td align="center">&#10006;</td><td align="center">&#10004; PDF only</td></tr>
<tr><td><b>4D/5D planning</b></td><td align="center">&#10004;</td><td align="center">&#10004;</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
<tr><td><b>Cost database included</b></td><td align="center">&#10004; 55K+ items with rates</td><td align="center">&#10006; extra cost</td><td align="center">&#10006; extra cost</td><td align="center">&#10006; extra cost</td><td align="center">&#10006;</td></tr>
<tr><td><b>Resource catalog</b></td><td align="center">&#10004; 7K+ with prices</td><td align="center">&#10006; extra cost</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
<tr><td><b>Validation engine</b></td><td align="center">&#10004; 42 rules</td><td align="center">&#9888; limited</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
<tr><td><b>REST API</b></td><td align="center">&#10004; full access</td><td align="center">&#9888; limited</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
<tr><td><b>Real-time collaboration</b></td><td align="center">&#10004; soft locks + presence</td><td align="center">&#10004;</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
<tr><td><b>Open data export</b></td><td align="center">&#10004; GAEB, Excel, CSV, JSON, PDF</td><td align="center">&#9888; limited</td><td align="center">&#9888; limited</td><td align="center">&#9888; limited</td><td align="center">PDF only</td></tr>
<tr><td><b>BIM requirements (IDS/COBie)</b></td><td align="center">&#10004; import + export</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td><td align="center">&#10006;</td></tr>
</table>

<sub>Product names are trademarks of their respective owners. This comparison is based on publicly available information as of Q1 2026. Pricing is approximate (per-seat, list price) and may vary by region. OpenConstructionERP is not affiliated with any of the listed vendors.</sub>

---

## See It In Action

Each block below is a short GIF cut from the full walkthrough above — same order as the video, so you can jump to whichever workflow matters most.

<table>
<tr>
<td align="center" width="50%">
<strong>👤 1 · Role-Based Onboarding</strong><br/>
<em>Sign in as Admin / Estimator / Manager — the wizard pre-selects the right 17 of 46 modules for your role</em><br/><br/>
<img src="docs/gifs/07_Role_Based_Onboarding.gif" alt="Role-Based Onboarding" width="400" />
</td>
<td align="center" width="50%">
<strong>🌍 2 · New Project, Any Region</strong><br/>
<em>Pick currency, classification standard, regional factor — live map & weather come along for free</em><br/><br/>
<img src="docs/gifs/08_New_Project_Global.gif" alt="New Project Global" width="400" />
</td>
</tr>
<tr>
<td align="center">
<strong>⚡ 3 · Build the Bill of Quantities</strong><br/>
<em>Keyboard-first editor, 55K+ priced items, AI cost finder & Smart AI — quality score updates live</em><br/><br/>
<img src="docs/gifs/15_BoQ_Editor.gif" alt="BoQ Editor" width="400" />
</td>
<td align="center">
<strong>🏗️ 4 · BIM → BOQ Bulk Link</strong><br/>
<em>Link 100 Revit walls → one BOQ line with aggregated area / volume / length — no IfcOpenShell</em><br/><br/>
<img src="docs/gifs/09_Bulk_Link_BIM_Group.gif" alt="Bulk Link BIM Group" width="400" />
</td>
</tr>
<tr>
<td align="center">
<strong>📐 5 · DWG Drawings & Layers</strong><br/>
<em>636 wall entities across 10 DWG layers — every one linkable to the BOQ, measured in place</em><br/><br/>
<img src="docs/gifs/10_DWG_Layers.gif" alt="DWG Layers" width="400" />
</td>
<td align="center">
<strong>🖊️ 6 · PDF Takeoff</strong><br/>
<em>Drop a floorplan, measure distance / area / count, push the numbers straight into the BOQ</em><br/><br/>
<img src="docs/gifs/16_PDF_Takeoff_v2.gif" alt="PDF Takeoff" width="400" />
</td>
</tr>
<tr>
<td align="center">
<strong>💵 7 · Complete Estimate — $6.26M</strong><br/>
<em>Real Revit project → 215 positions, 88 sections, CWICR-priced, quality score 99</em><br/><br/>
<img src="docs/gifs/11_Complete_Estimate_6M.gif" alt="Complete Estimate" width="400" />
</td>
<td align="center">
<strong>✅ 8 · Every Module — BIM-Linked Tasks</strong><br/>
<em>Issues tied to exact model elements, tracked on a Kanban board alongside schedule, docs & requirements</em><br/><br/>
<img src="docs/gifs/12_Tasks_Linked_To_BIM.gif" alt="Tasks Linked To BIM" width="400" />
</td>
</tr>
<tr>
<td align="center">
<strong>📊 9 · Data Explorer — Pivot → BOQ</strong><br/>
<em>CAD-BIM Explorer pivot becomes 10 BOQ positions in one click — charts, data bars & drill-down included</em><br/><br/>
<img src="docs/gifs/13_Data_Explorer_Pivot.gif" alt="Data Explorer Pivot" width="400" />
</td>
<td align="center">
<strong>📸 10 · AI Estimate from a Photo</strong><br/>
<em>Upload a construction photo → GPT-4o + YOLO return a scoped BOQ in seconds, confidence-scored</em><br/><br/>
<img src="docs/gifs/02_AI_Photo_to_Estimate.gif" alt="AI Photo to Estimate" width="400" />
</td>
</tr>
<tr>
<td align="center">
<strong>🗺️ 11 · Global Portfolio Dashboard</strong><br/>
<em>7 projects, 4 continents, $28.3M in active estimates — one workspace, one map</em><br/><br/>
<img src="docs/gifs/14_Projects_Dashboard.gif" alt="Projects Dashboard" width="400" />
</td>
<td align="center">
<strong>🔍 Bonus · Instant Search</strong><br/>
<em>Find any of 55K+ cost items across 11 regional databases by keyword, unit or classification</em><br/><br/>
<img src="docs/gifs/05_Instant_Search.gif" alt="Instant Search" width="400" />
</td>
</tr>
</table>

---

### Complete Estimation Workflow

OpenConstructionERP covers the full lifecycle — from first sketch to final tender submission:

```
  Upload              Convert            Validate           Estimate           Tender
 ┌────────┐        ┌──────────┐       ┌───────────┐      ┌──────────┐      ┌──────────┐
 │PDF/CAD │───────▶│ Extract  │──────▶│ 42 rules  │─────▶│BOQ Editor│─────▶│ Bid Pkgs │
 │Photo   │        │quantities│       │ DIN/NRM/  │      │ + AI     │      │ Compare  │
 │Text    │        │ + AI     │       │ MasterFmt │      │ + Costs  │      │ Award    │
 └────────┘        └──────────┘       └───────────┘      └──────────┘      └──────────┘
                                                               │
                                                         ┌─────┴──────┐
                                                         │ 4D Schedule│
                                                         │ 5D Costs   │
                                                         │ Risk Reg.  │
                                                         │ Reports    │
                                                         └────────────┘
```

---

## Key Features

### 📊 Bill of Quantities (BOQ) Management

<img src="docs/screenshots/feature-boq.jpg" alt="BOQ Editor — Create, manage and analyze Bills of Quantities" width="800" />

Build professional cost estimates with a powerful BOQ editor:

- **Hierarchical BOQ structure** — Sections, positions, sub-positions with drag-and-drop reordering
- **Inline editing** — Click any cell to edit. Tab between fields. Undo/redo with Ctrl+Z
- **Resources & assemblies** — Link labor, materials, equipment to each position. Build reusable cost recipes
- **Markups** — Overhead, profit, VAT, contingency — configure per project or use regional defaults
- **Automatic calculations** — Quantity × unit rate = total. Section subtotals. Grand total with markups
- **Validation** — 42 built-in rules check for missing quantities, zero prices, duplicate items, and compliance with DIN 276, NRM, MasterFormat
- **Export** — Download as Excel, CSV, PDF report, or GAEB XML (X83)

### 🗄️ Cost Databases & Resource Catalog

<img src="docs/screenshots/feature-databases.jpg" alt="Cost Database — 55,000+ items across 11 regions" width="800" />

Access the world's construction pricing data:

- **CWICR database** — 55,000+ cost items covering all major construction trades. Available in 9 languages with 11 regional price sets
- **Smart search** — Find items by description, code, or classification. AI-powered semantic search matches meaning, not just keywords ("concrete wall" finds "reinforced partition C30/37")
- **Resource catalog** — 7,000+ materials, equipment, labor rates, and operators. Build custom assemblies from catalog items
- **Regional pricing** — Automatic price adjustment based on project location. Compare rates across regions
- **Import your data** — Upload your own cost database from Excel, CSV, or connect via API

### 🏗️ CAD/BIM Takeoff & AI Estimation

<img src="docs/screenshots/feature-takeoff-ai.jpg" alt="CAD/BIM Takeoff and AI-powered estimation" width="800" />

Extract quantities from any source — drawings, models, text, or photos:

- **CAD/BIM takeoff** — Upload Revit (.rvt), IFC, AutoCAD (.dwg), or MicroStation (.dgn) files. DDC converters extract elements with volumes, areas, and lengths automatically
- **Interactive QTO** — Choose how to group extracted data: by Category, Type, Level, Family. Format-specific presets for Revit and IFC
- **Linked geometry preview** — Click the BIM link badge on any BOQ position to see a 3D preview of linked elements with interactive rotate/zoom/pan controls
- **BIM Quantity Picker** — Select quantities (area, volume, length) directly from linked BIM elements and apply them to BOQ positions. The source parameter name is shown next to the unit
- **DWG polyline measurement** — Click any polyline in the DWG viewer to instantly see area, perimeter, and individual segment lengths with on-canvas labels
- **PDF measurement** — Open construction drawings directly in the browser. Measure distances, areas, and count elements with calibrated scale
- **AI estimation** — Describe your project in plain text, upload a building photo, or paste a PDF — AI generates a complete BOQ with quantities and market rates
- **AI Cost Advisor** — Ask questions about pricing, materials, or estimation methodology. AI answers using your cost database as context
- **Cost matching** — After AI generates an estimate, match each item against your CWICR database to replace AI-guessed rates with real market prices

### 📅 4D Scheduling & 5D Cost Model

Plan your project timeline and track costs over time:

- **Gantt chart** — Visual project schedule with drag-and-drop activities, dependencies (FS/FF/SS/SF), and critical path highlighting
- **Auto-generate from BOQ** — Create schedule activities directly from your BOQ sections with cost-proportional durations
- **Earned Value Management** — Track SPI, CPI, EAC, and variance. S-curve visualization shows planned vs actual progress
- **Budget tracking** — Set baselines, compare snapshots, run what-if scenarios
- **Monte Carlo simulation** — Risk-adjusted schedule analysis with probability distributions

### 📋 Tendering, Risk & Reporting

Complete your estimation workflow:

- **Tendering** — Create bid packages, distribute to subcontractors, collect and compare bids with side-by-side price mirror
- **Change orders** — Track scope changes with cost and schedule impact analysis
- **Risk register** — Probability × impact matrix, mitigation strategies, risk-adjusted contingency
- **Reports** — Generate professional PDF reports, Excel exports, GAEB XML. 12 built-in templates
- **Documents** — Centralized file management with version tracking and drag-and-drop upload

### 📝 Requirements & Quality Gates

Track and validate construction requirements with the EAC (Entity-Attribute-Constraint) system:

- **EAC Triplets** — Capture requirements as structured data: Entity (wall), Attribute (fire_rating), Constraint (≥ F90)
- **4 Quality Gates** — Completeness → Consistency → Coverage → Compliance. Run sequentially to validate requirements
- **BOQ Traceability** — Link each requirement to BOQ positions for full traceability from spec to estimate
- **Bulk Import** — Import requirements from structured text (pipe-delimited format)
- **Categories** — Structural, fire safety, thermal, acoustic, waterproofing, electrical, mechanical, architectural

### ✏️ PDF Markups & Annotations

Annotate construction drawings and documents directly in the browser:

- **10 markup types** — Cloud, arrow, text, rectangle, highlight, polygon, distance, area, count, stamp
- **Custom stamps** — Approved, Rejected, For Review, Revised, Final + create your own with logo and date
- **Scale calibration** — Set real-world scale per page for accurate measurements
- **Markups List** — Table view of all annotations with filters, search, and CSV export
- **BOQ Integration** — Link measurements directly to BOQ positions (quantity = measured value)

### ✅ Punch List

Track construction deficiencies from discovery to resolution:

- **5-stage workflow** — Open → In Progress → Resolved → Verified → Closed
- **Location pins** — Mark exact position on PDF drawings (x/y coordinates)
- **Priority levels** — Low, Medium, High, Critical with color coding
- **Photo attachments** — Upload photos of deficiencies from the field
- **Categories** — Structural, mechanical, electrical, architectural, fire safety, plumbing, finishing
- **PDF Export** — Generate punch list reports for stakeholder review
- **Verification control** — Different user must verify (not the resolver)

### 🌍 20 Regional Standards

| Standard | Region | Format |
|----------|--------|--------|
| DIN 276 / ÖNORM / SIA | Germany / Austria / Switzerland | Excel, CSV |
| NRM 1/2 (RICS) | United Kingdom | Excel, CSV |
| CSI MasterFormat | United States / Canada | Excel, CSV |
| GAEB DA XML 3.3 | DACH region | XML |
| DPGF / DQE | France | Excel, CSV |
| ГЭСН / ФЕР | Russia / CIS | Excel, CSV |
| GB/T 50500 | China | Excel, CSV |
| CPWD / IS 1200 | India | Excel, CSV |
| Bayındırlık Birim Fiyat | Turkey | Excel, CSV |
| 積算基準 (Sekisan) | Japan | Excel, CSV |
| Computo Metrico / DEI | Italy | Excel, CSV |
| STABU / RAW | Netherlands | Excel, CSV |
| KNR / KNNR | Poland | Excel, CSV |
| 표준품셈 | South Korea | Excel, CSV |
| NS 3420 / AMA | Nordic countries | Excel, CSV |
| ÚRS / TSKP | Czech Republic / Slovakia | Excel, CSV |
| ACMM / ANZSMM | Australia / New Zealand | Excel, CSV |
| CSI / CIQS | Canada | Excel, CSV |
| FIDIC | UAE / GCC | Excel, CSV |
| PBC / Base de Precios | Spain | Excel, CSV |

### 🛡️ Validation & Compliance Engine

Ensure your estimates meet regulatory standards before submission:

- **42 built-in rules** across 13 rule sets — DIN 276, NRM, MasterFormat, GAEB, and universal BOQ quality checks
- **Real-time validation** — Run checks with Ctrl+Shift+V. Each position gets a pass/warning/error indicator
- **Quality score** — Overall BOQ quality percentage (0–100%) visible in the toolbar
- **Drill-down** — Click any finding to jump directly to the affected BOQ position and fix it
- **Custom rules** — Define project-specific validation rules via the rule builder or Python scripting

### 🚀 Guided Onboarding

Get productive in under 10 minutes:

1. **Choose language** — Select from 21 languages. The entire UI switches instantly
2. **Select region** — Determines default cost database, currency, and classification standard
3. **Load cost database** — One-click import of CWICR pricing data for your region (55,000+ items)
4. **Import resource catalog** — Materials, labor, equipment, and pre-built assemblies
5. **Configure AI** *(optional)* — Enter an API key from any supported LLM provider
6. **Create your first project** — Set name, region, standard, and start estimating

---

## Quick Start

### Fastest: One-Line Install

```bash
# Linux / macOS
curl -sSL https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/scripts/install.sh | bash

# Windows (PowerShell)
irm https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionERP/main/scripts/install.ps1 | iex
```

Auto-detects Docker / Python / uv → installs and runs at **http://localhost:8080**

### Option 1: Docker (recommended)

```bash
git clone https://github.com/datadrivenconstruction/OpenConstructionERP.git
cd OpenConstructionERP
make quickstart
```

Open **http://localhost:8080** — builds everything in ~2 minutes.

### Option 2: Local Development (no Docker)

```bash
git clone https://github.com/datadrivenconstruction/OpenConstructionERP.git
cd OpenConstructionERP

# Install dependencies
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..

# Start (Linux/macOS)
make dev

# Start (Windows — two terminals)
# Terminal 1: cd backend && uvicorn app.main:create_app --factory --reload --port 8000
# Terminal 2: cd frontend && npm run dev
```

Open **http://localhost:5173** — requires Python 3.12+ and Node.js 20+. Uses SQLite by default — zero configuration needed.

### Option 3: pip install (full app — backend + frontend)

```bash
pip install openconstructionerp
openconstructionerp serve --open
```

One command installs everything. Opens browser at **http://localhost:8080** with full UI. Uses SQLite — zero config. [PyPI package](https://pypi.org/project/openconstructionerp/) (2.6 MB, includes pre-built frontend).

### Demo Accounts

Three demo accounts are created automatically on first start. **Passwords are
randomly generated per installation and printed to the container logs** on
first boot — look for the `=== DEMO ACCOUNTS ===` banner in `docker compose
logs backend` (or in the stdout of `make dev`). You can override them with
environment variables before the first start.

| Account | Email | Password source | Role |
|---------|-------|-----------------|------|
| Admin | `demo@openestimator.io` | `DEMO_ADMIN_PASSWORD` env var, or generated | Full access |
| Estimator | `estimator@openestimator.io` | `DEMO_ESTIMATOR_PASSWORD` env var, or generated | Estimator |
| Manager | `manager@openestimator.io` | `DEMO_MANAGER_PASSWORD` env var, or generated | Manager |

> Demo accounts include 5 pre-loaded projects from Berlin, London, New York, Paris, and Dubai with complete BOQs, schedules, and cost models.
>
> **Security note.** For any internet-exposed deployment, set the three
> `DEMO_*_PASSWORD` variables to strong, unique secrets, or disable demo
> accounts entirely with `DISABLE_DEMO_ACCOUNTS=1`. Do not reuse
> passwords from examples, screenshots, or earlier versions of this README.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Backend | Python 3.12+ / FastAPI | Async API, Pydantic v2 validation, modular architecture |
| Frontend | React 18 / TypeScript / Vite | SPA with code splitting, 21 language bundles |
| Database | PostgreSQL 16+ / SQLite (dev) | OLTP with JSON columns, zero-config SQLite for development |
| UI | Tailwind CSS / AG Grid | Professional data grid, responsive design, dark mode |
| AI | Any LLM via REST API | Anthropic, OpenAI, Gemini, Mistral, Groq, DeepSeek |
| Vector Search | LanceDB (embedded) / Qdrant | Semantic cost item search, 384d or 3072d embeddings |
| CAD/BIM | [DDC cad2data](https://github.com/datadrivenconstruction) | RVT, IFC, DWG, DGN → structured quantities |
| i18n | i18next + 21 language packs | Full RTL support (Arabic), locale-aware formatting |

## Architecture

```mermaid
flowchart TB
    UI["Frontend SPA<br>React 18, TypeScript, Vite<br>AG Grid, Tailwind, PDF.js"]

    subgraph Backend ["FastAPI Backend, 60+ modules"]
        CORE["Core<br>Module loader, Event bus, Hooks, RBAC, Validation"]
        BIZ["Business modules<br>BOQ, Costs, Schedule, 5D, Takeoff<br>Tendering, Risk, Reports, Catalog<br>Requirements, Markups, Punch List, BIM Hub, CDE"]
        AIS["AI services<br>AI Chat SSE, AI Estimate, Cost Intelligence<br>7 LLM providers"]
        CORE --> BIZ
        CORE --> AIS
    end

    subgraph Data ["Data layer"]
        PG[("PostgreSQL 16<br>SQLite in dev")]
        VEC[("Vector DB<br>LanceDB / Qdrant")]
        S3[("MinIO / S3<br>files, CAD, PDFs")]
    end

    subgraph Pipelines ["Pipelines"]
        CAD["DDC cad2data<br>RVT, IFC, DWG, DGN to canonical JSON"]
        CV["CV / OCR<br>PaddleOCR 3.0, YOLOv11<br>PDF takeoff, symbol detection"]
    end

    UI -- "REST, SSE" --> CORE
    BIZ --> PG
    BIZ --> VEC
    BIZ --> S3
    CAD --> BIZ
    CV --> BIZ

    classDef fe fill:#1f6feb,stroke:#0d3885,color:#fff;
    classDef be fill:#238636,stroke:#104822,color:#fff;
    classDef ai fill:#db6d28,stroke:#7a3c14,color:#fff;
    classDef data fill:#8250df,stroke:#4a2c7d,color:#fff;
    class UI fe
    class CORE,BIZ be
    class AIS ai
    class PG,VEC,S3,CAD,CV data
```

<details>
<summary>Plain-text version (for screen readers or non-Mermaid renderers)</summary>

```
┌──────────────────────────────────────────────────┐
│  Frontend (React SPA)                            │
│  TypeScript · Tailwind · AG Grid · PDF.js        │
└──────────────────┬───────────────────────────────┘
                   │ REST + SSE
┌──────────────────┴───────────────────────────────┐
│  Backend (FastAPI)                               │
│  60+ auto-discovered modules · Plugin system     │
├──────────────────────────────────────────────────┤
│  BOQ · Costs · Schedule · 5D · Validation · AI   │
│  Takeoff · Tendering · Risk · Reports · Catalog  │
│  Requirements · Markups · Punch List · BIM Hub   │
├──────────────────────────────────────────────────┤
│  Database (PostgreSQL / SQLite)                  │
│  Vector DB (LanceDB / Qdrant)                    │
│  CAD Converters (DDC cad2data)                   │
│  CV Pipeline (PaddleOCR + YOLOv11)               │
└──────────────────────────────────────────────────┘
```

</details>

---

## Support the Project

OpenConstructionERP is built and maintained by the community. If you find it useful:

- ⭐ **[Star this repo](https://github.com/datadrivenconstruction/OpenConstructionERP)** — helps others discover the project
- 💬 **[Join Discussions](https://t.me/datadrivenconstruction)** — ask questions, share ideas, help others
- 🐛 **[Report issues](https://github.com/datadrivenconstruction/OpenConstructionERP/issues)** — help us improve
- 💼 **[Professional consulting](https://datadrivenconstruction.io/contact-support/)** — custom deployment, training, enterprise support

## Security

OpenConstructionERP includes security hardening for production deployments:
- Path traversal protection on all file download endpoints
- CORS wildcard blocking in production mode
- Bounded input validation on bulk price operations
- Generic error responses to prevent account enumeration
- Production startup checks for secrets, credentials, and database configuration

**Do not open public GitHub issues for security vulnerabilities.**
Report privately via
[GitHub Security Advisories](https://github.com/datadrivenconstruction/OpenConstructionERP/security/advisories/new)
or by email to
[info@datadrivenconstruction.io](mailto:info@datadrivenconstruction.io).
See [SECURITY.md](SECURITY.md) for the full coordinated-disclosure
policy, response timelines, supported versions, scope, and
regulatory-reporting obligations under EU Regulation 2024/2847
(Cyber Resilience Act).

## AI disclaimer

AI suggestions produced by this software are preliminary estimates. A
qualified construction-estimation professional must verify all
quantities, classifications, and costs before any contractual or
tender-submission use. See [NOTICE](NOTICE) and [TERMS.md](TERMS.md) §4.

## Trademarks

All product names, logos, and trademarks referenced in this repository
are property of their respective owners. Comparative references to
commercial products (e.g., RIB iTWO, Exactal CostX, Sage Estimating,
Bluebeam) reflect publicly available feature information at the time of
publication and are used for fair comparative purposes. OpenConstructionERP
is an independent project and is not affiliated with, endorsed by, or
sponsored by any of the trademark owners named. Full attributions in
[NOTICE](NOTICE).

## Export control

This software contains cryptographic functionality (bcrypt password
hashing, JWT signing). Export is classified under **US EAR 740.17** (TSU
mass-market exemption) and **EU Regulation 2021/821** (dual-use). The
Software is **not authorised** for download, use, or re-export to
jurisdictions subject to comprehensive OFAC sanctions. See [NOTICE](NOTICE)
for the full notice.

## License

**AGPL-3.0** — see [LICENSE](LICENSE). Third-party attributions in
[NOTICE](NOTICE).

You can freely use, modify, and distribute this software. If you modify
and deploy it as a service, AGPL §13 requires you to make the
corresponding source code available under the same licence.

For **commercial licensing** without AGPL obligations, see
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) or contact
[info@datadrivenconstruction.io](mailto:info@datadrivenconstruction.io).

## Privacy and terms

- [PRIVACY.md](PRIVACY.md) — GDPR / UK DPA / CCPA / LGPD baseline
- [TERMS.md](TERMS.md) — terms of use for the hosted instance
- [COOKIES.md](COOKIES.md) — browser storage inventory
- [SECURITY.md](SECURITY.md) — responsible disclosure

---

<p align="center">
  <!-- Social Links -->
  <a href="https://x.com/datadrivenconst" target="_blank">
    <img src="https://img.shields.io/twitter/follow/datadrivenconst?logo=X&style=flat&color=%23f5f5f5" alt="Follow on X">
  </a>
  <a href="https://www.youtube.com/@datadrivenconstruction" target="_blank">
    <img src="https://img.shields.io/badge/YouTube-FF0000?logo=youtube&logoColor=white" alt="Subscribe on YouTube">
  </a>
  <a href="https://www.linkedin.com/company/78381569" target="_blank">
    <img src="https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff" alt="Connect on LinkedIn">
  </a>
</p>


<p align="left">

  <a href="https://datadrivenconstruction.io">
    <img src="https://datadrivenconstruction.io/wp-content/uploads/2023/07/DataDrivenConstruction-1-1.png" alt="DDC Logo" width="200"/>
  </a>
  <br>
   <b>   Unlock the Power of Data in Construction</b>
   <br>
     🚀 Move to full-cycle data management  where only unified <br /> structured data & processes remain and where  🔓 your data is yours
</p>
