/**
 * AccommodationListPage — /accommodation
 *
 * Cards grid of accommodations grouped by kind (tabs: All / Worker camps /
 * Rentals / Hotels). Each card shows name, kind badge, project, capacity
 * with occupied/total, top-right "Open" + "Geo" overlay buttons. Includes
 * the create-accommodation WideModal and the HR-autobook trigger.
 *
 * Polish wave: summary KPI strip, RecoveryCard for fetch errors, warm
 * EmptyState pattern, hoverable Cards via the shared Card variant, mobile
 * bottom-anchored "New accommodation" FAB.
 */

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Building2,
  Plus,
  Hotel,
  Tent,
  Home,
  Globe2,
  ArrowRight,
  Sparkles,
  Users,
  CalendarCheck2,
  BedDouble,
  Filter,
  X,
} from 'lucide-react';

import {
  Card,
  Badge,
  BetaBanner,
  Button,
  DismissibleInfo,
  IntroRichText,
  EmptyState,
  RecoveryCard,
  Breadcrumb,
  ModuleHelpButton,
  SkeletonGrid,
} from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { projectsApi } from '@/features/projects/api';
import { getErrorMessage } from '@/shared/lib/api';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

import {
  listAccommodations,
  createAccommodation,
  type Accommodation,
  type AccommodationKind,
} from './api';
import { HrAutobookModal } from './HrAutobookModal';

type KindFilter = 'all' | AccommodationKind;

const KIND_ICON: Record<AccommodationKind, typeof Building2> = {
  worker_camp: Tent,
  rental: Home,
  hotel: Hotel,
};

const KIND_VARIANT: Record<AccommodationKind, 'blue' | 'success' | 'warning'> =
  {
    worker_camp: 'warning',
    rental: 'blue',
    hotel: 'success',
  };

export function AccommodationListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [filter, setFilter] = useState<KindFilter>('all');
  // Arrow-key navigation across the kind-filter tabs (WCAG 2.1.1).
  const onAccommodationTabKeyDown = useTabKeyboardNav<KindFilter>({
    ids: ['all', 'worker_camp', 'rental', 'hotel'] as const,
    activeId: filter,
    onChange: setFilter,
    orientation: 'horizontal',
  });
  const [createOpen, setCreateOpen] = useState(false);
  const [hrAutobookOpen, setHrAutobookOpen] = useState(false);

  const accommodationsQuery = useQuery({
    queryKey: ['accommodation', 'list'],
    queryFn: () => listAccommodations({ limit: 200 }),
  });
  const accommodations = accommodationsQuery.data ?? [];
  const isLoading = accommodationsQuery.isLoading;

  const { data: projects = [] } = useQuery({
    queryKey: ['projects', 'list'],
    queryFn: () => projectsApi.list(),
    staleTime: 60_000,
  });

  // Build a id→name lookup for project names on each card.
  const projectNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of projects) map.set(p.id, p.name);
    return map;
  }, [projects]);

  // Deep link: /accommodation?block=<blockId> (worker housing for a Property
  // Development block). The accommodation row carries property_dev_block_id,
  // so we filter the grid to that block client-side. A banner explains the
  // active scope and offers a one-click clear that drops the param.
  const [searchParams, setSearchParams] = useSearchParams();
  const blockFilter = searchParams.get('block');
  const clearBlockFilter = () => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('block');
        return next;
      },
      { replace: true },
    );
  };

  const filtered = useMemo(() => {
    let list = accommodations;
    if (blockFilter) {
      list = list.filter((a) => a.property_dev_block_id === blockFilter);
    }
    if (filter !== 'all') {
      list = list.filter((a) => a.kind === filter);
    }
    return list;
  }, [accommodations, filter, blockFilter]);

  // Counts per tab for the badges.
  const counts = useMemo(() => {
    const c: Record<KindFilter, number> = {
      all: accommodations.length,
      worker_camp: 0,
      rental: 0,
      hotel: 0,
    };
    for (const a of accommodations) {
      const k = a.kind;
      if (k === 'worker_camp' || k === 'rental' || k === 'hotel') {
        c[k] += 1;
      }
    }
    return c;
  }, [accommodations]);

  // Header-level KPIs — derived once per data refresh. Keeps the
  // operator oriented without forcing them into the calendar.
  const summary = useMemo(() => {
    let capacity = 0;
    for (const a of accommodations) capacity += a.capacity_total;
    return {
      properties: accommodations.length,
      capacity,
      worker_camps: counts.worker_camp,
      rentals: counts.rental,
      hotels: counts.hotel,
    };
  }, [accommodations, counts]);

  return (
    <div className="space-y-5 pb-20 sm:pb-0 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.accommodation', { defaultValue: 'Accommodation' }) }]} />

      {/* Header */}
      <PageHeader
        srTitle={t('accommodation.title', { defaultValue: 'Accommodation' })}
        subtitle={t('accommodation.subtitle', {
          defaultValue:
            'Worker camps, rentals and hotels - rooms, bookings and charges in one place. Bridges to PropDev units and HR contacts.',
        })}
        actions={
          <>
            <ModuleHelpButton tourId="accommodation" />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setHrAutobookOpen(true)}
              data-testid="accommodation-hr-autobook-button"
            >
              <Sparkles size={14} className="mr-1.5" aria-hidden="true" />
              {t('accommodation.hr_autobook.suggest_button', {
                defaultValue: 'Suggest room for employee',
              })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate('/accommodation/calendar')}
              data-testid="accommodation-calendar-link"
            >
              <CalendarCheck2 size={14} className="mr-1.5" aria-hidden="true" />
              {t('accommodation.calendar.title', { defaultValue: 'Calendar' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setCreateOpen(true)}
              data-testid="accommodation-new-button"
              className="hidden sm:inline-flex"
            >
              <Plus size={14} className="mr-1.5" aria-hidden="true" />
              {t('accommodation.new', { defaultValue: 'New accommodation' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="accommodation"
        title={t('accommodation.intro_title', {
          defaultValue: 'House the workforce without losing track',
        })}
        more={
          t('accommodation.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('accommodation.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('accommodation.intro_link_calendar', { defaultValue: 'Calendar' }),
            onClick: () => navigate('/accommodation/calendar'),
          },
          {
            label: t('accommodation.intro_link_contacts', { defaultValue: 'Contacts' }),
            onClick: () => navigate('/contacts'),
          },
        ]}
      >
        {t('accommodation.intro_body', {
          defaultValue:
            'Track three kinds of stays in one place: worker camps for site crews, rentals for staff, and hotels for visiting consultants. Each property holds rooms, bookings and charges, and the calendar shows who is where across every date. Suggest a room for an employee to bridge directly from HR contacts into a booking.',
        })}
      </DismissibleInfo>

      <BetaBanner moduleKey="accommodation" />

      {/* Summary KPI strip — collapses to a 2-col grid on phones,
          stretches to 4-col on desktop. Mute when nothing exists yet. */}
      {accommodations.length > 0 && (
        <div
          data-testid="accommodation-summary-strip"
          className="grid grid-cols-2 sm:grid-cols-4 gap-2"
        >
          <SummaryTile
            icon={<Building2 size={16} aria-hidden="true" />}
            label={t('accommodation.summary.properties', {
              defaultValue: 'Properties',
            })}
            value={summary.properties}
          />
          <SummaryTile
            icon={<Users size={16} aria-hidden="true" />}
            label={t('accommodation.summary.capacity', {
              defaultValue: 'Total capacity',
            })}
            value={summary.capacity}
          />
          <SummaryTile
            icon={<Tent size={16} aria-hidden="true" />}
            label={t('accommodation.kind.worker_camps', {
              defaultValue: 'Worker camps',
            })}
            value={summary.worker_camps}
          />
          <SummaryTile
            icon={<Hotel size={16} aria-hidden="true" />}
            label={t('accommodation.summary.rentals_hotels', {
              defaultValue: 'Rentals + Hotels',
            })}
            value={summary.rentals + summary.hotels}
          />
        </div>
      )}

      {/* Block deep-link scope banner — shown when arriving from a Property
          Development block. Tells the user the grid is filtered and lets them
          drop back to the full list. */}
      {blockFilter && (
        <div
          data-testid="accommodation-block-filter-banner"
          className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-oe-blue/30 bg-oe-blue/5 px-4 py-2.5"
        >
          <span className="inline-flex items-center gap-2 text-sm text-content-secondary">
            <Filter size={14} className="text-oe-blue" aria-hidden="true" />
            {t('accommodation.block_filter.active', {
              defaultValue:
                'Showing worker housing linked to the selected development block ({{count}}).',
              count: filtered.length,
            })}
          </span>
          <button
            type="button"
            onClick={clearBlockFilter}
            data-testid="accommodation-block-filter-clear"
            className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-elevated px-2.5 py-1 text-2xs font-medium text-content-primary hover:bg-surface-secondary"
          >
            <X size={11} aria-hidden="true" />
            {t('accommodation.block_filter.clear', { defaultValue: 'Show all accommodations' })}
          </button>
        </div>
      )}

      {/* Tabs */}
      <div
        role="tablist"
        aria-label={t('accommodation.filter_by_kind', {
          defaultValue: 'Filter by kind',
        })}
        onKeyDown={onAccommodationTabKeyDown}
        className="flex flex-wrap gap-1 border-b border-border-light"
      >
        {(['all', 'worker_camp', 'rental', 'hotel'] as const).map((k) => {
          const isActive = filter === k;
          const label =
            k === 'all'
              ? t('accommodation.kind.all', { defaultValue: 'All' })
              : t(`accommodation.kind.${k}`, {
                  defaultValue:
                    k === 'worker_camp'
                      ? 'Worker camps'
                      : k === 'rental'
                        ? 'Rentals'
                        : 'Hotels',
                });
          return (
            <button
              key={k}
              role="tab"
              id={`accommodation-tab-${k}`}
              aria-selected={isActive}
              aria-controls="accommodation-tabpanel"
              tabIndex={isActive ? 0 : -1}
              type="button"
              onClick={() => setFilter(k)}
              data-testid={`accommodation-tab-${k}`}
              className={clsx(
                'flex min-h-[44px] items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors -mb-px',
                isActive
                  ? 'border-oe-blue text-content-primary'
                  : 'border-transparent text-content-tertiary hover:text-content-primary hover:border-border',
              )}
            >
              {label}
              <span
                className={clsx(
                  'rounded-full px-1.5 text-2xs tabular-nums',
                  isActive
                    ? 'bg-oe-blue/10 text-oe-blue'
                    : 'bg-surface-secondary text-content-tertiary',
                )}
              >
                {counts[k]}
              </span>
            </button>
          );
        })}
      </div>

      {/* Body */}
      <div
        id="accommodation-tabpanel"
        role="tabpanel"
        aria-labelledby={`accommodation-tab-${filter}`}
      >
      {isLoading ? (
        <SkeletonGrid items={6} />
      ) : accommodationsQuery.isError ? (
        <RecoveryCard
          error={accommodationsQuery.error}
          onRetry={() => accommodationsQuery.refetch()}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Building2 size={22} aria-hidden="true" />}
          title={
            accommodations.length === 0
              ? t('accommodation.empty_state.title', {
                  defaultValue: 'No accommodations yet',
                })
              : blockFilter
                ? t('accommodation.empty_block.title', {
                    defaultValue: 'No housing linked to this block',
                  })
                : t('accommodation.empty_filtered.title', {
                    defaultValue: 'No properties match this filter',
                  })
          }
          description={
            accommodations.length === 0
              ? t('accommodation.empty_state.description', {
                  defaultValue:
                    'Track three kinds of stays: worker camps for site crews, rentals for staff, and hotels for visiting consultants - each with rooms, bookings and charges.',
                })
              : blockFilter
                ? t('accommodation.empty_block.description', {
                    defaultValue:
                      'No accommodation is linked to this development block yet. Clear the filter to see all properties, or create one and link it from its settings.',
                  })
                : t('accommodation.empty_filtered.description', {
                    defaultValue:
                      'Try a different kind, or create a new property of this kind.',
                  })
          }
          action={
            blockFilter
              ? {
                  label: t('accommodation.block_filter.clear', {
                    defaultValue: 'Show all accommodations',
                  }),
                  onClick: clearBlockFilter,
                }
              : {
                  label: t('accommodation.new', { defaultValue: 'New accommodation' }),
                  onClick: () => setCreateOpen(true),
                }
          }
        />
      ) : (
        <div
          data-testid="accommodation-grid"
          className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4"
        >
          {filtered.map((a) => (
            <AccommodationCard
              key={a.id}
              a={a}
              projectName={projectNameById.get(a.project_id)}
              onOpen={() => navigate(`/accommodation/${a.id}`)}
            />
          ))}
        </div>
      )}
      </div>

      {/* Mobile floating action button — keeps "New accommodation" within
          thumb reach on small screens where the header button is hidden. */}
      <button
        type="button"
        onClick={() => setCreateOpen(true)}
        data-testid="accommodation-new-fab"
        aria-label={t('accommodation.new', {
          defaultValue: 'New accommodation',
        })}
        className="sm:hidden fixed bottom-4 right-4 z-40 inline-flex h-14 w-14 items-center justify-center rounded-full bg-oe-blue text-white shadow-lg hover:bg-oe-blue/90 active:scale-95 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2"
      >
        <Plus size={22} aria-hidden="true" />
      </button>

      {/* Create modal */}
      {createOpen && (
        <CreateAccommodationModal
          defaultProjectId={activeProjectId ?? ''}
          projects={projects.map((p) => ({ id: p.id, name: p.name }))}
          onClose={() => setCreateOpen(false)}
          onCreated={(a) => {
            addToast({
              type: 'success',
              title: t('accommodation.toast.created', {
                defaultValue: 'Accommodation created',
              }),
            });
            queryClient.invalidateQueries({ queryKey: ['accommodation'] });
            setCreateOpen(false);
            navigate(`/accommodation/${a.id}`);
          }}
        />
      )}

      {/* HR autobook modal — visible from this page only for the MVP */}
      {hrAutobookOpen && (
        <HrAutobookModal onClose={() => setHrAutobookOpen(false)} />
      )}
    </div>
  );
}

/* ── Summary tile ────────────────────────────────────────────────────── */

interface SummaryTileProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
}

function SummaryTile({ icon, label, value }: SummaryTileProps) {
  return (
    <div
      className="flex items-center gap-3 rounded-xl border border-border-light bg-surface-elevated px-3 py-2.5"
      data-testid="accommodation-summary-tile"
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-secondary">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-2xs uppercase tracking-wide text-content-tertiary truncate">
          {label}
        </div>
        <div className="text-base font-semibold text-content-primary tabular-nums">
          {value}
        </div>
      </div>
    </div>
  );
}

/* ── Card ────────────────────────────────────────────────────────────── */

function AccommodationCard({
  a,
  projectName,
  onOpen,
}: {
  a: Accommodation;
  projectName: string | undefined;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const Icon = KIND_ICON[a.kind];
  const hasGeo = a.geo_lat !== null && a.geo_lon !== null;

  return (
    <Card
      hoverable
      padding="none"
      className="relative cursor-pointer focus-within:ring-2 focus-within:ring-oe-blue/40"
      onClick={onOpen}
      data-testid={`accommodation-card-${a.id}`}
    >
      {/* Overlay buttons */}
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5">
        {hasGeo && (
          <Link
            to={`/geo?lat=${a.geo_lat}&lon=${a.geo_lon}`}
            onClick={(e) => e.stopPropagation()}
            aria-label={t('accommodation.geo.view_on_map', {
              defaultValue: 'View on map',
            })}
            title={t('accommodation.geo.view_on_map', {
              defaultValue: 'View on map',
            })}
            className="inline-flex min-h-[28px] items-center gap-1 rounded-full border border-border bg-surface-elevated px-2 py-1 text-2xs font-medium text-oe-blue shadow-sm hover:bg-oe-blue/5"
            data-testid="accommodation-card-geo-link"
          >
            <Globe2 size={11} aria-hidden="true" />
            {t('accommodation.geo.short', { defaultValue: 'Geo' })}
          </Link>
        )}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onOpen();
          }}
          aria-label={t('common.open', { defaultValue: 'Open' })}
          className="inline-flex min-h-[28px] items-center gap-1 rounded-full border border-border bg-surface-elevated px-2 py-1 text-2xs font-medium text-content-primary shadow-sm hover:bg-surface-secondary"
        >
          {t('common.open', { defaultValue: 'Open' })}
          <ArrowRight size={11} aria-hidden="true" />
        </button>
      </div>

      <div className="p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
            <Icon size={18} aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1 pr-20">
            <h3 className="truncate text-base font-semibold text-content-primary">
              {a.name || t('common.unnamed', { defaultValue: '(unnamed)' })}
            </h3>
            <p className="mt-0.5 text-xs text-content-tertiary truncate">
              {projectName ?? t('accommodation.unknown_project', { defaultValue: 'Unknown project' })}
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          <Badge variant={KIND_VARIANT[a.kind]} size="sm">
            {t(`accommodation.kind.${a.kind}`, {
              defaultValue:
                a.kind === 'worker_camp'
                  ? 'Worker camp'
                  : a.kind === 'rental'
                    ? 'Rental'
                    : 'Hotel',
            })}
          </Badge>
          <span className="inline-flex items-center gap-1 text-content-secondary">
            <BedDouble size={12} aria-hidden="true" />
            {t('accommodation.capacity.label', {
              defaultValue: '{{count}} cap.',
              count: a.capacity_total,
            })}
          </span>
        </div>

        {a.address && (
          <p className="mt-3 text-xs text-content-tertiary line-clamp-2">
            {a.address}
          </p>
        )}
      </div>
    </Card>
  );
}

/* ── Create modal ────────────────────────────────────────────────────── */

interface CreateModalProps {
  defaultProjectId: string;
  projects: { id: string; name: string }[];
  onClose: () => void;
  onCreated: (a: Accommodation) => void;
}

function CreateAccommodationModal({
  defaultProjectId,
  projects,
  onClose,
  onCreated,
}: CreateModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    project_id: defaultProjectId,
    name: '',
    kind: 'worker_camp' as AccommodationKind,
    address: '',
    capacity_total: '0',
    notes: '',
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: createAccommodation,
    onSuccess: (a) => onCreated(a),
    onError: (err) => {
      const msg = getErrorMessage(err);
      setError(msg);
      addToast({
        type: 'error',
        title: t('accommodation.toast.create_failed', {
          defaultValue: 'Failed to create accommodation',
        }),
        message: msg,
      });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!form.project_id) {
      setError(
        t('accommodation.validation.project_required', {
          defaultValue: 'Project is required.',
        }),
      );
      return;
    }
    if (!form.name.trim()) {
      setError(
        t('accommodation.validation.name_required', {
          defaultValue: 'Name is required.',
        }),
      );
      return;
    }
    const capacity = Number(form.capacity_total);
    if (!Number.isFinite(capacity) || capacity < 0) {
      setError(
        t('accommodation.validation.capacity_invalid', {
          defaultValue: 'Capacity must be zero or a positive integer.',
        }),
      );
      return;
    }
    mutation.mutate({
      project_id: form.project_id,
      name: form.name.trim(),
      kind: form.kind,
      address: form.address.trim() || null,
      capacity_total: capacity,
      notes: form.notes.trim() || null,
    });
  };

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('accommodation.new', { defaultValue: 'New accommodation' })}
      size="md"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            loading={mutation.isPending}
            data-testid="accommodation-create-submit"
          >
            {t('common.create')}
          </Button>
        </>
      }
    >
      <form onSubmit={handleSubmit}>
        <WideModalSection columns={2}>
          <WideModalField
            label={t('accommodation.field.project', { defaultValue: 'Project' })}
            required
          >
            <select
              value={form.project_id}
              onChange={(e) =>
                setForm((f) => ({ ...f, project_id: e.target.value }))
              }
              className={inputCls}
              data-testid="accommodation-create-project"
            >
              <option value="">
                {t('accommodation.project.placeholder', {
                  defaultValue: '- Select project -',
                })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </WideModalField>
          <WideModalField
            label={t('accommodation.field.kind', { defaultValue: 'Kind' })}
            required
          >
            <select
              value={form.kind}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  kind: e.target.value as AccommodationKind,
                }))
              }
              className={inputCls}
              data-testid="accommodation-create-kind"
            >
              <option value="worker_camp">
                {t('accommodation.kind.worker_camp', {
                  defaultValue: 'Worker camp',
                })}
              </option>
              <option value="rental">
                {t('accommodation.kind.rental', { defaultValue: 'Rental' })}
              </option>
              <option value="hotel">
                {t('accommodation.kind.hotel', { defaultValue: 'Hotel' })}
              </option>
            </select>
          </WideModalField>
          <WideModalField
            label={t('accommodation.field.name', { defaultValue: 'Name' })}
            required
            span={2}
          >
            <input
              type="text"
              value={form.name}
              onChange={(e) =>
                setForm((f) => ({ ...f, name: e.target.value }))
              }
              className={inputCls}
              placeholder={t('accommodation.name.placeholder', {
                defaultValue: 'e.g. Camp North',
              })}
              autoFocus
              data-testid="accommodation-create-name"
            />
          </WideModalField>
          <WideModalField
            label={t('accommodation.field.address', { defaultValue: 'Address' })}
            span={2}
          >
            <input
              type="text"
              value={form.address}
              onChange={(e) =>
                setForm((f) => ({ ...f, address: e.target.value }))
              }
              className={inputCls}
            />
          </WideModalField>
          <WideModalField
            label={t('accommodation.field.capacity', {
              defaultValue: 'Total capacity',
            })}
          >
            <input
              type="number"
              min={0}
              value={form.capacity_total}
              onChange={(e) =>
                setForm((f) => ({ ...f, capacity_total: e.target.value }))
              }
              className={inputCls}
              data-testid="accommodation-create-capacity"
            />
          </WideModalField>
        </WideModalSection>

        <WideModalSection
          title={t('accommodation.field.notes', { defaultValue: 'Notes' })}
          columns={1}
        >
          <WideModalField label="" htmlFor="acc-notes">
            <textarea
              id="acc-notes"
              value={form.notes}
              onChange={(e) =>
                setForm((f) => ({ ...f, notes: e.target.value }))
              }
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary p-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </WideModalField>
        </WideModalSection>

        {error && (
          <div
            role="alert"
            className="mt-2 rounded-lg border border-semantic-error/30 bg-semantic-error/10 p-3 text-sm text-semantic-error"
          >
            {error}
          </div>
        )}
      </form>
    </WideModal>
  );
}
