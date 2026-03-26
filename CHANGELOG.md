# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-24

### Added

- **Project Management** — Create, configure, and manage estimation projects
- **BOQ Editor** — Hierarchical bill of quantities with inline editing, keyboard navigation, and real-time totals
- **Cost Database** — Built-in catalog with 55,000+ construction items (CWICR), semantic search via LanceDB
- **Assembly System** — Reusable cost assemblies (recipes) with regional adjustment factors
- **Validation Pipeline** — Configurable rule engine with DIN 276, GAEB, NRM, and MasterFormat rule sets
- **Cost Model** — Parametric cost modeling with benchmark comparison
- **Schedule Module** — Gantt-style project scheduling linked to BOQ positions
- **Tendering** — Bid package creation, distribution, and comparison
- **AI Integration** — LLM-powered cost suggestions, BOQ generation, and classification (OpenAI/Anthropic)
- **PDF Export** — Professional BOQ and report PDF generation
- **GAEB XML** — Import/export support for X83 tender format
- **20 Languages** — Full i18n support: EN, DE, RU, FR, ES, PT, IT, NL, PL, CS, TR, AR, ZH, JA, KO, HI, SV, NO, DA, FI
- **Module System** — Plugin architecture with manifest-based module discovery and marketplace
- **Demo Projects** — 3 built-in demo projects (Berlin residential, London office, Dubai warehouse)
- **Docker Support** — Single-image deployment with SQLite, multi-container with PostgreSQL
- **Desktop App** — Tauri v2 wrapper with PyInstaller sidecar (Windows, macOS, Linux)
- **CLI** — `openestimate serve` command for local installation
- **Cloud Templates** — Railway, Render, and DigitalOcean Terraform deployment configs
- **Dark Mode** — System-aware theme with manual toggle
- **Keyboard Shortcuts** — Comprehensive shortcuts with `Ctrl+K` command palette
- **Feedback System** — Built-in bug report and feature request submission

### Security

- JWT authentication with bcrypt password hashing
- Role-based access control (RBAC)
- CORS middleware with configurable origins
- Input validation via Pydantic v2
