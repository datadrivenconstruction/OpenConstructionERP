// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure helpers for the basis-of-estimate panel: render the document to Markdown
// for the proposal export, build a safe download filename, and factory a blank
// manual line. Kept free of React and network so they unit-test without a
// browser. All user-facing labels are passed in (already translated) so nothing
// here hardcodes a display string.

import type { EstimateBasisDocument, EstimateClassOption, QualificationCategory, QualificationItem } from './api';

/** The basis PATCH and persisted document currently support only AACE 1-5. */
export function editableBasisClasses(classes: EstimateClassOption[]): EstimateClassOption[] {
  return classes.filter((option) =>
    option.classification_system === 'aace' &&
    typeof option.estimate_class === 'number' &&
    Number.isInteger(option.estimate_class) &&
    option.estimate_class >= 1 && option.estimate_class <= 5,
  );
}

/** Only the lines the estimator has left enabled. */
export function enabledItems(items: QualificationItem[]): QualificationItem[] {
  return items.filter((it) => it.enabled);
}

/** Translated section headings + boilerplate the Markdown render weaves in. */
export interface MarkdownLabels {
  inclusions: string;
  exclusions: string;
  assumptions: string;
  notes: string;
  none: string;
  status: string;
  generated: string;
  estimate: string;
  total: string;
  directCost: string;
  markups: string;
  estimateClass: string;
  classNotStated: string;
  expectedRange: string;
  rangeTo: string;
  pricedAt: string;
  provenance: string;
  shareOfValue: string;
  shareOfLines: string;
  familyMeasured: string;
  familyImported: string;
  familyCatalogue: string;
  familyManual: string;
  marketConditions: string;
  contingencyRationale: string;
}

/**
 * Parse a published accuracy bound (`"-20%"`, `"+30"`) into a plain signed
 * number string.
 *
 * The class table states its bands the way the standard prints them; the model
 * stores and the inputs edit a bare signed percentage. Anything unreadable
 * yields `"0"` rather than a guess, so a malformed bound collapses the range to
 * the point estimate instead of inventing one.
 */
export function parseAccuracyPct(raw: string | null | undefined): string {
  const text = String(raw ?? '')
    .trim()
    .replace(/%/g, '')
    .replace(/\+/g, '');
  if (!text) return '0';
  const n = Number(text);
  return Number.isFinite(n) ? String(n) : '0';
}

/** The provenance family labels, keyed the way the wire keys them. */
function familyLabel(family: string, labels: MarkdownLabels): string {
  switch (family) {
    case 'measured':
      return labels.familyMeasured;
    case 'imported':
      return labels.familyImported;
    case 'catalogue':
      return labels.familyCatalogue;
    case 'manual':
      return labels.familyManual;
    default:
      return family;
  }
}

/**
 * The estimate's own figure, its class and the range that follows.
 *
 * A basis of estimate whose reader has to open a second document to learn what
 * number is being qualified is not a deliverable. Money is written as the
 * Decimal string it arrived as, with the currency code beside it: an exported
 * file is read outside the app, where the reader's number locale is not known.
 */
function headlineBlock(doc: EstimateBasisDocument, labels: MarkdownLabels): string[] {
  const financials = doc.financials;
  const grand = (financials?.grand_total ?? '').trim();
  if (!grand) return [];

  const ccy = (doc.currency || financials?.currency || '').trim();
  const suffix = ccy ? ` ${ccy}` : '';
  const out = [`## ${labels.estimate}`, '', `- ${labels.total}: ${grand}${suffix}`];
  if (financials.direct_cost) out.push(`- ${labels.directCost}: ${financials.direct_cost}${suffix}`);
  if (financials.markups_total) out.push(`- ${labels.markups}: ${financials.markups_total}${suffix}`);

  if (doc.estimate_class !== null && doc.estimate_class !== 0 && doc.estimate_class !== '') {
    const band = `${doc.accuracy_low_pct}% / ${doc.accuracy_high_pct}%`;
    out.push(`- ${labels.estimateClass}: ${doc.estimate_class} (${band})`);
    if (doc.accuracy_low_amount && doc.accuracy_high_amount) {
      out.push(
        `- ${labels.expectedRange}: ${doc.accuracy_low_amount}${suffix} ${labels.rangeTo} ${doc.accuracy_high_amount}${suffix}`,
      );
    }
  } else {
    out.push(`- ${labels.estimateClass}: ${labels.classNotStated}`);
  }
  if (doc.pricing_date) out.push(`- ${labels.pricedAt}: ${doc.pricing_date}`);
  out.push('');
  return out;
}

/** Where the estimate's lines came from, by family. */
function provenanceBlock(doc: EstimateBasisDocument, labels: MarkdownLabels): string[] {
  const families = doc.provenance?.families ?? [];
  if (families.length === 0) return [];

  const heading = doc.provenance.share_basis === 'value' ? labels.shareOfValue : labels.shareOfLines;
  const out = [`## ${labels.provenance}`, '', `${heading}:`, ''];
  for (const family of families) {
    out.push(`- ${familyLabel(family.family, labels)}: ${family.share_pct}%`);
  }
  out.push('');
  return out;
}

/**
 * Render a basis-of-estimate document to Markdown for the proposal export.
 *
 * Mirrors the server-side render (`EstimateBasisService.render_markdown`): the
 * title and meta line, the estimate's figure and accuracy class, where its
 * numbers came from, the three qualification sections with only the enabled
 * lines, the estimator's two judgements and any free-text notes. Both renderers
 * are changed together - the Export button and the API export must not produce
 * two different documents.
 *
 * Section headings arrive pre-translated so the export follows the viewer's
 * language.
 */
export function renderBasisMarkdown(doc: EstimateBasisDocument, labels: MarkdownLabels): string {
  const lines: string[] = [`# ${doc.title}`, ''];

  const meta = [`${labels.status}: ${doc.status}`];
  if (doc.generated_at) meta.push(`${labels.generated}: ${doc.generated_at}`);
  lines.push(`_${meta.join('  ·  ')}_`, '');
  lines.push(...headlineBlock(doc, labels));
  lines.push(...provenanceBlock(doc, labels));

  const sections: Array<[string, QualificationItem[]]> = [
    [labels.inclusions, doc.inclusions],
    [labels.exclusions, doc.exclusions],
    [labels.assumptions, doc.assumptions],
  ];
  for (const [heading, items] of sections) {
    lines.push(`## ${heading}`);
    const on = enabledItems(items ?? []);
    if (on.length > 0) {
      for (const it of on) lines.push(`- ${it.text.trim()}`);
    } else {
      lines.push(`- ${labels.none}`);
    }
    lines.push('');
  }

  const judgements: Array<[string, string]> = [
    [labels.marketConditions, doc.market_conditions ?? ''],
    [labels.contingencyRationale, doc.contingency_rationale ?? ''],
  ];
  for (const [heading, body] of judgements) {
    if (body.trim()) lines.push(`## ${heading}`, body.trim(), '');
  }

  if (doc.notes && doc.notes.trim()) {
    lines.push(`## ${labels.notes}`, doc.notes.trim(), '');
  }

  return `${lines.join('\n').replace(/\s+$/, '')}\n`;
}

/**
 * Safe download filename for a document, mirroring the server export
 * (`basis_of_estimate_<title>.md`). Only filename-safe characters survive.
 */
export function basisFilename(title: string): string {
  const cleaned = (title || '')
    .trim()
    .replace(/[/\\]/g, '-')
    .replace(/\s+/g, '_')
    .replace(/[^A-Za-z0-9_-]/g, '')
    .slice(0, 80);
  return `basis_of_estimate_${cleaned || 'document'}.md`;
}

/**
 * A blank, user-added line for a section. The caller supplies the id (so the
 * factory stays deterministic and testable); the component uses a unique value.
 */
export function newManualItem(category: QualificationCategory, id: string): QualificationItem {
  return {
    id,
    category,
    text: '',
    trade_code: null,
    trade_label: null,
    basis: 'manual',
    source: 'manual',
    enabled: true,
  };
}

/** Generate a reasonably unique id for a new manual line at runtime. */
export function makeItemId(): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2);
  return `manual-${rand}`;
}
