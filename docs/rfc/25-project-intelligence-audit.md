# RFC 25 — Project Intelligence audit

**Status:** draft
**Related items:** ROADMAP_v1.9.md #25 (R2 → v1.9.1)
**Date:** 2026-04-17

## 1. Context

At `/project-intelligence` the current page (v1.7.2) renders a score ring, 9 domain bars, a critical-gaps card, an achievements card, and an AI advisor panel. Backend collects state across 13 domains in parallel, then a rule-based scorer computes domain percentages and detects gaps against ~13 canned rules.

### Honest assessment

**The module is misaligned with its users.** It's a **project-readiness checklist** for PMs, not a **cost-analysis dashboard** for estimators.

Evidence:
- 50% of the domain weight goes to BOQ + Validation, but both are rendered as compliance metrics (items present / zero-price count) rather than financial metrics (total value, outliers, variance).
- No budget variance, no cost-per-unit benchmark, no Pareto of cost drivers, no price volatility, no vendor concentration.
- "Intelligence" in the name is misleading: scoring is 13 hardcoded if-then rules; an LLM narration sits on top, but no ML, no anomaly detection, no forecast.
- 5-minute client cache makes the page feel stale after the user edits a sibling module.

### Widget inventory

| Widget | File | Source | Relevance to estimators |
|--------|------|--------|-------------------------|
| Score ring | `ScoreRing.tsx:1-113` | aggregate of 9 domain scores | Medium — needs retargeting to cost readiness |
| 9 domain bars | `ProjectIntelligencePage.tsx:448-466` | scorer.py | Mixed — 4 relevant, 5 noise |
| Critical gaps card | `GapCard.tsx:1-152` | scorer `_GAP_RULES` | High — but missing $ impact |
| Achievements card | `AchievementCard.tsx:1-26` | scorer `_ACHIEVEMENT_RULES` | Low — vanity metric |
| AI Advisor | `AIAdvisorPanel.tsx:1-303` | optional LLM, fallback rule text | Medium — generic advice |
| Domain details (9 tabs) | `DomainDetails.tsx:1-396` | state snapshot per domain | Mixed |
| Hero onboarding | `ProjectIntelligencePage.tsx:174-285` | static copy | Low — can be dropped |

## 2. Options considered

### Option A — Incremental fix (keep the shell, swap widgets)

Rename to "Estimation Dashboard," delete Achievements, tighten cache, replace bottom half of domain bars with 3 KPI cards + 4 analytics widgets.

### Option B — Full rewrite as a new module

New route `/estimation-intelligence` with a clean slate; leave the existing page as an admin readiness checklist. Large scope; defer.

### Option C — Do nothing — accept the page as a readiness checklist, move cost analytics to the Dashboard

Ignores the user's explicit "нужна максимально профессиональная и понятная страница."

## 3. Decision

**Option A** — keep URL, rename surface label, repurpose the layout toward cost analytics. Changes land in v1.9.1; further ML-driven widgets in v1.9.2+.

### Hero renamed + 3 KPI cards

| KPI | Source | Threshold |
|-----|--------|-----------|
| **Budget variance** | `/v1/costmodel/variance` (new) | 🟢 ±3% · 🟡 ±5% · 🔴 > ±5% |
| **Schedule health** | existing schedule endpoint | % of activities on baseline |
| **Risk-adjusted cost** | `/v1/boq/anomalies` + existing risk | point estimate ± 90% CI |

### Main grid reshape (2-column)

- **Left:** Critical Gaps (keep + add $ impact) — e.g. "12 items missing prices → $4.2M cost uncertainty"
- **Right:** 2×3 analytics widgets
  - **Cost drivers (Pareto)** — top 5 items by total cost (calls new `/v1/boq/line-items?group=cost`)
  - **Price volatility heatmap** — box plot of unit cost across bids (calls new `/v1/tendering/bid-analysis`)
  - **Schedule ↔ cost correlation** — stacked area, labor cost by phase (`/v1/schedule/labor-cost-by-phase`)
  - **Vendor concentration** — top 3 bidders' share
  - **Scope coverage** — current BOQ line count vs. baseline (% kept)
  - **Real-time validation** — live rule pass count (replace stale report snapshot)

### Drop

- Achievements card (demoralising compliance vanity)
- Hero onboarding (saves 200 px of vertical space)
- Domains: Documents, Reports, Tendering (low signal for estimators)

### AI Assistant — repositioned

Rename to "Cost Intelligence Advisor." Feed it cost-specific context (BOQ outliers, variance, bid spread) instead of generic checklist data.

### Cache

Reduce TTL from 5 min to 60 s; keep the manual refresh button.

## 4. Implementation sketch

### 4.1 New backend endpoints

```
GET  /v1/costmodel/variance?project_id=X
      → { budget, current, variance_abs, variance_pct, red_line }

GET  /v1/boq/line-items?project_id=X&group=cost&top_n=20
      → [{ position_id, description, total_cost, share_of_total }]

GET  /v1/boq/cost-rollup?project_id=X&group_by=cost_code
      → [{ code, label, total }]

GET  /v1/tendering/bid-analysis?project_id=X
      → { vendors: [...], outliers: [...], spread: {...} }

GET  /v1/boq/anomalies?project_id=X
      → [{ position_id, type: 'outlier'|'jump'|'format', severity, detail }]
```

All live under existing module routers; no new module needed.

### 4.2 Frontend shape

Replace `ProjectIntelligencePage.tsx` layout sections ordered:
1. KPI strip (3 cards) — new component `ProjectKPIHero`
2. Gaps column + Analytics grid — new `ProjectAnalyticsGrid`
3. Domain detail tabs — reduce to 4 (BOQ / Cost / Schedule / Risk)
4. AI assistant strip (existing component, new prompt context)

`ScoreRing` stays but its weighting moves: BOQ 40% · Cost Model 30% · Validation 20% · Risk 10%.

### 4.3 Rename

Label shown in the header and sidebar: "Estimation Dashboard" (EN). For DE/RU, `estimation_dashboard.title` with fallback.

## 5. Testing plan

**Unit** (`frontend/src/features/project-intelligence/__tests__/`):
- Pareto helper returns top N by share, no ties drift
- Variance traffic-light thresholds correctly placed
- Cache TTL reduced to 60 s in queryClient options

**E2E** (`frontend/e2e/v1.9/25-estimation-dashboard.spec.ts`):
- Page renders all 3 KPI cards + 5 analytics widgets within 5 s
- No "N/A" states after 10 s
- No console errors
- Refresh button refetches and clears the "n min ago" timer
- AI assistant responds to role change

**Performance:** full page load < 2 s with warm cache; backend `/summary/` < 800 ms at p95 for 5 k-position projects.

## 6. Risks / follow-ups

- **Backend endpoints are net-new.** 5 of them. Each needs Pydantic + service + router + unit test. Plan two weeks for backend work, one for frontend.
- **Stakeholder confusion.** "Intelligence" → "Estimation Dashboard" rename. Keep URL unchanged so bookmarks survive; add a comment in the changelog.
- **Anomaly detection (ML) deferred to v1.9.2.** For v1.9.1 the anomalies endpoint uses simple statistical rules (z-score on unit cost, IQR on quantity) — good enough to flag the obvious cases.
- **Risk-adjusted cost display.** Needs decision on methodology: simple ±% range vs. Monte Carlo. Start with ±%; Monte Carlo is R3+.
