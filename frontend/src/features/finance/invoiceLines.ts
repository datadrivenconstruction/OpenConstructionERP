// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The invoice form's lines, and the money they add up to.
 *
 * Every figure is read with `Number`, never `parseFloat`, and written back in
 * canonical form: a grouped or comma-decimal string read through `parseFloat`
 * loses digits silently (#466). VAT is a rate on each line, not an amount the
 * person types, and the invoice's tax is the sum of the lines' VAT rounded to
 * the cent per line, which is how a VAT invoice is itemised.
 */

/** One row of the line editor, held as the strings the inputs show. */
export interface InvoiceEditorLine {
  key: string;
  description: string;
  quantity: string;
  unit: string;
  unit_rate: string;
  /** Net amount of the line. Recomputed from quantity x rate when either moves;
   *  a stored line keeps its own amount until then (a claim line's amount is
   *  not always quantity x rate). */
  amount: string;
  /** Percent. Empty means "not given": the server fills the country default. */
  vat_rate: string;
  /** Set once the person edits the rate, so a default arriving later does not
   *  overwrite what they typed (including an explicit 0). */
  vat_touched: boolean;
  /** Fields of a stored line the editor does not show, sent back unchanged so
   *  a save does not cut the line's link to its cost line, WBS or category. */
  keep?: Record<string, unknown>;
}

/** The stored line shape the editor loads (InvoiceLineItemResponse). */
export interface StoredInvoiceLine {
  description?: string | null;
  quantity?: string | number | null;
  unit?: string | null;
  unit_rate?: string | number | null;
  amount?: string | number | null;
  vat_rate?: string | number | null;
  vat_category?: string | null;
  wbs_id?: string | null;
  cost_category?: string | null;
  cost_line_id?: string | null;
  sort_order?: number | null;
}

let seq = 0;
function nextKey(): string {
  seq += 1;
  return `line-${seq}`;
}

export function readNumber(raw: string | number | null | undefined): number | null {
  if (raw == null) return null;
  const text = String(raw).trim();
  if (text === '') return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

export function roundCents(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/** A canonical number string a `<input type="number">` accepts. */
export function canonical(value: number, decimals = 2): string {
  return Number.isFinite(value) ? value.toFixed(decimals) : '';
}

/** A rate as the field shows it: "25", "12.5", never "25.00". */
export function rateText(raw: string | number | null | undefined): string {
  const n = readNumber(raw);
  return n == null ? '' : String(Number(n.toFixed(4)));
}

export function newEditorLine(defaultVat: string | null): InvoiceEditorLine {
  return {
    key: nextKey(),
    description: '',
    quantity: '1',
    unit: '',
    unit_rate: '',
    amount: '',
    vat_rate: defaultVat ?? '',
    vat_touched: false,
  };
}

export function lineNet(line: InvoiceEditorLine): number {
  const stored = readNumber(line.amount);
  if (stored != null) return roundCents(stored);
  const qty = readNumber(line.quantity) ?? 0;
  const rate = readNumber(line.unit_rate) ?? 0;
  return roundCents(qty * rate);
}

export function lineVat(line: InvoiceEditorLine): number {
  const rate = readNumber(line.vat_rate) ?? 0;
  return roundCents((lineNet(line) * rate) / 100);
}

export function invoiceTotals(lines: InvoiceEditorLine[]): { subtotal: number; tax: number; total: number } {
  let subtotal = 0;
  let tax = 0;
  for (const line of lines) {
    subtotal += lineNet(line);
    tax += lineVat(line);
  }
  subtotal = roundCents(subtotal);
  tax = roundCents(tax);
  return { subtotal, tax, total: roundCents(subtotal + tax) };
}

/** Apply an edit to one field; quantity and rate re-derive the net amount. */
export function editLine(
  line: InvoiceEditorLine,
  field: 'description' | 'quantity' | 'unit' | 'unit_rate' | 'vat_rate',
  value: string,
): InvoiceEditorLine {
  const next: InvoiceEditorLine = { ...line, [field]: value };
  if (field === 'quantity' || field === 'unit_rate') {
    const qty = readNumber(next.quantity);
    const rate = readNumber(next.unit_rate);
    next.amount = qty != null && rate != null ? canonical(roundCents(qty * rate)) : '';
  }
  if (field === 'vat_rate') next.vat_touched = true;
  return next;
}

/**
 * Lines for an existing invoice. Stored lines load as they are; an invoice
 * saved as one sum without lines loads as one line whose rate reproduces its
 * stored tax, so opening it shows the figures it was saved with.
 */
export function editorLinesFromInvoice(
  stored: StoredInvoiceLine[] | null | undefined,
  amounts: { subtotal?: string | number | null; tax?: string | number | null },
  defaultVat: string | null,
): InvoiceEditorLine[] {
  if (stored && stored.length > 0) {
    return stored.map((item) => ({
      key: nextKey(),
      description: item.description ?? '',
      quantity: item.quantity != null ? String(item.quantity) : '1',
      unit: item.unit ?? '',
      unit_rate: item.unit_rate != null ? String(item.unit_rate) : '',
      amount: item.amount != null ? String(item.amount) : '',
      vat_rate: rateText(item.vat_rate),
      // A stored line shows what it was saved with; a country default arriving
      // after it loaded must not rewrite it.
      vat_touched: true,
      keep: {
        wbs_id: item.wbs_id ?? null,
        cost_category: item.cost_category ?? null,
        cost_line_id: item.cost_line_id ?? null,
        vat_category: item.vat_category ?? null,
        sort_order: item.sort_order ?? 0,
      },
    }));
  }
  const subtotal = readNumber(amounts.subtotal);
  if (subtotal == null || subtotal === 0) return [newEditorLine(defaultVat)];
  const tax = readNumber(amounts.tax) ?? 0;
  return [
    {
      ...newEditorLine(null),
      unit_rate: canonical(subtotal),
      amount: canonical(subtotal),
      vat_rate: rateText(roundCents((tax / subtotal) * 10000) / 100),
      vat_touched: true,
    },
  ];
}

/**
 * The request body's `line_items`. A line with no net amount carries no money
 * and is left out; a blank description takes the fallback, since the server
 * requires one. An empty VAT field travels as `null` so the server applies the
 * project country's rate, while a typed 0 stays 0.
 */
export function linesToPayload(lines: InvoiceEditorLine[], fallbackDescription: string) {
  return lines
    .filter((line) => lineNet(line) > 0)
    .map((line, index) => {
      const vat = line.vat_rate.trim();
      const qty = readNumber(line.quantity);
      const rate = readNumber(line.unit_rate);
      const net = lineNet(line);
      return {
        ...(line.keep ?? {}),
        description: line.description.trim() || fallbackDescription,
        quantity: qty != null ? String(qty) : '1',
        unit: line.unit.trim() || null,
        unit_rate: rate != null ? canonical(rate) : canonical(net),
        amount: canonical(net),
        vat_rate: vat === '' ? null : String(readNumber(vat) ?? vat),
        sort_order: (line.keep?.sort_order as number | undefined) ?? index,
      };
    });
}

/** A tax configuration row (TaxConfigResponse on the wire). */
export interface TaxConfigRow {
  rate_pct: string;
  tax_type?: string | null;
  subdivision_code?: string | null;
  is_default?: boolean;
}

/**
 * The VAT rates a country offers, and the one a new line starts with.
 *
 * Country-wide rates only (a subdivision's own rate is not a VAT choice for
 * the line). The default is the configuration marked default, else the
 * highest rate, which is the standard rate wherever reduced ones exist.
 */
export function vatChoices(rows: TaxConfigRow[] | null | undefined): { options: string[]; defaultRate: string | null } {
  const national = (rows ?? []).filter((r) => !r.subdivision_code && readNumber(r.rate_pct) != null);
  const options = Array.from(new Set(national.map((r) => rateText(r.rate_pct)))).sort(
    (a, b) => Number(b) - Number(a),
  );
  const marked = national.find((r) => r.is_default);
  const defaultRate = marked ? rateText(marked.rate_pct) : (options[0] ?? null);
  return { options, defaultRate };
}
