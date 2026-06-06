/**
 * AccommodationDetailPage — /accommodation/:id
 *
 * Information architecture:
 *   The five operator-level tabs (rooms / bookings / calendar / charges /
 *   settings) are grouped into three logical blocks so the page reads as
 *   "Inventory · Occupancy · Billing" with Settings parked at the end:
 *
 *     Inventory  → Rooms
 *     Occupancy  → Bookings · Calendar
 *     Billing    → Charges
 *     Settings   → General · Bootstrap · Danger zone
 *
 *   The top tab strip toggles blocks; a secondary segmented control
 *   within Occupancy switches Bookings/Calendar. Charges is rebuilt as a
 *   booking-picker (no more UUID-paste UX) backed by the existing
 *   `/bookings/{id}/charges` endpoint.
 *
 * Header KPIs: an at-a-glance strip (capacity, active bookings, rooms,
 * vacant) replaces the dense single-line text list.
 *
 * Money discipline: every charge amount + base_rate is sent / read as a
 * STRING; we never `parseFloat()` a money field.
 */

import { useState, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  useQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import clsx from 'clsx';
import {
  BedDouble,
  CalendarClock,
  CalendarRange,
  Receipt,
  Settings as SettingsIcon,
  Globe2,
  Box,
  Plus,
  AlertTriangle,
  Trash2,
  MoreHorizontal,
  Users,
  CircleCheck,
  Layers,
  ExternalLink,
  Wallet,
  FileText,
} from 'lucide-react';

import {
  Card,
  Badge,
  Button,
  Breadcrumb,
  ConfirmDialog,
  ModuleHelpButton,
  SkeletonCard,
  SkeletonTable,
  EmptyState,
  RecoveryCard,
  TabBar,
  tabIds,
} from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

import {
  getAccommodation,
  updateAccommodation,
  deleteAccommodation,
  createBooking,
  createCharge,
  bootstrapFromPropDev,
  allowedBookingTransitions,
  isBookingTerminal,
  listAccommodationBookings,
  updateBooking,
  getBooking,
  type AccommodationDetail,
  type Room,
  type RoomStatus,
  type Booking,
  type BookingStatus,
  type ChargeKind,
  type ChargeStatus,
} from './api';
import { fetchBIMModels } from '@/features/bim/api';
import {
  listDevelopments,
  listPhases,
  listBlocks,
} from '@/features/property-dev/api';
import { BulkRoomAddModal } from './BulkRoomAddModal';
import { AccommodationCalendar } from './AccommodationCalendar';

/** Visual badge palette for the per-row booking-status pill. */
const BOOKING_STATUS_BADGE: Record<BookingStatus, string> = {
  reserved: 'bg-sky-100 text-sky-800 border-sky-300',
  checked_in: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  checked_out: 'bg-slate-200 text-slate-700 border-slate-300',
  cancelled: 'bg-rose-100 text-rose-800 border-rose-300',
};

const CHARGE_STATUS_BADGE: Record<ChargeStatus, string> = {
  pending: 'bg-amber-100 text-amber-800 border-amber-300',
  invoiced: 'bg-sky-100 text-sky-800 border-sky-300',
  paid: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  waived: 'bg-slate-200 text-slate-700 border-slate-300',
};

/** Status filter pill keys in display order (incl. `all`). */
const FILTER_PILLS: Array<'all' | BookingStatus> = [
  'all',
  'reserved',
  'checked_in',
  'checked_out',
  'cancelled',
];

/* ── IA grouping ──────────────────────────────────────────────────────── */

/** Top-level page sections (3 logical blocks + Settings). */
type DetailBlock = 'inventory' | 'occupancy' | 'billing' | 'settings';

/** Sub-tabs inside the Occupancy block (Bookings + Calendar). */
type OccupancyTab = 'bookings' | 'calendar';
const OCCUPANCY_TAB_IDS: readonly OccupancyTab[] = ['bookings', 'calendar'];

const ROOM_STATUS_STYLES: Record<RoomStatus, string> = {
  available: 'bg-emerald-100 text-emerald-800 border-emerald-300',
  occupied: 'bg-amber-100 text-amber-800 border-amber-300',
  maintenance: 'bg-slate-200 text-slate-700 border-slate-300',
  blocked: 'bg-rose-100 text-rose-800 border-rose-300',
};

export function AccommodationDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [block, setBlock] = useState<DetailBlock>('inventory');
  const [occupancyTab, setOccupancyTab] = useState<OccupancyTab>('bookings');

  const detailQuery = useQuery({
    queryKey: ['accommodation', 'detail', id],
    queryFn: () => getAccommodation(id!),
    enabled: !!id,
  });

  if (!id) return null;

  if (detailQuery.isLoading) {
    return (
      <div className="space-y-4" data-testid="accommodation-detail-loading">
        <SkeletonCard />
        <SkeletonTable rows={4} columns={4} />
      </div>
    );
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div data-testid="accommodation-detail-error">
        <RecoveryCard
          error={detailQuery.error}
          onRetry={() => detailQuery.refetch()}
        />
      </div>
    );
  }

  const data = detailQuery.data;
  const hasGeo = data.geo_lat !== null && data.geo_lon !== null;

  // ── Derived KPIs ────────────────────────────────────────────────────
  const roomCounts = {
    available: 0,
    occupied: 0,
    maintenance: 0,
    blocked: 0,
  } as Record<RoomStatus, number>;
  for (const r of data.rooms) roomCounts[r.status] += 1;

  const blockIds = tabIds('accommodation-detail');

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          {
            label: t('nav.accommodation', { defaultValue: 'Accommodation' }),
            to: '/accommodation',
          },
          { label: data.name || t('common.unnamed', { defaultValue: '(unnamed)' }) },
        ]}
      />

      <div
        data-testid="accommodation-detail-header"
        className="rounded-2xl border border-border-light bg-surface-elevated p-4 space-y-4"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-xl font-semibold text-content-primary">
                {data.name || t('common.unnamed', { defaultValue: '(unnamed)' })}
              </h1>
              <Badge variant="blue" size="sm">
                {t(`accommodation.kind.${data.kind}`, {
                  defaultValue: data.kind,
                })}
              </Badge>
              {data.bim_model_id && (
                <Link
                  to={`/bim/${data.bim_model_id}`}
                  aria-label={t('accommodation.bim_link.aria', {
                    defaultValue: 'Open linked BIM model',
                  })}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary hover:text-oe-blue"
                  data-testid="accommodation-bim-link"
                >
                  <Box size={11} aria-hidden="true" />
                  {t('accommodation.bim_link.label', { defaultValue: 'BIM' })}
                </Link>
              )}
              <ModuleHelpButton tourId="accommodation" />
            </div>
            {data.address && (
              <p className="mt-1 text-sm text-content-secondary">{data.address}</p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {hasGeo && (
              <Link
                to={`/geo?lat=${data.geo_lat}&lon=${data.geo_lon}`}
                className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-2.5 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/10"
                data-testid="accommodation-detail-geo-link"
              >
                <Globe2 size={12} aria-hidden="true" />
                {t('accommodation.geo.view_on_map', {
                  defaultValue: 'View on map',
                })}
              </Link>
            )}
          </div>
        </div>

        {/* KPI strip — capacity / bookings / rooms / vacant. Collapses
            to 2 columns on phones, 4 across on tablets+ for breathing
            room without scrolling. */}
        <div
          data-testid="accommodation-header-kpis"
          className="grid grid-cols-2 sm:grid-cols-4 gap-2"
        >
          <HeaderKpi
            icon={<Users size={14} aria-hidden="true" />}
            label={t('accommodation.summary.capacity', {
              defaultValue: 'Capacity',
            })}
            value={data.capacity_total}
          />
          <HeaderKpi
            icon={<CalendarClock size={14} aria-hidden="true" />}
            label={t('accommodation.summary.active', {
              defaultValue: 'Active stays',
            })}
            value={data.active_bookings_count}
            accent={
              data.active_bookings_count > 0 ? 'text-emerald-700' : undefined
            }
          />
          <HeaderKpi
            icon={<BedDouble size={14} aria-hidden="true" />}
            label={t('accommodation.summary.rooms', { defaultValue: 'Rooms' })}
            value={data.rooms.length}
          />
          <HeaderKpi
            icon={<CircleCheck size={14} aria-hidden="true" />}
            label={t('accommodation.summary.vacant', { defaultValue: 'Vacant' })}
            value={roomCounts.available}
            accent={
              roomCounts.available === 0 && data.rooms.length > 0
                ? 'text-amber-700'
                : undefined
            }
          />
        </div>
      </div>

      {/* Primary block tab strip — 3 logical blocks + Settings */}
      <TabBar<DetailBlock>
        tabs={[
          {
            id: 'inventory',
            label: t('accommodation.block.inventory', {
              defaultValue: 'Inventory',
            }),
            icon: <Layers size={16} aria-hidden="true" />,
            badge: (
              <span className="rounded-full bg-surface-secondary px-1.5 text-2xs tabular-nums text-content-tertiary">
                {data.rooms.length}
              </span>
            ),
          },
          {
            id: 'occupancy',
            label: t('accommodation.block.occupancy', {
              defaultValue: 'Occupancy',
            }),
            icon: <CalendarRange size={16} aria-hidden="true" />,
            badge: (
              <span className="rounded-full bg-surface-secondary px-1.5 text-2xs tabular-nums text-content-tertiary">
                {data.active_bookings_count}
              </span>
            ),
          },
          {
            id: 'billing',
            label: t('accommodation.block.billing', {
              defaultValue: 'Billing',
            }),
            icon: <Receipt size={16} aria-hidden="true" />,
          },
          {
            id: 'settings',
            label: t('accommodation.tabs.settings', {
              defaultValue: 'Settings',
            }),
            icon: <SettingsIcon size={16} aria-hidden="true" />,
          },
        ]}
        activeId={block}
        onChange={setBlock}
        ariaLabel={t('accommodation.tabs.aria', {
          defaultValue: 'Accommodation sections',
        })}
        idPrefix="accommodation-detail"
        testIdPrefix="accommodation-detail"
      />

      {block === 'inventory' && (
        <div
          role="tabpanel"
          id={blockIds.panelId('inventory')}
          aria-labelledby={blockIds.tabId('inventory')}
        >
          <RoomsTab data={data} />
        </div>
      )}
      {block === 'occupancy' && (
        <div
          role="tabpanel"
          id={blockIds.panelId('occupancy')}
          aria-labelledby={blockIds.tabId('occupancy')}
          className="space-y-3"
        >
          <OccupancySubTabs
            value={occupancyTab}
            onChange={setOccupancyTab}
            bookingCount={data.active_bookings_count}
          />
          {occupancyTab === 'bookings' && <BookingsTab data={data} />}
          {occupancyTab === 'calendar' && (
            <div data-testid="accommodation-tab-panel-calendar">
              <AccommodationCalendar
                embedded
                scopedAccommodationId={data.id}
              />
            </div>
          )}
        </div>
      )}
      {block === 'billing' && (
        <div
          role="tabpanel"
          id={blockIds.panelId('billing')}
          aria-labelledby={blockIds.tabId('billing')}
        >
          <ChargesTab data={data} />
        </div>
      )}
      {block === 'settings' && (
        <div
          role="tabpanel"
          id={blockIds.panelId('settings')}
          aria-labelledby={blockIds.tabId('settings')}
        >
          <SettingsTab
            data={data}
            onDeleted={() => {
              addToast({
                type: 'success',
                title: t('accommodation.toast.deleted', {
                  defaultValue: 'Accommodation deleted',
                }),
              });
              queryClient.invalidateQueries({ queryKey: ['accommodation'] });
              navigate('/accommodation');
            }}
          />
        </div>
      )}
    </div>
  );
}

/* ── Header KPI tile ─────────────────────────────────────────────────── */

interface HeaderKpiProps {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent?: string;
}

function HeaderKpi({ icon, label, value, accent }: HeaderKpiProps) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-border-light bg-surface-primary px-3 py-2">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-secondary text-content-secondary">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wide text-content-tertiary leading-tight">
          {label}
        </div>
        <div
          className={clsx(
            'text-base font-semibold tabular-nums leading-tight',
            accent ?? 'text-content-primary',
          )}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

/* ── Occupant reference ──────────────────────────────────────────────── */

/**
 * Render a booking's occupant. When the booking is tied to a real
 * directory contact (``occupant_contact_id`` present), the name becomes
 * a deep link into the Contacts directory so an operator can open the
 * housed worker's record. Falls back to plain text for free-text
 * occupants (no contact behind the name).
 *
 * The link carries the contact id as a ``?contactId=`` hint - the
 * Contacts page resolves it to open the matching record. The label is
 * always the human name, so the user sees who it is regardless.
 */
function OccupantRef({
  contactId,
  name,
  className,
}: {
  contactId: string | null;
  name: string | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const label =
    name ||
    t('accommodation.bookings.unnamed_occupant', { defaultValue: '(unnamed)' });

  if (!contactId) {
    return <span className={className}>{label}</span>;
  }

  return (
    <Link
      to={`/contacts?contactId=${encodeURIComponent(contactId)}`}
      className={clsx(
        'inline-flex items-center gap-1 text-oe-blue hover:underline',
        className,
      )}
      title={t('accommodation.bookings.open_contact', {
        defaultValue: 'Open contact record',
      })}
      data-testid="occupant-contact-link"
    >
      <span className="truncate">{label}</span>
      <ExternalLink size={11} aria-hidden="true" className="shrink-0" />
    </Link>
  );
}

/* ── Occupancy sub-tabs ──────────────────────────────────────────────── */

function OccupancySubTabs({
  value,
  onChange,
  bookingCount,
}: {
  value: OccupancyTab;
  onChange: (next: OccupancyTab) => void;
  bookingCount: number;
}) {
  const { t } = useTranslation();
  const onKey = useTabKeyboardNav<OccupancyTab>({
    ids: OCCUPANCY_TAB_IDS,
    activeId: value,
    onChange,
    orientation: 'horizontal',
  });
  return (
    <div
      role="tablist"
      aria-label={t('accommodation.occupancy.sub_aria', {
        defaultValue: 'Occupancy views',
      })}
      onKeyDown={onKey}
      data-testid="accommodation-occupancy-subtabs"
      className="inline-flex rounded-lg border border-border-light bg-surface-secondary p-0.5"
    >
      <button
        type="button"
        role="tab"
        id="accommodation-occupancy-sub-bookings"
        aria-selected={value === 'bookings'}
        tabIndex={value === 'bookings' ? 0 : -1}
        onClick={() => onChange('bookings')}
        data-testid="accommodation-occupancy-sub-bookings"
        className={clsx(
          'inline-flex min-h-[36px] items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition',
          value === 'bookings'
            ? 'bg-surface-elevated text-content-primary shadow-sm'
            : 'text-content-secondary hover:text-content-primary',
        )}
      >
        <CalendarClock size={14} aria-hidden="true" />
        {t('accommodation.tabs.bookings', { defaultValue: 'Bookings' })}
        <span className="rounded-full bg-surface-secondary px-1.5 text-2xs tabular-nums text-content-tertiary">
          {bookingCount}
        </span>
      </button>
      <button
        type="button"
        role="tab"
        id="accommodation-occupancy-sub-calendar"
        aria-selected={value === 'calendar'}
        tabIndex={value === 'calendar' ? 0 : -1}
        onClick={() => onChange('calendar')}
        data-testid="accommodation-occupancy-sub-calendar"
        className={clsx(
          'inline-flex min-h-[36px] items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition',
          value === 'calendar'
            ? 'bg-surface-elevated text-content-primary shadow-sm'
            : 'text-content-secondary hover:text-content-primary',
        )}
      >
        <CalendarRange size={14} aria-hidden="true" />
        {t('accommodation.tabs.calendar', { defaultValue: 'Calendar' })}
      </button>
    </div>
  );
}

/* ── Rooms tab ───────────────────────────────────────────────────────── */

function RoomsTab({ data }: { data: AccommodationDetail }) {
  const { t } = useTranslation();
  const [bulkOpen, setBulkOpen] = useState(false);
  const [assignRoom, setAssignRoom] = useState<Room | null>(null);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const counts = useMemo(() => {
    const c: Record<RoomStatus, number> = {
      available: 0,
      occupied: 0,
      maintenance: 0,
      blocked: 0,
    };
    for (const r of data.rooms) c[r.status] += 1;
    return c;
  }, [data.rooms]);

  return (
    <div
      data-testid="accommodation-tab-panel-rooms"
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2 text-xs">
          {(Object.keys(counts) as RoomStatus[]).map((s) => (
            <span
              key={s}
              className={clsx(
                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium',
                ROOM_STATUS_STYLES[s],
              )}
            >
              {t(`accommodation.room.status.${s}`, { defaultValue: s })}
              <span className="tabular-nums opacity-80">{counts[s]}</span>
            </span>
          ))}
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setBulkOpen(true)}
          data-testid="accommodation-rooms-bulk-add"
        >
          <Plus size={14} className="mr-1.5" aria-hidden="true" />
          {t('accommodation.rooms.bulk_add', { defaultValue: 'Add rooms' })}
        </Button>
      </div>

      {data.rooms.length === 0 ? (
        <EmptyState
          icon={<BedDouble size={22} aria-hidden="true" />}
          title={t('accommodation.rooms.empty_title', {
            defaultValue: 'No rooms yet',
          })}
          description={t('accommodation.rooms.empty_description', {
            defaultValue:
              'Add rooms in bulk with a label generator (e.g. B-201..B-212) or paste your own list. Each room can be booked, status-tracked and billed.',
          })}
          action={{
            label: t('accommodation.rooms.bulk_add', {
              defaultValue: 'Add rooms',
            }),
            onClick: () => setBulkOpen(true),
          }}
        />
      ) : (
        <div
          data-testid="accommodation-rooms-grid"
          className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 gap-2"
        >
          {data.rooms.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => setAssignRoom(r)}
              data-testid={`accommodation-room-${r.label}`}
              aria-label={t('accommodation.room.tile_aria', {
                defaultValue: 'Room {{label}} - {{status}}',
                label: r.label,
                status: t(`accommodation.room.status.${r.status}`, {
                  defaultValue: r.status,
                }),
              })}
              className={clsx(
                'flex min-h-[68px] flex-col items-start rounded-lg border p-2.5 text-left text-xs transition hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                ROOM_STATUS_STYLES[r.status],
              )}
            >
              <span className="font-semibold text-sm leading-tight">{r.label}</span>
              <span className="mt-1 text-2xs opacity-80">
                {t('accommodation.room.cap_short', {
                  defaultValue: '{{count}} cap',
                  count: r.capacity,
                })}
              </span>
              <span className="mt-0.5 text-2xs opacity-80">
                {t(`accommodation.room.status.${r.status}`, {
                  defaultValue: r.status,
                })}
              </span>
            </button>
          ))}
        </div>
      )}

      {bulkOpen && (
        <BulkRoomAddModal
          accommodationId={data.id}
          existingLabels={data.rooms.map((r) => r.label)}
          onClose={() => setBulkOpen(false)}
          onCreated={() => setBulkOpen(false)}
        />
      )}

      {assignRoom && (
        <AssignOccupantModal
          room={assignRoom}
          onClose={() => setAssignRoom(null)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['accommodation'] });
            addToast({
              type: 'success',
              title: t('accommodation.booking.created_toast', {
                defaultValue: 'Booking created',
              }),
            });
            setAssignRoom(null);
          }}
        />
      )}
    </div>
  );
}

/* ── Assign occupant — invoked from a room cell ─────────────────────── */

function AssignOccupantModal({
  room,
  onClose,
  onCreated,
}: {
  room: Room;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [contactId, setContactId] = useState('');
  const [contactName, setContactName] = useState('');
  const [occupantName, setOccupantName] = useState('');
  const [checkIn, setCheckIn] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [checkOut, setCheckOut] = useState('');

  const mutation = useMutation({
    mutationFn: async () => {
      return createBooking(room.id, {
        occupant_contact_id: contactId || null,
        occupant_name: occupantName.trim() || contactName || null,
        check_in: checkIn,
        check_out: checkOut || null,
        status: 'reserved',
        source: 'manual',
      });
    },
    onSuccess: () => onCreated(),
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
      title={t('accommodation.assign.title', {
        defaultValue: 'Assign occupant - {{label}}',
        label: room.label,
      })}
      size="md"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={disabled || (!contactId && !occupantName.trim())}
            data-testid="accommodation-assign-submit"
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
          <AlertTriangle className="mr-1.5 inline h-3.5 w-3.5" aria-hidden="true" />
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
            data-testid="accommodation-assign-occupant-name"
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.assign.check_in', { defaultValue: 'Check-in' })}
          required
        >
          <input
            type="date"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
            className={inputCls}
            data-testid="accommodation-assign-check-in"
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
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Bookings tab ────────────────────────────────────────────────────── */

function BookingsTab({ data }: { data: AccommodationDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [filter, setFilter] = useState<'all' | BookingStatus>('all');
  const [pickerRoom, setPickerRoom] = useState<Room | null>(null);
  const onFilterKeyDown = useTabKeyboardNav<'all' | BookingStatus>({
    ids: FILTER_PILLS,
    activeId: filter,
    onChange: setFilter,
    orientation: 'horizontal',
  });

  const statusFilter = filter === 'all' ? undefined : [filter];

  // Real list endpoint — server returns `items` + `room_label` decorated
  // per booking so we never need a per-row /rooms/{id} round-trip.
  const bookingsQuery = useQuery({
    queryKey: ['accommodation', 'bookings', data.id, filter],
    queryFn: () =>
      listAccommodationBookings(data.id, {
        status: statusFilter,
        limit: 200,
      }),
    enabled: data.rooms.length > 0,
  });

  if (data.rooms.length === 0) {
    return (
      <div
        data-testid="accommodation-tab-panel-bookings"
        className="space-y-4"
      >
        <EmptyState
          icon={<CalendarClock size={22} aria-hidden="true" />}
          title={t('accommodation.bookings.no_rooms_title', {
            defaultValue: 'No rooms to book yet',
          })}
          description={t('accommodation.bookings.no_rooms_desc', {
            defaultValue:
              'Bookings live on rooms. Add some rooms first - Inventory tab → Add rooms - then come back here.',
          })}
        />
      </div>
    );
  }

  const items = bookingsQuery.data?.items ?? [];

  return (
    <div
      data-testid="accommodation-tab-panel-bookings"
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          role="tablist"
          aria-label={t('accommodation.bookings.filter_aria', {
            defaultValue: 'Filter bookings by status',
          })}
          onKeyDown={onFilterKeyDown}
          className="flex flex-wrap gap-1.5"
        >
          {FILTER_PILLS.map((pill) => {
            const active = filter === pill;
            const label =
              pill === 'all'
                ? t('accommodation.bookings.filter.all', { defaultValue: 'All' })
                : t(`accommodation.booking.status.${pill}`, {
                    defaultValue: pill,
                  });
            return (
              <button
                key={pill}
                type="button"
                role="tab"
                id={`bookings-filter-tab-${pill}`}
                aria-selected={active}
                aria-controls={`bookings-filter-panel-${pill}`}
                tabIndex={active ? 0 : -1}
                onClick={() => setFilter(pill)}
                data-testid={`bookings-filter-${pill}`}
                className={clsx(
                  'min-h-[32px] rounded-full border px-3 py-1 text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                  active
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border bg-surface-secondary/40 text-content-secondary hover:text-content-primary',
                )}
              >
                {label}
              </button>
            );
          })}
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setPickerRoom(data.rooms[0] ?? null)}
          disabled={data.rooms.length === 0}
          data-testid="bookings-new-button"
        >
          <Plus size={14} className="mr-1.5" aria-hidden="true" />
          {t('accommodation.booking.actions.new', {
            defaultValue: 'New booking',
          })}
        </Button>
      </div>

      {bookingsQuery.isLoading && (
        <SkeletonTable rows={4} columns={4} />
      )}

      {bookingsQuery.isError && (
        <RecoveryCard
          error={bookingsQuery.error}
          onRetry={() => bookingsQuery.refetch()}
        />
      )}

      {!bookingsQuery.isLoading && !bookingsQuery.isError && items.length === 0 && (
        <EmptyState
          icon={<CalendarClock size={22} aria-hidden="true" />}
          title={
            filter === 'all'
              ? t('accommodation.bookings.empty_all_title', {
                  defaultValue: 'No bookings yet',
                })
              : t('accommodation.bookings.empty_filtered_title', {
                  defaultValue: 'Nothing matches this filter',
                })
          }
          description={
            filter === 'all'
              ? t('accommodation.bookings.empty_all_desc', {
                  defaultValue:
                    'Bookings stretch from reservation to check-out. Open a room from the Inventory tab to assign an occupant, or hit "New booking" to get started.',
                })
              : t('accommodation.bookings.empty_filtered_desc', {
                  defaultValue:
                    'Try a different status filter, or clear it to see every booking.',
                })
          }
          action={
            filter === 'all'
              ? {
                  label: t('accommodation.booking.actions.new', {
                    defaultValue: 'New booking',
                  }),
                  onClick: () => setPickerRoom(data.rooms[0] ?? null),
                }
              : {
                  label: t('common.clear_filters', {
                    defaultValue: 'Clear filters',
                  }),
                  onClick: () => setFilter('all'),
                }
          }
        />
      )}

      {items.length > 0 && (
        <BookingsList
          accommodationId={data.id}
          items={items}
          onMutated={() => {
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'bookings', data.id],
            });
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'detail', data.id],
            });
          }}
          onError={(err) =>
            addToast({
              type: 'error',
              title: t('accommodation.booking.update_failed', {
                defaultValue: 'Could not update booking',
              }),
              message: getErrorMessage(err),
            })
          }
        />
      )}

      {pickerRoom && (
        <AssignOccupantModal
          room={pickerRoom}
          onClose={() => setPickerRoom(null)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ['accommodation'] });
            addToast({
              type: 'success',
              title: t('accommodation.booking.created_toast', {
                defaultValue: 'Booking created',
              }),
            });
            setPickerRoom(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * Renders the booking list — desktop table + mobile cards (auto-switched
 * at <640px) — plus the per-row 3-dot action menu that drives the state
 * machine via PATCH /bookings/{id}.
 */
function BookingsList({
  accommodationId: _accommodationId,
  items,
  onMutated,
  onError,
}: {
  accommodationId: string;
  items: Booking[];
  onMutated: () => void;
  onError: (err: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [confirm, setConfirm] = useState<{
    booking: Booking;
    target: BookingStatus;
  } | null>(null);

  const mutation = useMutation({
    mutationFn: ({
      bookingId,
      target,
    }: {
      bookingId: string;
      target: BookingStatus;
    }) => updateBooking(bookingId, { status: target }),
    onSuccess: (_data, vars) => {
      onMutated();
      addToast({
        type: 'success',
        title: t(`accommodation.booking.transition_toast.${vars.target}`, {
          defaultValue: 'Booking updated',
        }),
      });
    },
    onError,
  });

  const handleAction = (booking: Booking, target: BookingStatus) => {
    // Destructive / irreversible transitions get a confirm dialog;
    // ``checked_in`` is reversible (operator can cancel) so we just go.
    if (target === 'checked_out' || target === 'cancelled') {
      setConfirm({ booking, target });
      return;
    }
    mutation.mutate({ bookingId: booking.id, target });
  };

  return (
    <>
      {/* Desktop / tablet ≥640px — full table */}
      <div
        data-testid="bookings-table-wrapper"
        className="hidden sm:block overflow-x-auto rounded-xl border border-border-light"
      >
        <table className="min-w-full text-sm">
          <thead className="bg-surface-secondary/60 text-left text-xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('accommodation.bookings.col.room', { defaultValue: 'Room' })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('accommodation.bookings.col.occupant', {
                  defaultValue: 'Occupant',
                })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('accommodation.bookings.col.check_in', {
                  defaultValue: 'Check-in',
                })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('accommodation.bookings.col.check_out', {
                  defaultValue: 'Check-out',
                })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('accommodation.bookings.col.status', {
                  defaultValue: 'Status',
                })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('accommodation.bookings.col.source', {
                  defaultValue: 'Source',
                })}
              </th>
              <th scope="col" className="px-3 py-2 font-medium text-right">
                <span className="sr-only">
                  {t('common.actions')}
                </span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {items.map((b) => (
              <tr
                key={b.id}
                data-testid={`booking-row-${b.id}`}
                className="hover:bg-surface-secondary/30"
              >
                <td className="px-3 py-2 font-mono text-xs">
                  {b.room_label ?? '—'}
                </td>
                <td className="px-3 py-2">
                  <OccupantRef
                    contactId={b.occupant_contact_id}
                    name={b.occupant_name}
                  />
                </td>
                <td className="px-3 py-2 tabular-nums">{b.check_in}</td>
                <td className="px-3 py-2 tabular-nums">
                  {b.check_out ?? '—'}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={clsx(
                      'inline-flex items-center rounded-md border px-1.5 py-0.5 text-2xs font-semibold',
                      BOOKING_STATUS_BADGE[b.status],
                    )}
                    data-testid={`booking-status-${b.id}`}
                  >
                    {t(`accommodation.booking.status.${b.status}`, {
                      defaultValue: b.status,
                    })}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-content-tertiary">
                  {t(`accommodation.booking.source.${b.source}`, {
                    defaultValue: b.source,
                  })}
                </td>
                <td className="px-3 py-2 text-right">
                  <BookingActionMenu booking={b} onAction={handleAction} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile <640px — cards */}
      <div className="sm:hidden space-y-2" data-testid="bookings-cards-wrapper">
        {items.map((b) => (
          <Card key={b.id} padding="none" data-testid={`booking-card-${b.id}`}>
            <div className="p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold">
                      {b.room_label ?? '—'}
                    </span>
                    <span
                      className={clsx(
                        'inline-flex items-center rounded-md border px-1.5 py-0.5 text-2xs font-semibold',
                        BOOKING_STATUS_BADGE[b.status],
                      )}
                    >
                      {t(`accommodation.booking.status.${b.status}`, {
                        defaultValue: b.status,
                      })}
                    </span>
                  </div>
                  <div className="mt-1 text-sm">
                    <OccupantRef
                      contactId={b.occupant_contact_id}
                      name={b.occupant_name}
                    />
                  </div>
                  <div className="mt-0.5 text-xs text-content-tertiary tabular-nums">
                    {b.check_in} {'→'} {b.check_out ?? '∞'}
                  </div>
                </div>
                <BookingActionMenu booking={b} onAction={handleAction} />
              </div>
            </div>
          </Card>
        ))}
      </div>

      <ConfirmDialog
        open={!!confirm}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (!confirm) return;
          mutation.mutate({
            bookingId: confirm.booking.id,
            target: confirm.target,
          });
          setConfirm(null);
        }}
        title={
          confirm?.target === 'cancelled'
            ? t('accommodation.confirm.cancel_booking_title', {
                defaultValue: 'Cancel this booking?',
              })
            : t('accommodation.confirm.checkout_title', {
                defaultValue: 'Check out this booking?',
              })
        }
        message={
          confirm?.target === 'cancelled'
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
          confirm?.target === 'cancelled'
            ? t('accommodation.booking.actions.cancel', {
                defaultValue: 'Cancel booking',
              })
            : t('accommodation.booking.actions.check_out', {
                defaultValue: 'Check out',
              })
        }
        variant={confirm?.target === 'cancelled' ? 'danger' : 'warning'}
        loading={mutation.isPending}
      />
    </>
  );
}

/** 3-dot popover menu — drives state-machine actions per booking. */
function BookingActionMenu({
  booking,
  onAction,
}: {
  booking: Booking;
  onAction: (booking: Booking, target: BookingStatus) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Click-outside + Escape dismiss.
  useEffect(() => {
    if (!open) return undefined;
    const onClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const actions = nextBookingActions(booking);
  const disabled = actions.length === 0 || isBookingTerminal(booking.status);

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('accommodation.bookings.row_menu_aria', {
          defaultValue: 'Booking actions',
        })}
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        data-testid={`booking-actions-${booking.id}`}
        className={clsx(
          'inline-flex h-9 w-9 sm:h-7 sm:w-7 items-center justify-center rounded-md border border-transparent transition focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
          disabled
            ? 'cursor-not-allowed text-content-tertiary opacity-40'
            : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
        )}
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {open && actions.length > 0 && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 min-w-[10rem] rounded-lg border border-border bg-surface-elevated shadow-lg"
          data-testid={`booking-actions-menu-${booking.id}`}
        >
          {actions.map((target) => (
            <button
              key={target}
              role="menuitem"
              type="button"
              onClick={() => {
                setOpen(false);
                onAction(booking, target);
              }}
              data-testid={`booking-action-${target}-${booking.id}`}
              className={clsx(
                'block w-full px-3 py-2 text-left text-xs hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none',
                target === 'cancelled' && 'text-semantic-error',
              )}
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
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Charges tab ─────────────────────────────────────────────────────── */

/**
 * Operator-friendly charges view:
 *   1. List active bookings as a left-rail picker (instead of asking the
 *      user to paste a booking UUID — that was unusable).
 *   2. When a booking is selected, fetch its detail and render the
 *      charge list inline with an "Add charge" CTA.
 *   3. Empty state when there are no bookings (no charges possible).
 */
function ChargesTab({ data }: { data: AccommodationDetail }) {
  const { t } = useTranslation();

  // We need at least one room+booking pair to add a charge. Pull a wide
  // booking list so even checked-out stays can have catch-up charges.
  const bookingsQuery = useQuery({
    queryKey: ['accommodation', 'bookings', data.id, 'all-for-charges'],
    queryFn: () => listAccommodationBookings(data.id, { limit: 200 }),
    enabled: data.rooms.length > 0,
  });
  const bookings = bookingsQuery.data?.items ?? [];

  const [selectedBookingId, setSelectedBookingId] = useState<string | null>(
    null,
  );

  // Auto-select first booking on first non-empty load so the panel
  // shows something useful immediately.
  useEffect(() => {
    if (!selectedBookingId && bookings.length > 0) {
      setSelectedBookingId(bookings[0]!.id);
    }
  }, [bookings, selectedBookingId]);

  if (data.rooms.length === 0) {
    return (
      <div data-testid="accommodation-tab-panel-charges">
        <EmptyState
          icon={<Receipt size={22} aria-hidden="true" />}
          title={t('accommodation.charges.no_rooms_title', {
            defaultValue: 'No charges without rooms',
          })}
          description={t('accommodation.charges.no_rooms_desc', {
            defaultValue:
              'Charges belong to bookings, and bookings belong to rooms. Add rooms first to start billing.',
          })}
        />
      </div>
    );
  }

  if (bookingsQuery.isLoading) {
    return (
      <div data-testid="accommodation-tab-panel-charges">
        <SkeletonTable rows={3} columns={3} />
      </div>
    );
  }

  if (bookingsQuery.isError) {
    return (
      <div data-testid="accommodation-tab-panel-charges">
        <RecoveryCard
          error={bookingsQuery.error}
          onRetry={() => bookingsQuery.refetch()}
        />
      </div>
    );
  }

  if (bookings.length === 0) {
    return (
      <div data-testid="accommodation-tab-panel-charges">
        <EmptyState
          icon={<Receipt size={22} aria-hidden="true" />}
          title={t('accommodation.charges.no_bookings_title', {
            defaultValue: 'No bookings to charge yet',
          })}
          description={t('accommodation.charges.no_bookings_desc', {
            defaultValue:
              'Create a booking from the Occupancy tab - charges (base rent, extras, deposits, refunds) appear here once a stay exists.',
          })}
        />
      </div>
    );
  }

  return (
    <div
      data-testid="accommodation-tab-panel-charges"
      className="grid grid-cols-1 md:grid-cols-[260px_minmax(0,1fr)] gap-4"
    >
      {/* Booking picker rail */}
      <Card padding="none">
        <div className="p-3 border-b border-border-light">
          <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('accommodation.charges.picker_title', {
              defaultValue: 'Pick a booking',
            })}
          </div>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {t('accommodation.charges.picker_hint', {
              defaultValue: 'Charges are scoped to one booking at a time.',
            })}
          </p>
        </div>
        <ul
          role="listbox"
          aria-label={t('accommodation.charges.picker_aria', {
            defaultValue: 'Bookings',
          })}
          className="max-h-[420px] overflow-y-auto"
          data-testid="charges-booking-picker"
        >
          {bookings.map((b) => {
            const active = selectedBookingId === b.id;
            return (
              <li key={b.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => setSelectedBookingId(b.id)}
                  data-testid={`charges-pick-booking-${b.id}`}
                  className={clsx(
                    'w-full px-3 py-2.5 text-left text-xs transition border-l-2 min-h-[56px]',
                    active
                      ? 'border-oe-blue bg-oe-blue/5'
                      : 'border-transparent hover:bg-surface-secondary/40',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-2xs font-semibold">
                      {b.room_label ?? '—'}
                    </span>
                    <span
                      className={clsx(
                        'inline-flex items-center rounded-md border px-1.5 py-0 text-[10px] font-semibold',
                        BOOKING_STATUS_BADGE[b.status],
                      )}
                    >
                      {t(`accommodation.booking.status.${b.status}`, {
                        defaultValue: b.status,
                      })}
                    </span>
                  </div>
                  <div className="mt-1 truncate text-sm font-medium text-content-primary">
                    {b.occupant_name ||
                      t('accommodation.bookings.unnamed_occupant', {
                        defaultValue: '(unnamed)',
                      })}
                  </div>
                  <div className="text-2xs text-content-tertiary tabular-nums">
                    {b.check_in} {'→'} {b.check_out ?? '∞'}
                  </div>
                  {/* occupant deep link lives in the panel header to keep
                      the rail button a single click target */}
                </button>
              </li>
            );
          })}
        </ul>
      </Card>

      {/* Selected booking — charges list + add */}
      {selectedBookingId ? (
        <BookingChargesPanel
          accommodationId={data.id}
          projectId={data.project_id}
          bookingId={selectedBookingId}
        />
      ) : (
        <Card>
          <EmptyState
            icon={<Receipt size={22} aria-hidden="true" />}
            title={t('accommodation.charges.pick_one_title', {
              defaultValue: 'Pick a booking to see its charges',
            })}
            description={t('accommodation.charges.pick_one_desc', {
              defaultValue:
                'Select any booking on the left to view billed items, add an extra charge, or chase pending invoices.',
            })}
          />
        </Card>
      )}
    </div>
  );
}

function BookingChargesPanel({
  accommodationId,
  projectId,
  bookingId,
}: {
  accommodationId: string;
  projectId: string;
  bookingId: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [editorOpen, setEditorOpen] = useState(false);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Finance deep link for this accommodation's project. Charges are not
  // FK-linked to a specific invoice row on the backend (the charge only
  // carries a status enum), so we route to the project's Finance invoices
  // register rather than faking a per-invoice id. From there the operator
  // raises the invoice (pending charges) or finds the issued one
  // (invoiced / paid charges).
  const financeInvoicesPath = projectId
    ? `/projects/${projectId}/finance?tab=invoices`
    : '/finance?tab=invoices';

  const bookingDetail = useQuery({
    queryKey: ['accommodation', 'booking-detail', bookingId],
    queryFn: () => getBooking(bookingId),
  });

  if (bookingDetail.isLoading) {
    return <SkeletonTable rows={3} columns={3} />;
  }
  if (bookingDetail.isError || !bookingDetail.data) {
    return (
      <RecoveryCard
        error={bookingDetail.error}
        onRetry={() => bookingDetail.refetch()}
      />
    );
  }

  const data = bookingDetail.data;
  const charges = data.charges;

  return (
    <Card padding="none" data-testid="charges-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border-light p-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-content-primary truncate">
            <OccupantRef
              contactId={data.occupant_contact_id}
              name={data.occupant_name}
            />
          </div>
          <div className="text-2xs text-content-tertiary tabular-nums">
            {data.check_in} {'→'} {data.check_out ?? '∞'}
          </div>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => setEditorOpen(true)}
          data-testid="charges-add-button"
        >
          <Plus size={12} className="mr-1" aria-hidden="true" />
          {t('accommodation.charges.add', { defaultValue: 'Add charge' })}
        </Button>
      </div>

      {charges.length === 0 ? (
        <div className="p-2">
          <EmptyState
            icon={<Receipt size={20} aria-hidden="true" />}
            title={t('accommodation.charges.empty_title', {
              defaultValue: 'No charges on this booking yet',
            })}
            description={t('accommodation.charges.empty_desc', {
              defaultValue:
                'Add base rent for the stay or one-off extras (cleaning, damage, deposit). Amounts stay exact through to billing.',
            })}
            action={{
              label: t('accommodation.charges.add', {
                defaultValue: 'Add charge',
              }),
              onClick: () => setEditorOpen(true),
            }}
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm" data-testid="charges-table">
            <thead className="bg-surface-secondary/60 text-left text-xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-3 py-2 font-medium">
                  {t('accommodation.charges.kind', { defaultValue: 'Kind' })}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('accommodation.charges.description', {
                    defaultValue: 'Description',
                  })}
                </th>
                <th className="px-3 py-2 font-medium text-right">
                  {t('accommodation.charges.amount', {
                    defaultValue: 'Amount',
                  })}
                </th>
                <th className="px-3 py-2 font-medium">
                  {t('accommodation.charges.status_col', {
                    defaultValue: 'Status',
                  })}
                </th>
                <th className="px-3 py-2 font-medium text-right">
                  <span className="sr-only">{t('common.actions')}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {charges.map((c) => (
                <tr
                  key={c.id}
                  data-testid={`charge-row-${c.id}`}
                  className="hover:bg-surface-secondary/30"
                >
                  <td className="px-3 py-2 text-xs">
                    {t(`accommodation.charge.kind.${c.kind}`, {
                      defaultValue: c.kind,
                    })}
                  </td>
                  <td className="px-3 py-2 text-xs text-content-secondary">
                    {c.description || '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-mono text-xs">
                    {c.amount}{' '}
                    <span className="text-content-tertiary">{c.currency}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={clsx(
                        'inline-flex items-center rounded-md border px-1.5 py-0.5 text-2xs font-semibold',
                        CHARGE_STATUS_BADGE[c.status],
                      )}
                    >
                      {t(`accommodation.charge.status.${c.status}`, {
                        defaultValue: c.status,
                      })}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {c.status === 'pending' ? (
                      <button
                        type="button"
                        onClick={() => navigate(financeInvoicesPath)}
                        data-testid={`charge-invoice-${c.id}`}
                        className="inline-flex items-center gap-1 rounded-md border border-oe-blue/30 bg-oe-blue/5 px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10"
                        title={t('accommodation.charges.invoice_hint', {
                          defaultValue:
                            'Raise this charge as an invoice in Finance.',
                        })}
                      >
                        <Wallet size={11} aria-hidden="true" />
                        {t('accommodation.charges.invoice_in_finance', {
                          defaultValue: 'Invoice in Finance',
                        })}
                      </button>
                    ) : c.status === 'invoiced' || c.status === 'paid' ? (
                      <button
                        type="button"
                        onClick={() => navigate(financeInvoicesPath)}
                        data-testid={`charge-view-invoice-${c.id}`}
                        className="inline-flex items-center gap-1 text-2xs font-medium text-oe-blue hover:underline"
                        title={t('accommodation.charges.view_invoice_hint', {
                          defaultValue: 'Open the Finance invoices register.',
                        })}
                      >
                        <FileText size={11} aria-hidden="true" />
                        {t('accommodation.charges.view_invoice', {
                          defaultValue: 'View in Finance',
                        })}
                      </button>
                    ) : (
                      <span className="text-2xs text-content-tertiary">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editorOpen && (
        <AddChargeModal
          bookingId={bookingId}
          onClose={() => setEditorOpen(false)}
          onCreated={() => {
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'booking-detail', bookingId],
            });
            queryClient.invalidateQueries({
              queryKey: ['accommodation', 'bookings', accommodationId],
            });
            addToast({
              type: 'success',
              title: t('accommodation.charges.created_toast', {
                defaultValue: 'Charge created',
              }),
            });
            setEditorOpen(false);
          }}
        />
      )}
    </Card>
  );
}

function AddChargeModal({
  bookingId,
  onClose,
  onCreated,
}: {
  bookingId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [kind, setKind] = useState<ChargeKind>('extra');
  const [description, setDescription] = useState('');
  /** Decimal as string — never parseFloat. */
  const [amount, setAmount] = useState('0');
  const [currency, setCurrency] = useState('');
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');

  const mutation = useMutation({
    mutationFn: () =>
      createCharge(bookingId, {
        kind,
        description: description.trim() || null,
        amount: amount.trim(),
        currency: currency.trim() || '',
        period_start: periodStart || null,
        period_end: periodEnd || null,
        status: 'pending',
      }),
    onSuccess: () => onCreated(),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('accommodation.charges.create_failed', {
          defaultValue: 'Could not create charge',
        }),
        message: getErrorMessage(err),
      }),
  });

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  // Amount must be a non-negative decimal expressed as a string. We do
  // not call parseFloat() — instead we validate via a regex so values
  // like "199.99" stay exact through to the backend Decimal.
  const amountValid = /^\d+(?:\.\d+)?$/.test(amount.trim());

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('accommodation.charges.modal_title', {
        defaultValue: 'Add charge',
      })}
      size="md"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={!amountValid}
            data-testid="charge-submit"
          >
            {t('common.create')}
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('accommodation.charges.kind', { defaultValue: 'Kind' })}
          required
        >
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as ChargeKind)}
            className={inputCls}
            data-testid="charge-kind"
          >
            {(['base_rent', 'extra', 'deposit', 'refund'] as const).map((k) => (
              <option key={k} value={k}>
                {t(`accommodation.charge.kind.${k}`, { defaultValue: k })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('accommodation.charges.amount', { defaultValue: 'Amount' })}
          required
          hint={t('accommodation.charges.amount_hint', {
            defaultValue: 'Decimal - e.g. 199.99. Stays exact through to billing.',
          })}
          error={
            !amountValid
              ? t('accommodation.charges.amount_invalid', {
                  defaultValue: 'Enter a non-negative decimal.',
                })
              : undefined
          }
        >
          <input
            type="text"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className={inputCls}
            data-testid="charge-amount"
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.charges.currency', {
            defaultValue: 'Currency (ISO 4217)',
          })}
          hint={t('accommodation.charges.currency_hint', {
            defaultValue: 'Empty → inherit from room / project.',
          })}
        >
          <input
            type="text"
            maxLength={3}
            value={currency}
            onChange={(e) =>
              setCurrency(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))
            }
            className={`${inputCls} font-mono uppercase`}
            data-testid="charge-currency"
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.charges.period_start', {
            defaultValue: 'Period start',
          })}
        >
          <input
            type="date"
            value={periodStart}
            onChange={(e) => setPeriodStart(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.charges.period_end', {
            defaultValue: 'Period end',
          })}
        >
          <input
            type="date"
            value={periodEnd}
            onChange={(e) => setPeriodEnd(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.charges.description', {
            defaultValue: 'Description',
          })}
          span={2}
        >
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className={inputCls}
            data-testid="charge-description"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Cross-module pickers (replace raw UUID inputs) ──────────────────── */

const PICKER_INPUT_CLS =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/**
 * BIM model picker — replaces the raw "Linked BIM model id" text input.
 *
 * Lists the project's BIM models so the operator selects by name instead
 * of pasting a UUID. If the currently-saved id is no longer in the
 * project's model list (deleted / cross-project legacy value), it is
 * preserved as a "kept" option so saving the form does not silently drop
 * it. Falls back to a plain text input when the model list cannot be
 * loaded so the field never becomes unusable.
 */
function BimModelPicker({
  projectId,
  value,
  onChange,
}: {
  projectId: string;
  value: string;
  onChange: (next: string) => void;
}) {
  const { t } = useTranslation();
  const modelsQuery = useQuery({
    queryKey: ['accommodation', 'bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  if (modelsQuery.isError) {
    // Degrade gracefully — keep the value editable as text.
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${PICKER_INPUT_CLS} font-mono`}
        data-testid="accommodation-bim-model-input"
        placeholder={t('accommodation.field.bim_model_id', {
          defaultValue: 'Linked BIM model id',
        })}
      />
    );
  }

  const models = modelsQuery.data?.items ?? [];
  const known = value && models.some((m) => m.id === value);

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={PICKER_INPUT_CLS}
      data-testid="accommodation-bim-model-select"
      disabled={modelsQuery.isLoading}
    >
      <option value="">
        {modelsQuery.isLoading
          ? t('common.loading', { defaultValue: 'Loading…' })
          : t('accommodation.bim_picker.none', {
              defaultValue: 'No linked model',
            })}
      </option>
      {/* Preserve a previously-saved id that is no longer in the list so
          the user does not lose it just by opening the form. */}
      {value && !known && (
        <option value={value}>
          {t('accommodation.bim_picker.kept', {
            defaultValue: 'Current link ({{id}})',
            id: value.slice(0, 8),
          })}
        </option>
      )}
      {models.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name || m.filename || m.id.slice(0, 8)}
        </option>
      ))}
    </select>
  );
}

/**
 * PropDev block picker — replaces the raw "PropDev block UUID" input.
 *
 * A block lives under a phase, which lives under a development, so the
 * picker cascades Development → Phase → Block. On mount it seeds the
 * cascade from the currently-saved block id where possible (best effort:
 * we can only resolve the parents by walking the lists). Selecting a
 * block reports its id up; clearing the development clears the block.
 *
 * Falls back to a plain text input if developments cannot be loaded.
 */
function PropDevBlockPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const { t } = useTranslation();
  const [devId, setDevId] = useState('');
  const [phaseId, setPhaseId] = useState('');

  const developmentsQuery = useQuery({
    queryKey: ['accommodation', 'propdev-developments'],
    queryFn: () => listDevelopments({ limit: 100 }),
    staleTime: 30_000,
  });
  const phasesQuery = useQuery({
    queryKey: ['accommodation', 'propdev-phases', devId],
    queryFn: () => listPhases(devId),
    enabled: !!devId,
  });
  const blocksQuery = useQuery({
    queryKey: ['accommodation', 'propdev-blocks', phaseId],
    queryFn: () => listBlocks(phaseId),
    enabled: !!phaseId,
  });

  if (developmentsQuery.isError) {
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${PICKER_INPUT_CLS} font-mono`}
        data-testid="accommodation-block-input"
        placeholder={t('accommodation.bootstrap.block_id', {
          defaultValue: 'PropDev block UUID',
        })}
      />
    );
  }

  const developments = developmentsQuery.data ?? [];
  const phases = phasesQuery.data ?? [];
  const blocks = blocksQuery.data ?? [];

  return (
    <div className="space-y-2" data-testid="accommodation-block-picker">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <select
          value={devId}
          onChange={(e) => {
            setDevId(e.target.value);
            setPhaseId('');
            onChange('');
          }}
          className={PICKER_INPUT_CLS}
          data-testid="accommodation-block-dev-select"
          disabled={developmentsQuery.isLoading}
          aria-label={t('propdev.developments', {
            defaultValue: 'Developments',
          })}
        >
          <option value="">
            {t('accommodation.block_picker.pick_development', {
              defaultValue: 'Development…',
            })}
          </option>
          {developments.map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} - {d.name}
            </option>
          ))}
        </select>
        <select
          value={phaseId}
          onChange={(e) => {
            setPhaseId(e.target.value);
            onChange('');
          }}
          className={PICKER_INPUT_CLS}
          data-testid="accommodation-block-phase-select"
          disabled={!devId || phasesQuery.isLoading}
          aria-label={t('propdev.phases', { defaultValue: 'Phases' })}
        >
          <option value="">
            {t('accommodation.block_picker.pick_phase', {
              defaultValue: 'Phase…',
            })}
          </option>
          {phases.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} - {p.name}
            </option>
          ))}
        </select>
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={PICKER_INPUT_CLS}
          data-testid="accommodation-block-block-select"
          disabled={!phaseId || blocksQuery.isLoading}
          aria-label={t('propdev.blocks', { defaultValue: 'Blocks' })}
        >
          <option value="">
            {t('accommodation.block_picker.pick_block', {
              defaultValue: 'Block…',
            })}
          </option>
          {value && !blocks.some((b) => b.id === value) && (
            <option value={value}>
              {t('accommodation.block_picker.kept', {
                defaultValue: 'Current block ({{id}})',
                id: value.slice(0, 8),
              })}
            </option>
          )}
          {blocks.map((b) => (
            <option key={b.id} value={b.id}>
              {b.code} - {b.name}
            </option>
          ))}
        </select>
      </div>
      {value && (
        <p className="text-2xs text-content-tertiary">
          {t('accommodation.block_picker.selected', {
            defaultValue: 'Selected block: {{id}}',
            id: value,
          })}
        </p>
      )}
    </div>
  );
}

/* ── Settings tab ────────────────────────────────────────────────────── */

function SettingsTab({
  data,
  onDeleted,
}: {
  data: AccommodationDetail;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [name, setName] = useState(data.name);
  const [address, setAddress] = useState(data.address ?? '');
  const [geoLat, setGeoLat] = useState(data.geo_lat ?? '');
  const [geoLon, setGeoLon] = useState(data.geo_lon ?? '');
  const [bimModelId, setBimModelId] = useState(data.bim_model_id ?? '');
  const [notes, setNotes] = useState(data.notes ?? '');
  const [blockId, setBlockId] = useState(data.property_dev_block_id ?? '');
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  // Keep form in sync if the query refetches.
  useEffect(() => {
    setName(data.name);
    setAddress(data.address ?? '');
    setGeoLat(data.geo_lat ?? '');
    setGeoLon(data.geo_lon ?? '');
    setBimModelId(data.bim_model_id ?? '');
    setNotes(data.notes ?? '');
    setBlockId(data.property_dev_block_id ?? '');
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: () =>
      updateAccommodation(data.id, {
        name,
        address: address.trim() || null,
        // Coords stay as strings to preserve precision; backend
        // accepts string → Decimal. Empty strings → null.
        geo_lat: geoLat.trim() || null,
        geo_lon: geoLon.trim() || null,
        bim_model_id: bimModelId.trim() || null,
        property_dev_block_id: blockId.trim() || null,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accommodation'] });
      addToast({
        type: 'success',
        title: t('accommodation.settings.saved', {
          defaultValue: 'Settings saved',
        }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('accommodation.settings.save_failed', {
          defaultValue: 'Could not save settings',
        }),
        message: getErrorMessage(err),
      }),
  });

  const bootstrapMutation = useMutation({
    mutationFn: () => bootstrapFromPropDev(data.id, blockId.trim()),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['accommodation'] });
      addToast({
        type: 'success',
        title: t('accommodation.bootstrap.toast', {
          defaultValue: 'Imported {{created}} rooms (skipped {{skipped}}).',
          created: result.rooms_created,
          skipped: result.rooms_skipped,
        }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('accommodation.bootstrap.failed', {
          defaultValue: 'Bootstrap failed',
        }),
        message: getErrorMessage(err),
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteAccommodation(data.id),
    onSuccess: onDeleted,
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('accommodation.delete.failed', {
          defaultValue: 'Delete failed',
        }),
        message: getErrorMessage(err),
      }),
  });

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <div
      data-testid="accommodation-tab-panel-settings"
      className="space-y-4"
    >
      <Card>
        <div className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-content-primary">
              {t('accommodation.settings.general', { defaultValue: 'General' })}
            </h2>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('accommodation.settings.general_hint', {
                defaultValue:
                  'Core metadata - name, address and links to the BIM model / Geo Hub coordinates that power the right-rail shortcuts.',
              })}
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-xs font-medium text-content-primary">
              {t('accommodation.field.name', { defaultValue: 'Name' })}
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={`${inputCls} mt-1`}
              />
            </label>
            <label className="text-xs font-medium text-content-primary">
              {t('accommodation.field.address', { defaultValue: 'Address' })}
              <input
                type="text"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                className={`${inputCls} mt-1`}
              />
            </label>
            <label className="text-xs font-medium text-content-primary">
              {t('accommodation.field.geo_lat', {
                defaultValue: 'Latitude (decimal)',
              })}
              <input
                type="text"
                inputMode="decimal"
                value={geoLat}
                onChange={(e) => setGeoLat(e.target.value)}
                className={`${inputCls} mt-1`}
                placeholder="-90 to 90"
              />
            </label>
            <label className="text-xs font-medium text-content-primary">
              {t('accommodation.field.geo_lon', {
                defaultValue: 'Longitude (decimal)',
              })}
              <input
                type="text"
                inputMode="decimal"
                value={geoLon}
                onChange={(e) => setGeoLon(e.target.value)}
                className={`${inputCls} mt-1`}
                placeholder="-180 to 180"
              />
            </label>
            <div className="text-xs font-medium text-content-primary sm:col-span-2">
              <label htmlFor="accommodation-bim-model" className="block">
                {t('accommodation.field.bim_model', {
                  defaultValue: 'Linked BIM model',
                })}
              </label>
              <div className="mt-1" id="accommodation-bim-model">
                <BimModelPicker
                  projectId={data.project_id}
                  value={bimModelId}
                  onChange={setBimModelId}
                />
              </div>
            </div>
            <label className="text-xs font-medium text-content-primary sm:col-span-2">
              {t('accommodation.field.notes', { defaultValue: 'Notes' })}
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-lg border border-border bg-surface-primary p-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </label>
          </div>
          <div className="flex justify-end border-t border-border-light pt-3">
            <Button
              variant="primary"
              size="sm"
              onClick={() => saveMutation.mutate()}
              loading={saveMutation.isPending}
              data-testid="accommodation-settings-save"
            >
              {t('common.save', { defaultValue: 'Save changes' })}
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <div className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-content-primary">
              {t('accommodation.bootstrap.from_propdev', {
                defaultValue: 'Bootstrap from PropDev block',
              })}
            </h2>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('accommodation.bootstrap.idempotent_note', {
                defaultValue:
                  "Idempotent: re-running won't duplicate rooms. Each PropDev plot becomes a Room labelled with its plot number.",
              })}
            </p>
          </div>
          <div className="space-y-2">
            <div className="text-xs font-medium text-content-primary">
              {t('accommodation.bootstrap.block_label', {
                defaultValue: 'PropDev block',
              })}
              <div className="mt-1">
                <PropDevBlockPicker value={blockId} onChange={setBlockId} />
              </div>
            </div>
            <div className="flex justify-end">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => bootstrapMutation.mutate()}
                loading={bootstrapMutation.isPending}
                disabled={!blockId.trim()}
                data-testid="accommodation-bootstrap-run"
              >
                {t('accommodation.bootstrap.run', { defaultValue: 'Bootstrap' })}
              </Button>
            </div>
          </div>
        </div>
      </Card>

      <Card className="border-semantic-error/30">
        <div className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-semantic-error">
              {t('accommodation.settings.danger_zone', {
                defaultValue: 'Danger zone',
              })}
            </h2>
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('accommodation.delete.warning', {
                defaultValue:
                  'Soft-delete removes this accommodation from active views. Audit history is preserved.',
              })}
            </p>
          </div>
          <div>
            <Button
              variant="danger"
              size="sm"
              onClick={() => setConfirmDeleteOpen(true)}
              data-testid="accommodation-delete-button"
            >
              <Trash2 size={13} className="mr-1.5" aria-hidden="true" />
              {t('accommodation.delete.cta', {
                defaultValue: 'Delete accommodation',
              })}
            </Button>
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmDeleteOpen}
        onCancel={() => setConfirmDeleteOpen(false)}
        onConfirm={() => {
          setConfirmDeleteOpen(false);
          deleteMutation.mutate();
        }}
        title={t('accommodation.confirm.delete', {
          defaultValue: 'Delete accommodation?',
        })}
        message={t('accommodation.confirm.delete_message', {
          defaultValue:
            'This soft-deletes the accommodation. Rooms, bookings and charges remain available for audit.',
        })}
        confirmLabel={t('accommodation.delete.cta', {
          defaultValue: 'Delete accommodation',
        })}
        loading={deleteMutation.isPending}
        variant="danger"
      />
    </div>
  );
}

/* ── Booking state-machine helper used by BookingsTab in future iter ─ */
// Currently unused but exported so child components can call into the
// state-machine without importing from api.ts directly.
export function nextBookingActions(b: Booking): BookingStatus[] {
  if (isBookingTerminal(b.status)) return [];
  return allowedBookingTransitions(b.status);
}
