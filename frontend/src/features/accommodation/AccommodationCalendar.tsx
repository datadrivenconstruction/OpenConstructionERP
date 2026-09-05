// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * AccommodationCalendar — visual rooms × dates grid.
 *
 * Layout: rooms as rows (grouped + sorted by accommodation.name, then
 * room.label), days as columns. Each booking is rendered as a coloured
 * block spanning its [check_in, check_out) date range. Click an empty
 * cell to open a create-booking modal pre-filled with room + check_in;
 * click an existing block to open the state-machine detail drawer.
 *
 * Pure-DOM grid hand-rolled with `date-fns` (no calendar library) per
 * the LIGHTWEIGHT principle.
 *
 * Money discipline: charge.amount is Decimal-as-string. We never
 * parseFloat() a money value and never blend currencies — charges are
 * grouped BY currency and each subtotal is rendered with its ISO code
 * (e.g. "320.00 EUR · 50.00 USD"). Summation uses BigInt over a scaled
 * integer so precision is preserved. For display only, never for
 * persisted state. Charges that fail to parse are skipped.
 *
 * Performance: cells are derived from `(viewStart, viewEnd, rooms,
 * bookings)` via useMemo. We never materialise an N×M cell array — the
 * grid renders rooms × days directly and absolutely-positions blocks
 * inside each room row.
 *
 * Both views (Week / Month) share the same grid primitives; only
 * `daysToShow` differs.
 */

import {
  useState,
  useMemo,
  useEffect,
  useRef,
  useCallback,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ChevronLeft,
  ChevronRight,
  CalendarRange,
  CalendarDays,
  AlertTriangle,
  X,
  Plus,
} from 'lucide-react';
import {
  startOfWeek,
  endOfWeek,
  startOfMonth,
  endOfMonth,
  addDays,
  addWeeks,
  addMonths,
  differenceInCalendarDays,
  format,
  parseISO,
  isSameMonth,
  isToday as dfIsToday,
} from 'date-fns';
import { useDateFnsLocale } from '@/shared/lib/dateFnsLocale';

import {
  Button,
  Badge,
  ConfirmDialog,
  Breadcrumb,
  DismissibleInfo,
  EmptyState,
  RecoveryCard,
  SkeletonCard,
} from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

import {
  listAccommodations,
  listAccommodationBookings,
  getAccommodation,
  createBooking,
  getBooking,
  updateBooking,
  allowedBookingTransitions,
  isBookingTerminal,
  type Accommodation,
  type AccommodationDetail,
  type Room,
  type Booking,
  type BookingStatus,
  type Charge,
} from './api';

type CalendarView = 'week' | 'month';
const CALENDAR_VIEW_IDS: readonly CalendarView[] = ['week', 'month'];

/** Pixel width of one day-column. Kept generous for hover targets. */
const DAY_WIDTH_PX = 56;
const ROW_HEIGHT_PX = 44;
const ROOM_LABEL_WIDTH_PX = 200;

const STATE_BLOCK_CLASS: Record<BookingStatus, string> = {
  reserved: 'bg-amber-200 text-amber-900 border-amber-400',
  checked_in: 'bg-emerald-300 text-emerald-900 border-emerald-500',
  checked_out:
    'bg-slate-200 text-slate-700 border-slate-300 line-through opacity-70',
  cancelled: 'bg-rose-200 text-rose-900 border-rose-400 line-through',
};

/* ── Date helpers ─────────────────────────────────────────────────────── */

/**
 * Compute the inclusive list of dates rendered in the grid given the
 * current view + anchor date.
 *
 * - Week: 7 days starting Monday.
 * - Month: full weeks bracketing the anchor month (always 35 or 42 days,
 *   includes leading + trailing greyed-out days from neighbour months).
 */
function computeRange(view: CalendarView, anchor: Date): { start: Date; end: Date } {
  if (view === 'week') {
    const start = startOfWeek(anchor, { weekStartsOn: 1 });
    const end = addDays(start, 6);
    return { start, end };
  }
  const start = startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 });
  const end = endOfWeek(endOfMonth(anchor), { weekStartsOn: 1 });
  return { start, end };
}

function rangeDays(start: Date, end: Date): Date[] {
  const out: Date[] = [];
  const total = differenceInCalendarDays(end, start);
  for (let i = 0; i <= total; i += 1) out.push(addDays(start, i));
  return out;
}

/**
 * Half-open booking interval clipped to the visible window:
 *   - check_in is inclusive
 *   - check_out (when set) is exclusive — last occupied night is
 *     check_out - 1 day. NULL check_out → open-ended → clip to viewEnd.
 *
 * Returns `null` when the booking does not intersect the visible window.
 */
function clipBookingToView(
  b: Booking,
  viewStart: Date,
  viewEnd: Date,
): { startDayIdx: number; spanDays: number } | null {
  const checkIn = parseISO(b.check_in);
  // NULL check_out → open-ended: render through the end of the view.
  // We add one day past the visible window so the block visually spans
  // to the right edge.
  const checkOut = b.check_out ? parseISO(b.check_out) : addDays(viewEnd, 1);

  // Half-open: [checkIn, checkOut) — empty interval guard.
  if (differenceInCalendarDays(checkOut, checkIn) <= 0) return null;

  // viewStart..viewEnd is the inclusive day range we render. The block
  // spans days `[max(checkIn, viewStart), min(checkOut - 1, viewEnd)]`.
  const lastNight = addDays(checkOut, -1);
  const clipStart =
    differenceInCalendarDays(checkIn, viewStart) < 0 ? viewStart : checkIn;
  const clipEnd =
    differenceInCalendarDays(lastNight, viewEnd) > 0 ? viewEnd : lastNight;

  const startDayIdx = differenceInCalendarDays(clipStart, viewStart);
  const endDayIdx = differenceInCalendarDays(clipEnd, viewStart);
  if (endDayIdx < 0 || startDayIdx > differenceInCalendarDays(viewEnd, viewStart)) {
    return null;
  }
  const spanDays = endDayIdx - startDayIdx + 1;
  if (spanDays <= 0) return null;
  return { startDayIdx, spanDays };
}

/**
 * Count nights for a booking. For NULL check_out we return null so the
 * tooltip displays "open-ended".
 */
function bookingNights(b: Booking): number | null {
  if (!b.check_out) return null;
  return differenceInCalendarDays(parseISO(b.check_out), parseISO(b.check_in));
}

// Decimal scale for the BigInt string-arithmetic accumulator (max 6
// fractional digits — covers ISO money + the module's high-precision rates).
const _CHARGE_SCALE = 6;

/**
 * Render a scaled BigInt back to a Decimal string at ``_CHARGE_SCALE``,
 * trimming trailing fractional zeros. Pure string arithmetic — never
 * routes money through Number()/parseFloat().
 */
function _formatScaled(totalScaled: bigint): string {
  const negative = totalScaled < 0n;
  const absStr = (negative ? -totalScaled : totalScaled)
    .toString()
    .padStart(_CHARGE_SCALE + 1, '0');
  const intStr = absStr.slice(0, absStr.length - _CHARGE_SCALE) || '0';
  const fracStr = absStr.slice(absStr.length - _CHARGE_SCALE).replace(/0+$/, '');
  return `${negative ? '-' : ''}${intStr}${fracStr ? '.' + fracStr : ''}`;
}

/**
 * Group Decimal-as-string charge amounts BY CURRENCY and return one
 * subtotal per currency, each carrying its ISO code (money discipline:
 * never blend amounts of different currencies into one scalar, and money
 * must always show its ISO code).
 *
 * A blank ``currency`` (operator left it inherited / unset) is bucketed
 * under a sentinel and rendered without a code so the amount is still
 * visible. Buckets are ordered by descending magnitude so the dominant
 * currency leads. Summation uses BigInt over a scaled integer so we
 * never lose precision and never parseFloat() a money value.
 *
 * For display only — never feeds back into a write request. Returns an
 * empty array when no parseable charges are present.
 */
function sumChargesByCurrency(charges: Charge[]): { currency: string; total: bigint }[] {
  const buckets = new Map<string, bigint>();
  for (const c of charges) {
    const raw = c.amount.trim();
    if (!/^-?\d+(?:\.\d+)?$/.test(raw)) continue;
    const negative = raw.startsWith('-');
    const abs = negative ? raw.slice(1) : raw;
    const [intPart, fracPartRaw = ''] = abs.split('.');
    const fracPart = (fracPartRaw + '0'.repeat(_CHARGE_SCALE)).slice(0, _CHARGE_SCALE);
    const scaled = BigInt(intPart + fracPart);
    const code = (c.currency || '').trim().toUpperCase();
    buckets.set(code, (buckets.get(code) ?? 0n) + (negative ? -scaled : scaled));
  }
  return [...buckets.entries()]
    .map(([currency, total]) => ({ currency, total }))
    .sort((a, b) => {
      const am = a.total < 0n ? -a.total : a.total;
      const bm = b.total < 0n ? -b.total : b.total;
      return am > bm ? -1 : am < bm ? 1 : a.currency.localeCompare(b.currency);
    });
}

/**
 * Display string for the grouped charge subtotals, e.g.
 * ``"320.00 EUR · 50.00 USD"``. A blank-currency bucket prints the
 * amount with no code. Returns null when there is nothing to show so the
 * caller can fall back to an em-dash.
 */
function formatChargeSubtotals(charges: Charge[]): string | null {
  const groups = sumChargesByCurrency(charges);
  if (groups.length === 0) return null;
  return groups
    .map(({ currency, total }) => {
      const amount = _formatScaled(total);
      return currency ? `${amount} ${currency}` : amount;
    })
    .join(' · ');
}

/**
 * Build the stable cell key matching the data-testid we render on each
 * empty day-cell button. Keep this in lock-step with the testid format.
 */
function cellKey(roomId: string, date: Date): string {
  return `${roomId}:${format(date, 'yyyy-MM-dd')}`;
}

/* ── Skeleton (loading state) ────────────────────────────────────────── */

function CalendarSkeleton({ rowCount = 4 }: { rowCount?: number }) {
  const { t } = useTranslation();
  return (
    <div
      data-testid="accommodation-calendar-skeleton"
      role="status"
      aria-busy="true"
      aria-label={t('accommodation.calendar_loading', { defaultValue: 'Loading calendar' })}
      className="space-y-2 rounded-2xl border border-border-light bg-surface-elevated p-3"
    >
      <div className="h-8 w-full animate-pulse rounded-md bg-surface-secondary/60" />
      {Array.from({ length: rowCount }).map((_, i) => (
        <div key={i} className="flex gap-2">
          <div className="h-9 w-48 animate-pulse rounded-md bg-surface-secondary/60" />
          <div className="h-9 flex-1 animate-pulse rounded-md bg-surface-secondary/40" />
        </div>
      ))}
    </div>
  );
}

/* ── Top-level page ──────────────────────────────────────────────────── */

interface AccommodationCalendarProps {
  /**
   * When `embedded` is true the component renders without the page
   * header / breadcrumb (used by the Calendar tab inside the detail
   * page). Defaults to standalone page mode.
   */
  embedded?: boolean;
  /**
   * Pre-select a single accommodation (used by the embedded mode on the
   * detail page). When omitted, the user picks from a dropdown.
   */
  scopedAccommodationId?: string;
}

export function AccommodationCalendar({
  embedded = false,
  scopedAccommodationId,
}: AccommodationCalendarProps = {}) {
  const { t } = useTranslation();

  const [view, setView] = useState<CalendarView>('week');
  const onViewKeyDown = useTabKeyboardNav<CalendarView>({
    ids: CALENDAR_VIEW_IDS,
    activeId: view,
    onChange: setView,
    orientation: 'horizontal',
  });
  const [anchor, setAnchor] = useState<Date>(() => new Date());
  const [filterId, setFilterId] = useState<string>(scopedAccommodationId ?? '');

  // Keep internal filter in sync when the embedding component changes
  // the scope (e.g. user navigates between accommodations).
  useEffect(() => {
    if (scopedAccommodationId) setFilterId(scopedAccommodationId);
  }, [scopedAccommodationId]);

  const { start: viewStart, end: viewEnd } = useMemo(
    () => computeRange(view, anchor),
    [view, anchor],
  );

  // List of accommodations — used both for the filter dropdown (when
  // not scoped) and to know which accommodation each room belongs to.
  const accommodationsQuery = useQuery({
    queryKey: ['accommodation', 'list'],
    queryFn: () => listAccommodations(),
    enabled: !scopedAccommodationId,
  });

  // When scoped, fetch the single accommodation detail directly so we
  // don't depend on the list endpoint at all.
  const scopedDetailQuery = useQuery({
    queryKey: ['accommodation', 'detail', scopedAccommodationId],
    queryFn: () => getAccommodation(scopedAccommodationId!),
    enabled: !!scopedAccommodationId,
  });

  const allAccommodations: Accommodation[] = useMemo(() => {
    if (scopedAccommodationId && scopedDetailQuery.data) {
      return [scopedDetailQuery.data];
    }
    return accommodationsQuery.data ?? [];
  }, [scopedAccommodationId, scopedDetailQuery.data, accommodationsQuery.data]);

  // The chosen accommodations are: (a) the scoped one, (b) the picker
  // selection, or (c) every accommodation when "All" is chosen on the
  // standalone page.
  const chosenAccommodations: Accommodation[] = useMemo(() => {
    if (scopedAccommodationId) return allAccommodations;
    if (filterId === '') return allAccommodations;
    return allAccommodations.filter((a) => a.id === filterId);
  }, [scopedAccommodationId, filterId, allAccommodations]);

  // Fetch room + booking data per accommodation. We use a single
  // composite query keyed on the chosen ids so re-renders are cheap.
  const dataQuery = useQuery({
    queryKey: [
      'accommodation',
      'calendar',
      chosenAccommodations.map((a) => a.id).sort().join(','),
      // Booking query window — fetch ±1 month around the visible range
      // so navigating week-by-week mostly reuses cache.
      format(addDays(viewStart, -31), 'yyyy-MM-dd'),
      format(addDays(viewEnd, 31), 'yyyy-MM-dd'),
    ],
    queryFn: async (): Promise<{
      details: AccommodationDetail[];
      bookings: Booking[];
    }> => {
      if (chosenAccommodations.length === 0) {
        return { details: [], bookings: [] };
      }
      const details: AccommodationDetail[] = [];
      const bookings: Booking[] = [];
      for (const a of chosenAccommodations) {
        const [detail, list] = await Promise.all([
          getAccommodation(a.id),
          listAccommodationBookings(a.id, {
            from_date: format(addDays(viewStart, -31), 'yyyy-MM-dd'),
            to_date: format(addDays(viewEnd, 31), 'yyyy-MM-dd'),
            // Backend caps this at 200; 200 is enough for a 60-day
            // window across any reasonable accommodation.
            limit: 200,
          }),
        ]);
        details.push(detail);
        bookings.push(...list.items);
      }
      return { details, bookings };
    },
    enabled: chosenAccommodations.length > 0,
  });

  // Flatten + sort rooms: by accommodation.name (case-insensitive), then
  // room.label (natural-ish — labels like B-201 sort lexicographically
  // but at least we lowercase). We tag each row with its parent
  // accommodation so the leftmost column can group visually.
  interface CalendarRow {
    accommodation: AccommodationDetail;
    room: Room;
  }
  const rows: CalendarRow[] = useMemo(() => {
    if (!dataQuery.data) return [];
    const out: CalendarRow[] = [];
    const detailsByName = [...dataQuery.data.details].sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
    );
    for (const acc of detailsByName) {
      const sortedRooms = [...acc.rooms].sort((a, b) =>
        a.label.localeCompare(b.label, undefined, {
          numeric: true,
          sensitivity: 'base',
        }),
      );
      for (const room of sortedRooms) {
        out.push({ accommodation: acc, room });
      }
    }
    return out;
  }, [dataQuery.data]);

  // Bucket bookings by room id. We do this once per data refresh so the
  // per-row render does an O(1) lookup. Each room can have multiple
  // bookings on different (or — guarded — overlapping) date ranges.
  const bookingsByRoom = useMemo(() => {
    const map = new Map<string, Booking[]>();
    if (!dataQuery.data) return map;
    for (const b of dataQuery.data.bookings) {
      const arr = map.get(b.room_id) ?? [];
      arr.push(b);
      map.set(b.room_id, arr);
    }
    return map;
  }, [dataQuery.data]);

  // Day array — derived, not state.
  const days = useMemo(() => rangeDays(viewStart, viewEnd), [viewStart, viewEnd]);

  // Click-to-create state.
  const [createCtx, setCreateCtx] = useState<{
    room: Room;
    accommodationName: string;
    checkIn: string;
  } | null>(null);
  const [openBookingId, setOpenBookingId] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const handlePrev = useCallback(() => {
    setAnchor((d) => (view === 'week' ? addWeeks(d, -1) : addMonths(d, -1)));
  }, [view]);
  const handleNext = useCallback(() => {
    setAnchor((d) => (view === 'week' ? addWeeks(d, 1) : addMonths(d, 1)));
  }, [view]);
  const handleToday = useCallback(() => setAnchor(new Date()), []);

  const inputCls =
    'h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  // Month and weekday names are the only date-fns output on this page a reader
  // sees as words, so they are the only calls that take a locale. Every other
  // `format` here writes `yyyy-MM-dd` for a query parameter or a React key,
  // where a locale would be a bug rather than a fix.
  const dfLocale = useDateFnsLocale();

  const headerLabel = useMemo(() => {
    if (view === 'week') {
      return `${format(viewStart, 'MMM d', { locale: dfLocale })} – ${format(viewEnd, 'MMM d, yyyy', { locale: dfLocale })}`;
    }
    return format(anchor, 'MMMM yyyy', { locale: dfLocale });
  }, [view, viewStart, viewEnd, anchor, dfLocale]);

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-5 animate-fade-in'}>
      {!embedded && (
        <>
          <Breadcrumb
            items={[
              {
                label: t('nav.accommodation', {
                  defaultValue: 'Accommodation',
                }),
                to: '/accommodation',
              },
              {
                label: t('accommodation.calendar.title', {
                  defaultValue: 'Calendar',
                }),
              },
            ]}
          />
          <PageHeader
            srTitle={t('accommodation.calendar.title', { defaultValue: 'Calendar' })}
            subtitle={t('accommodation.calendar.subtitle', {
              defaultValue: 'See room bookings and occupancy across all accommodation on a timeline.',
            })}
          />
          <DismissibleInfo
            storageKey="accommodation-calendar"
            title={t('accommodation.calendar.intro_title', {
              defaultValue: 'See every bed across every date',
            })}
          >
            {t('accommodation.calendar.intro_body', {
              defaultValue:
                'Rooms run down the rows, dates across the columns, and each booking is a coloured block over its stay. Click an empty cell to reserve a room for that date, or click an existing block to check a guest in or out. Switch between Week and Month to zoom the timeline, and filter to a single property when you only need one site.',
            })}
          </DismissibleInfo>
        </>
      )}

      {/* Controls bar */}
      <div
        data-testid="accommodation-calendar-controls"
        className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-border-light bg-surface-elevated p-3"
      >
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={handlePrev}
            data-testid="accommodation-calendar-prev"
            aria-label={t('common.previous', { defaultValue: 'Previous' })}
          >
            <ChevronLeft size={14} />
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleToday}
            data-testid="accommodation-calendar-today"
          >
            {t('accommodation.calendar.today', { defaultValue: 'Today' })}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleNext}
            data-testid="accommodation-calendar-next"
            aria-label={t('common.next', { defaultValue: 'Next' })}
          >
            <ChevronRight size={14} />
          </Button>
          <span className="ml-2 text-sm font-medium text-content-primary tabular-nums">
            {headerLabel}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {!scopedAccommodationId && (
            <select
              value={filterId}
              onChange={(e) => setFilterId(e.target.value)}
              className={inputCls}
              data-testid="accommodation-calendar-filter"
              aria-label={t('accommodation.calendar.filter_aria', {
                defaultValue: 'Filter by accommodation',
              })}
            >
              <option value="">
                {t('accommodation.calendar.all', {
                  defaultValue: 'All accommodations',
                })}
              </option>
              {allAccommodations.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}

          <div
            className="inline-flex rounded-lg border border-border bg-surface-secondary p-0.5"
            role="tablist"
            aria-label={t('accommodation.calendar.view_aria', {
              defaultValue: 'Calendar view',
            })}
            onKeyDown={onViewKeyDown}
          >
            <button
              type="button"
              role="tab"
              id="accommodation-calendar-view-tab-week"
              aria-selected={view === 'week'}
              tabIndex={view === 'week' ? 0 : -1}
              onClick={() => setView('week')}
              data-testid="accommodation-calendar-view-week"
              className={clsx(
                'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition',
                view === 'week'
                  ? 'bg-surface-elevated text-content-primary shadow-sm'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              <CalendarRange size={12} />
              {t('accommodation.calendar.viewWeek', { defaultValue: 'Week' })}
            </button>
            <button
              type="button"
              role="tab"
              id="accommodation-calendar-view-tab-month"
              aria-selected={view === 'month'}
              tabIndex={view === 'month' ? 0 : -1}
              onClick={() => setView('month')}
              data-testid="accommodation-calendar-view-month"
              className={clsx(
                'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition',
                view === 'month'
                  ? 'bg-surface-elevated text-content-primary shadow-sm'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              <CalendarDays size={12} />
              {t('accommodation.calendar.viewMonth', { defaultValue: 'Month' })}
            </button>
          </div>
        </div>
      </div>

      {/* Body — row-shape skeleton during load */}
      {(accommodationsQuery.isLoading || scopedDetailQuery.isLoading || dataQuery.isLoading) && (
        <CalendarSkeleton rowCount={4} />
      )}

      {(accommodationsQuery.isError ||
        scopedDetailQuery.isError ||
        dataQuery.isError) && (
        <div data-testid="accommodation-calendar-error">
          <RecoveryCard
            error={
              accommodationsQuery.error ??
              scopedDetailQuery.error ??
              dataQuery.error
            }
            onRetry={() => {
              accommodationsQuery.refetch();
              scopedDetailQuery.refetch();
              dataQuery.refetch();
            }}
          />
        </div>
      )}

      {!dataQuery.isLoading &&
        !dataQuery.isError &&
        chosenAccommodations.length === 0 && (
          <div data-testid="accommodation-calendar-empty">
            <EmptyState
              icon={<CalendarRange size={22} aria-hidden="true" />}
              title={t('accommodation.calendar.empty_title', {
                defaultValue: 'No accommodations to schedule yet',
              })}
              description={t('accommodation.calendar.noAccommodations', {
                defaultValue:
                  'No accommodations yet. Create your first accommodation to start booking rooms.',
              })}
            />
          </div>
        )}

      {!dataQuery.isLoading &&
        !dataQuery.isError &&
        chosenAccommodations.length > 0 &&
        rows.length === 0 && (
          <div data-testid="accommodation-calendar-empty-rows">
            <EmptyState
              icon={<CalendarRange size={22} aria-hidden="true" />}
              title={t('accommodation.calendar.no_rooms_title', {
                defaultValue: 'No rooms to schedule yet',
              })}
              description={t('accommodation.calendar.noRooms', {
                defaultValue:
                  'No bookings this week - pick a cell to create one. Add rooms from the accommodation detail page if your camp is empty.',
              })}
            />
          </div>
        )}

      {rows.length > 0 && (
        <CalendarGrid
          rows={rows}
          days={days}
          viewStart={viewStart}
          viewEnd={viewEnd}
          view={view}
          bookingsByRoom={bookingsByRoom}
          onEmptyClick={(row, date) =>
            setCreateCtx({
              room: row.room,
              accommodationName: row.accommodation.name,
              checkIn: format(date, 'yyyy-MM-dd'),
            })
          }
          onBlockClick={(booking) => setOpenBookingId(booking.id)}
        />
      )}

      {createCtx && (
        <CreateBookingModal
          room={createCtx.room}
          accommodationName={createCtx.accommodationName}
          defaultCheckIn={createCtx.checkIn}
          onClose={() => setCreateCtx(null)}
          onCreated={() => {
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'calendar'],
            });
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'detail'],
            });
            setCreateCtx(null);
          }}
        />
      )}

      {openBookingId && (
        <BookingDetailDrawer
          bookingId={openBookingId}
          onClose={() => setOpenBookingId(null)}
          onMutated={() => {
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'calendar'],
            });
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'detail'],
            });
          }}
        />
      )}
    </div>
  );
}

/* ── Grid (rooms × days) ──────────────────────────────────────────────── */

interface CalendarGridProps {
  rows: { accommodation: AccommodationDetail; room: Room }[];
  days: Date[];
  viewStart: Date;
  viewEnd: Date;
  view: CalendarView;
  bookingsByRoom: Map<string, Booking[]>;
  onEmptyClick: (
    row: { accommodation: AccommodationDetail; room: Room },
    date: Date,
  ) => void;
  onBlockClick: (b: Booking) => void;
}

function CalendarGrid({
  rows,
  days,
  viewStart,
  viewEnd,
  view,
  bookingsByRoom,
  onEmptyClick,
  onBlockClick,
}: CalendarGridProps) {
  const { t } = useTranslation();
  // The day-column headers below print a weekday name, the one piece of
  // date-fns output in this component a reader sees as a word.
  const dfLocale = useDateFnsLocale();
  // Use the middle day as the anchor for month-view shading. `days` is
  // never empty in practice (week=7, month=35/42) but `noUncheckedIndexedAccess`
  // makes us provide a fallback for safety.
  const anchorMonth = days[Math.floor(days.length / 2)] ?? days[0] ?? new Date();

  // ── Keyboard navigation ────────────────────────────────────────────
  // The grid is a roving-tabindex pattern: only the focused cell has
  // tabIndex=0, all others have tabIndex=-1. Arrow keys traverse rooms
  // (Up/Down) and days (Left/Right); Enter opens the booking modal;
  // Escape returns focus to today.
  const cellRefs = useRef<Map<string, HTMLButtonElement | null>>(new Map());
  const today = useMemo(() => new Date(), []);
  const todayInView = useMemo(
    () =>
      days.some(
        (d) => differenceInCalendarDays(d, today) === 0,
      ),
    [days, today],
  );
  // Default focus = today on the first room row (or first day if today is
  // outside the visible window).
  const firstRoomId = rows[0]?.room.id ?? '';
  const initialDate =
    todayInView && firstRoomId
      ? days.find((d) => differenceInCalendarDays(d, today) === 0)!
      : days[0];
  const [focusedKey, setFocusedKey] = useState<string>(() =>
    firstRoomId && initialDate ? cellKey(firstRoomId, initialDate) : '',
  );

  // Re-focus today when rows or days change (e.g. switched accommodation
  // or paged the view). We only set initial focus; we don't yank focus
  // away from a user who is mid-navigation.
  const initialFocusAppliedRef = useRef(false);
  useEffect(() => {
    if (initialFocusAppliedRef.current) return;
    if (!firstRoomId || !initialDate) return;
    const key = cellKey(firstRoomId, initialDate);
    setFocusedKey(key);
    // Best-effort initial focus — only if a parent container received
    // focus already (so we don't steal focus on page mount).
    const el = cellRefs.current.get(key);
    if (el && document.activeElement && (document.activeElement === document.body)) {
      // Don't steal focus from the URL bar on first page load.
    } else if (el && document.activeElement?.closest('[data-testid="accommodation-calendar-grid"]')) {
      el.focus();
    }
    initialFocusAppliedRef.current = true;
  }, [firstRoomId, initialDate]);

  const moveFocus = useCallback(
    (currentRoomId: string, currentDate: Date, dx: number, dy: number) => {
      const rowIdx = rows.findIndex((r) => r.room.id === currentRoomId);
      const dayIdx = days.findIndex(
        (d) => differenceInCalendarDays(d, currentDate) === 0,
      );
      if (rowIdx === -1 || dayIdx === -1) return;
      const nextRow = Math.min(Math.max(0, rowIdx + dy), rows.length - 1);
      const nextDay = Math.min(Math.max(0, dayIdx + dx), days.length - 1);
      const nextRoom = rows[nextRow]?.room.id;
      const nextDate = days[nextDay];
      if (!nextRoom || !nextDate) return;
      const key = cellKey(nextRoom, nextDate);
      setFocusedKey(key);
      const el = cellRefs.current.get(key);
      el?.focus();
    },
    [rows, days],
  );

  const handleCellKeyDown = useCallback(
    (
      e: ReactKeyboardEvent<HTMLButtonElement>,
      roomId: string,
      date: Date,
    ) => {
      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          moveFocus(roomId, date, -1, 0);
          break;
        case 'ArrowRight':
          e.preventDefault();
          moveFocus(roomId, date, 1, 0);
          break;
        case 'ArrowUp':
          e.preventDefault();
          moveFocus(roomId, date, 0, -1);
          break;
        case 'ArrowDown':
          e.preventDefault();
          moveFocus(roomId, date, 0, 1);
          break;
        case 'Home':
          e.preventDefault();
          moveFocus(roomId, date, -days.length, 0);
          break;
        case 'End':
          e.preventDefault();
          moveFocus(roomId, date, days.length, 0);
          break;
        case 'Escape': {
          e.preventDefault();
          const todayDate = days.find(
            (d) => differenceInCalendarDays(d, today) === 0,
          );
          const targetRoom = rows[0]?.room.id;
          if (todayDate && targetRoom) {
            const k = cellKey(targetRoom, todayDate);
            setFocusedKey(k);
            cellRefs.current.get(k)?.focus();
          }
          break;
        }
        default:
          // Enter / Space handled by the button's native onClick.
          break;
      }
    },
    [moveFocus, days, today, rows],
  );

  return (
    <div
      data-testid="accommodation-calendar-grid"
      role="grid"
      aria-label={t('accommodation.calendar.grid_aria', {
        defaultValue: 'Bookings grid - use arrow keys to navigate cells',
      })}
      className="overflow-x-auto rounded-2xl border border-border-light bg-surface-elevated"
    >
      <div
        style={{
          minWidth: ROOM_LABEL_WIDTH_PX + days.length * DAY_WIDTH_PX,
        }}
      >
        {/* Date header row */}
        <div
          className="sticky top-0 z-10 flex border-b border-border-light bg-surface-elevated"
          style={{ height: 56 }}
        >
          <div
            className="flex shrink-0 items-center px-3 text-xs font-semibold uppercase tracking-wide text-content-tertiary border-r border-border-light"
            style={{ width: ROOM_LABEL_WIDTH_PX }}
          >
            {t('accommodation.calendar.room_column', {
              defaultValue: 'Room',
            })}
          </div>
          <div className="flex flex-1">
            {days.map((d) => {
              const today = dfIsToday(d);
              const dim = view === 'month' && !isSameMonth(d, anchorMonth);
              return (
                <div
                  key={d.toISOString()}
                  data-testid={`accommodation-calendar-day-header-${format(d, 'yyyy-MM-dd')}`}
                  className={clsx(
                    'flex shrink-0 flex-col items-center justify-center border-r border-border-light text-xs',
                    today && 'bg-oe-blue/10',
                    dim && 'opacity-50',
                  )}
                  style={{ width: DAY_WIDTH_PX }}
                >
                  <span className="font-medium text-content-tertiary uppercase">
                    {format(d, 'EEE', { locale: dfLocale })}
                  </span>
                  <span
                    className={clsx(
                      'tabular-nums',
                      today
                        ? 'font-semibold text-oe-blue'
                        : 'text-content-primary',
                    )}
                  >
                    {format(d, 'd')}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Body rows */}
        <div>
          {rows.map((row, rowIdx) => {
            const roomBookings = bookingsByRoom.get(row.room.id) ?? [];
            return (
              <RoomRow
                key={row.room.id}
                row={row}
                rowIdx={rowIdx}
                days={days}
                viewStart={viewStart}
                viewEnd={viewEnd}
                view={view}
                bookings={roomBookings}
                onEmptyClick={onEmptyClick}
                onBlockClick={onBlockClick}
                showAccommodationLabel={
                  rowIdx === 0 ||
                  rows[rowIdx - 1]?.accommodation.id !== row.accommodation.id
                }
                focusedKey={focusedKey}
                onCellKeyDown={handleCellKeyDown}
                registerCellRef={(key, el) => {
                  if (el) cellRefs.current.set(key, el);
                  else cellRefs.current.delete(key);
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

interface RoomRowProps {
  row: { accommodation: AccommodationDetail; room: Room };
  rowIdx: number;
  days: Date[];
  viewStart: Date;
  viewEnd: Date;
  view: CalendarView;
  bookings: Booking[];
  onEmptyClick: (
    row: { accommodation: AccommodationDetail; room: Room },
    date: Date,
  ) => void;
  onBlockClick: (b: Booking) => void;
  showAccommodationLabel: boolean;
  /** Stable id of the currently-focused cell — only one cell across the
   *  grid has tabIndex=0; the rest have tabIndex=-1 (roving-tabindex). */
  focusedKey: string;
  onCellKeyDown: (
    e: ReactKeyboardEvent<HTMLButtonElement>,
    roomId: string,
    date: Date,
  ) => void;
  /** Per-cell ref registration so the grid-level controller can call
   *  `.focus()` on the target cell after arrow-key navigation. */
  registerCellRef: (key: string, el: HTMLButtonElement | null) => void;
}

function RoomRow({
  row,
  rowIdx: _rowIdx,
  days,
  viewStart,
  viewEnd,
  view,
  bookings,
  onEmptyClick,
  onBlockClick,
  showAccommodationLabel,
  focusedKey,
  onCellKeyDown,
  registerCellRef,
}: RoomRowProps) {
  const { t } = useTranslation();

  // Clip + stack bookings. We compute lanes for overlapping bookings so
  // the rare data-bug case of two bookings on the same room overlapping
  // dates is at least visually distinguishable instead of hidden.
  interface LaidOutBlock {
    booking: Booking;
    startDayIdx: number;
    spanDays: number;
    lane: number;
  }
  const blocks: LaidOutBlock[] = useMemo(() => {
    const clipped: { booking: Booking; startDayIdx: number; spanDays: number }[] = [];
    for (const b of bookings) {
      const clip = clipBookingToView(b, viewStart, viewEnd);
      if (clip) clipped.push({ booking: b, ...clip });
    }
    // Sort by start day, then by id (stable across renders).
    clipped.sort(
      (a, b) =>
        a.startDayIdx - b.startDayIdx ||
        a.booking.id.localeCompare(b.booking.id),
    );
    // Assign lanes — greedy: walk in start order, place in the first
    // lane whose previous block ended before this block starts.
    const laneEnds: number[] = [];
    return clipped.map((c) => {
      const blockEnd = c.startDayIdx + c.spanDays; // exclusive
      let assigned = -1;
      for (let i = 0; i < laneEnds.length; i += 1) {
        const end = laneEnds[i];
        if (end !== undefined && end <= c.startDayIdx) {
          assigned = i;
          break;
        }
      }
      if (assigned === -1) {
        assigned = laneEnds.length;
        laneEnds.push(blockEnd);
      } else {
        laneEnds[assigned] = blockEnd;
      }
      return { ...c, lane: assigned };
    });
  }, [bookings, viewStart, viewEnd]);

  const laneCount = Math.max(1, ...blocks.map((b) => b.lane + 1));
  const rowHeight = Math.max(ROW_HEIGHT_PX, laneCount * (ROW_HEIGHT_PX - 8) + 8);
  const anchorMonth = days[Math.floor(days.length / 2)] ?? days[0] ?? new Date();

  return (
    <div
      data-testid={`accommodation-calendar-row-${row.room.id}`}
      className="flex border-b border-border-light hover:bg-surface-secondary/30"
      style={{ height: rowHeight }}
    >
      <div
        className="flex shrink-0 flex-col justify-center px-3 border-r border-border-light"
        style={{ width: ROOM_LABEL_WIDTH_PX }}
      >
        {showAccommodationLabel && (
          <span
            className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary truncate"
            title={row.accommodation.name}
          >
            {row.accommodation.name}
          </span>
        )}
        <span className="text-sm font-medium text-content-primary truncate">
          {row.room.label}
        </span>
        <span className="text-2xs text-content-tertiary">
          {t('accommodation.room.cap_short', {
            defaultValue: '{{count}} cap',
            count: row.room.capacity,
          })}
        </span>
      </div>

      <div className="relative flex-1">
        {/* Empty day cells (click-to-create) */}
        <div className="flex h-full" role="row">
          {days.map((d) => {
            const today = dfIsToday(d);
            const dim = view === 'month' && !isSameMonth(d, anchorMonth);
            const key = cellKey(row.room.id, d);
            const isFocused = key === focusedKey;
            return (
              <button
                key={d.toISOString()}
                ref={(el) => registerCellRef(key, el)}
                type="button"
                role="gridcell"
                tabIndex={isFocused ? 0 : -1}
                onClick={() => onEmptyClick(row, d)}
                onKeyDown={(e) => onCellKeyDown(e, row.room.id, d)}
                aria-label={t('accommodation.calendar.emptySlot', {
                  defaultValue: 'Create booking on {{date}}',
                  date: format(d, 'yyyy-MM-dd'),
                })}
                data-testid={`accommodation-calendar-cell-${row.room.id}-${format(d, 'yyyy-MM-dd')}`}
                data-focused={isFocused || undefined}
                className={clsx(
                  'group h-full shrink-0 border-r border-border-light transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-oe-blue focus-visible:bg-oe-blue/20',
                  today && 'bg-oe-blue/5',
                  dim && 'bg-surface-secondary/20',
                  'hover:bg-oe-blue/10',
                )}
                style={{ width: DAY_WIDTH_PX }}
              >
                <span className="sr-only opacity-0 group-hover:opacity-100">
                  <Plus size={12} />
                </span>
              </button>
            );
          })}
        </div>

        {/* Booking blocks (absolutely-positioned over the cell strip).
            role="presentation" prevents the inner buttons from being
            scanned as direct children of role="grid" (axe a11y rule
            aria-required-children would otherwise flag them). */}
        <div role="presentation" className="pointer-events-none absolute inset-0">
          {blocks.map(({ booking, startDayIdx, spanDays, lane }) => {
            const left = startDayIdx * DAY_WIDTH_PX + 2;
            const width = spanDays * DAY_WIDTH_PX - 4;
            const top = 4 + lane * (ROW_HEIGHT_PX - 12);
            const height = ROW_HEIGHT_PX - 16;
            const style: CSSProperties = {
              left,
              width,
              top,
              height,
            };
            const nights = bookingNights(booking);
            const tooltip = `${booking.occupant_name ?? '—'} · ${
              nights === null
                ? '∞'
                : `${nights} ${nights === 1 ? 'night' : 'nights'}`
            }`;
            return (
              <button
                key={booking.id}
                type="button"
                onClick={() => onBlockClick(booking)}
                title={tooltip}
                data-testid={`accommodation-calendar-block-${booking.id}`}
                style={style}
                className={clsx(
                  'pointer-events-auto absolute flex items-center overflow-hidden truncate rounded-md border px-2 text-xs font-medium shadow-sm transition hover:scale-[1.02] hover:shadow focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                  STATE_BLOCK_CLASS[booking.status],
                )}
              >
                <span className="truncate">
                  {booking.occupant_name ??
                    t('accommodation.bookings.unnamed_occupant', {
                      defaultValue: '(unnamed)',
                    })}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ── Create-booking modal ────────────────────────────────────────────── */

interface CreateBookingModalProps {
  room: Room;
  accommodationName: string;
  defaultCheckIn: string;
  onClose: () => void;
  onCreated: () => void;
}

function CreateBookingModal({
  room,
  accommodationName,
  defaultCheckIn,
  onClose,
  onCreated,
}: CreateBookingModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [contactId, setContactId] = useState('');
  const [contactName, setContactName] = useState('');
  const [occupantName, setOccupantName] = useState('');
  const [checkIn, setCheckIn] = useState(defaultCheckIn);
  const [checkOut, setCheckOut] = useState('');

  const mutation = useMutation({
    mutationFn: () =>
      createBooking(room.id, {
        occupant_contact_id: contactId || null,
        occupant_name: occupantName.trim() || contactName || null,
        check_in: checkIn,
        check_out: checkOut || null,
        status: 'reserved',
        source: 'manual',
      }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('accommodation.booking.created_toast', {
          defaultValue: 'Booking created',
        }),
      });
      onCreated();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('accommodation.booking.create_failed', {
          defaultValue: 'Could not create booking',
        }),
        message: getErrorMessage(err),
      }),
  });

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  const disabled = room.status === 'maintenance' || room.status === 'blocked';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('accommodation.calendar.createBooking', {
        defaultValue: 'Create booking - {{room}} ({{acc}})',
        room: room.label,
        acc: accommodationName,
      })}
      size="md"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={disabled || (!contactId && !occupantName.trim())}
            data-testid="accommodation-calendar-create-submit"
          >
            {t('accommodation.assign.confirm', {
              defaultValue: 'Create booking',
            })}
          </Button>
        </>
      }
    >
      {disabled && (
        <div className="mb-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" />
          {t('accommodation.assign.disabled', {
            defaultValue:
              'Room is {{status}} - change its status before booking.',
            status: room.status,
          })}
        </div>
      )}
      <WideModalSection columns={2}>
        <WideModalField
          label={t('accommodation.assign.contact', {
            defaultValue: 'Contact (optional)',
          })}
          span={2}
        >
          <ContactSearchInput
            value={contactId}
            displayValue={contactName}
            onChange={(id, name) => {
              setContactId(id);
              setContactName(name);
            }}
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.assign.occupant_name', {
            defaultValue: 'Or occupant name',
          })}
          hint={t('accommodation.assign.either_or', {
            defaultValue: 'Provide a contact or a free-text name.',
          })}
          span={2}
        >
          <input
            type="text"
            value={occupantName}
            onChange={(e) => setOccupantName(e.target.value)}
            className={inputCls}
            data-testid="accommodation-calendar-occupant-name"
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.assign.check_in', {
            defaultValue: 'Check-in',
          })}
          required
        >
          <input
            type="date"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
            className={inputCls}
            data-testid="accommodation-calendar-check-in"
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.assign.check_out', {
            defaultValue: 'Check-out (optional)',
          })}
        >
          <input
            type="date"
            value={checkOut}
            onChange={(e) => setCheckOut(e.target.value)}
            className={inputCls}
            data-testid="accommodation-calendar-check-out"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Booking detail drawer (state-machine actions) ───────────────────── */

interface BookingDetailDrawerProps {
  bookingId: string;
  onClose: () => void;
  onMutated: () => void;
}

function BookingDetailDrawer({
  bookingId,
  onClose,
  onMutated,
}: BookingDetailDrawerProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [confirmTarget, setConfirmTarget] = useState<BookingStatus | null>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  const detailQuery = useQuery({
    queryKey: ['accommodation', 'booking-detail', bookingId],
    queryFn: () => getBooking(bookingId),
  });

  const mutation = useMutation({
    mutationFn: (target: BookingStatus) =>
      updateBooking(bookingId, { status: target }),
    onSuccess: (_data, target) => {
      addToast({
        type: 'success',
        title: t(`accommodation.booking.transition_toast.${target}`, {
          defaultValue: 'Booking updated',
        }),
      });
      detailQuery.refetch();
      onMutated();
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('accommodation.booking.update_failed', {
          defaultValue: 'Could not update booking',
        }),
        message: getErrorMessage(err),
      }),
  });

  const handleAction = (target: BookingStatus) => {
    if (target === 'checked_out' || target === 'cancelled') {
      setConfirmTarget(target);
      return;
    }
    mutation.mutate(target);
  };

  // Escape-to-close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Trap focus inside the drawer so Tab cannot escape to the dimmed
  // page underneath. Hook also restores focus to the opener on unmount.
  useFocusTrap(drawerRef, true);

  const data = detailQuery.data;
  const nights = data ? bookingNights(data) : null;
  const totalCharges = data ? formatChargeSubtotals(data.charges) : null;
  const actions = data && !isBookingTerminal(data.status)
    ? allowedBookingTransitions(data.status)
    : [];

  return (
    <>
      {/* Backdrop — Material 220ms ease-standard fade-in */}
      <div
        className="fixed inset-0 z-40 bg-black/40"
        style={{
          animation: 'accomCalFadeIn 150ms cubic-bezier(0.4, 0, 0.2, 1) both',
        }}
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer */}
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('accommodation.calendar.booking_drawer_aria', {
          defaultValue: 'Booking details',
        })}
        data-testid="accommodation-calendar-booking-drawer"
        tabIndex={-1}
        style={{
          animation:
            'accomCalSlideIn 220ms cubic-bezier(0.4, 0, 0.2, 1) both',
        }}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-surface-elevated shadow-2xl"
      >
        <div className="flex items-start justify-between border-b border-border-light p-4">
          <div>
            <h2 className="text-base font-semibold text-content-primary">
              {t('accommodation.calendar.booking_drawer_title', {
                defaultValue: 'Booking details',
              })}
            </h2>
            {/* The occupant names the booking. The id stays available for
                support on the title, it is not something to read off a screen. */}
            {data && (
              <p
                className="mt-0.5 text-xs text-content-tertiary"
                title={data.id}
              >
                {data.occupant_name ??
                  t('accommodation.bookings.unnamed_occupant', {
                    defaultValue: '(unnamed)',
                  })}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {detailQuery.isLoading && <SkeletonCard />}
          {detailQuery.isError && (
            <RecoveryCard
              error={detailQuery.error}
              onRetry={() => detailQuery.refetch()}
            />
          )}
          {data && (
            <>
              <div
                className="flex items-center gap-2"
                role="status"
                aria-live="polite"
                aria-atomic="true"
                data-testid="accommodation-calendar-drawer-status"
              >
                <Badge
                  variant={
                    data.status === 'checked_in'
                      ? 'success'
                      : data.status === 'reserved'
                        ? 'warning'
                        : data.status === 'cancelled'
                          ? 'error'
                          : 'neutral'
                  }
                  size="sm"
                >
                  {t(`accommodation.booking.status.${data.status}`, {
                    defaultValue: data.status,
                  })}
                </Badge>
                <span className="text-xs text-content-tertiary">
                  {t(`accommodation.booking.source.${data.source}`, {
                    defaultValue: data.source,
                  })}
                </span>
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('accommodation.calendar.guest', {
                      defaultValue: 'Guest',
                    })}
                  </dt>
                  <dd className="text-content-primary">
                    {data.occupant_name ??
                      t('accommodation.bookings.unnamed_occupant', {
                        defaultValue: '(unnamed)',
                      })}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('accommodation.calendar.nights', {
                      defaultValue: 'Nights',
                    })}
                  </dt>
                  <dd
                    className="text-content-primary tabular-nums"
                    data-testid="accommodation-calendar-drawer-nights"
                  >
                    {nights === null ? '∞' : nights}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('accommodation.bookings.col.check_in', {
                      defaultValue: 'Check-in',
                    })}
                  </dt>
                  <dd className="text-content-primary tabular-nums">
                    {data.check_in}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('accommodation.bookings.col.check_out', {
                      defaultValue: 'Check-out',
                    })}
                  </dt>
                  <dd className="text-content-primary tabular-nums">
                    {data.check_out ?? '—'}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-xs font-medium text-content-tertiary uppercase tracking-wide">
                    {t('accommodation.calendar.total', {
                      defaultValue: 'Total charges',
                    })}
                  </dt>
                  <dd
                    className="text-content-primary tabular-nums font-mono"
                    data-testid="accommodation-calendar-drawer-total"
                  >
                    {totalCharges ?? '—'}{' '}
                    <span className="text-xs text-content-tertiary">
                      ({data.charges.length})
                    </span>
                  </dd>
                </div>
              </dl>
            </>
          )}
        </div>

        {data && actions.length > 0 && (
          <div className="border-t border-border-light p-3 flex flex-wrap gap-2 justify-end">
            {actions.map((target) => (
              <Button
                key={target}
                variant={target === 'cancelled' ? 'danger' : 'primary'}
                size="sm"
                onClick={() => handleAction(target)}
                loading={mutation.isPending && mutation.variables === target}
                data-testid={`accommodation-calendar-drawer-action-${target}`}
              >
                {t(`accommodation.booking.actions.${target}`, {
                  defaultValue:
                    target === 'checked_in'
                      ? 'Check in'
                      : target === 'checked_out'
                        ? 'Check out'
                        : target === 'cancelled'
                          ? 'Cancel booking'
                          : target,
                })}
              </Button>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmTarget}
        onCancel={() => setConfirmTarget(null)}
        onConfirm={() => {
          if (!confirmTarget) return;
          mutation.mutate(confirmTarget);
          setConfirmTarget(null);
        }}
        title={
          confirmTarget === 'cancelled'
            ? t('accommodation.confirm.cancel_booking_title', {
                defaultValue: 'Cancel this booking?',
              })
            : t('accommodation.confirm.checkout_title', {
                defaultValue: 'Check out this booking?',
              })
        }
        message={
          confirmTarget === 'cancelled'
            ? t('accommodation.confirm.cancel_booking_message', {
                defaultValue:
                  'Cancelling locks the booking - no further status changes are possible.',
              })
            : t('accommodation.confirm.checkout_message', {
                defaultValue:
                  'Checking out closes the stay. The booking moves to a terminal state and the room returns to "available".',
              })
        }
        confirmLabel={
          confirmTarget === 'cancelled'
            ? t('accommodation.booking.actions.cancel', {
                defaultValue: 'Cancel booking',
              })
            : t('accommodation.booking.actions.check_out', {
                defaultValue: 'Check out',
              })
        }
        variant={confirmTarget === 'cancelled' ? 'danger' : 'warning'}
        loading={mutation.isPending}
      />
      {/* Material-standard easings — local to the calendar drawer */}
      <style>{`
        @keyframes accomCalFadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes accomCalSlideIn {
          from { transform: translateX(16px); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </>
  );
}
