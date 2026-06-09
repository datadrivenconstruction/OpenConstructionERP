/**
 * ProductTour — first-run guided tour of OpenConstructionERP.
 *
 * A multi-step spotlight coachmark walkthrough that introduces a new user
 * to the key surfaces of the app: sidebar navigation, project picker,
 * BOQ editor, BIM Hub, Property Development, Geo Hub, Help menu and a
 * wrap-up step.
 *
 * Lifecycle:
 *   - Auto-starts on first login when the user is on the dashboard route
 *     ("/" or "/dashboard") and `localStorage.getItem('oe.tour_completed')`
 *     is not `'true'`.
 *   - Listens for the `oe:start-tour` window event so any "Take a quick
 *     tour" CTA can (re-)launch the tour without prop-drilling.
 *   - On Finish / Skip / Esc → writes `oe.tour_completed = 'true'`.
 *   - Esc prompts a soft confirm to avoid accidental dismissal.
 *
 * Resilience:
 *   - If a step's target selector resolves to nothing, the tour logs a
 *     single console warning and auto-advances to the next step.  The
 *     wrap-up step has no target and renders as a centred modal.
 *   - On `resize` / `scroll` the spotlight + tooltip are recomputed via
 *     `getBoundingClientRect()` so the highlight stays pinned to the
 *     element even on long pages or zoom changes.
 *   - Esc handler is registered on mount (and only when active) and
 *     unregistered on close — no global leak.
 *
 * NOTE: ProductTour is the canonical global onboarding tour. The
 * older `OnboardingTour` (which keys off `oe_tour_completed` — no
 * dot) is no longer mounted globally; it survives only as a building
 * block for per-feature custom tours (e.g. the Pipelines page).
 * ProductTour uses storage key `oe.tour_completed` — note the dot —
 * and `data-testid` selectors so the two systems do not interfere.
 * The one-shot migration from the legacy key lives in
 * `App.tsx`. The "Take a quick tour" CTA in WhatsNewCard and the Help
 * menu both target ProductTour via the `oe:start-tour` event.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { X, ArrowLeft, ArrowRight, MapPin, Check } from 'lucide-react';
import clsx from 'clsx';

import { ConfirmDialog } from './ConfirmDialog';
import { apiGet, apiPut } from '@/shared/lib/api';

/* ── Constants ──────────────────────────────────────────────────────────── */

/** Tour completion flag.  Tested against the literal string `'true'`.
 *  Per-tour storage uses `${TOUR_COMPLETED_KEY}.<tourId>` (e.g.
 *  `oe.tour_completed.boq`) so finishing one module's tour never blocks
 *  another from launching.  The bare key is kept for the historical
 *  global tour (tourId === 'global') so legacy installs keep working. */
export const TOUR_COMPLETED_KEY = 'oe.tour_completed';

/** Window event that any external trigger (e.g. WhatsNewCard "Take a
 *  quick tour" button, Help menu item, per-module ModuleHelpButton) can
 *  dispatch to (re-)start.  The event detail may carry a `tourId` to
 *  pick a registered tour playlist; omitting it launches the global
 *  default. */
export const TOUR_START_EVENT = 'oe:start-tour';

/** Known tour identifiers.  Add a new id here when registering a new
 *  per-module tour so callers get autocompletion + type safety. */
export type TourId =
  | 'global'
  | 'boq'
  | 'accommodation'
  | 'bim'
  | 'geo'
  | 'propdev'
  | 'dashboard';

/** Per-tour storage key.  `global` keeps the bare key for backward
 *  compatibility with installs upgraded from before this refactor. */
function storageKeyFor(tourId: TourId): string {
  return tourId === 'global' ? TOUR_COMPLETED_KEY : `${TOUR_COMPLETED_KEY}.${tourId}`;
}

/** Per-tour persistence record returned by the backend. */
interface TourStateEntry {
  dismissed_at: string | null;
  completed_at: string | null;
}

/** Top-level shape of ``GET /api/v1/users/me/tour-state/``. */
interface TourStatePayload {
  tours: Record<string, TourStateEntry>;
}

/**
 * Persist the dismissed / completed timestamps for the supplied tour id
 * to the server. Idempotent — fire-and-forget; localStorage is the
 * authoritative cache so a network blip never re-pops the tour on the
 * next page-load.
 *
 * Re-fetches the current bucket first so we don't clobber sibling tours'
 * completion state. Silently swallows network errors — the user already
 * dismissed the tour, and a 4xx/5xx on the persistence write must not
 * re-open it.
 */
async function persistTourState(
  tourId: TourId,
  patch: TourStateEntry,
): Promise<void> {
  try {
    const current = await apiGet<TourStatePayload>('/v1/users/me/tour-state/');
    const merged: TourStatePayload = {
      tours: { ...(current?.tours ?? {}), [tourId]: patch },
    };
    await apiPut<TourStatePayload, TourStatePayload>(
      '/v1/users/me/tour-state/',
      merged,
    );
  } catch {
    /* Network / auth failure — localStorage still suppresses the tour. */
  }
}

/** Routes where the *auto-start* must NOT mount on top of the page (the
 *  spotlight overlay would block form inputs / primary CTAs).  Manual
 *  launches via the `oe:start-tour` event bypass this guard. */
const AUTO_START_BLOCKED_PREFIXES = ['/login', '/register', '/forgot-password', '/onboarding', '/setup'];

/** localStorage flag the OnboardingWizard sets on every completion path
 *  (`markOnboardingCompleted`). The first-run tour is GATED on this so the
 *  spotlight never lands on top of the setup wizard. The tour and the
 *  onboarding flow are two distinct first-run experiences and must not run
 *  at once. Kept as a local string (not imported from the onboarding feature)
 *  to avoid a shared/ui to features import cycle; the key is the stable
 *  contract between the two. */
const ONBOARDING_COMPLETED_KEY = 'oe_onboarding_completed';

/** Window event the OnboardingWizard dispatches the instant onboarding is
 *  completed/skipped. The auto-start effect listens for it so the global tour
 *  can begin the moment the wizard closes instead of only on the next reload.
 *  Mirrors `ONBOARDING_COMPLETED_EVENT` exported from the onboarding feature. */
const ONBOARDING_COMPLETED_EVENT = 'oe:onboarding-completed';

/** Whether the user has finished (or skipped) the onboarding wizard. The
 *  tour's first-run auto-start requires this to be true. Reads the same
 *  localStorage flag the wizard and the dashboard first-run redirect use, so
 *  a returning user whose flag the dashboard has already primed from the
 *  server is correctly treated as "onboarding done". */
function isOnboardingDone(): boolean {
  try {
    return localStorage.getItem(ONBOARDING_COMPLETED_KEY) === 'true';
  } catch {
    // Storage unavailable: fail OPEN so a user who can never persist the
    // onboarding flag is not permanently locked out of the tour.
    return true;
  }
}

/** Routes that count as the dashboard for auto-start eligibility. */
const DASHBOARD_ROUTES = new Set(['/', '/dashboard']);

const TOOLTIP_W = 340; // px — fixed tooltip width
const TOOLTIP_H = 200; // px — estimated tooltip height (used for pre-positioning)
const TOOLTIP_OFFSET = 16; // px gap between spotlight and tooltip
const PADDING = 8; // px halo around the highlighted element
const VIEWPORT_MARGIN = 12; // px keep-away from viewport edges

/* ── Types ──────────────────────────────────────────────────────────────── */

export interface ProductTourStep {
  /** CSS selector for the element to highlight.  `null` → centred modal. */
  selector: string | null;
  /** i18n key for the step title (resolved at render time). */
  titleKey: string;
  /** i18n key for the supporting body copy (~30 words). */
  bodyKey: string;
  /** Preferred position relative to target.  Falls back if it would clip. */
  preferredPosition?: 'top' | 'right' | 'bottom' | 'left';
  /** When the target lives inside a collapsible sidebar group that is
   *  collapsed by default, the row is unmounted from the DOM and cannot be
   *  measured.  Set this to the sidebar group id so the tour can dispatch
   *  `oe:tour-reveal` to expand the group (and switch to advanced view if the
   *  group is hidden in simple mode) before re-attempting measurement. */
  revealGroupId?: string;
}

interface SpotlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface TooltipCoords {
  top: number;
  left: number;
}

/* ── Default 8-step tour ────────────────────────────────────────────────── */

export const DEFAULT_PRODUCT_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="app-sidebar"]',
    titleKey: 'tour.step.1.title',
    bodyKey: 'tour.step.1.body',
    preferredPosition: 'right',
  },
  {
    selector: '[data-testid="header-project-picker"]',
    titleKey: 'tour.step.2.title',
    bodyKey: 'tour.step.2.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="sidebar-nav-boq"]',
    titleKey: 'tour.step.3.title',
    bodyKey: 'tour.step.3.body',
    preferredPosition: 'right',
  },
  {
    selector: '[data-testid="sidebar-nav-bim"]',
    titleKey: 'tour.step.4.title',
    bodyKey: 'tour.step.4.body',
    preferredPosition: 'right',
    // BIM viewer moved into the collapsed-by-default "Reality Capture & 3D"
    // group (grp_reality); reveal it so the spotlight can latch on.
    revealGroupId: 'grp_reality',
  },
  {
    selector: '[data-testid="sidebar-nav-property-dev"]',
    titleKey: 'tour.step.5.title',
    bodyKey: 'tour.step.5.body',
    preferredPosition: 'right',
    // Row lives in the collapsed-by-default "property" group (hideInSimple).
    revealGroupId: 'property',
  },
  {
    selector: '[data-testid="sidebar-nav-geo-hub"]',
    titleKey: 'tour.step.6.title',
    bodyKey: 'tour.step.6.body',
    preferredPosition: 'right',
    // Geo Hub moved into the collapsed-by-default "Reality Capture & 3D"
    // group (grp_reality); reveal it so the spotlight can latch on.
    revealGroupId: 'grp_reality',
  },
  {
    selector: '[data-testid="header-help-menu"]',
    titleKey: 'tour.step.7.title',
    bodyKey: 'tour.step.7.body',
    preferredPosition: 'bottom',
  },
  {
    selector: null,
    titleKey: 'tour.step.8.title',
    bodyKey: 'tour.step.8.body',
  },
];

/* ── Per-module tour: BOQ Editor (8 steps) ──────────────────────────────
 *
 * Steps walk a brand-new estimator from "what is this page" through every
 * load-bearing surface of the BOQ editor:
 *   1. Toolbar — primary action band, undo/redo + add + import/export.
 *   2. Add Position — the primary CTA every user hits first.
 *   3. AG Grid — the editable table itself, inline editing + keyboard nav.
 *   4. Quality & AI menu — validate, AI rate recovery, anomaly check.
 *   5. Resource summary panel — material / labour / equipment rollup.
 *   6. Markup panel — overhead / profit / VAT / contingency configuration.
 *   7. Quality score ring — live traffic light driven by validation.
 *   8. Export menu (closing tip) — Excel / GAEB X83 / PDF / CSV.
 *
 * Selectors target stable `data-testid` attributes added in BOQEditorPage
 * and BOQToolbar so the tour survives Tailwind churn / button reorders.
 */
export const BOQ_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="boq-toolbar"]',
    titleKey: 'tour.boq.step.1.title',
    bodyKey: 'tour.boq.step.1.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="boq-add-position-button"]',
    titleKey: 'tour.boq.step.2.title',
    bodyKey: 'tour.boq.step.2.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="boq-grid"]',
    titleKey: 'tour.boq.step.3.title',
    bodyKey: 'tour.boq.step.3.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="boq-quality-ai-menu"]',
    titleKey: 'tour.boq.step.4.title',
    bodyKey: 'tour.boq.step.4.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="boq-resource-summary"]',
    titleKey: 'tour.boq.step.5.title',
    bodyKey: 'tour.boq.step.5.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="boq-markup-panel"]',
    titleKey: 'tour.boq.step.6.title',
    bodyKey: 'tour.boq.step.6.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="boq-quality-ring"]',
    titleKey: 'tour.boq.step.7.title',
    bodyKey: 'tour.boq.step.7.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="boq-export-button"]',
    titleKey: 'tour.boq.step.8.title',
    bodyKey: 'tour.boq.step.8.body',
    preferredPosition: 'bottom',
  },
];

/* ── Per-module tour: Accommodation (7 steps) ─────────────────────────
 *
 * Walks a new operator through the Accommodation detail page + the
 * list-page CTAs that surround it:
 *   1. Header — name, kind badge, BIM link, Geo CTA.
 *   2. Tabs strip — Inventory / Occupancy / Billing / Settings blocks.
 *   3. Rooms grid — colour-coded by status (green/amber/grey/red).
 *   4. Bulk-add — Add rooms generator (prefix + start + count).
 *   5. Occupancy — bookings state machine (reserved → checked_in → checked_out).
 *   6. PropDev bootstrap — clone rooms from a PropDev block in Settings.
 *   7. HR autobook — wrap-up: list-page CTA suggests rooms to new hires.
 */
export const ACCOMMODATION_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="accommodation-detail-header"]',
    titleKey: 'tour.accommodation.step.1.title',
    bodyKey: 'tour.accommodation.step.1.body',
    preferredPosition: 'bottom',
  },
  {
    // The detail page renders its block strip via <TabBar idPrefix/
    // testIdPrefix="accommodation-detail">, which emits a per-tab
    // `accommodation-detail-tab-<id>` testid but no container testid.
    // Anchor on the first (always-rendered) tab so the spotlight lands
    // on the strip instead of degrading to a centred modal.
    selector: '[data-testid="accommodation-detail-tab-inventory"]',
    titleKey: 'tour.accommodation.step.2.title',
    bodyKey: 'tour.accommodation.step.2.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="accommodation-rooms-grid"]',
    titleKey: 'tour.accommodation.step.3.title',
    bodyKey: 'tour.accommodation.step.3.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="accommodation-rooms-bulk-add"]',
    titleKey: 'tour.accommodation.step.4.title',
    bodyKey: 'tour.accommodation.step.4.body',
    preferredPosition: 'bottom',
  },
  {
    // Bookings live under the Occupancy block (no standalone "bookings"
    // block tab exists). Anchor on the Occupancy tab trigger, which is
    // the entry point to the booking state machine.
    selector: '[data-testid="accommodation-detail-tab-occupancy"]',
    titleKey: 'tour.accommodation.step.5.title',
    bodyKey: 'tour.accommodation.step.5.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="accommodation-detail-tab-settings"]',
    titleKey: 'tour.accommodation.step.6.title',
    bodyKey: 'tour.accommodation.step.6.body',
    preferredPosition: 'bottom',
  },
  {
    selector: null,
    titleKey: 'tour.accommodation.step.7.title',
    bodyKey: 'tour.accommodation.step.7.body',
  },
];

/* ── Per-module tour: BIM Hub (7 steps) ────────────────────────────────
 *
 * Walks a brand-new BIM user from "what is this app" through every
 * load-bearing surface of the 3D viewer:
 *   1. Models filmstrip — the file browser / model picker at the bottom.
 *   2. Active model name — confirms which model is currently loaded.
 *   3. Filter button — federation tree, type / storey / property filters.
 *   4. Property search — column / operator / value query against the
 *      DDC Parquet, matches drive the isolation overlay.
 *   5. Asset Card — element register pop-up triggered by selection.
 *   6. Linked BOQ panel — the BIM-to-BOQ link badge / right-rail tab.
 *   7. View on map / federation hub — cross-module navigation.
 */
export const BIM_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="bim-filmstrip-toggle"]',
    titleKey: 'tour.bim.step.1.title',
    bodyKey: 'tour.bim.step.1.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="bim-active-model-name"]',
    titleKey: 'tour.bim.step.2.title',
    bodyKey: 'tour.bim.step.2.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="bim-tour-filter-button"]',
    titleKey: 'tour.bim.step.3.title',
    bodyKey: 'tour.bim.step.3.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="bim-property-search-toggle"]',
    titleKey: 'tour.bim.step.4.title',
    bodyKey: 'tour.bim.step.4.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="bim-asset-card-toggle"]',
    titleKey: 'tour.bim.step.5.title',
    bodyKey: 'tour.bim.step.5.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="bim-tour-linked-boq-button"]',
    titleKey: 'tour.bim.step.6.title',
    bodyKey: 'tour.bim.step.6.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="bim-view-on-map"]',
    titleKey: 'tour.bim.step.7.title',
    bodyKey: 'tour.bim.step.7.body',
    preferredPosition: 'bottom',
  },
];

/* ── Per-module tour: Geo Hub (6 steps) ────────────────────────────────
 *
 * The 3D-globe / project-map module. Walks a new user through:
 *   1. Mode picker — Global / Project / Development scope segmented
 *      control at the top-right of every Geo page.
 *   2. Live HUD — cursor lat/lon, altitude and scale-bar overlay.
 *   3. Anchored Projects rail — left-side overlay listing every
 *      anchored project; click to fly the camera.
 *   4. Cesium canvas — the 3D globe itself (drag / scroll / pick pins).
 *   5. Overlay panel — pin a PDF or image to the globe.
 *   6. Deep links — ?model= / ?plot= / ?dev_id= persisted in URL.
 */
export const GEO_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="geo-tour-mode-picker"]',
    titleKey: 'tour.geo.step.1.title',
    bodyKey: 'tour.geo.step.1.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="geo-tour-hud"]',
    titleKey: 'tour.geo.step.2.title',
    bodyKey: 'tour.geo.step.2.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="geo-tour-anchored-rail"]',
    titleKey: 'tour.geo.step.3.title',
    bodyKey: 'tour.geo.step.3.body',
    preferredPosition: 'right',
  },
  {
    selector: '[data-testid="geo-hub-cesium-container"]',
    titleKey: 'tour.geo.step.4.title',
    bodyKey: 'tour.geo.step.4.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="geo-overlay-panel"]',
    titleKey: 'tour.geo.step.5.title',
    bodyKey: 'tour.geo.step.5.body',
    preferredPosition: 'left',
  },
  {
    selector: null,
    titleKey: 'tour.geo.step.6.title',
    bodyKey: 'tour.geo.step.6.body',
  },
];

/* ── Per-module tour: Property Development (7 steps) ──────────────────
 *
 * Real-estate developer module. The page is a tab-based hub; this tour
 * highlights the pipeline + the deepest workflow surfaces.
 *   1. Pipeline banner — Development → Buyers → Contracts → Finance.
 *   2. Sub-entity tab strip — Phases / Blocks / Plots / Brokers / Price
 *      Matrix / Escrow / SPA / Payment Schedule grouped by lifecycle.
 *   3. New-entity primary CTA — context-aware Add button.
 *   4. House Types tab — reusable ISO 3166-1 unit templates with
 *      Custom-region fallback.
 *   5. Handovers tab — Snags + Warranty workflow entry point.
 *   6. Leads tab — Lead → Reservation → SPA conversion flow.
 *   7. Dashboards button — portfolio analytics + funnel + cash flow.
 */
export const PROPDEV_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="propdev-tour-pipeline"]',
    titleKey: 'tour.propdev.step.1.title',
    bodyKey: 'tour.propdev.step.1.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="propdev-tour-tabs"]',
    titleKey: 'tour.propdev.step.2.title',
    bodyKey: 'tour.propdev.step.2.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="propdev-tour-new-button"]',
    titleKey: 'tour.propdev.step.3.title',
    bodyKey: 'tour.propdev.step.3.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="propdev-tour-house-types-tab"]',
    titleKey: 'tour.propdev.step.4.title',
    bodyKey: 'tour.propdev.step.4.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="propdev-tour-handovers-tab"]',
    titleKey: 'tour.propdev.step.5.title',
    bodyKey: 'tour.propdev.step.5.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="propdev-tour-leads-tab"]',
    titleKey: 'tour.propdev.step.6.title',
    bodyKey: 'tour.propdev.step.6.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="propdev-tour-dashboards-button"]',
    titleKey: 'tour.propdev.step.7.title',
    bodyKey: 'tour.propdev.step.7.body',
    preferredPosition: 'bottom',
  },
];

/* ── Per-module tour: Dashboard (5 steps) ─────────────────────────────
 *
 * The home / first-page-after-login surface.  Walks a new user through:
 *   1. Hero row — greeting + the 3 primary CTAs (new project / new
 *      estimate / quick start).
 *   2. Customize button — opens the layout manager.
 *   3. KPI ribbon — Total Value / Active Estimates / Schedule / Priced.
 *   4. Today widget — open tasks / RFIs / safety incidents drill-in.
 *   5. Next Steps cards — context-aware suggestions for what to do.
 */
export const DASHBOARD_TOUR_STEPS: ProductTourStep[] = [
  {
    selector: '[data-testid="dashboard-tour-hero-actions"]',
    titleKey: 'tour.dashboard.step.1.title',
    bodyKey: 'tour.dashboard.step.1.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="dashboard-tour-customize-button"]',
    titleKey: 'tour.dashboard.step.2.title',
    bodyKey: 'tour.dashboard.step.2.body',
    preferredPosition: 'bottom',
  },
  {
    selector: '[data-testid="dashboard-tour-kpi-ribbon"]',
    titleKey: 'tour.dashboard.step.3.title',
    bodyKey: 'tour.dashboard.step.3.body',
    preferredPosition: 'top',
  },
  {
    selector: '[data-testid="dashboard-tour-projects-list"]',
    titleKey: 'tour.dashboard.step.4.title',
    bodyKey: 'tour.dashboard.step.4.body',
    preferredPosition: 'top',
  },
  {
    selector: null,
    titleKey: 'tour.dashboard.step.5.title',
    bodyKey: 'tour.dashboard.step.5.body',
  },
];

/* ── Tour registry — id → playlist of steps ────────────────────────────── */

export const TOUR_REGISTRY: Record<TourId, ProductTourStep[]> = {
  global: DEFAULT_PRODUCT_TOUR_STEPS,
  boq: BOQ_TOUR_STEPS,
  accommodation: ACCOMMODATION_TOUR_STEPS,
  bim: BIM_TOUR_STEPS,
  geo: GEO_TOUR_STEPS,
  propdev: PROPDEV_TOUR_STEPS,
  dashboard: DASHBOARD_TOUR_STEPS,
};

/* ── Hard-coded fallbacks for the locale keys, used when i18n misses ────── */

const STEP_FALLBACKS: Record<string, string> = {
  'tour.step.1.title': 'Sidebar navigation',
  'tour.step.1.body':
    'Your project workflow lives in the sidebar. Modules are grouped by lifecycle - Estimation, Tendering, Construction, Operations.',
  'tour.step.2.title': 'Active project',
  'tour.step.2.body':
    'Pick the active project at the top. The whole app scopes data to this project - BOQs, BIM models, RFIs, snags.',
  'tour.step.3.title': 'Bill of Quantities',
  'tour.step.3.body':
    'Bills of Quantity live here. Create positions, apply unit rates, link to CAD elements, export GAEB or Excel.',
  'tour.step.4.title': 'BIM Hub',
  'tour.step.4.body':
    'Upload IFC, RVT or DWG. Federate multiple models. Run clash detection. Take quantity off the 3D model.',
  'tour.step.5.title': 'Property Development',
  'tour.step.5.body':
    'Real-estate developer module - Leads, Buyers, Reservations, SPA, Handover, Warranty. End-to-end click-flow.',
  'tour.step.6.title': 'Geo Hub',
  'tour.step.6.body':
    '3D globe with project anchors, CAD tilesets and pins from HSE, Punchlist and Daily Diary.',
  'tour.step.7.title': 'Help and bug reports',
  'tour.step.7.body':
    'Found something? Report a bug from here - it lands on GitHub. You can also re-launch this quick tour from this menu.',
  'tour.step.8.title': "You're set!",
  'tour.step.8.body':
    'Pick a module from the sidebar to dive in. Full docs are linked from the About page.',
  'tour.skip': 'Skip tour',
  'tour.back': 'Back',
  'tour.next': 'Next',
  'tour.finish': 'Finish',
  'tour.step_counter': 'Step {{current}} of {{total}}',

  // ── BOQ Editor tour ──────────────────────────────────────────────────
  'tour.boq.step.1.title': 'BOQ toolbar',
  'tour.boq.step.1.body':
    'Every action lives here: add sections and positions, import GAEB or Excel, pick from the cost database, validate, run AI checks, and export. Hover any icon for its keyboard shortcut.',
  'tour.boq.step.2.title': 'Add a position',
  'tour.boq.step.2.body':
    'Creates a new line under the section you last clicked. The Description cell opens for inline edit automatically - type, then Tab through unit, quantity and unit rate.',
  'tour.boq.step.3.title': 'The estimating grid',
  'tour.boq.step.3.body':
    'Click any cell to edit; arrow keys / Tab navigate; formulas like =2*A1 are supported; right-click a row for duplicate, indent, link to BIM, or save-as-assembly.',
  'tour.boq.step.4.title': 'Quality & AI tools',
  'tour.boq.step.4.body':
    'Run validation against DIN 276 / GAEB / NRM, recalculate rates from the cost database, price-check against market medians, or open the AI assistant for plain-text BOQ generation.',
  'tour.boq.step.5.title': 'Resource summary',
  'tour.boq.step.5.body':
    'Live rollup of every material, labour and equipment line consumed across this BOQ - quantities, unit costs and total spend per resource. Click a row to see which positions use it.',
  'tour.boq.step.6.title': 'Markups & VAT',
  'tour.boq.step.6.body':
    'Add overhead, profit, tax, contingency, insurance or bonds - pick a regional template (DACH VOB, UK NRM, US RSMeans, FR BATIPRIX, …) or roll your own. Markups stack on the direct cost.',
  'tour.boq.step.7.title': 'Quality score',
  'tour.boq.step.7.body':
    'Traffic light driven by the validation pipeline - green over 80, amber 50-80, red below. Hover for the breakdown: descriptions filled, quantities set, rates set, markups configured.',
  'tour.boq.step.8.title': 'Export anywhere',
  'tour.boq.step.8.body':
    'Export to Excel (.xlsx), CSV, PDF report, or GAEB XML X83 for German tender submission. Currency, FX rates and markups are baked in so the recipient sees the same totals.',

  // ── Accommodation tour ───────────────────────────────────────────────
  'tour.accommodation.step.1.title': 'Accommodation header',
  'tour.accommodation.step.1.body':
    'Name, kind badge (worker camp / rental / hotel) and quick links to the linked BIM model and the Geo Hub when geo-coordinates are set. Launch the per-module tour from the Tour button here.',
  'tour.accommodation.step.2.title': 'Tabs',
  'tour.accommodation.step.2.body':
    'Rooms, Bookings, Charges and Settings. Each tab scopes its data to this accommodation only - no cross-contamination between properties on the same project.',
  'tour.accommodation.step.3.title': 'Rooms grid',
  'tour.accommodation.step.3.body':
    'Colour-coded by status - green available, amber occupied, grey maintenance, red blocked. Click any room tile to assign an occupant or open its booking history.',
  'tour.accommodation.step.4.title': 'Add rooms in bulk',
  'tour.accommodation.step.4.body':
    'Generator creates a contiguous block of rooms in one shot: pick a prefix (B-), start number (201) and count (12) and you get B-201..B-212 with default capacity and base rate. Or paste a CSV list.',
  'tour.accommodation.step.5.title': 'Bookings & state machine',
  'tour.accommodation.step.5.body':
    'Bookings follow reserved → checked_in → checked_out. Cancel is allowed from any non-final state. The room status flips to occupied on check-in and back to available on check-out / cancel - fully automatic.',
  'tour.accommodation.step.6.title': 'Bootstrap from PropDev',
  'tour.accommodation.step.6.body':
    'In Settings → Bootstrap from PropDev, paste a PropDev block id to clone its plots as rooms here. Idempotent - re-run safely whenever the source block grows. Great for staff-quarter accommodation tied to a residential development.',
  'tour.accommodation.step.7.title': 'HR autobook is in the list page',
  'tour.accommodation.step.7.body':
    'From /accommodation the "Suggest room for employee" button picks the lowest-numbered free worker-camp room for a new hire - feed it an employee id and a check-in date, accept the suggestion, and the booking is created in one click.',

  // ── BIM Hub tour ─────────────────────────────────────────────────────
  'tour.bim.step.1.title': 'Models filmstrip',
  'tour.bim.step.1.body':
    'Every model you upload (RVT, IFC, DWG-to-IFC, CSV-with-geometry) lives here. Click a card to load it, the Plus tile to upload a new one, or the chevron to collapse the strip and reclaim the canvas.',
  'tour.bim.step.2.title': 'Active model',
  'tour.bim.step.2.body':
    'Shows the name of the model currently in the 3D viewport - drag to rotate, scroll to zoom, right-drag to pan. Hover for the storage breakdown (artifacts + originals on disk).',
  'tour.bim.step.3.title': 'Filter & section box',
  'tour.bim.step.3.body':
    'Filter by storey, IFC class, discipline or any property - type a value or pick from the federation tree. Saved filter sets become reusable element groups. Hidden elements vanish from the canvas instantly.',
  'tour.bim.step.4.title': 'Property search',
  'tour.bim.step.4.body':
    'Query the DDC-extracted Parquet directly: pick a column, an operator (=, contains, >, <), and a value. Matches are isolated in the viewport so you can audit "all walls thicker than 30 cm" in one click.',
  'tour.bim.step.5.title': 'Asset Card & element properties',
  'tour.bim.step.5.body':
    'Toggle the floating Asset Card to see every property on the selected element - IFC params, materials, custom asset-register fields. Edit notes / status inline; changes sync to the Asset module.',
  'tour.bim.step.6.title': 'Linked BOQ',
  'tour.bim.step.6.body':
    'Opens the right-rail panel showing which BOQ positions reference the selected element. Drag elements onto a position to link them, or click "Quick takeoff" on a filter to auto-create a position from a group.',
  'tour.bim.step.7.title': 'View on map & federation',
  'tour.bim.step.7.body':
    'Jump to the Geo Hub with this model anchored on the globe, federate multiple models together for clash detection, or open the extracted data in the Data Explorer for SQL-style analysis.',

  // ── Geo Hub tour ─────────────────────────────────────────────────────
  'tour.geo.step.1.title': 'Mode picker',
  'tour.geo.step.1.body':
    'Three scopes: Global shows every anchored project on one earth-scale map. Project drops into one project - anchor, tilesets, viewpoints. Development is the per-development PropDev plot map.',
  'tour.geo.step.2.title': 'Live HUD',
  'tour.geo.step.2.body':
    'Cursor latitude / longitude, camera altitude and a scale bar update as you drag the globe. The north arrow always points up - click it to reset the camera to true-north.',
  'tour.geo.step.3.title': 'Anchored Projects',
  'tour.geo.step.3.body':
    'Every project you can access that has a real-world anchor is listed here. Click the name to fly the camera to its pin, or "Open" to drop into that project\'s map. Collapse to a slim pill to reclaim canvas.',
  'tour.geo.step.4.title': '3D globe',
  'tour.geo.step.4.body':
    'Drag to rotate, scroll to zoom, right-drag to pan. Click any pin (project, HSE incident, Punchlist defect, Daily Diary entry) to open it in its module. Tilesets fly into view as you zoom in.',
  'tour.geo.step.5.title': 'Raster overlays',
  'tour.geo.step.5.body':
    'Pin a PDF site plan or a georeferenced image onto the globe - click Add, drop the file, then drag the corner handles to align. Use Crop to mask the title block. Opacity slider per overlay.',
  'tour.geo.step.6.title': 'Deep links you can share',
  'tour.geo.step.6.body':
    'Every camera move / opened overlay updates the URL - ?model=… anchors a specific BIM tileset, ?plot=… focuses a PropDev plot, ?dev_id=… opens a development map. Copy and paste to colleagues; they land exactly where you are.',

  // ── Property Development tour ────────────────────────────────────────
  'tour.propdev.step.1.title': 'Lifecycle pipeline',
  'tour.propdev.step.1.body':
    'A residential sale runs Lead → Reservation → SPA (Sale & Purchase Agreement) → Handover → Warranty. Contract values feed Finance automatically. The banner shows where the active development sits on that path.',
  'tour.propdev.step.2.title': 'Sub-entity tabs',
  'tour.propdev.step.2.body':
    'Master data (Developments, Phases, Blocks, Plots, House Types) on the left, sales (Leads, Buyers, Reservations, SPAs, Payment Schedules) in the middle, operations (Brokers, Price Matrix, Escrow, Handovers, Warranty) on the right.',
  'tour.propdev.step.3.title': 'Context-aware Add',
  'tour.propdev.step.3.body':
    'The primary button always creates the right entity for the active tab - "New Plot" on Plots, "New Lead" on Leads, "New Reservation" on Reservations. SPA / Payment Schedule rows route back to Reservations because that\'s where the flow starts.',
  'tour.propdev.step.4.title': 'House Types catalogue',
  'tour.propdev.step.4.body':
    'Reusable unit templates with floors, area, bedrooms, base price and ISO 3166-1 region (180+ countries). Pick "Custom region" for areas without an ISO code. Variants let you spin off a Type-A-mirrored or Type-A-balcony.',
  'tour.propdev.step.5.title': 'Handovers & Snags',
  'tour.propdev.step.5.body':
    'Per handover you can log a snag list (punch list of defects), photo-document each item, and close them out before signing off. Snags are visible to the buyer in the buyer portal and feed the Warranty workflow.',
  'tour.propdev.step.6.title': 'Leads → Reservation',
  'tour.propdev.step.6.body':
    'Every inbound enquiry starts as a Lead with source attribution. The "Convert" button creates a Reservation (with deposit) on a chosen plot and optionally syncs the buyer to the Contacts directory so CRM and PropDev share one person record.',
  'tour.propdev.step.7.title': 'Dashboards',
  'tour.propdev.step.7.body':
    'Six analytics views: Buyer Journey Timeline, Cash Flow Waterfall, Funnel Conversion, Inventory Ageing, Inventory Heatmap, Sales Velocity. Each is shareable as a full-screen URL for stakeholders.',

  // ── Dashboard tour ──────────────────────────────────────────────────
  'tour.dashboard.step.1.title': 'Primary actions',
  'tour.dashboard.step.1.body':
    'Three high-traffic CTAs: New Project starts a fresh project; New Estimate creates a BOQ inside the most recent project; Quick Start resumes your latest BOQ in one click.',
  'tour.dashboard.step.2.title': 'Customize',
  'tour.dashboard.step.2.body':
    'Click to open the layout manager: show / hide / reorder every widget on this page. Your layout is saved server-side, so it follows you across browsers and machines under the same account.',
  'tour.dashboard.step.3.title': 'KPI ribbon',
  'tour.dashboard.step.3.body':
    'Total Value rolls up every active estimate. Active Estimates excludes archived / closed. Schedule Status counts active programmes. Priced Positions is the live ratio of priced vs total BOQ lines - click it to run validation if it\'s still null.',
  'tour.dashboard.step.4.title': 'Projects list & drill-in',
  'tour.dashboard.step.4.body':
    'Every project card shows BOQ value, position count, open tasks, RFIs and safety incidents. Click any card to make it the active project - every page in the app then scopes its data to that project.',
  'tour.dashboard.step.5.title': 'Some widgets need data',
  'tour.dashboard.step.5.body':
    'BIM Coverage, Critical Path, Procurement Pipeline and others render an empty state until the corresponding module has data - every empty card links you straight to the module so you can fill it in.',

  // ── ModuleHelpButton labels ──────────────────────────────────────────
  'module_help.tour_button': 'Tour',
  'module_help.tour_aria': 'Start guided tour for this module',
};

/* ── Geometry helpers ───────────────────────────────────────────────────── */

function measureSpotlight(selector: string): SpotlightRect | null {
  const el = document.querySelector(selector);
  if (!el) return null;
  const rect = (el as Element).getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return {
    top: rect.top - PADDING,
    left: rect.left - PADDING,
    width: rect.width + PADDING * 2,
    height: rect.height + PADDING * 2,
  };
}

function placeTooltip(
  spotlight: SpotlightRect,
  preferred: ProductTourStep['preferredPosition'] = 'bottom',
): TooltipCoords {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  // Candidate positions ordered by preference; first that fully fits wins.
  const order: Array<ProductTourStep['preferredPosition']> = [
    preferred,
    'bottom',
    'right',
    'top',
    'left',
  ];

  const tryPlace = (pos: ProductTourStep['preferredPosition']): TooltipCoords => {
    switch (pos) {
      case 'right':
        return {
          top: spotlight.top + spotlight.height / 2 - TOOLTIP_H / 2,
          left: spotlight.left + spotlight.width + TOOLTIP_OFFSET,
        };
      case 'left':
        return {
          top: spotlight.top + spotlight.height / 2 - TOOLTIP_H / 2,
          left: spotlight.left - TOOLTIP_W - TOOLTIP_OFFSET,
        };
      case 'top':
        return {
          top: spotlight.top - TOOLTIP_H - TOOLTIP_OFFSET,
          left: spotlight.left + spotlight.width / 2 - TOOLTIP_W / 2,
        };
      case 'bottom':
      default:
        return {
          top: spotlight.top + spotlight.height + TOOLTIP_OFFSET,
          left: spotlight.left + spotlight.width / 2 - TOOLTIP_W / 2,
        };
    }
  };

  const fits = ({ top, left }: TooltipCoords) =>
    top >= VIEWPORT_MARGIN &&
    left >= VIEWPORT_MARGIN &&
    top + TOOLTIP_H <= vh - VIEWPORT_MARGIN &&
    left + TOOLTIP_W <= vw - VIEWPORT_MARGIN;

  for (const pos of order) {
    const candidate = tryPlace(pos);
    if (fits(candidate)) return candidate;
  }
  // Nothing fit cleanly — fall back to preferred and clamp.
  const fallback = tryPlace(preferred);
  return {
    top: Math.max(VIEWPORT_MARGIN, Math.min(fallback.top, vh - TOOLTIP_H - VIEWPORT_MARGIN)),
    left: Math.max(VIEWPORT_MARGIN, Math.min(fallback.left, vw - TOOLTIP_W - VIEWPORT_MARGIN)),
  };
}

function centerOfViewport(): TooltipCoords {
  return {
    top: Math.max(VIEWPORT_MARGIN, (window.innerHeight - TOOLTIP_H) / 2),
    left: Math.max(VIEWPORT_MARGIN, (window.innerWidth - TOOLTIP_W) / 2),
  };
}

/* ── Component ──────────────────────────────────────────────────────────── */

export interface ProductTourProps {
  /** Fallback playlist (legacy callers).  When omitted the component
   *  resolves the active tour from `defaultTourId` / the dispatched
   *  start event payload via the registry. */
  steps?: ProductTourStep[];
  /** Tour id auto-launched on first-login when no tour-completed flag
   *  is set for that id.  Defaults to `'global'` so the legacy
   *  installer behaviour (dashboard first-run) is preserved. */
  defaultTourId?: TourId;
}

export function ProductTour({ steps, defaultTourId = 'global' }: ProductTourProps) {
  const { t } = useTranslation();
  const location = useLocation();

  // Active tour id drives which playlist + storage key we use. Starts at
  // `defaultTourId` and is replaced whenever the start-tour event fires
  // with a `{detail: {tourId}}` payload.
  const [activeTourId, setActiveTourId] = useState<TourId>(defaultTourId);

  // Resolve playlist: explicit `steps` prop wins (legacy callers), then
  // registry lookup by active id, then the global default.
  const resolvedSteps: ProductTourStep[] =
    steps ?? TOUR_REGISTRY[activeTourId] ?? DEFAULT_PRODUCT_TOUR_STEPS;
  const totalSteps = resolvedSteps.length;

  const [active, setActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [spotlight, setSpotlight] = useState<SpotlightRect | null>(null);
  const [tooltipCoords, setTooltipCoords] = useState<TooltipCoords>(() => centerOfViewport());
  const [confirmExitOpen, setConfirmExitOpen] = useState(false);
  // Track current theme so we can swap inline colour values (box-shadow,
  // accent-ring rgba) — Tailwind's `dark:` prefix only handles className
  // styles, not the dynamic inline boxShadow we use for the cutout.
  const [isDark, setIsDark] = useState<boolean>(() =>
    typeof document !== 'undefined'
      ? document.documentElement.classList.contains('dark')
      : false,
  );
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains('dark'));
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => mo.disconnect();
  }, []);
  // Track which missing-target warnings we've already emitted so we don't
  // spam the console on resize/recompute.
  const warnedRef = useRef<Set<string>>(new Set());
  // Pending reveal-retry timers (steps whose target lives in a collapsed
  // sidebar group). Cleared on step change / unmount so a stale retry never
  // re-positions onto a newer step's target.
  const revealTimersRef = useRef<number[]>([]);
  const clearRevealTimers = useCallback(() => {
    for (const id of revealTimersRef.current) window.clearTimeout(id);
    revealTimersRef.current = [];
  }, []);

  const step = resolvedSteps[currentStep];
  const isFirst = currentStep === 0;
  const isLast = currentStep === totalSteps - 1;

  /* ── Persist completion + close ──────────────────────────────────────── */
  /**
   * ``kind`` distinguishes the two exit paths so we can store both a
   * ``dismissed_at`` (Skip / Esc) and a ``completed_at`` (Finish) on the
   * server bucket — the UI doesn't need to differentiate but downstream
   * analytics (and the auto-start check) treats them the same: either
   * marker suppresses subsequent auto-opens. */
  const completeTour = useCallback(
    (kind: 'completed' | 'dismissed' = 'completed') => {
      try {
        // Per-tour completion key — finishing the BOQ tour doesn't suppress
        // the global tour and vice-versa. Kept as the local cache so the
        // tour never re-pops on a network blip.
        localStorage.setItem(storageKeyFor(activeTourId), 'true');
      } catch {
        /* localStorage unavailable — non-fatal */
      }
      // Fire-and-forget server persistence so the dismiss / completion
      // follows the user across browsers and devices. The local flag above
      // is the source of truth on this device; the server bucket primes the
      // local flag on the next first-login on a new browser (effect below).
      const now = new Date().toISOString();
      const patch: TourStateEntry = {
        dismissed_at: kind === 'dismissed' ? now : null,
        completed_at: kind === 'completed' ? now : null,
      };
      void persistTourState(activeTourId, patch);
      setActive(false);
      setCurrentStep(0);
    },
    [activeTourId],
  );

  /* ── Scroll target into view + measure ───────────────────────────────── */
  const positionForStep = useCallback(
    (idx: number) => {
      const s = resolvedSteps[idx];
      if (!s) return;

      // Cancel any reveal-retry timers from a previous step so they can't
      // re-position onto this step's spotlight after the fact.
      clearRevealTimers();

      // Wrap-up step (no selector) → centred modal, no spotlight.
      if (s.selector == null) {
        setSpotlight(null);
        setTooltipCoords(centerOfViewport());
        return;
      }
      const selector = s.selector;

      const el = document.querySelector(selector);
      if (el) {
        try {
          (el as Element).scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
        } catch {
          /* older browsers — ignore */
        }
      } else if (s.revealGroupId) {
        // Target's sidebar group is collapsed (and possibly hidden in simple
        // view), so the row is unmounted. Ask the Sidebar to expand it; the
        // bounded retry below re-queries once the row mounts.
        window.dispatchEvent(
          new CustomEvent('oe:tour-reveal', { detail: { groupId: s.revealGroupId } }),
        );
      } else if (!warnedRef.current.has(selector)) {
        warnedRef.current.add(selector);
        // eslint-disable-next-line no-console
        console.warn(`[ProductTour] target not found, skipping step: ${selector}`);
      }

      // Latch onto the target once it settles. The first attempt is deferred
      // so the smooth scroll has a chance to finish; if the row needs to be
      // revealed first we retry a few times at ~80ms intervals before
      // degrading to a centred modal.
      const apply = (rect: SpotlightRect) => {
        setSpotlight(rect);
        setTooltipCoords(placeTooltip(rect, s.preferredPosition));
      };
      const degrade = () => {
        // Target missing — degrade gracefully to a centred modal so the tour
        // never stalls on a broken selector.
        setSpotlight(null);
        setTooltipCoords(centerOfViewport());
      };
      const MAX_ATTEMPTS = 5;
      const attempt = (n: number) => {
        const rect = measureSpotlight(selector);
        if (rect) {
          // The row may have just mounted/scrolled — ensure it's in view.
          if (n > 0) {
            const just = document.querySelector(selector);
            try {
              (just as Element | null)?.scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
                inline: 'nearest',
              });
            } catch {
              /* older browsers — ignore */
            }
          }
          apply(rect);
          return;
        }
        if (n + 1 >= MAX_ATTEMPTS) {
          degrade();
          return;
        }
        const id = window.setTimeout(() => attempt(n + 1), 80);
        revealTimersRef.current.push(id);
      };
      // First measurement deferred to let the initial smooth scroll settle.
      const firstId = window.setTimeout(() => attempt(0), 180);
      revealTimersRef.current.push(firstId);
    },
    [resolvedSteps, clearRevealTimers],
  );

  /* ── (Re)compute on currentStep change + resize/scroll/observer ──────── */
  useEffect(() => {
    if (!active) return;
    positionForStep(currentStep);

    const recompute = () => {
      const s = resolvedSteps[currentStep];
      if (!s) return;
      if (s.selector == null) {
        setTooltipCoords(centerOfViewport());
        return;
      }
      const rect = measureSpotlight(s.selector);
      if (rect) {
        setSpotlight(rect);
        setTooltipCoords(placeTooltip(rect, s.preferredPosition));
      }
    };

    window.addEventListener('resize', recompute);
    window.addEventListener('scroll', recompute, true);

    // Observe layout shifts (collapsible sidebar, lazy-mounted nav items).
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(recompute);
      ro.observe(document.body);
    }

    return () => {
      window.removeEventListener('resize', recompute);
      window.removeEventListener('scroll', recompute, true);
      if (ro) ro.disconnect();
      // Stop any pending reveal-retry timers when the step changes / unmounts.
      clearRevealTimers();
    };
  }, [active, currentStep, positionForStep, resolvedSteps, clearRevealTimers]);

  /* ── Esc key — soft-confirm dismiss ──────────────────────────────────── */
  useEffect(() => {
    if (!active) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (confirmExitOpen) return;
      const otherDialog = document.querySelector(
        '[role=dialog]:not([data-product-tour]), [role=alertdialog]:not([data-product-tour])',
      );
      if (otherDialog) return;
      e.preventDefault();
      setConfirmExitOpen(true);
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [active, confirmExitOpen]);

  /* ── External trigger: `oe:start-tour` window event ────────────────────
   *
   * Optional `event.detail.tourId` picks a registered playlist (e.g.
   * `{tourId: 'boq'}` from the BOQ Editor's Tour button).  Unknown ids
   * silently fall back to the existing active id so a typo never wipes
   * the user's tour mid-session. */
  useEffect(() => {
    const start = (evt: Event) => {
      const detail = (evt as CustomEvent<{ tourId?: TourId } | undefined>).detail;
      const requested = detail?.tourId;
      if (requested && requested in TOUR_REGISTRY) {
        setActiveTourId(requested);
      }
      warnedRef.current.clear();
      setCurrentStep(0);
      setActive(true);
    };
    window.addEventListener(TOUR_START_EVENT, start);
    return () => window.removeEventListener(TOUR_START_EVENT, start);
  }, []);

  /* ── Server tour-state hydration ─────────────────────────────────────── */
  /**
   * Pull the user's saved tour-state ONCE on mount and prime the local
   * cache for any tours the server flags as dismissed / completed. This
   * is how the tour stops re-popping on a fresh browser after the user
   * dismissed it elsewhere.
   *
   * Failure modes (network / 401 / 5xx) are non-fatal — the tour just
   * falls back to localStorage-only semantics. */
  const [serverHydrated, setServerHydrated] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<TourStatePayload>('/v1/users/me/tour-state/');
        if (cancelled) return;
        const tours = data?.tours ?? {};
        for (const [tid, entry] of Object.entries(tours)) {
          if (!entry) continue;
          const stamped = Boolean(entry.dismissed_at) || Boolean(entry.completed_at);
          if (!stamped) continue;
          try {
            localStorage.setItem(storageKeyFor(tid as TourId), 'true');
          } catch {
            /* localStorage unavailable */
          }
        }
      } catch {
        /* Anonymous / offline / 5xx — fall back to localStorage only. */
      } finally {
        if (!cancelled) setServerHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /* ── Onboarding gate ─────────────────────────────────────────────────── */
  /**
   * The first-run tour must start ONLY AFTER the onboarding wizard is
   * finished or skipped, otherwise the spotlight overlay lands on top of
   * the setup wizard (the two distinct first-run experiences collide).
   *
   * Seeded from the persisted flag so a returning user (who finished
   * onboarding long ago, or whose flag the dashboard primed from the
   * server) is gated open immediately. Flipped true the instant onboarding
   * completes via the `oe:onboarding-completed` event, so the tour begins
   * the moment the wizard closes instead of waiting for a reload. Also
   * re-checked on route change (the auto-start effect lists it as a dep)
   * which covers the dashboard's server-flag priming path.
   */
  const [onboardingDone, setOnboardingDone] = useState<boolean>(() => isOnboardingDone());
  useEffect(() => {
    const onDone = () => setOnboardingDone(true);
    window.addEventListener(ONBOARDING_COMPLETED_EVENT, onDone);
    // Cross-tab / dashboard-primed flag: pick up a flip we didn't fire.
    const onStorage = (e: StorageEvent) => {
      if (e.key === ONBOARDING_COMPLETED_KEY && e.newValue === 'true') {
        setOnboardingDone(true);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(ONBOARDING_COMPLETED_EVENT, onDone);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  /* ── First-login auto-start ──────────────────────────────────────────── */
  useEffect(() => {
    if (active) return;
    if (typeof window === 'undefined') return;
    // Don't auto-open until the server bucket has been merged into
    // localStorage — otherwise a fresh browser would briefly auto-pop
    // the tour even when the user dismissed it on another machine.
    if (!serverHydrated) return;

    // GATE: never auto-start over an unfinished onboarding wizard. A brand
    // new user lands on the dashboard with neither flag set; the dashboard
    // first-run redirect then sends them to /onboarding. Without this guard
    // the 600ms timer below armed on the dashboard and the tour popped on
    // top of the wizard. Re-check live (not just the seeded state) so a flag
    // primed between renders is honoured. Manual launches via the
    // `oe:start-tour` event are unaffected; they live in a separate effect.
    if (!onboardingDone && !isOnboardingDone()) return;

    let completed = 'false';
    try {
      // Auto-start only fires for the `defaultTourId` (typically global).
      // Per-module tours are launched explicitly via the Tour button —
      // they never auto-pop.
      completed = localStorage.getItem(storageKeyFor(defaultTourId)) ?? 'false';
    } catch {
      /* ignore */
    }
    if (completed === 'true') return;

    const blocked = AUTO_START_BLOCKED_PREFIXES.some((p) => location.pathname.startsWith(p));
    if (blocked) return;

    if (!DASHBOARD_ROUTES.has(location.pathname)) return;

    // Small delay so the dashboard has time to mount its targets.
    const id = window.setTimeout(() => {
      warnedRef.current.clear();
      setActiveTourId(defaultTourId);
      setCurrentStep(0);
      setActive(true);
    }, 600);
    return () => window.clearTimeout(id);
  }, [active, location.pathname, defaultTourId, serverHydrated, onboardingDone]);

  /* ── Navigation handlers ─────────────────────────────────────────────── */
  const handleNext = useCallback(() => {
    if (isLast) {
      completeTour();
      return;
    }
    setCurrentStep((s) => s + 1);
  }, [isLast, completeTour]);

  const handleBack = useCallback(() => {
    if (isFirst) return;
    setCurrentStep((s) => s - 1);
  }, [isFirst]);

  const handleSkip = useCallback(() => {
    completeTour('dismissed');
  }, [completeTour]);

  /* ── Memoised resolved strings ───────────────────────────────────────── */
  const resolved = useMemo(() => {
    if (!step) return null;
    return {
      title: t(step.titleKey, { defaultValue: STEP_FALLBACKS[step.titleKey] ?? step.titleKey }),
      body: t(step.bodyKey, { defaultValue: STEP_FALLBACKS[step.bodyKey] ?? step.bodyKey }),
      counter: t('tour.step_counter', {
        defaultValue: STEP_FALLBACKS['tour.step_counter'],
        current: currentStep + 1,
        total: totalSteps,
      }),
      skip: t('tour.skip', { defaultValue: STEP_FALLBACKS['tour.skip'] }),
      back: t('tour.back', { defaultValue: STEP_FALLBACKS['tour.back'] }),
      next: t('tour.next', { defaultValue: STEP_FALLBACKS['tour.next'] }),
      finish: t('tour.finish', { defaultValue: STEP_FALLBACKS['tour.finish'] }),
    };
  }, [step, t, currentStep, totalSteps]);

  if (!active || !step || !resolved) return null;

  const SHADOW_SPREAD = 9999; // px — large enough to dim the entire viewport.
  // Dark-mode darker scrim + bright cyan accent ring around the cutout so
  // the highlighted area is visually obvious against the dimmed background.
  // Light mode keeps the historical slate tint that has worked for a year.
  const scrimColor = isDark
    ? 'rgba(2, 6, 23, 0.78)' /* slate-950 @ 78% — near-black, high contrast */
    : 'rgba(15, 23, 42, 0.42)'; /* slate-900 @ 42% — historical light value  */

  return (
    <>
      {/* Dim backdrop with rectangular cutout via box-shadow.  When there's
          no spotlight (wrap-up step) we render a full-screen scrim that
          accepts pointer events so the user has to engage with the modal. */}
      <div
        data-testid="product-tour-overlay"
        data-product-tour="overlay"
        className={clsx(
          'fixed inset-0 z-[9000]',
          spotlight
            ? 'pointer-events-none'
            : 'pointer-events-auto bg-black/35 dark:bg-black/75',
        )}
        aria-hidden="true"
      >
        {spotlight && (
          <>
            {/* The dimming layer — uses an enormous box-shadow spread to
                paint the entire viewport while leaving a rectangular cutout
                over the spotlight element itself. */}
            <div
              data-testid="product-tour-spotlight"
              style={{
                position: 'fixed',
                top: spotlight.top,
                left: spotlight.left,
                width: spotlight.width,
                height: spotlight.height,
                boxShadow: `0 0 0 ${SHADOW_SPREAD}px ${scrimColor}`,
                borderRadius: 10,
                zIndex: 9001,
                pointerEvents: 'none',
                transition: 'top 180ms ease, left 180ms ease, width 180ms ease, height 180ms ease',
              }}
            />
            {/* Bright accent ring + glow around the highlighted area.
                Sits on top of the dimming layer (z 9002) so it draws a
                clear, unmistakable boundary between dimmed-background and
                spotlit-content. Stronger in dark mode where the dimming
                alone is hard to see against already-dark surfaces. */}
            <div
              aria-hidden="true"
              data-testid="product-tour-spotlight-ring"
              style={{
                position: 'fixed',
                top: spotlight.top,
                left: spotlight.left,
                width: spotlight.width,
                height: spotlight.height,
                borderRadius: 10,
                zIndex: 9002,
                pointerEvents: 'none',
                border: isDark
                  ? '2px solid rgba(125, 211, 252, 0.95)' /* sky-300, near-opaque */
                  : '2px solid rgba(14, 165, 233, 0.85)', /* sky-500, vivid blue */
                boxShadow: isDark
                  ? '0 0 0 4px rgba(125, 211, 252, 0.25), 0 0 32px 6px rgba(56, 189, 248, 0.55)'
                  : '0 0 0 4px rgba(14, 165, 233, 0.20), 0 0 18px 2px rgba(14, 165, 233, 0.35)',
                transition:
                  'top 180ms ease, left 180ms ease, width 180ms ease, height 180ms ease',
              }}
            />
          </>
        )}
      </div>

      {/* Tooltip card */}
      <div
        role="dialog"
        aria-modal="false"
        aria-labelledby="product-tour-title"
        data-testid="product-tour-tooltip"
        data-product-tour="tooltip"
        style={{
          position: 'fixed',
          top: tooltipCoords.top,
          left: tooltipCoords.left,
          width: TOOLTIP_W,
          zIndex: 9100,
        }}
        className={clsx(
          'rounded-2xl border',
          // Light: subtle hairline. Dark: bright sky tint + outer glow
          // ring so the card stands away from the near-black scrim.
          'border-border-light dark:border-sky-400/60',
          'bg-surface-elevated shadow-xl',
          'dark:shadow-[0_8px_32px_rgba(2,6,23,0.6),0_0_0_1px_rgba(125,211,252,0.25)]',
          'p-5 pointer-events-auto animate-scale-in',
        )}
      >
        {/* Header row */}
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className={clsx(
                'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                isLast ? 'bg-emerald-500/10 text-emerald-600' : 'bg-oe-blue/10 text-oe-blue',
              )}
            >
              {isLast ? <Check size={15} /> : <MapPin size={15} />}
            </div>
            <h3
              id="product-tour-title"
              className="text-sm font-semibold text-content-primary leading-snug"
            >
              {resolved.title}
            </h3>
          </div>
          <button
            type="button"
            onClick={handleSkip}
            data-testid="product-tour-skip"
            className={clsx(
              'shrink-0 flex h-6 w-6 items-center justify-center rounded-md',
              'text-content-tertiary hover:text-content-primary hover:bg-surface-secondary',
              'transition-colors',
            )}
            aria-label={resolved.skip}
            title={resolved.skip}
          >
            <X size={14} />
          </button>
        </div>

        {/* Body copy */}
        <p className="text-xs text-content-secondary leading-relaxed mb-4">{resolved.body}</p>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3">
          <span
            data-testid="product-tour-step-counter"
            className="text-2xs font-medium text-content-tertiary tabular-nums"
          >
            {resolved.counter}
          </span>

          {/* Dot indicators */}
          <div className="flex items-center gap-1 mx-auto" aria-hidden>
            {resolvedSteps.map((_, idx) => (
              <div
                key={idx}
                className={clsx(
                  'rounded-full transition-all duration-150',
                  idx === currentStep ? 'h-2 w-4 bg-oe-blue' : 'h-1.5 w-1.5 bg-border',
                )}
              />
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            {!isFirst && (
              <button
                type="button"
                onClick={handleBack}
                data-testid="product-tour-back"
                className={clsx(
                  'flex h-7 items-center gap-1 rounded-lg px-2.5',
                  'border border-border text-content-secondary text-xs',
                  'hover:bg-surface-secondary hover:text-content-primary',
                  'transition-colors',
                )}
                aria-label={resolved.back}
              >
                <ArrowLeft size={12} />
                {resolved.back}
              </button>
            )}
            <button
              type="button"
              onClick={handleNext}
              data-testid="product-tour-next"
              className={clsx(
                'flex h-7 items-center gap-1.5 rounded-lg px-3',
                isLast
                  ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                  : 'bg-oe-blue text-white hover:opacity-90',
                'text-xs font-medium transition-colors',
              )}
              aria-label={isLast ? resolved.finish : resolved.next}
            >
              {isLast ? resolved.finish : resolved.next}
              {!isLast && <ArrowRight size={12} />}
            </button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmExitOpen}
        onCancel={() => setConfirmExitOpen(false)}
        onConfirm={() => {
          setConfirmExitOpen(false);
          completeTour('dismissed');
        }}
        variant="warning"
        title={t('tour.confirm_skip_title', { defaultValue: 'Exit tour?' })}
        message={t('tour.confirm_skip', {
          defaultValue: 'Skip the product tour? You can re-launch it from the Help menu.',
        })}
        confirmLabel={t('tour.confirm_skip_confirm', { defaultValue: 'Exit tour' })}
        cancelLabel={t('tour.confirm_skip_cancel', { defaultValue: 'Keep going' })}
      />
    </>
  );
}
