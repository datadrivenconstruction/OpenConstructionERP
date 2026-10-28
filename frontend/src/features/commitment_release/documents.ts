// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The documents of a project that an item can count: contracts and their
// lines, purchase orders, change and variation orders, and the packages an
// award comes from.
//
// The commitment API takes a document id and has no list of its own, so the
// picker reads each kind from the module that owns it. Those lists differ in
// three ways, and each difference is written down per kind below instead of
// being guessed from the payload: whether the answer is a page or a bare
// array, which field carries the number and which the name, and which field
// carries the currency. Every list is read one page deep (100 rows); a list
// that may hold more says so, and the picker tells the reader.

import { apiGet, type Page } from '@/shared/lib/api';

import type { LinkKind } from './api';

export interface DocumentOption {
  id: string;
  /** "SC-014 Structural works": the number or code, then the title. */
  label: string;
  /** The document's own currency, when its list carries one. */
  currency: string | null;
}

export interface DocumentList {
  options: DocumentOption[];
  /** The project may hold more documents of this kind than were read. */
  truncated: boolean;
}

/** Rows asked for per list. Every list below accepts it (their maxima are 100, 200 or 500). */
export const PAGE_SIZE = 100;

/** Kinds read from a list of the project. A contract line is picked through its contract. */
export type ListedKind = Exclude<LinkKind, 'contract_line'>;

export const LISTED_KINDS: readonly ListedKind[] = [
  'contract',
  'purchase_order',
  'change_order',
  'variation_order',
  'tender_package',
  'bid_package',
  'rfq',
];

/** Kinds the picker offers, in the order a reader meets them. */
export const PICKABLE_KINDS: readonly LinkKind[] = [
  'contract',
  'contract_line',
  'purchase_order',
  'change_order',
  'variation_order',
  'tender_package',
  'bid_package',
  'rfq',
];

type Row = Record<string, unknown>;

interface Source {
  /** One page of the list for one project. The path is written out at the call, so the route check reads it whole. */
  read: (projectId: string) => Promise<unknown>;
  /** The field with the number or code a person quotes; null when the kind has none. */
  number: string | null;
  /** Fields that name the document, first one that is filled wins. */
  name: readonly string[];
  currency: string | null;
}

export const SOURCES: Record<ListedKind, Source> = {
  contract: {
    read: (id) => apiGet<Page<Row>>(`/v1/contracts/contracts/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: 'code',
    name: ['title'],
    currency: 'currency',
  },
  // A purchase order has no title; the supplier is what tells two orders apart.
  purchase_order: {
    read: (id) => apiGet<unknown>(`/v1/procurement/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: 'po_number',
    name: ['vendor_name'],
    currency: 'currency_code',
  },
  change_order: {
    read: (id) => apiGet<unknown>(`/v1/changeorders/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: 'code',
    name: ['title'],
    currency: 'currency',
  },
  variation_order: {
    read: (id) => apiGet<Page<Row>>(`/v1/variations/variation-orders/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: 'code',
    name: ['title'],
    currency: 'currency',
  },
  // A tender package has a name only, and no amount of its own.
  tender_package: {
    read: (id) => apiGet<unknown>(`/v1/tendering/packages/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: null,
    name: ['name'],
    currency: null,
  },
  bid_package: {
    read: (id) => apiGet<unknown>(`/v1/bid-management/bid-packages/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: 'code',
    name: ['title'],
    currency: 'currency',
  },
  rfq: {
    read: (id) => apiGet<unknown>(`/v1/rfq-bidding/?project_id=${id}&limit=${PAGE_SIZE}`),
    number: 'rfq_number',
    name: ['title'],
    currency: 'currency_code',
  },
};

/** A contract line: its position code, then what it describes. */
const LINE_SOURCE: Omit<Source, 'read'> = {
  number: 'code',
  name: ['description'],
  currency: null,
};

const text = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

function rowLabel(row: Row, source: Pick<Source, 'number' | 'name'>): string {
  const number = source.number ? text(row[source.number]) : '';
  const name = source.name.map((field) => text(row[field])).find(Boolean) ?? '';
  return [number, name].filter(Boolean).join(' ');
}

/** One readable line for a row of the list of one kind: its number or code, then its name. */
export function documentLabel(kind: ListedKind, row: Row): string {
  return rowLabel(row, SOURCES[kind]);
}

function toOptions(rows: unknown[], source: Omit<Source, 'read'>): DocumentOption[] {
  const options: DocumentOption[] = [];
  for (const raw of rows) {
    if (!raw || typeof raw !== 'object') continue;
    const row = raw as Row;
    const id = text(row.id);
    if (!id) continue;
    const currency = source.currency ? text(row[source.currency]).toUpperCase() : '';
    options.push({ id, label: rowLabel(row, source) || id, currency: currency || null });
  }
  return options;
}

/**
 * Reduce the answer of one list to options. A page says how many rows exist,
 * so it is cut short exactly when that is more than it carries. A bare array
 * carries no count: a full page may be all there is or may not, and it is
 * reported as possibly cut short rather than passed off as complete.
 */
export function toDocumentList(kind: ListedKind, payload: unknown): DocumentList {
  const source = SOURCES[kind];
  if (Array.isArray(payload)) {
    return { options: toOptions(payload, source), truncated: payload.length >= PAGE_SIZE };
  }
  if (payload && typeof payload === 'object' && Array.isArray((payload as { items?: unknown }).items)) {
    const page = payload as { items: unknown[]; total?: unknown };
    const total = typeof page.total === 'number' ? page.total : page.items.length;
    return { options: toOptions(page.items, source), truncated: total > page.items.length };
  }
  return { options: [], truncated: false };
}

const EMPTY: DocumentList = { options: [], truncated: false };

export async function listDocuments(projectId: string, kind: LinkKind): Promise<DocumentList> {
  // Without a project some of these lists answer for every project the
  // caller can see; an item never links across projects, so nothing is asked.
  if (!projectId || kind === 'contract_line') return EMPTY;
  const source = SOURCES[kind];
  if (!source) return EMPTY;
  return toDocumentList(kind, await source.read(projectId));
}

/** The lines of one contract, all of them: that list is not paged. */
export function toContractLines(payload: unknown): DocumentOption[] {
  return Array.isArray(payload) ? toOptions(payload, LINE_SOURCE) : [];
}

export async function listContractLines(contractId: string): Promise<DocumentOption[]> {
  if (!contractId) return [];
  return toContractLines(await apiGet<unknown>(`/v1/contracts/contracts/${contractId}/lines`));
}
