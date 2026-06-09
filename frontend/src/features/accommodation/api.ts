/**
 * API helpers for the Accommodation module.
 *
 * Backed by /api/v1/accommodation/ — see
 * backend/app/modules/accommodation/router.py (14 endpoints).
 *
 * Money discipline: every Decimal field (base_rate, charge.amount, geo
 * coordinates) is serialized as a STRING in JSON. The TypeScript types
 * here keep them as `string`, and every caller is expected to keep the
 * value as a string end-to-end (no `parseFloat()`!). Display widgets
 * accept Decimal-shaped strings directly.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Enum literals (mirror backend regex patterns) ───────────────────── */

export type AccommodationKind = 'worker_camp' | 'rental' | 'hotel';
export type RoomStatus = 'available' | 'occupied' | 'maintenance' | 'blocked';
export type BookingStatus =
  | 'reserved'
  | 'checked_in'
  | 'checked_out'
  | 'cancelled';
export type BookingSource =
  | 'manual'
  | 'hr_autobook'
  | 'propdev_import'
  | 'pms_sync';
export type ChargeKind = 'base_rent' | 'extra' | 'deposit' | 'refund';
export type ChargeStatus = 'pending' | 'invoiced' | 'paid' | 'waived';

/* ── Read shapes ─────────────────────────────────────────────────────── */

export interface Accommodation {
  id: string;
  project_id: string;
  name: string;
  kind: AccommodationKind;
  address: string | null;
  /** Decimal as string — keep as string, never parseFloat. */
  geo_lat: string | null;
  geo_lon: string | null;
  bim_model_id: string | null;
  property_dev_block_id: string | null;
  capacity_total: number;
  notes: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface Room {
  id: string;
  accommodation_id: string;
  label: string;
  capacity: number;
  bim_element_id: string | null;
  /** Decimal as string. */
  base_rate: string;
  base_rate_currency: string;
  status: RoomStatus;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface AccommodationDetail extends Accommodation {
  rooms: Room[];
  active_bookings_count: number;
}

export interface Booking {
  id: string;
  room_id: string;
  /**
   * Server-decorated convenience field — only populated by list
   * endpoints (`GET /accommodation/{id}/bookings`,
   * `GET /accommodation/rooms/{id}/bookings`). Single-booking GETs
   * leave this `null` because the caller already has the room id.
   */
  room_label?: string | null;
  occupant_contact_id: string | null;
  occupant_name: string | null;
  /** ISO date (YYYY-MM-DD). */
  check_in: string;
  check_out: string | null;
  status: BookingStatus;
  source: BookingSource;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface BookingListResponse {
  items: Booking[];
  total: number;
  limit: number;
  offset: number;
}

export interface BookingListQuery {
  /** Multi-value: `?status=reserved&status=checked_in`. */
  status?: BookingStatus[];
  /** ISO date — booking ends strictly after this. */
  from_date?: string;
  /** ISO date — booking starts on or before this. */
  to_date?: string;
  limit?: number;
  offset?: number;
}

export interface Charge {
  id: string;
  booking_id: string;
  kind: ChargeKind;
  description: string | null;
  /** Decimal as string — never parseFloat. */
  amount: string;
  currency: string;
  period_start: string | null;
  period_end: string | null;
  status: ChargeStatus;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface BookingDetail extends Booking {
  charges: Charge[];
}

/* ── Write shapes (mirror Pydantic Create/Update) ────────────────────── */

export interface AccommodationCreatePayload {
  project_id: string;
  name?: string;
  kind?: AccommodationKind;
  address?: string | null;
  /** Decimal as string. */
  geo_lat?: string | null;
  geo_lon?: string | null;
  bim_model_id?: string | null;
  property_dev_block_id?: string | null;
  capacity_total?: number;
  notes?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AccommodationUpdatePayload {
  name?: string;
  kind?: AccommodationKind;
  address?: string | null;
  geo_lat?: string | null;
  geo_lon?: string | null;
  bim_model_id?: string | null;
  property_dev_block_id?: string | null;
  capacity_total?: number;
  notes?: string | null;
  metadata?: Record<string, unknown>;
}

export interface RoomCreatePayload {
  label: string;
  capacity?: number;
  bim_element_id?: string | null;
  /** Decimal as string. */
  base_rate?: string;
  base_rate_currency?: string;
  status?: RoomStatus;
  metadata?: Record<string, unknown>;
}

export interface RoomUpdatePayload {
  label?: string;
  capacity?: number;
  bim_element_id?: string | null;
  /** Decimal as string. */
  base_rate?: string;
  base_rate_currency?: string;
  status?: RoomStatus;
  metadata?: Record<string, unknown>;
}

export interface BookingCreatePayload {
  occupant_contact_id?: string | null;
  occupant_name?: string | null;
  /** ISO date. */
  check_in: string;
  check_out?: string | null;
  status?: BookingStatus;
  source?: BookingSource;
  metadata?: Record<string, unknown>;
}

export interface BookingUpdatePayload {
  occupant_contact_id?: string | null;
  occupant_name?: string | null;
  check_in?: string;
  check_out?: string | null;
  status?: BookingStatus;
  source?: BookingSource;
  metadata?: Record<string, unknown>;
}

export interface ChargeCreatePayload {
  kind?: ChargeKind;
  description?: string | null;
  /** Decimal as string. Required by server. */
  amount: string;
  currency?: string;
  period_start?: string | null;
  period_end?: string | null;
  status?: ChargeStatus;
  metadata?: Record<string, unknown>;
}

export interface ChargeUpdatePayload {
  kind?: ChargeKind;
  description?: string | null;
  /** Decimal as string. */
  amount?: string;
  currency?: string;
  period_start?: string | null;
  period_end?: string | null;
  status?: ChargeStatus;
  metadata?: Record<string, unknown>;
}

export interface BootstrapFromPropDevResult {
  accommodation_id: string;
  block_id: string;
  rooms_created: number;
  rooms_skipped: number;
  total_rooms: number;
}

export interface SuggestFromHRRequest {
  employee_contact_id: string;
  /** ISO date. */
  start_date: string;
}

export interface SuggestFromHRResponse {
  room_id: string;
  room_label: string;
  accommodation_id: string;
  accommodation_name: string;
  accommodation_kind: AccommodationKind;
  capacity: number;
  /** Decimal as string. */
  base_rate: string;
  base_rate_currency: string;
}

/* ── Accommodation CRUD ──────────────────────────────────────────────── */

export function listAccommodations(params?: {
  project_id?: string;
  limit?: number;
  offset?: number;
}): Promise<Accommodation[]> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  const q = qs.toString();
  return apiGet<Accommodation[]>(`/v1/accommodation/${q ? `?${q}` : ''}`);
}

export function createAccommodation(
  data: AccommodationCreatePayload,
): Promise<Accommodation> {
  return apiPost<Accommodation>('/v1/accommodation/', data);
}

export function getAccommodation(id: string): Promise<AccommodationDetail> {
  return apiGet<AccommodationDetail>(`/v1/accommodation/${id}`);
}

export function updateAccommodation(
  id: string,
  data: AccommodationUpdatePayload,
): Promise<Accommodation> {
  return apiPatch<Accommodation>(`/v1/accommodation/${id}`, data);
}

export function deleteAccommodation(id: string): Promise<void> {
  return apiDelete(`/v1/accommodation/${id}`);
}

/* ── Rooms ───────────────────────────────────────────────────────────── */

export function listRooms(
  accommodationId: string,
  status?: RoomStatus,
): Promise<Room[]> {
  const qs = new URLSearchParams();
  if (status) qs.set('status', status);
  const q = qs.toString();
  return apiGet<Room[]>(
    `/v1/accommodation/${accommodationId}/rooms${q ? `?${q}` : ''}`,
  );
}

export function bulkCreateRooms(
  accommodationId: string,
  rooms: RoomCreatePayload[],
): Promise<Room[]> {
  return apiPost<Room[]>(`/v1/accommodation/${accommodationId}/rooms`, {
    rooms,
  });
}

export function updateRoom(
  roomId: string,
  data: RoomUpdatePayload,
): Promise<Room> {
  return apiPatch<Room>(`/v1/accommodation/rooms/${roomId}`, data);
}

/* ── Bookings ────────────────────────────────────────────────────────── */

function bookingQueryToSearch(query?: BookingListQuery): string {
  if (!query) return '';
  const qs = new URLSearchParams();
  if (query.status) {
    // FastAPI accepts repeated query params for list values.
    for (const s of query.status) qs.append('status', s);
  }
  if (query.from_date) qs.set('from_date', query.from_date);
  if (query.to_date) qs.set('to_date', query.to_date);
  if (query.limit !== undefined) qs.set('limit', String(query.limit));
  if (query.offset !== undefined) qs.set('offset', String(query.offset));
  const q = qs.toString();
  return q ? `?${q}` : '';
}

export function listAccommodationBookings(
  accommodationId: string,
  query?: BookingListQuery,
): Promise<BookingListResponse> {
  return apiGet<BookingListResponse>(
    `/v1/accommodation/${accommodationId}/bookings${bookingQueryToSearch(query)}`,
  );
}

export function listRoomBookings(
  roomId: string,
  query?: BookingListQuery,
): Promise<BookingListResponse> {
  return apiGet<BookingListResponse>(
    `/v1/accommodation/rooms/${roomId}/bookings${bookingQueryToSearch(query)}`,
  );
}

export function createBooking(
  roomId: string,
  data: BookingCreatePayload,
): Promise<Booking> {
  return apiPost<Booking>(`/v1/accommodation/rooms/${roomId}/bookings`, data);
}

export function getBooking(bookingId: string): Promise<BookingDetail> {
  return apiGet<BookingDetail>(`/v1/accommodation/bookings/${bookingId}`);
}

export function updateBooking(
  bookingId: string,
  data: BookingUpdatePayload,
): Promise<Booking> {
  return apiPatch<Booking>(`/v1/accommodation/bookings/${bookingId}`, data);
}

/* ── Charges ─────────────────────────────────────────────────────────── */

export function createCharge(
  bookingId: string,
  data: ChargeCreatePayload,
): Promise<Charge> {
  return apiPost<Charge>(
    `/v1/accommodation/bookings/${bookingId}/charges`,
    data,
  );
}

export function listCharges(bookingId: string): Promise<Charge[]> {
  return apiGet<Charge[]>(`/v1/accommodation/bookings/${bookingId}/charges`);
}

export function updateCharge(
  chargeId: string,
  data: ChargeUpdatePayload,
): Promise<Charge> {
  return apiPatch<Charge>(`/v1/accommodation/charges/${chargeId}`, data);
}

export function deleteCharge(chargeId: string): Promise<void> {
  return apiDelete(`/v1/accommodation/charges/${chargeId}`);
}

/* ── Cross-module integrations ───────────────────────────────────────── */

export function bootstrapFromPropDev(
  accommodationId: string,
  blockId: string,
): Promise<BootstrapFromPropDevResult> {
  return apiPost<BootstrapFromPropDevResult>(
    `/v1/accommodation/${accommodationId}/bootstrap-from-propdev/${blockId}`,
    {},
  );
}

export function suggestFromHR(
  data: SuggestFromHRRequest,
): Promise<SuggestFromHRResponse> {
  return apiPost<SuggestFromHRResponse>(
    '/v1/accommodation/bookings/suggest-from-hr',
    data,
  );
}

/* ── State-machine helpers ───────────────────────────────────────────── */

/** Mirror the backend transition map (service.py _BOOKING_TRANSITIONS). */
const BOOKING_TRANSITIONS: Record<BookingStatus, BookingStatus[]> = {
  reserved: ['checked_in', 'cancelled'],
  checked_in: ['checked_out', 'cancelled'],
  checked_out: [],
  cancelled: [],
};

export function allowedBookingTransitions(
  current: BookingStatus,
): BookingStatus[] {
  return BOOKING_TRANSITIONS[current] ?? [];
}

export function isBookingTerminal(status: BookingStatus): boolean {
  return status === 'checked_out' || status === 'cancelled';
}

/**
 * Mirror the backend charge lifecycle (service.py _CHARGE_TRANSITIONS):
 * pending -> invoiced -> paid, with `waived` reachable from any
 * non-settled state. `paid` / `waived` are terminal (locked records).
 */
const CHARGE_TRANSITIONS: Record<ChargeStatus, ChargeStatus[]> = {
  pending: ['invoiced', 'paid', 'waived'],
  invoiced: ['paid', 'waived'],
  paid: [],
  waived: [],
};

export function allowedChargeTransitions(
  current: ChargeStatus,
): ChargeStatus[] {
  return CHARGE_TRANSITIONS[current] ?? [];
}

/**
 * A charge is locked (read-only - no edit, delete or status change) once
 * it is settled or written off. Mirrors service._LOCKED_CHARGE_STATUSES.
 */
export function isChargeLocked(status: ChargeStatus): boolean {
  return status === 'paid' || status === 'waived';
}
