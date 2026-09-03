// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client resolver shared by the project form, the projects list and the
 * dashboard "Clients" widget.
 *
 * A project's `client_id` is a SOFT link: it holds the id of a contact whose
 * `contact_type` is `client`. The column is `String(36)` with no foreign key,
 * and rows written before the picker existed carry a free-text client name
 * in the same column - so anything that is not a UUID is treated as a plain
 * name to display, never as a broken reference.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet, type Page } from '@/shared/lib/api';
import {
  createContact,
  updateContact,
  type Contact,
  type UpdateContactPayload,
} from '@/features/contacts/api';

const UUID_RX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** True when `s` is a canonical 36-char UUID (the shape a contact id has). */
export function isUuid(s: string | null | undefined): s is string {
  return typeof s === 'string' && UUID_RX.test(s.trim());
}

export type ClientDirectory = ReadonlyArray<Contact>;
/** Either the raw directory or a pre-built id -> contact map. */
export type ClientLookup = ClientDirectory | ReadonlyMap<string, Contact>;

/**
 * Query key of the client directory. Prefixed with `contacts` so the
 * Contacts page's own `['contacts']` invalidations (create / edit / delete)
 * refresh this list as well.
 */
export const CLIENT_DIRECTORY_QUERY_KEY = ['contacts', 'client-directory'] as const;

/** Every `client` contact visible to the caller (the backend caps at 500). */
export async function fetchClientDirectory(): Promise<Contact[]> {
  const page = await apiGet<Page<Contact>>('/v1/contacts/?contact_type=client&limit=500');
  return page.items ?? [];
}

export function useClientDirectory(enabled = true) {
  return useQuery({
    queryKey: CLIENT_DIRECTORY_QUERY_KEY,
    queryFn: fetchClientDirectory,
    enabled,
    staleTime: 60_000,
  });
}

/** The directory as an id -> contact map, memoised for list rendering. */
export function useClientLookup(enabled = true) {
  const query = useClientDirectory(enabled);
  const lookup = useMemo(() => buildClientLookup(query.data ?? []), [query.data]);
  return { ...query, lookup };
}

export function buildClientLookup(directory: ClientDirectory): ReadonlyMap<string, Contact> {
  return new Map(directory.map((c) => [c.id.toLowerCase(), c]));
}

/** Company name first, then the person's name, then the email - never ''
 *  for a contact that has any of the three. */
export function contactDisplayName(
  c: Pick<Contact, 'company_name' | 'first_name' | 'last_name' | 'primary_email'>,
): string {
  const company = (c.company_name ?? '').trim();
  if (company) return company;
  const person = [c.first_name, c.last_name]
    .map((s) => (s ?? '').trim())
    .filter(Boolean)
    .join(' ');
  if (person) return person;
  return (c.primary_email ?? '').trim();
}

export function findClient(
  clientId: string | null | undefined,
  lookup: ClientLookup,
): Contact | undefined {
  const raw = (clientId ?? '').trim();
  if (!isUuid(raw)) return undefined;
  const key = raw.toLowerCase();
  if (lookup instanceof Map) return lookup.get(key);
  return (lookup as ClientDirectory).find((c) => c.id.toLowerCase() === key);
}

/**
 * What to print for a project's `client_id`.
 *
 * - a contact id that resolves -> the contact's display name
 * - a legacy free-text name    -> the name itself
 * - empty                      -> ''
 * - a contact id that does NOT resolve (deleted, out of scope, or the
 *   directory has not loaded yet) -> `unresolvedLabel` (default '')
 */
export function clientLabel(
  clientId: string | null | undefined,
  lookup: ClientLookup,
  unresolvedLabel = '',
): string {
  const raw = (clientId ?? '').trim();
  if (!raw) return '';
  if (!isUuid(raw)) return raw;
  const contact = findClient(raw, lookup);
  if (!contact) return unresolvedLabel;
  return contactDisplayName(contact) || unresolvedLabel;
}

/** Mint a `client` contact carrying only a company name - the one field the
 *  create schema needs beyond `contact_type`. An optional brand colour is
 *  written straight after (the create schema has no custom_properties). */
export async function createClientContact(name: string, brandColor = ''): Promise<Contact> {
  const contact = await createContact({ contact_type: 'client', company_name: name.trim() });
  const hex = normalizeHex(brandColor);
  if (!hex) return contact;
  return setClientColor(contact, hex);
}

/* ── Brand colour ───────────────────────────────────────────────────────
 *
 * Contract (shared with the Team Standup board, which only READS it): the
 * colour lives on the client contact as `custom_properties.brand_color`, a
 * 7-char lowercase hex like `#d62828`; empty or absent means "no colour".
 * It is written with PATCH /v1/contacts/{id} carrying the whole
 * custom_properties object read-modify-written, so other modules' buckets
 * in that dict survive.
 */

export const BRAND_COLOR_KEY = 'brand_color';

const HEX6_RX = /^#?([0-9a-f]{6})$/i;
const HEX3_RX = /^#?([0-9a-f]{3})$/i;

/** `'#D62828'` / `'d62828'` / `'#d28'` -> `'#d62828'`; anything else -> ''. */
export function normalizeHex(input: string | null | undefined): string {
  const s = (input ?? '').trim();
  if (!s) return '';
  const six = HEX6_RX.exec(s);
  if (six) return `#${six[1]!.toLowerCase()}`;
  const three = HEX3_RX.exec(s);
  if (three) {
    const [r, g, b] = three[1]!.toLowerCase().split('');
    return `#${r}${r}${g}${g}${b}${b}`;
  }
  return '';
}

/** The brand colour stored on a contact, normalised, or ''. */
export function contactColor(
  contact: Pick<Contact, 'custom_properties'> | null | undefined,
): string {
  const raw = contact?.custom_properties?.[BRAND_COLOR_KEY];
  return typeof raw === 'string' ? normalizeHex(raw) : '';
}

/** The brand colour of a project's `client_id` (hex or ''). A legacy
 *  free-text client, an unresolved id or an unset colour all give ''. */
export function clientColor(
  clientId: string | null | undefined,
  lookup: ClientLookup,
): string {
  return contactColor(findClient(clientId, lookup));
}

/**
 * Save a client's brand colour. `hex` is normalised; '' clears it (the key
 * is written as '' rather than dropped, so a merge on the server cannot
 * resurrect the old value). The PATCH carries every other key in
 * custom_properties unchanged.
 */
export function setClientColor(
  contact: Pick<Contact, 'id' | 'custom_properties'>,
  hex: string,
): Promise<Contact> {
  const color = normalizeHex(hex);
  if (hex.trim() && !color) {
    return Promise.reject(new Error(`Not a hex colour: ${hex}`));
  }
  return updateContact(contact.id, {
    custom_properties: { ...(contact.custom_properties ?? {}), [BRAND_COLOR_KEY]: color },
  });
}

/** Twelve well-spaced hues for the quick picks (all readable as a swatch on
 *  light and dark surfaces; text on them goes through contrastText). */
export const CLIENT_PALETTE: ReadonlyArray<{ hex: string; name: string }> = [
  { hex: '#dc2626', name: 'Red' },
  { hex: '#ea580c', name: 'Orange' },
  { hex: '#d97706', name: 'Amber' },
  { hex: '#ca8a04', name: 'Yellow' },
  { hex: '#65a30d', name: 'Lime' },
  { hex: '#16a34a', name: 'Green' },
  { hex: '#0d9488', name: 'Teal' },
  { hex: '#0891b2', name: 'Cyan' },
  { hex: '#2563eb', name: 'Blue' },
  { hex: '#4f46e5', name: 'Indigo' },
  { hex: '#9333ea', name: 'Purple' },
  { hex: '#db2777', name: 'Pink' },
];

/** Relative luminance per WCAG 2.x. */
function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const chan = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * chan((n >> 16) & 255) + 0.7152 * chan((n >> 8) & 255) + 0.0722 * chan(n & 255);
}

/** Black or white, whichever has the higher contrast ratio on `hex`.
 *  A non-hex input gets dark text (the "no colour" chip is a light grey). */
export function contrastText(hex: string): '#111827' | '#ffffff' {
  const color = normalizeHex(hex);
  if (!color) return '#111827';
  const l = luminance(color);
  const onWhite = 1.05 / (l + 0.05);
  const onBlack = (l + 0.05) / 0.05;
  return onBlack >= onWhite ? '#111827' : '#ffffff';
}

/* ── Addresses ──────────────────────────────────────────────────────────
 *
 * Contract: a client can carry any number of addresses under
 * `custom_properties.addresses`, an ordered list of
 *   { id, label, line1, line2, suburb, state, postcode, country, is_primary }
 * `label` is free text ("Head office", "Site", "Postal", "Billing" are the
 * quick picks). Exactly one entry is primary whenever the list is non-empty;
 * the primary is ALSO mirrored into the contact's plain `address` column
 * (text/street/line1 + city + postcode + state + country) so the upstream
 * Contacts screen and the e-invoice merge keep seeing one address.
 */

export const ADDRESSES_KEY = 'addresses';

export interface ClientAddress {
  id: string;
  label: string;
  line1: string;
  line2: string;
  suburb: string;
  state: string;
  postcode: string;
  country: string;
  is_primary: boolean;
}

export const ADDRESS_LABEL_PICKS: ReadonlyArray<string> = ['Head office', 'Site', 'Postal', 'Billing'];

let addressSeq = 0;
/** A short unique id for a new address row (stable across re-renders). */
export function newAddressId(): string {
  addressSeq += 1;
  const rand = Math.random().toString(36).slice(2, 8);
  return `adr_${Date.now().toString(36)}${rand}${addressSeq}`;
}

const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');

/** Coerce one raw stored entry to the contract; null when it is not an
 *  object. Missing strings become '', a missing id is minted. */
export function normalizeAddress(raw: unknown): ClientAddress | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  return {
    id: str(r.id) || newAddressId(),
    label: str(r.label),
    line1: str(r.line1),
    line2: str(r.line2),
    suburb: str(r.suburb) || str(r.city),
    state: str(r.state),
    postcode: str(r.postcode) || str(r.postal_code),
    country: str(r.country),
    is_primary: r.is_primary === true,
  };
}

/** Every stored address, in order. Guarantees at most one primary: the first
 *  flagged entry wins; when none is flagged the first entry is primary. */
export function clientAddresses(
  contact: Pick<Contact, 'custom_properties'> | null | undefined,
): ClientAddress[] {
  const raw = contact?.custom_properties?.[ADDRESSES_KEY];
  if (!Array.isArray(raw)) return [];
  const rows = raw.map(normalizeAddress).filter((a): a is ClientAddress => a !== null);
  return ensureOnePrimary(rows);
}

/** Exactly one primary in a non-empty list (first flagged, else first). */
export function ensureOnePrimary(rows: ReadonlyArray<ClientAddress>): ClientAddress[] {
  if (rows.length === 0) return [];
  const idx = Math.max(0, rows.findIndex((a) => a.is_primary));
  return rows.map((a, i) => ({ ...a, is_primary: i === idx }));
}

export function primaryAddress(
  contact: Pick<Contact, 'custom_properties'> | null | undefined,
): ClientAddress | undefined {
  return clientAddresses(contact).find((a) => a.is_primary);
}

/** One line: "12 Example Street, Unit 4, Sampletown NSW 2000, Australia". */
export function formatAddress(a: Partial<ClientAddress> | null | undefined): string {
  if (!a) return '';
  const locality = [a.suburb, a.state, a.postcode].map(str).filter(Boolean).join(' ');
  return [a.line1, a.line2, locality, a.country].map(str).filter(Boolean).join(', ');
}

/** Validation for the editor. `line1` is required; `postcode` is optional
 *  but must be a plausible code (digits, letters, spaces or dashes, 3-10
 *  chars) when given. */
export function validateAddress(a: Partial<ClientAddress>): { line1?: string; postcode?: string } {
  const errors: { line1?: string; postcode?: string } = {};
  if (!str(a.line1)) errors.line1 = 'Address line 1 is required';
  const pc = str(a.postcode);
  if (pc && !/^[0-9A-Za-z][0-9A-Za-z -]{1,9}$/.test(pc)) errors.postcode = 'Not a valid postcode';
  return errors;
}

/* Pure list operations shared by the editor dialog and its tests. */

export function addAddress(
  rows: ReadonlyArray<ClientAddress>,
  partial: Partial<ClientAddress> = {},
): ClientAddress[] {
  const next: ClientAddress = {
    id: partial.id ?? newAddressId(),
    label: partial.label ?? '',
    line1: partial.line1 ?? '',
    line2: partial.line2 ?? '',
    suburb: partial.suburb ?? '',
    state: partial.state ?? '',
    postcode: partial.postcode ?? '',
    country: partial.country ?? '',
    // The first address is primary by construction; later ones only when asked.
    is_primary: rows.length === 0 ? true : partial.is_primary === true,
  };
  return ensureOnePrimary(next.is_primary ? [...rows.map((a) => ({ ...a, is_primary: false })), next] : [...rows, next]);
}

export function updateAddress(
  rows: ReadonlyArray<ClientAddress>,
  id: string,
  patch: Partial<Omit<ClientAddress, 'id' | 'is_primary'>>,
): ClientAddress[] {
  return rows.map((a) => (a.id === id ? { ...a, ...patch } : a));
}

export function removeAddress(rows: ReadonlyArray<ClientAddress>, id: string): ClientAddress[] {
  return ensureOnePrimary(rows.filter((a) => a.id !== id));
}

export function setPrimaryAddress(rows: ReadonlyArray<ClientAddress>, id: string): ClientAddress[] {
  if (!rows.some((a) => a.id === id)) return [...rows];
  return rows.map((a) => ({ ...a, is_primary: a.id === id }));
}

/** Move one row up (-1) or down (+1); a move off either end is a no-op. */
export function moveAddress(
  rows: ReadonlyArray<ClientAddress>,
  id: string,
  direction: -1 | 1,
): ClientAddress[] {
  const i = rows.findIndex((a) => a.id === id);
  const j = i + direction;
  if (i < 0 || j < 0 || j >= rows.length) return [...rows];
  const next = [...rows];
  [next[i], next[j]] = [next[j]!, next[i]!];
  return next;
}

/**
 * The plain `address` column mirror of the primary address, in the keys
 * the upstream Contacts form reads (`text`/`street`/`line1`, `city`,
 * `postcode`) plus state/country. Absent keys rather than empty ones - the
 * e-invoice merge treats '' as an answer. null when there is no primary.
 */
export function mirrorAddress(a: ClientAddress | undefined): Record<string, string> | null {
  if (!a) return null;
  const out: Record<string, string> = {};
  const line = [a.line1, a.line2].map(str).filter(Boolean).join(', ');
  if (line) {
    out.text = line;
    out.street = line;
    out.line1 = a.line1;
  }
  if (str(a.line2)) out.line2 = a.line2;
  if (str(a.suburb)) out.city = a.suburb;
  if (str(a.state)) out.state = a.state;
  if (str(a.postcode)) out.postcode = a.postcode;
  if (str(a.country)) out.country = a.country;
  if (str(a.label)) out.label = a.label;
  return Object.keys(out).length > 0 ? out : null;
}

export interface ClientDetailsPatch {
  name?: string;
  brand_color?: string;
  primary_email?: string;
  primary_phone?: string;
  addresses?: ReadonlyArray<ClientAddress>;
}

/**
 * Save a client end-to-end in ONE PATCH: name -> company_name, colour ->
 * custom_properties.brand_color, email/phone -> the plain columns ('' clears
 * them with null), addresses -> custom_properties.addresses with the
 * primary mirrored into `address`. custom_properties is read-modify-written
 * whole so other modules' buckets survive the server's shallow merge.
 */
export function saveClientDetails(
  contact: Pick<Contact, 'id' | 'custom_properties'>,
  patch: ClientDetailsPatch,
): Promise<Contact> {
  const body: UpdateContactPayload = {};
  const props: Record<string, unknown> = { ...(contact.custom_properties ?? {}) };
  let touchedProps = false;

  if (patch.name !== undefined) body.company_name = patch.name.trim() || null;
  if (patch.primary_email !== undefined) body.primary_email = patch.primary_email.trim() || null;
  if (patch.primary_phone !== undefined) body.primary_phone = patch.primary_phone.trim() || null;
  if (patch.brand_color !== undefined) {
    const color = normalizeHex(patch.brand_color);
    if (patch.brand_color.trim() && !color) {
      return Promise.reject(new Error(`Not a hex colour: ${patch.brand_color}`));
    }
    props[BRAND_COLOR_KEY] = color;
    touchedProps = true;
  }
  if (patch.addresses !== undefined) {
    // Trim every string on the way out (normalizeAddress does) so a row
    // typed as "  9 Ninth St  " is stored, mirrored and printed the same.
    const rows = ensureOnePrimary(
      patch.addresses.map((a) => normalizeAddress(a) ?? { ...a }),
    );
    props[ADDRESSES_KEY] = rows.map((a) => ({ ...a }));
    body.address = mirrorAddress(rows.find((a) => a.is_primary));
    touchedProps = true;
  }
  if (touchedProps) body.custom_properties = props;
  return updateContact(contact.id, body);
}

/** Case-insensitive "does this typed text already name a client" check, so
 *  the picker never offers to add a duplicate. */
export function findClientByName(
  name: string,
  directory: ClientDirectory,
): Contact | undefined {
  const needle = name.trim().toLowerCase();
  if (!needle) return undefined;
  return directory.find((c) => contactDisplayName(c).toLowerCase() === needle);
}
