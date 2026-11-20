// Design module (ERP side of the design editor link).
/**
 * One summary screen for every proposal (AI reading of text or files, a template, a plot drawn on the map): all
 * values with their sources, the doubtful ones first and marked, the person corrects or leaves out what is needed
 * and confirms the rest with one button. Pure helpers; the screen is ProposalSummary.tsx.
 */
import { getAt, setAt, type BriefDoc, type Provenance, type ProvenanceSource } from './briefModel';
import { keepConfirmed } from './workspace';

export type Origin = 'text' | 'files' | 'template' | 'map';
export type Doubt = 'no_quote' | 'question' | 'typical' | null;

export interface SummaryItem {
  pointer: string;
  value: unknown;
  source: ProvenanceSource | null;
  /** Why a person should look twice; null when the value is quoted from what they gave. */
  doubt: Doubt;
}

/** A draft with every value marked proposed, ready for the summary screen. */
export interface ProposalSet {
  origin: Origin;
  draft: BriefDoc;
  items: SummaryItem[];
  questions: string[];
  /** Document names by id, to say which file a value was read from. */
  documents?: Record<string, string>;
  /** Values read again that the brief already has confirmed (left as they are). */
  known?: number;
}

/** From an R5 extraction: a value without a quote, or one the AI asked about, is doubtful. */
export function fromExtraction(origin: Origin, draft: BriefDoc, proposed: string[], questions: string[],
  documents?: Record<string, string>, known = 0): ProposalSet {
  const asked = new Set((draft.questions ?? []).map((q) => q.pointer));
  const items = proposed
    .filter((p) => getAt(draft, p) !== undefined)
    .map((p) => {
      const src = draft.provenance?.[p]?.sources?.[0] ?? null;
      const doubt: Doubt = asked.has(p) ? 'question' : src?.quote ? null : 'no_quote';
      return { pointer: p, value: getAt(draft, p), source: src, doubt };
    });
  return { origin, draft, items: ordered(items), questions, documents, known };
}

/** Values a template or the map proposes, written into `base` as proposed with their source. */
export function fromValues(origin: Origin, base: BriefDoc,
  values: { pointer: string; value: unknown; doubtful?: boolean; source: ProvenanceSource; note?: string }[]): ProposalSet {
  let draft = base;
  const prov: Record<string, Provenance> = { ...(base.provenance ?? {}) };
  for (const v of values) {
    draft = setAt(draft, v.pointer, v.value);
    prov[v.pointer] = { status: 'proposed', sources: [v.source], ...(v.note ? { note: v.note } : {}) };
  }
  draft = { ...draft, provenance: prov };
  const items = values.map((v) => ({
    pointer: v.pointer, value: v.value, source: v.source, doubt: (v.doubtful ? 'typical' : null) as Doubt,
  }));
  return { origin, draft, items: ordered(items), questions: [] };
}

/** Doubtful values first (in their own order), then the rest. */
function ordered(items: SummaryItem[]): SummaryItem[] {
  return [...items.filter((i) => i.doubt), ...items.filter((i) => !i.doubt)];
}

/**
 * The brief to save: the kept values (as proposed, corrected ones with the person as their source), everything
 * left out removed. Confirmation follows on the saved version for exactly `pointers`.
 */
export function applySummary(set: ProposalSet, leftOut: ReadonlySet<string>, edits: Readonly<Record<string, unknown>>):
  { doc: BriefDoc; pointers: string[] } {
  const all = set.items.map((i) => i.pointer);
  const keep = all.filter((p) => !leftOut.has(p) && !(p in edits && edits[p] === undefined));
  let doc = keepConfirmed(set.draft, all, keep);
  for (const p of keep) {
    if (!(p in edits)) continue;
    doc = setAt(doc, p, edits[p]);
    doc = { ...doc, provenance: { ...(doc.provenance ?? {}), [p]: { status: 'proposed', sources: [{ kind: 'user' }] } } };
  }
  return { doc, pointers: keep };
}
