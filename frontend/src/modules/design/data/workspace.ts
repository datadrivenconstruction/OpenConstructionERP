// Design module (ERP side of the design editor link).
/** Pure parts of the editor workspace: the open message, the side panel's estimate lines, the AI draft the person confirmed. */
import type { OpenMsg, SelectedElement } from '../bridge/protocol';
import type { DraftLine, DraftView } from '../draftApi';
import type { RevisionView } from './revisions';
import { isImported } from './revisions';
import type { EstimatePosition } from './estimate';
import { getAt, setAt, type BriefDoc } from './briefModel';

/** The revision the editor builds on: newest waiting or published design (imports never, README §8). */
export function chainTip(revs: RevisionView[]): RevisionView | null {
  return revs
    .filter((r) => (r.status === 'shared' || r.status === 'published') && !isImported(r))
    .reduce<RevisionView | null>((best, r) => (!best || r.number > best.number ? r : best), null);
}

interface ManifestFile { path: string; role: string; bytes: number }

export function openMessage(o: {
  project: { id: string; name: string };
  brief: BriefDoc | null;
  revisions: RevisionView[];
  locale: string;
  theme: 'light' | 'dark';
  draft: DraftView | null;
  mode: 'edit' | 'view';
  canEdit: boolean;
  canAccept: boolean;
  ai: boolean;
}): OpenMsg {
  const tip = chainTip(o.revisions);
  const files = ((tip?.manifest as { files?: ManifestFile[] } | undefined)?.files ?? []).map((f) => ({
    path: f.path, role: f.role, bytes: f.bytes,
    url: `/api/v1/design/revisions/${tip!.revision_id}/files/${f.path.split('/').map(encodeURIComponent).join('/')}`,
  }));
  return {
    bridge: 1, type: 'open',
    project: { id: o.project.id, name: o.project.name.slice(0, 500) },
    brief: (o.brief as unknown as Record<string, unknown>) ?? null,
    brief_version: o.brief?.version ?? null,
    revision: tip ? { revision_id: tip.revision_id, number: tip.number, status: tip.status as 'shared' | 'published', files } : null,
    draft: o.draft ? { revision_id: o.draft.revision_id, parent_revision_id: o.draft.parent_revision_id,
      updated_at: o.draft.updated_at, element_count: o.draft.element_count } : null,
    mode: o.canEdit ? o.mode : 'view',
    locale: o.locale, theme: o.theme,
    permissions: { can_edit: o.canEdit, can_accept: o.canAccept },
    ai: { available: o.ai },
  };
}

/* ── Side panel: estimate lines for the selection ────────────────────── */

export type Match = 'yes' | 'maybe' | 'no';

/**
 * Whether a rule's `select` (rules.py `matches`) takes this element. What the element does not say (type key,
 * material, storey, quantities in `where`) cannot be decided here: 'maybe', never a guess.
 */
export function ruleMatch(e: SelectedElement, sel: Record<string, unknown> | undefined): Match {
  if (!sel || typeof sel !== 'object') return 'no';
  const parts: Match[] = [];
  if (Array.isArray(sel.any_of)) {
    const subs = (sel.any_of as Record<string, unknown>[]).map((s) => ruleMatch(e, s));
    parts.push(subs.includes('yes') ? 'yes' : subs.includes('maybe') ? 'maybe' : 'no');
  }
  if (Array.isArray(sel.ifc_class)) {
    parts.push(!e.ifc_class ? 'maybe' : (sel.ifc_class as string[]).includes(e.ifc_class) ? 'yes' : 'no');
  }
  if (Array.isArray(sel.type_key_prefix)) {
    parts.push(e.type_key === undefined ? 'maybe' : (sel.type_key_prefix as string[]).some((p) => e.type_key!.startsWith(p)) ? 'yes' : 'no');
  }
  if (Array.isArray(sel.type_key_not_prefix)) {
    parts.push(e.type_key === undefined ? 'maybe' : (sel.type_key_not_prefix as string[]).some((p) => e.type_key!.startsWith(p)) ? 'no' : 'yes');
  }
  if (typeof sel.key_matches === 'string') {
    try { parts.push(new RegExp(sel.key_matches).test(e.element_key) ? 'yes' : 'no'); } catch { parts.push('maybe'); }
  }
  if ('material_contains' in sel || 'storey' in sel || (Array.isArray(sel.where) && sel.where.length > 0)) parts.push('maybe');
  if (parts.length === 0) return 'no';
  return parts.includes('no') ? 'no' : parts.includes('maybe') ? 'maybe' : 'yes';
}

export interface LineForSelection { position: EstimatePosition; match: Exclude<Match, 'no'> }

/** Model lines of the estimate that take any selected element; 'yes' before 'maybe', estimate order kept. */
export function linesFor(elements: SelectedElement[], positions: EstimatePosition[]): LineForSelection[] {
  const out: LineForSelection[] = [];
  for (const p of positions) {
    if (p.kind !== 'model') continue;
    const sel = p.provenance?.select as Record<string, unknown> | undefined;
    const ms = elements.map((e) => ruleMatch(e, sel));
    const m: Match = ms.includes('yes') ? 'yes' : ms.includes('maybe') ? 'maybe' : 'no';
    if (m !== 'no') out.push({ position: p, match: m });
  }
  return [...out.filter((l) => l.match === 'yes'), ...out.filter((l) => l.match === 'maybe')];
}

/** Lines of the saved draft that take a selected element: exact (the server evaluated the rules on the draft). */
export function draftLinesFor(elements: SelectedElement[], draft: DraftView | null): DraftLine[] {
  if (!draft || elements.length === 0) return [];
  const keys = new Set(elements.map((e) => e.element_key));
  return draft.estimate.lines.filter((l) => l.element_keys.some((k) => keys.has(k)));
}

/** Lines whose draft quantity differs from the estimate's, for the "what changes" list. */
export function changedLines(draft: DraftView | null): DraftLine[] {
  if (!draft) return [];
  return draft.estimate.lines.filter((l) => l.quantity !== null && l.current_quantity !== null
    && Number(l.quantity) !== Number(l.current_quantity));
}

/**
 * Editing needs a fine pointer and room for the canvas beside the panels; tablets and phones look and select.
 * Width alone would let a narrow desktop window edit, so both are required.
 */
export function deviceMode(env: { finePointer: boolean; width: number }): 'edit' | 'view' {
  return env.finePointer && env.width >= 900 ? 'edit' : 'view';
}

/* ── AI draft → what the person confirmed ────────────────────────────── */

/**
 * The extraction draft keeps only the proposed values the person confirmed; the others are taken out with their
 * provenance. Values the draft did not propose (the base brief's, project defaults) stay as they are.
 */
export function keepConfirmed(draft: BriefDoc, proposed: string[], confirmed: string[]): BriefDoc {
  const keep = new Set(confirmed);
  let out = draft;
  // deepest and last first, so removing a list item does not move the pointers still to visit
  for (const p of [...proposed].sort().reverse()) {
    if (keep.has(p)) continue;
    out = setAt(out, p, undefined);
    if (out.provenance) {
      const { [p]: _gone, ...rest } = out.provenance;
      out = { ...out, provenance: rest };
    }
  }
  return out;
}

export interface Proposal { pointer: string; value: unknown; quote: string | null; page: number | null }

export function proposals(draft: BriefDoc, proposed: string[]): Proposal[] {
  return proposed
    .filter((p) => getAt(draft, p) !== undefined)
    .map((p) => {
      const src = draft.provenance?.[p]?.sources?.[0];
      return { pointer: p, value: getAt(draft, p), quote: src?.quote ?? null, page: src?.page ?? null };
    });
}

/** Services set up in the person's ERP AI settings, named as the settings name them (`<name>_api_key_set`, `<name>_base_url`). */
export function aiServices(settings: unknown): string[] {
  if (!settings || typeof settings !== 'object') return [];
  const out = new Set<string>();
  for (const [k, v] of Object.entries(settings as Record<string, unknown>)) {
    if (k.endsWith('_api_key_set') && v === true) out.add(k.slice(0, -'_api_key_set'.length));
    if (k.endsWith('_base_url') && typeof v === 'string' && v.trim() !== '') out.add(k.slice(0, -'_base_url'.length));
  }
  return [...out].sort();
}

/** The person's AI settings name at least one configured service (key set or endpoint given). */
export function aiConfigured(settings: unknown): boolean {
  if (!settings || typeof settings !== 'object') return false;
  return Object.entries(settings as Record<string, unknown>).some(([k, v]) =>
    (k.endsWith('_api_key_set') && v === true) || (k.endsWith('_base_url') && typeof v === 'string' && v.trim() !== ''));
}
