// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Waste Factors (net-to-gross quantity adjustment).
 *
 * All endpoints are mounted at /api/v1/waste-factors/. Factors and
 * quantities are decimal strings in and out (the platform-wide "money /
 * quantity as string" convention) so a precise multiplier or a large
 * takeoff quantity never loses digits through a JS Number. The app runs
 * with redirect_slashes disabled, so collection paths keep their trailing
 * slash.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

const BASE = '/v1/waste-factors';

/* -- Types ---------------------------------------------------------------- */

export interface WasteFactor {
  id: string;
  category: string;
  label: string;
  /** Multiplier >= 1 as a decimal string, e.g. "1.1000". */
  factor: string;
  note: string | null;
  tenant_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface WasteFactorCreatePayload {
  category: string;
  label?: string;
  factor: string;
  note?: string | null;
}

export interface WasteFactorUpdatePayload {
  category?: string;
  label?: string;
  factor?: string;
  note?: string | null;
}

export interface SeedResult {
  inserted: number;
  skipped: number;
  total_after: number;
}

/** One net line submitted to /apply. */
export interface ApplyLineInput {
  category: string;
  net_qty: string;
}

/** One converted line returned by /apply. */
export interface ApplyLineResult {
  category: string;
  net_qty: string;
  factor: string;
  gross_qty: string;
  /** False when the category had no library entry (factor 1.0 applied). */
  matched: boolean;
}

export interface ApplyResponse {
  lines: ApplyLineResult[];
}

/* -- Formatting (pure, unit-tested) --------------------------------------- */

/**
 * Trim trailing zeros from a decimal string for display, without touching
 * the value ("12.5000" -> "12.5", "1.0000" -> "1", "100" -> "100"). Works on
 * the raw string so a precise quantity never round-trips through a float.
 * A non-decimal input is passed through unchanged.
 */
export function trimQty(raw: string | null | undefined): string {
  if (raw == null || raw === '') return '0';
  const s = String(raw).trim();
  if (!/^-?\d+(\.\d+)?$/.test(s)) return s;
  if (!s.includes('.')) return s;
  const trimmed = s.replace(/\.?0+$/, '');
  return trimmed === '' || trimmed === '-' ? '0' : trimmed;
}

/** A line parsed from the quick-apply textarea. */
export interface ParsedApplyLine {
  category: string;
  net_qty: string;
}

const QTY_TOKEN_RE = /^\d+(\.\d+)?$/;

/**
 * Parse pasted "category  quantity" lines into apply inputs.
 *
 * Each non-empty line is split on commas, semicolons, tabs or spaces; the
 * last token is the (non-negative) net quantity and everything before it is
 * the category (so multi-word categories like "structural steel 100" work).
 * The quantity is kept as its raw string - never parsed to a float - so it
 * reaches the backend Decimal engine intact. Lines whose last token is not a
 * plain non-negative number, or that have no category, are skipped.
 *
 * @example
 * parseApplyInput('concrete 12.5\nrebar, 340\nstructural steel 8')
 * // [{category:'concrete',net_qty:'12.5'}, {category:'rebar',net_qty:'340'},
 * //  {category:'structural steel',net_qty:'8'}]
 */
export function parseApplyInput(text: string): ParsedApplyLine[] {
  const out: ParsedApplyLine[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const parts = line.split(/[\s,;]+/).filter(Boolean);
    if (parts.length < 2) continue;
    const qty = parts[parts.length - 1];
    if (qty === undefined || !QTY_TOKEN_RE.test(qty)) continue;
    const category = parts.slice(0, -1).join(' ').trim();
    if (!category) continue;
    out.push({ category, net_qty: qty });
  }
  return out;
}

/**
 * Map a project's material resource lines onto net apply-lines for the
 * net-to-gross calculator: the material name becomes the category and the
 * server's exact quantity string is preserved verbatim (never parsed through a
 * float), so a loaded quantity matches the estimate to the last digit. Lines
 * with no name, or whose quantity is not a plain non-negative number, are
 * skipped. Read-only helper: it fills the calculator input, it never edits the
 * estimate or its billed quantities.
 *
 * @example
 * materialLinesToApplyInput([{ name: 'Concrete C30/37', quantity: '12.5000' }])
 * // [{ category: 'Concrete C30/37', net_qty: '12.5000' }]
 */
export function materialLinesToApplyInput(
  lines: ReadonlyArray<{ name: string; quantity: string }>,
): ApplyLineInput[] {
  const out: ApplyLineInput[] = [];
  for (const line of lines) {
    const category = (line.name ?? '').trim();
    const net_qty = (line.quantity ?? '').trim();
    if (!category || !QTY_TOKEN_RE.test(net_qty)) continue;
    out.push({ category, net_qty });
  }
  return out;
}

/* -- Factor library CRUD -------------------------------------------------- */

export async function listFactors(category?: string): Promise<WasteFactor[]> {
  const suffix = category ? `?category=${encodeURIComponent(category)}` : '';
  const res = await apiGet<WasteFactor[]>(`${BASE}/factors/${suffix}`);
  return Array.isArray(res) ? res : [];
}

export async function createFactor(data: WasteFactorCreatePayload): Promise<WasteFactor> {
  return apiPost<WasteFactor>(`${BASE}/factors/`, data);
}

export async function updateFactor(
  id: string,
  data: WasteFactorUpdatePayload,
): Promise<WasteFactor> {
  return apiPatch<WasteFactor>(`${BASE}/factors/${id}`, data);
}

export async function deleteFactor(id: string): Promise<void> {
  return apiDelete(`${BASE}/factors/${id}`);
}

export async function seedDefaults(): Promise<SeedResult> {
  return apiPost<SeedResult>(`${BASE}/seed-defaults`, {});
}

/* -- Apply (net -> gross) ------------------------------------------------- */

export async function applyFactors(lines: ApplyLineInput[]): Promise<ApplyResponse> {
  return apiPost<ApplyResponse>(`${BASE}/apply`, { lines });
}
