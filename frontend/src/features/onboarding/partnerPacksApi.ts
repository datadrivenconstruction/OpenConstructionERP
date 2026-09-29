// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Onboarding ↔ partner-pack API helpers.
 *
 * The "Set up by country" picker in the onboarding wizard installs an entire
 * localized workspace for one of the real partner packs we ship (see
 * ``docs/country-pack-oneclick/DESIGN.md`` §5/§7). These helpers wrap the two
 * endpoints that flow drives:
 *
 *   - ``GET  /api/v1/partner-pack/installed``   → list discovered packs.
 *   - ``POST /api/v1/partner-pack/full-install`` → one-click install everything
 *     (apply pack + locale + relational cost DB + vector DB + N country demos).
 *
 * Logos are streamed per-slug from ``GET /api/v1/partner-pack/logo/{slug}`` and
 * rendered as plain ``<img src>``.
 */

import { apiGet, apiPost, API_BASE, getAuthToken } from '@/shared/lib/api';
import type { PackType } from '@/shared/hooks/usePartnerPack';
import { packCountryCode } from '@/shared/lib/regionalPack';

// ── Installed packs ──────────────────────────────────────────────────────────

/** Branding subset of a pack's public manifest (see ``manifest.to_public_dict``). */
export interface PartnerPackBranding {
  primary_color: string;
  accent_color: string;
  has_logo: boolean;
  has_favicon: boolean;
  powered_by_text: string;
}

/**
 * A discovered partner pack as returned by ``GET /partner-pack/installed``.
 *
 * Mirrors ``PartnerPackManifest.to_public_dict()``; only the fields the
 * onboarding picker consumes are typed. ``metadata`` is free-form per pack —
 * the reference packs carry ``country`` (ISO-3166 alpha-2) and
 * ``country_name_en``, which we use for the flag + card title.
 */
export interface InstalledPartnerPack {
  slug: string;
  /** Pack type; absent on older backends, treated as ``partner``. */
  type?: PackType;
  partner_name: string;
  partner_url: string | null;
  pack_version: string;
  description: string;
  default_locale: string;
  additional_locales: string[];
  cwicr_regions: string[];
  default_currency: string;
  default_tax_template: string | null;
  validation_rule_packs: string[];
  default_modules: string[];
  hidden_modules: string[];
  branding: PartnerPackBranding;
  has_onboarding_script: boolean;
  metadata: Record<string, unknown>;
}

/** Response of ``GET /api/v1/partner-pack/installed``. */
export interface InstalledPacksResponse {
  active_slug: string | null;
  installed: InstalledPartnerPack[];
}

/** Fetch every discovered partner pack (+ which one is active). */
export async function fetchInstalledPacks(): Promise<InstalledPacksResponse> {
  return apiGet<InstalledPacksResponse>('/v1/partner-pack/installed');
}

/** URL for a pack's logo image, suitable for ``<img src>``. */
export function partnerPackLogoUrl(slug: string): string {
  return `${API_BASE}/v1/partner-pack/logo/${encodeURIComponent(slug)}`;
}

// ── Full install (one-click localized workspace) ─────────────────────────────

/** The five orchestration steps reported by ``full-install`` (DESIGN §5). */
export type FullInstallStepName =
  | 'apply_pack'
  | 'locale'
  | 'cost_db'
  | 'vector_db'
  | 'demos';

/** Per-step status from the ``full-install`` response. */
export type FullInstallStepStatus = 'ok' | 'error' | 'skipped';

/** One entry in the ``full-install`` ``steps`` list. */
export interface FullInstallStep {
  step: FullInstallStepName;
  status: FullInstallStepStatus;
  detail: Record<string, unknown>;
}

/** Response of ``POST /api/v1/partner-pack/full-install``. */
export interface FullInstallResponse {
  slug: string;
  ok: boolean;
  steps: FullInstallStep[];
}

/** Body of ``POST /api/v1/partner-pack/full-install``. */
export interface FullInstallRequest {
  slug: string;
  set_locale: boolean;
  install_cost_db: boolean;
  vectorize: boolean;
  demo_count: number;
}

/**
 * Install an entire localized workspace for ``slug`` in one call.
 *
 * This is heavy (relational cost DB import + vectorization + ``demoCount``
 * fully-worked demos, ~30–90s), so it opts into the api client's long-running
 * (5-minute) abort budget. The endpoint is fail-soft: it always resolves with
 * the §5 response object (never throws on a single failed step), so the caller
 * renders ``response.steps`` directly into a progress checklist.
 */
export async function fullInstallPack(
  slug: string,
  demoCount = 2,
): Promise<FullInstallResponse> {
  return apiPost<FullInstallResponse, FullInstallRequest>(
    '/v1/partner-pack/full-install',
    {
      slug,
      set_locale: true,
      install_cost_db: true,
      // The semantic vector index is intentionally NOT built during activation.
      // It only powers AI fuzzy search of cost items (which degrades to exact /
      // keyword search when absent) and is by far the slowest step (embedding
      // 55K+ items on CPU), so building it inline made activation appear frozen
      // for minutes. It can be built later on demand.
      vectorize: false,
      demo_count: demoCount,
    },
    { longRunning: true },
  );
}

/** The ordered step names the checklist renders, even before a response. */
export const FULL_INSTALL_STEPS: FullInstallStepName[] = [
  'apply_pack',
  'locale',
  'cost_db',
  'vector_db',
  'demos',
];

// ── Streaming full install (live per-step progress over SSE) ─────────────────

/**
 * The step ids the streaming installer emits. Superset of
 * {@link FullInstallStepName}: the stream additionally announces a dedicated
 * ``resources`` row (CWICR work items bundle their labour/material/equipment
 * breakdown in the same load, so loading the work catalog loads the resource
 * database in one pass; the stream surfaces the embedded resource count as its
 * own progress row for clarity).
 */
export type StreamStepName =
  | 'apply_pack'
  | 'locale'
  | 'cost_db'
  | 'resources'
  | 'catalog'
  | 'vector_db'
  | 'demos';

/** A step descriptor from the stream's opening ``start`` event. */
export interface StreamStepDescriptor {
  step: StreamStepName;
  /** i18next key the frontend can localize. */
  label_key: string;
  /** English fallback label (use as ``defaultValue``). */
  label: string;
}

/** Discriminated union of the SSE frames the installer emits. */
export type StreamInstallEvent =
  | { type: 'start'; slug: string; total: number; steps: StreamStepDescriptor[] }
  | { type: 'step_start'; step: StreamStepName; index: number; total: number }
  | {
      type: 'step_done';
      step: StreamStepName;
      index: number;
      total: number;
      status: FullInstallStepStatus;
      detail: Record<string, unknown>;
    }
  | { type: 'done'; slug: string; ok: boolean; steps: FullInstallStep[] };

/**
 * Why a streamed install did not run to its ``done`` frame.
 *
 * ``forbidden`` is the one production hit first: a viewer account opened the
 * dialog, the server answered 403 before the first frame, and the dialog had
 * nothing to show but an empty checklist.
 */
export type PackInstallFailureKind =
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'invalid'
  | 'server'
  | 'network'
  | 'incomplete'
  | 'http';

/**
 * A streamed install that failed as a whole, as opposed to one step of it.
 *
 * ``message`` stays a readable English sentence because the onboarding picker
 * and the cases strip print it as is. ``kind`` is what a screen that can
 * localize should branch on, and ``detail`` is the server's own ``detail``
 * string when it sent one, never a raw HTML page from a proxy.
 */
export class PackInstallError extends Error {
  readonly kind: PackInstallFailureKind;
  readonly status: number | null;
  readonly detail: string | null;

  constructor(kind: PackInstallFailureKind, status: number | null, detail: string | null, message: string) {
    super(message);
    this.name = 'PackInstallError';
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

/** Map an HTTP status to the failure kind the dialog explains. */
export function packInstallFailureKind(status: number): PackInstallFailureKind {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 400 || status === 422) return 'invalid';
  if (status >= 500) return 'server';
  return 'http';
}

/**
 * The ``detail`` of a FastAPI error body, or null.
 *
 * Only a JSON ``detail`` string is kept. A 502 from nginx is an HTML page, and
 * printing that into a dialog is how a user ends up reading markup.
 */
function errorDetail(body: string): string | null {
  if (!body) return null;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) return parsed.detail.trim();
    if (Array.isArray(parsed.detail)) {
      const msgs = parsed.detail
        .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : ''))
        .filter(Boolean);
      return msgs.length ? msgs.join('; ') : null;
    }
  } catch {
    // Not JSON: a proxy page or plain text. Say nothing rather than markup.
  }
  return null;
}

/** Options for {@link fullInstallPackStream}. */
export interface FullInstallStreamOptions {
  demoCount?: number;
  confirmDisables?: boolean;
  vectorize?: boolean;
  /**
   * Which of the pack's declared cost regions to load. Omitted means all of
   * them, which is what the onboarding picker and the cases strip want. An
   * empty list loads none.
   */
  costRegions?: string[];
  /** Load the resource catalogue of each loaded region. Default true. */
  installCatalog?: boolean;
  /**
   * Run only these steps, for retrying the ones that failed. Omitted runs the
   * full install.
   */
  onlySteps?: StreamStepName[];
  signal?: AbortSignal;
}

/**
 * Activate a partner pack with live per-step progress.
 *
 * Calls ``POST /api/v1/partner-pack/full-install-stream`` (Server-Sent Events)
 * and invokes ``onEvent`` for every ``start`` / ``step_start`` / ``step_done`` /
 * ``done`` frame, so the caller can drive a determinate progress bar + a named
 * step checklist as each step actually runs server-side (apply preset, install
 * language, load the work catalog and its resource database, build the vector
 * index, create the demo projects).
 *
 * The endpoint is fail-soft: every step reports ``ok`` / ``skipped`` / ``error``
 * and the stream always reaches a ``done`` frame, so a single failed step never
 * throws here. What rejects is the install failing as a whole, and it rejects
 * with a {@link PackInstallError} naming why: the server refused the request
 * (401, 403, 404, 409, 422, 5xx), the network dropped before an answer, or the
 * stream closed before its ``done`` frame. An abort rejects with the browser's
 * own ``AbortError`` so callers can keep ignoring it.
 *
 * Uses raw ``fetch`` + a ``ReadableStream`` reader (not the native
 * ``EventSource``, which cannot send the ``Authorization`` header) - the same
 * pattern the ERP chat stream uses.
 */
export async function fullInstallPackStream(
  slug: string,
  onEvent: (event: StreamInstallEvent) => void,
  opts: FullInstallStreamOptions = {},
): Promise<void> {
  // ``vectorize`` defaults to false: the semantic index only powers AI fuzzy
  // search (graceful fallback when absent) and is the slowest step by far, so
  // building it inline made activation look stuck. Pass ``vectorize: true``
  // only from an explicit "build search index" action.
  const {
    demoCount = 2,
    confirmDisables = false,
    vectorize = false,
    costRegions,
    installCatalog = true,
    onlySteps,
    signal,
  } = opts;
  const token = getAuthToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/v1/partner-pack/full-install-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        slug,
        set_locale: true,
        install_cost_db: true,
        install_catalog: installCatalog,
        vectorize,
        confirm_disables: confirmDisables,
        demo_count: demoCount,
        ...(costRegions ? { cost_regions: costRegions } : {}),
        ...(onlySteps ? { only_steps: onlySteps } : {}),
      }),
      signal,
    });
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') throw err;
    throw new PackInstallError(
      'network',
      null,
      null,
      'Could not reach the server to activate this pack. Check the connection and try again.',
    );
  }

  if (!response.ok || !response.body) {
    const body = await response.text().catch(() => '');
    const detail = errorDetail(body);
    const kind = response.ok ? 'incomplete' : packInstallFailureKind(response.status);
    throw new PackInstallError(
      kind,
      response.status,
      detail,
      detail
        ? `Activation failed (HTTP ${response.status}): ${detail}`
        : `Activation failed (HTTP ${response.status})`,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';
  let sawDone = false;

  // Parse standard SSE frames: ``event:`` line names the frame, the following
  // ``data:`` line carries the JSON payload, a blank line terminates the frame.
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') throw err;
      throw new PackInstallError(
        'incomplete',
        response.status,
        null,
        'The connection dropped while the pack was installing. Completed steps are kept.',
      );
    }
    const { done, value } = chunk;
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, '');
      if (line.trim() === '') {
        currentEvent = '';
        continue;
      }
      if (line.startsWith('event:')) {
        currentEvent = line.slice(6).trim();
        continue;
      }
      if (!line.startsWith('data:')) continue;
      const jsonStr = line.slice(5).trim();
      if (!jsonStr) continue;
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(jsonStr) as Record<string, unknown>;
      } catch {
        continue;
      }
      if (currentEvent === 'start' || currentEvent === 'step_start' || currentEvent === 'step_done' || currentEvent === 'done') {
        if (currentEvent === 'done') sawDone = true;
        onEvent({ type: currentEvent, ...payload } as StreamInstallEvent);
      }
    }
  }

  // A stream that ends without ``done`` was cut, by a proxy timeout or a
  // server restart. Returning quietly here is what let a caller read the
  // missing verdict as a finished install.
  if (!sawDone) {
    throw new PackInstallError(
      'incomplete',
      response.status,
      null,
      'The connection dropped while the pack was installing. Completed steps are kept.',
    );
  }
}

/**
 * Derive an ISO-3166 alpha-2 country code for a pack.
 *
 * The implementation moved to ``@/shared/lib/regionalPack`` when the dashboard
 * and the cases runner started asking the same question. Features here do not
 * import from one another, so the alternative was a second copy in ``shared``
 * and this one drifting away from it. Re-exported rather than renamed so the
 * dozen call sites in this feature keep reading the way they read.
 */
export { packCountryCode };

/*
 * ``packCountryName`` used to live here and read ``metadata.country_name_en``.
 * It is gone rather than deprecated, on purpose. That field is English by its
 * own name, so every one of its eleven callers rendered English in all
 * forty-one languages, and us-california, us-costdata and us-texas share one
 * "United States" between them in it. A function still exported is a function
 * the next screen will reach for. The replacement is ``packDisplayName`` in
 * OnboardingWizard, which reads the translated ``modules.pp_name_<slug>``.
 */

/**
 * A 1–2 character monogram for a pack's logo badge.
 *
 * Every reference pack ships a *wide wordmark* logo (≈5:1 aspect, e.g.
 * 240×50) intended for the co-brand strip — squeezing it into the small
 * square tile the onboarding picker uses renders an unreadable sliver. So
 * the picker draws a clean monogram badge instead (brand colour + initials),
 * which is legible at 40px and never breaks.
 *
 * Source order:
 *   1. ``metadata.country`` ISO code, when it's a real 2-letter country
 *      (skips placeholder ``XX``) — gives "US", "DE", "CA", "BR"…
 *   2. Initials of the partner name's words ("US Construction Pack" → "US",
 *      "New Zealand Construction Pack" → "NZ", "batimatech" → "BA").
 */
export function packInitials(pack: InstalledPartnerPack): string {
  const country = pack.metadata?.country;
  if (typeof country === 'string') {
    const code = country.trim().toUpperCase();
    if (/^[A-Z]{2}$/.test(code) && code !== 'XX') return code;
  }
  const words = pack.partner_name
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
    // Drop generic suffixes so "US Construction Pack" → "US", not "UC".
    .filter((w) => !/^(construction|pack|the|and|of|für|de|für)$/i.test(w));
  if (words.length >= 2) {
    return (words[0]![0]! + words[1]![0]!).toUpperCase();
  }
  if (words.length === 1) {
    return words[0]!.slice(0, 2).toUpperCase();
  }
  return pack.partner_name.slice(0, 2).toUpperCase() || '··';
}
