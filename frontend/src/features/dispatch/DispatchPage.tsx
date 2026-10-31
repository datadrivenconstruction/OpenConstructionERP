// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dispatch board: a magnet board of crews, people and machines on sites, yard and shop.
 *
 * Drag cards between columns, or select them and use "Move selected to" from the keyboard.
 * Conflicts come from the server and are always shown; nothing is silently refused.
 */
import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  AlertTriangle,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Copy,
  FileDown,
  HardHat,
  Plus,
  Send,
  Timer,
  Trash2,
  Truck,
  User,
  Users,
} from 'lucide-react';
import { Badge, Button, Card, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';
import {
  copyDay,
  createCrew,
  createLocation,
  downloadPlanPdf,
  fetchBoard,
  fetchCards,
  fetchPlan,
  fetchPref,
  fetchUtilisation,
  fetchWeek,
  moveCards,
  placeCards,
  prefillTimesheet,
  removeCards,
  savePref,
  scheduleMove,
  sharePlan,
  updatePlacement,
  type CardItem,
  type CardKind,
  type ConflictKind,
  type DispatchLocation,
  type LocationKind,
  type Placement,
} from './api';
import { STATUS_CLASS, addDays, conflictSummary, groupByLocation, isoDay, mondayOf, sortLocations, toggle } from './boardModel';

type View = 'day' | 'week' | 'utilisation';
type Density = 'compact' | 'detailed';

const KIND_ICON: Record<CardKind, ReactNode> = {
  crew: <Users size={14} />,
  worker: <User size={14} />,
  equipment: <Truck size={14} />,
  rental: <Truck size={14} className="text-amber-600" />,
};

function useLabels() {
  const { t } = useTranslation();
  const kind: Record<CardKind, string> = {
    crew: t('dispatch.kind_crew', { defaultValue: 'Crews' }),
    worker: t('dispatch.kind_worker', { defaultValue: 'People' }),
    equipment: t('dispatch.kind_equipment', { defaultValue: 'Machines' }),
    rental: t('dispatch.kind_rental', { defaultValue: 'Rentals' }),
  };
  const location: Record<LocationKind, string> = {
    project: t('dispatch.loc_project', { defaultValue: 'Site' }),
    yard: t('dispatch.loc_yard', { defaultValue: 'Yard' }),
    shop: t('dispatch.loc_shop', { defaultValue: 'Shop' }),
    rental_return: t('dispatch.loc_rental_return', { defaultValue: 'Rental returned' }),
  };
  const status: Record<string, string> = {
    available: t('dispatch.status_available', { defaultValue: 'Available' }),
    assigned: t('dispatch.status_assigned', { defaultValue: 'On a job' }),
    maintenance: t('dispatch.status_maintenance', { defaultValue: 'Down for maintenance' }),
    in_transit: t('dispatch.status_in_transit', { defaultValue: 'In transit' }),
    absent: t('dispatch.status_absent', { defaultValue: 'Absent' }),
  };
  const conflict: Record<ConflictKind, string> = {
    double_booked: t('dispatch.conflict_double_booked', { defaultValue: 'On two sites the same day' }),
    maintenance_block: t('dispatch.conflict_maintenance_block', { defaultValue: 'Machine down for maintenance' }),
    maintenance_overdue: t('dispatch.conflict_maintenance_overdue', { defaultValue: 'Maintenance past due' }),
    missing_certificate: t('dispatch.conflict_missing_certificate', { defaultValue: 'Operator not certified' }),
    worker_absent: t('dispatch.conflict_worker_absent', { defaultValue: 'Person on leave or sick' }),
    crew_under_minimum: t('dispatch.conflict_crew_under_minimum', { defaultValue: 'Crew short of people' }),
  };
  return { kind, location, status, conflict };
}

export function DispatchPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const labels = useLabels();
  const today = isoDay(new Date());
  const [day, setDay] = useState(today);
  const [view, setView] = useState<View>('day');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showPlan, setShowPlan] = useState(false);

  const board = useQuery({ queryKey: ['dispatch', 'board', day], queryFn: () => fetchBoard(day), enabled: view === 'day' });
  const pref = useQuery({ queryKey: ['dispatch', 'pref'], queryFn: fetchPref, staleTime: Infinity });
  const density: Density = pref.data?.card_density ?? 'detailed';

  const refresh = () => qc.invalidateQueries({ queryKey: ['dispatch'] });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('dispatch.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) });

  const densityMut = useMutation({
    mutationFn: (d: Density) => savePref({ card_density: d, settings: pref.data?.settings ?? {} }),
    onSuccess: (data) => qc.setQueryData(['dispatch', 'pref'], data),
    onError,
  });
  const placeMut = useMutation({
    mutationFn: (args: { location_id: string; cards: { card_kind: CardKind; card_ref: string }[] }) =>
      placeCards({ day, ...args }),
    onSuccess: () => {
      setSelected(new Set());
      void refresh();
    },
    onError,
  });
  const moveMut = useMutation({
    mutationFn: (args: { ids: string[]; to: string }) => moveCards(args.ids, args.to),
    onSuccess: () => {
      setSelected(new Set());
      void refresh();
    },
    onError,
  });
  const removeMut = useMutation({
    mutationFn: (ids: string[]) => removeCards(ids),
    onSuccess: () => {
      setSelected(new Set());
      void refresh();
    },
    onError,
  });
  const copyMut = useMutation({
    mutationFn: () => copyDay(addDays(day, -1), day),
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('dispatch.copied', { defaultValue: '{{count}} cards copied from the day before', count: r.copied }),
      });
      void refresh();
    },
    onError,
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const placements = board.data?.placements ?? [];
  const locations = useMemo(() => sortLocations(board.data?.locations ?? []), [board.data?.locations]);
  const grouped = useMemo(() => groupByLocation(placements), [placements]);
  const selectedPlacements = placements.filter((p) => selected.has(p.id));

  const onDragEnd = (e: DragEndEvent) => {
    const over = e.over?.id ? String(e.over.id) : '';
    if (!over.startsWith('loc:')) return;
    const to = over.slice(4);
    const id = String(e.active.id);
    if (id.startsWith('pal:')) {
      const [, kind, ref] = id.split(':');
      placeMut.mutate({ location_id: to, cards: [{ card_kind: kind as CardKind, card_ref: ref ?? '' }] });
      return;
    }
    const pid = id.slice(3);
    const ids = selected.has(pid) ? [...selected] : [pid];
    moveMut.mutate({ ids, to });
  };

  return (
    <div className="space-y-4">
      <PageHeader
        srTitle={t('dispatch.title', { defaultValue: 'Dispatch board' })}
        subtitle={t('dispatch.subtitle', {
          defaultValue: 'Put crews, people and machines where they work each day. Conflicts show up at once.',
        })}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => copyMut.mutate()} disabled={copyMut.isPending}>
              <Copy size={14} className="mr-1" />
              {t('dispatch.copy_yesterday', { defaultValue: 'Repeat the day before' })}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setShowPlan((v) => !v)}>
              <ClipboardList size={14} className="mr-1" />
              {t('dispatch.daily_plan', { defaultValue: 'Daily plan' })}
            </Button>
            <div role="group" aria-label={t('dispatch.density', { defaultValue: 'Card size' })} className="flex rounded border border-border">
              {(['compact', 'detailed'] as Density[]).map((d) => (
                <button
                  key={d}
                  type="button"
                  aria-pressed={density === d}
                  onClick={() => densityMut.mutate(d)}
                  className={clsx('px-2 py-1 text-xs', density === d ? 'bg-oe-blue text-white' : 'text-content-secondary')}
                >
                  {d === 'compact'
                    ? t('dispatch.density_compact', { defaultValue: 'Compact' })
                    : t('dispatch.density_detailed', { defaultValue: 'Detailed' })}
                </button>
              ))}
            </div>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" aria-label={t('dispatch.prev_day', { defaultValue: 'Previous day' })} onClick={() => setDay(addDays(day, view === 'day' ? -1 : -7))}>
          <ChevronLeft size={16} />
        </Button>
        <input
          type="date"
          value={day}
          onChange={(e) => e.target.value && setDay(e.target.value)}
          aria-label={t('dispatch.pick_day', { defaultValue: 'Day' })}
          className="rounded border border-border bg-surface-primary px-2 py-1 text-sm"
        />
        <Button variant="ghost" size="sm" aria-label={t('dispatch.next_day', { defaultValue: 'Next day' })} onClick={() => setDay(addDays(day, view === 'day' ? 1 : 7))}>
          <ChevronRight size={16} />
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setDay(today)}>
          {t('dispatch.today', { defaultValue: 'Today' })}
        </Button>
        <div role="tablist" className="ml-auto flex rounded border border-border">
          {(['day', 'week', 'utilisation'] as View[]).map((v) => (
            <button
              key={v}
              role="tab"
              type="button"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={clsx('px-3 py-1 text-sm', view === v ? 'bg-oe-blue text-white' : 'text-content-secondary')}
            >
              {v === 'day'
                ? t('dispatch.view_day', { defaultValue: 'Day' })
                : v === 'week'
                  ? t('dispatch.view_week', { defaultValue: 'Week' })
                  : t('dispatch.view_utilisation', { defaultValue: 'Use of machines' })}
            </button>
          ))}
        </div>
      </div>

      {showPlan && <PlanPanel day={addDays(day, day === today ? 1 : 0)} onClose={() => setShowPlan(false)} />}

      {view === 'week' && <WeekView start={mondayOf(day)} onPickDay={(d) => { setDay(d); setView('day'); }} />}
      {view === 'utilisation' && <UtilisationView day={day} />}

      {view === 'day' && (
        <>
          <ConflictStrip conflicts={board.data?.conflicts ?? []} labels={labels.conflict} />
          {(board.data?.pending_moves.length ?? 0) > 0 && (
            <p className="flex items-center gap-1 text-xs text-content-secondary">
              <CalendarClock size={14} />
              {t('dispatch.pending_moves', {
                defaultValue: '{{count}} moves are booked for this day and will be applied on the day.',
                count: board.data?.pending_moves.length ?? 0,
              })}
            </p>
          )}
          <SelectionBar
            selected={selectedPlacements}
            locations={locations}
            onMove={(to) => moveMut.mutate({ ids: [...selected], to })}
            onRemove={() => removeMut.mutate([...selected])}
            onClear={() => setSelected(new Set())}
          />
          <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <div className="flex gap-3">
              <Palette locations={locations} onPlace={(location_id, cards) => placeMut.mutate({ location_id, cards })} />
              <div className="flex min-w-0 flex-1 gap-3 overflow-x-auto pb-2">
                {locations.length === 0 && !board.isLoading && <NoColumns />}
                {locations.map((loc) => (
                  <Column
                    key={loc.id}
                    location={loc}
                    kindLabel={labels.location[loc.kind]}
                    day={day}
                    placements={grouped[loc.id] ?? []}
                    density={density}
                    selected={selected}
                    onToggle={(id) => setSelected((s) => toggle(s, id))}
                    locations={locations}
                  />
                ))}
                <AddColumn />
              </div>
            </div>
          </DndContext>
          <p className="text-xs text-content-tertiary">
            {t('dispatch.keyboard_hint', {
              defaultValue:
                'Keyboard: tick cards with Space, then use "Move selected to". Or focus a card, press Space to lift it, arrows to move, Space to drop.',
            })}
          </p>
        </>
      )}
    </div>
  );
}

function ConflictStrip({ conflicts, labels }: { conflicts: { kind: ConflictKind; severity: 'error' | 'warning'; message: string; placement_ids: string[]; card_kind: string; card_ref: string; details: Record<string, unknown> }[]; labels: Record<ConflictKind, string> }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!conflicts.length) {
    return (
      <p className="text-sm text-emerald-700 dark:text-emerald-400">
        {t('dispatch.no_conflicts', { defaultValue: 'No conflicts on this day.' })}
      </p>
    );
  }
  return (
    <Card className="border-amber-300 p-3">
      <button type="button" className="flex w-full flex-wrap items-center gap-2 text-left" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <AlertTriangle size={16} className="text-amber-600" />
        <span className="text-sm font-medium">
          {t('dispatch.conflicts_count', { defaultValue: '{{count}} conflicts need a look', count: conflicts.length })}
        </span>
        {conflictSummary(conflicts).map((s) => (
          <Badge key={s.kind} variant={s.severity === 'error' ? 'error' : 'warning'}>
            {labels[s.kind]}: {s.count}
          </Badge>
        ))}
      </button>
      {open && (
        <ul className="mt-2 space-y-1 text-sm">
          {conflicts.map((c, i) => (
            <li key={`${c.kind}-${c.card_ref}-${i}`} className={c.severity === 'error' ? 'text-red-700 dark:text-red-400' : 'text-amber-800 dark:text-amber-300'}>
              {c.message}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SelectionBar({
  selected,
  locations,
  onMove,
  onRemove,
  onClear,
}: {
  selected: Placement[];
  locations: DispatchLocation[];
  onMove: (to: string) => void;
  onRemove: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const [to, setTo] = useState('');
  if (!selected.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded border border-oe-blue/40 bg-oe-blue/5 px-3 py-2 text-sm">
      <span>{t('dispatch.selected_count', { defaultValue: '{{count}} selected', count: selected.length })}</span>
      <label className="flex items-center gap-1">
        {t('dispatch.move_selected_to', { defaultValue: 'Move selected to' })}
        <select value={to} onChange={(e) => setTo(e.target.value)} className="rounded border border-border bg-surface-primary px-2 py-1">
          <option value="">-</option>
          {locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </label>
      <Button size="sm" disabled={!to} onClick={() => onMove(to)}>
        {t('dispatch.move', { defaultValue: 'Move' })}
      </Button>
      <Button size="sm" variant="danger" onClick={onRemove}>
        <Trash2 size={14} className="mr-1" />
        {t('dispatch.remove', { defaultValue: 'Take off the board' })}
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear}>
        {t('dispatch.clear_selection', { defaultValue: 'Clear' })}
      </Button>
    </div>
  );
}

function Palette({
  locations,
  onPlace,
}: {
  locations: DispatchLocation[];
  onPlace: (location_id: string, cards: { card_kind: CardKind; card_ref: string }[]) => void;
}) {
  const { t } = useTranslation();
  const labels = useLabels();
  const [kind, setKind] = useState<CardKind>('crew');
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [to, setTo] = useState('');
  const cards = useQuery({ queryKey: ['dispatch', 'cards', kind, q, offset], queryFn: () => fetchCards(kind, q, offset) });
  const items = cards.data?.items ?? [];
  const total = cards.data?.total ?? 0;

  return (
    <aside className="w-64 shrink-0 space-y-2" aria-label={t('dispatch.palette', { defaultValue: 'Cards to place' })}>
      <div className="flex flex-wrap gap-1">
        {(['crew', 'worker', 'equipment', 'rental'] as CardKind[]).map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={kind === k}
            onClick={() => {
              setKind(k);
              setOffset(0);
              setPicked(new Set());
            }}
            className={clsx('flex items-center gap-1 rounded px-2 py-1 text-xs', kind === k ? 'bg-oe-blue text-white' : 'bg-surface-secondary')}
          >
            {KIND_ICON[k]}
            {labels.kind[k]}
          </button>
        ))}
      </div>
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOffset(0);
        }}
        placeholder={t('dispatch.search', { defaultValue: 'Search by name or code' })}
        className="w-full rounded border border-border bg-surface-primary px-2 py-1 text-sm"
      />
      {kind === 'crew' && <NewCrew />}
      <ul className="max-h-[55vh] space-y-1 overflow-y-auto">
        {items.map((c) => (
          <PaletteCard key={c.card_ref} card={c} checked={picked.has(c.card_ref)} onToggle={() => setPicked((s) => toggle(s, c.card_ref))} />
        ))}
        {!items.length && !cards.isLoading && (
          <li className="text-xs text-content-tertiary">{t('dispatch.no_cards', { defaultValue: 'Nothing found.' })}</li>
        )}
      </ul>
      {total > 50 && (
        <div className="flex items-center justify-between text-xs">
          <Button size="sm" variant="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>
            <ChevronLeft size={14} />
          </Button>
          <span>
            {offset + 1}-{Math.min(offset + 50, total)} / {total}
          </span>
          <Button size="sm" variant="ghost" disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>
            <ChevronRight size={14} />
          </Button>
        </div>
      )}
      {picked.size > 0 && (
        <div className="space-y-1 rounded border border-border p-2 text-xs">
          <label className="block">
            {t('dispatch.place_selected_on', { defaultValue: 'Place {{count}} on', count: picked.size })}
            <select value={to} onChange={(e) => setTo(e.target.value)} className="mt-1 w-full rounded border border-border bg-surface-primary px-2 py-1">
              <option value="">-</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
          <Button
            size="sm"
            disabled={!to}
            onClick={() => {
              onPlace(to, [...picked].map((ref) => ({ card_kind: kind, card_ref: ref })));
              setPicked(new Set());
            }}
          >
            {t('dispatch.place', { defaultValue: 'Place' })}
          </Button>
        </div>
      )}
    </aside>
  );
}

function PaletteCard({ card, checked, onToggle }: { card: CardItem; checked: boolean; onToggle: () => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `pal:${card.card_kind}:${card.card_ref}` });
  return (
    <li
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      className={clsx(
        'flex cursor-grab items-center gap-2 rounded border border-border border-l-4 bg-surface-primary px-2 py-1 text-xs',
        card.status === 'maintenance' ? STATUS_CLASS.maintenance : STATUS_CLASS.available,
        isDragging && 'opacity-50',
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        onPointerDown={(e) => e.stopPropagation()}
        aria-label={card.label}
      />
      {KIND_ICON[card.card_kind]}
      <span className="min-w-0 flex-1 truncate" title={card.label}>
        {card.label}
      </span>
      {card.subtitle && <span className="truncate text-content-tertiary">{card.subtitle}</span>}
    </li>
  );
}

function Column({
  location,
  kindLabel,
  day,
  placements,
  density,
  selected,
  onToggle,
  locations,
}: {
  location: DispatchLocation;
  kindLabel: string;
  day: string;
  placements: Placement[];
  density: Density;
  selected: Set<string>;
  onToggle: (id: string) => void;
  locations: DispatchLocation[];
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { setNodeRef, isOver } = useDroppable({ id: `loc:${location.id}` });
  const prefill = useMutation({
    mutationFn: () => prefillTimesheet(location.id, day),
    onSuccess: (r) =>
      addToast({
        type: 'success',
        title: r.created
          ? t('dispatch.prefill_created', { defaultValue: 'Timesheet {{ref}} drafted with {{count}} lines', ref: r.reference, count: r.lines_added })
          : t('dispatch.prefill_topped_up', { defaultValue: 'Timesheet {{ref}}: {{count}} lines added', ref: r.reference, count: r.lines_added }),
        message: t('dispatch.prefill_hint', { defaultValue: 'The foreman confirms hours and quantities in Field time.' }),
      }),
    onError: (e) => addToast({ type: 'error', title: t('dispatch.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) }),
  });
  return (
    <section
      ref={setNodeRef}
      aria-label={location.name}
      className={clsx(
        'flex w-64 shrink-0 flex-col rounded-lg border bg-surface-secondary p-2',
        isOver ? 'border-oe-blue ring-2 ring-oe-blue/40' : 'border-border',
      )}
    >
      <header className="mb-2 flex items-start justify-between gap-1">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold" title={location.name}>
            {location.name}
          </h3>
          <p className="text-xs text-content-tertiary">
            {kindLabel} · {placements.length}
          </p>
        </div>
        {location.kind === 'project' && (
          <Button
            size="sm"
            variant="ghost"
            title={t('dispatch.prefill', { defaultValue: 'Prefill the site timesheet' })}
            aria-label={t('dispatch.prefill', { defaultValue: 'Prefill the site timesheet' })}
            onClick={() => prefill.mutate()}
            disabled={prefill.isPending || placements.length === 0}
          >
            <Timer size={14} />
          </Button>
        )}
      </header>
      <ul className="flex min-h-24 flex-col gap-1.5">
        {placements.map((p) => (
          <PlacementCard key={p.id} p={p} density={density} checked={selected.has(p.id)} onToggle={() => onToggle(p.id)} locations={locations} />
        ))}
        {!placements.length && (
          <li className="rounded border border-dashed border-border p-3 text-center text-xs text-content-tertiary">
            {t('dispatch.drop_here', { defaultValue: 'Drop cards here' })}
          </li>
        )}
      </ul>
    </section>
  );
}

function PlacementCard({
  p,
  density,
  checked,
  onToggle,
  locations,
}: {
  p: Placement;
  density: Density;
  checked: boolean;
  onToggle: () => void;
  locations: DispatchLocation[];
}) {
  const { t } = useTranslation();
  const labels = useLabels();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [edit, setEdit] = useState(false);
  const [time, setTime] = useState(p.start_time);
  const [notes, setNotes] = useState(p.notes);
  const [moveDate, setMoveDate] = useState('');
  const [moveTo, setMoveTo] = useState('');
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `pl:${p.id}` });
  const onError = (e: unknown) =>
    addToast({ type: 'error', title: t('dispatch.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) });
  const save = useMutation({
    mutationFn: () => updatePlacement(p.id, { start_time: time, notes }),
    onSuccess: () => {
      setEdit(false);
      void qc.invalidateQueries({ queryKey: ['dispatch'] });
    },
    onError,
  });
  const book = useMutation({
    mutationFn: () => scheduleMove({ card_kind: p.card_kind, card_ref: p.card_ref, to_location_id: moveTo, effective_date: moveDate }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('dispatch.move_booked', { defaultValue: 'Move booked for {{day}}', day: moveDate }) });
      setEdit(false);
      void qc.invalidateQueries({ queryKey: ['dispatch'] });
    },
    onError,
  });
  const hasError = p.conflict_kinds.some((k) => k === 'double_booked' || k === 'maintenance_block');
  return (
    <li
      ref={setNodeRef}
      className={clsx(
        'rounded border border-l-4 bg-surface-primary px-2 py-1.5 text-xs shadow-sm',
        p.status ? STATUS_CLASS[p.status] : 'border-l-border',
        hasError ? 'border-red-400' : p.conflict_kinds.length ? 'border-amber-400' : 'border-border',
        isDragging && 'opacity-50',
      )}
    >
      <div className="flex items-center gap-1.5">
        <input type="checkbox" checked={checked} onChange={onToggle} aria-label={p.label} />
        <span {...attributes} {...listeners} className="flex min-w-0 flex-1 cursor-grab items-center gap-1" aria-roledescription={t('dispatch.card', { defaultValue: 'card' })}>
          {KIND_ICON[p.card_kind]}
          <span className="truncate font-medium" title={p.label}>
            {p.label}
          </span>
        </span>
        <span className="text-content-tertiary">{p.start_time}</span>
        <button type="button" className="text-content-tertiary hover:text-content-primary" aria-expanded={edit} aria-label={t('dispatch.edit_card', { defaultValue: 'Details' })} onClick={() => setEdit((v) => !v)}>
          ⋯
        </button>
      </div>
      {p.status && density === 'detailed' && <p className="mt-0.5 text-content-tertiary">{labels.status[p.status]}</p>}
      {p.conflict_kinds.length > 0 && (
        <p className={clsx('mt-0.5 flex items-center gap-1', hasError ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-300')}>
          <AlertTriangle size={12} />
          {p.conflict_kinds.map((k) => labels.conflict[k]).join(' · ')}
        </p>
      )}
      {density === 'detailed' && p.card_kind === 'crew' && p.members.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-1">
          {p.members.map((m) => (
            <li key={m.id} className={clsx('rounded bg-surface-secondary px-1', m.absent && 'line-through text-purple-700')}>
              <HardHat size={10} className="mr-0.5 inline" />
              {m.name}
            </li>
          ))}
        </ul>
      )}
      {density === 'detailed' && p.notes && !edit && <p className="mt-1 text-content-secondary">{p.notes}</p>}
      {edit && (
        <div className="mt-2 space-y-1.5 border-t border-border pt-1.5">
          <label className="flex items-center gap-1">
            {t('dispatch.start_time', { defaultValue: 'Start' })}
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="rounded border border-border bg-surface-primary px-1" />
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder={t('dispatch.notes', { defaultValue: 'Notes for the foreman' })}
            className="w-full rounded border border-border bg-surface-primary px-1"
          />
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          <fieldset className="space-y-1 border-t border-border pt-1.5">
            <legend className="text-content-secondary">{t('dispatch.book_move', { defaultValue: 'Book a move for later' })}</legend>
            <input type="date" value={moveDate} min={isoDay(new Date())} onChange={(e) => setMoveDate(e.target.value)} className="rounded border border-border bg-surface-primary px-1" aria-label={t('dispatch.move_date', { defaultValue: 'Move on' })} />
            <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} className="w-full rounded border border-border bg-surface-primary px-1" aria-label={t('dispatch.move_to', { defaultValue: 'Move to' })}>
              <option value="">-</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
            <Button size="sm" variant="secondary" disabled={!moveDate || !moveTo || book.isPending} onClick={() => book.mutate()}>
              <CalendarClock size={12} className="mr-1" />
              {t('dispatch.book', { defaultValue: 'Book move' })}
            </Button>
          </fieldset>
        </div>
      )}
    </li>
  );
}

function NoColumns() {
  const { t } = useTranslation();
  return (
    <EmptyState
      title={t('dispatch.empty_title', { defaultValue: 'No columns yet' })}
      description={t('dispatch.empty_desc', {
        defaultValue: 'Add a column for each site you run, plus your yard and shop. Then drag crews and machines onto them.',
      })}
    />
  );
}

function AddColumn() {
  const { t } = useTranslation();
  const labels = useLabels();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<LocationKind>('project');
  const [name, setName] = useState('');
  const [projectId, setProjectId] = useState('');
  const projects = useQuery({ queryKey: ['projects', 'list'], queryFn: projectsApi.list, enabled: open && kind === 'project' });
  const mut = useMutation({
    mutationFn: () => {
      const project = projects.data?.find((p) => p.id === projectId);
      return createLocation({ name: name || project?.name || labels.location[kind], kind, project_id: kind === 'project' ? projectId : null });
    },
    onSuccess: () => {
      setOpen(false);
      setName('');
      setProjectId('');
      void qc.invalidateQueries({ queryKey: ['dispatch'] });
    },
    onError: (e) => addToast({ type: 'error', title: t('dispatch.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) }),
  });
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="flex w-40 shrink-0 items-center justify-center gap-1 rounded-lg border border-dashed border-border text-sm text-content-secondary hover:text-content-primary">
        <Plus size={14} />
        {t('dispatch.add_column', { defaultValue: 'Add column' })}
      </button>
    );
  }
  return (
    <div className="w-64 shrink-0 space-y-2 rounded-lg border border-border p-2 text-sm">
      <select value={kind} onChange={(e) => setKind(e.target.value as LocationKind)} className="w-full rounded border border-border bg-surface-primary px-2 py-1">
        {(Object.keys(labels.location) as LocationKind[]).map((k) => (
          <option key={k} value={k}>
            {labels.location[k]}
          </option>
        ))}
      </select>
      {kind === 'project' && (
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="w-full rounded border border-border bg-surface-primary px-2 py-1" aria-label={t('dispatch.project', { defaultValue: 'Project' })}>
          <option value="">{t('dispatch.pick_project', { defaultValue: 'Pick a project' })}</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('dispatch.column_name', { defaultValue: 'Name (optional)' })} className="w-full rounded border border-border bg-surface-primary px-2 py-1" />
      <div className="flex gap-2">
        <Button size="sm" disabled={(kind === 'project' && !projectId) || mut.isPending} onClick={() => mut.mutate()}>
          {t('dispatch.add', { defaultValue: 'Add' })}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}

function NewCrew() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [minSize, setMinSize] = useState(0);
  const [members, setMembers] = useState<Set<string>>(new Set());
  const people = useQuery({ queryKey: ['dispatch', 'cards', 'worker', '', 0], queryFn: () => fetchCards('worker', '', 0), enabled: open });
  const mut = useMutation({
    mutationFn: () => createCrew({ name, member_ids: [...members], min_size: minSize }),
    onSuccess: () => {
      setOpen(false);
      setName('');
      setMembers(new Set());
      void qc.invalidateQueries({ queryKey: ['dispatch', 'cards'] });
    },
    onError: (e) => addToast({ type: 'error', title: t('dispatch.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) }),
  });
  if (!open) {
    return (
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        <Plus size={14} className="mr-1" />
        {t('dispatch.new_crew', { defaultValue: 'New crew' })}
      </Button>
    );
  }
  return (
    <div className="space-y-1 rounded border border-border p-2 text-xs">
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('dispatch.crew_name', { defaultValue: 'Crew name' })} className="w-full rounded border border-border bg-surface-primary px-2 py-1" />
      <label className="flex items-center gap-1">
        {t('dispatch.crew_min', { defaultValue: 'Needs at least' })}
        <input type="number" min={0} value={minSize} onChange={(e) => setMinSize(Number(e.target.value) || 0)} className="w-14 rounded border border-border bg-surface-primary px-1" />
      </label>
      <ul className="max-h-32 overflow-y-auto">
        {(people.data?.items ?? []).map((w) => (
          <li key={w.card_ref}>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={members.has(w.card_ref)} onChange={() => setMembers((s) => toggle(s, w.card_ref))} />
              {w.label}
            </label>
          </li>
        ))}
      </ul>
      <Button size="sm" disabled={!name || mut.isPending} onClick={() => mut.mutate()}>
        {t('dispatch.add', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}

function PlanPanel({ day, onClose }: { day: string; onClose: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const plan = useQuery({ queryKey: ['dispatch', 'plan', day], queryFn: () => fetchPlan(day) });
  const share = useMutation({
    mutationFn: () => sharePlan(day),
    onSuccess: (r) =>
      addToast({
        type: 'success',
        title: t('dispatch.shared', { defaultValue: 'Sent to {{count}} foremen', count: r.notified }),
        message: r.without_user.length
          ? t('dispatch.shared_missing', { defaultValue: 'No platform account for: {{names}}', names: r.without_user.join(', ') })
          : undefined,
      }),
    onError: (e) => addToast({ type: 'error', title: t('dispatch.action_failed', { defaultValue: 'That did not work' }), message: getErrorMessage(e) }),
  });
  return (
    <Card className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{t('dispatch.plan_for', { defaultValue: 'Daily plan for {{day}}', day })}</h2>
        <Button size="sm" variant="secondary" onClick={() => void downloadPlanPdf(day)}>
          <FileDown size={14} className="mr-1" />
          {t('dispatch.print_pdf', { defaultValue: 'Print (PDF)' })}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => share.mutate()} disabled={share.isPending}>
          <Send size={14} className="mr-1" />
          {t('dispatch.send_foremen', { defaultValue: 'Send to foremen' })}
        </Button>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      </div>
      {(plan.data?.plans ?? []).length === 0 && !plan.isLoading && (
        <p className="text-sm text-content-tertiary">{t('dispatch.plan_empty', { defaultValue: 'Nothing is dispatched for this day yet.' })}</p>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {(plan.data?.plans ?? []).map((f, i) => (
          <div key={`${f.foreman}-${i}`} className="rounded border border-border p-2">
            <h3 className="mb-1 text-sm font-medium">{f.foreman || t('dispatch.no_foreman', { defaultValue: 'No foreman set' })}</h3>
            <table className="w-full text-xs">
              <thead className="text-left text-content-tertiary">
                <tr>
                  <th>{t('dispatch.start_time', { defaultValue: 'Start' })}</th>
                  <th>{t('dispatch.where', { defaultValue: 'Where' })}</th>
                  <th>{t('dispatch.who_what', { defaultValue: 'Who / what' })}</th>
                  <th>{t('dispatch.notes_short', { defaultValue: 'Notes' })}</th>
                </tr>
              </thead>
              <tbody>
                {f.lines.map((ln, j) => (
                  <tr key={j} className="border-t border-border align-top">
                    <td className="pr-2">{ln.start_time}</td>
                    <td className="pr-2">{ln.location}</td>
                    <td className="pr-2">
                      {ln.who_or_what}
                      {ln.operator && <span className="text-content-tertiary"> ({ln.operator})</span>}
                    </td>
                    <td>{ln.notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </Card>
  );
}

function WeekView({ start, onPickDay }: { start: string; onPickDay: (day: string) => void }) {
  const { t } = useTranslation();
  const week = useQuery({ queryKey: ['dispatch', 'week', start], queryFn: () => fetchWeek(start) });
  const locations = sortLocations(week.data?.locations ?? []);
  const days = week.data?.days ?? [];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-xs">
        <thead>
          <tr>
            <th className="p-1 text-left">{t('dispatch.where', { defaultValue: 'Where' })}</th>
            {days.map((d) => (
              <th key={d.day} className="p-1 text-left">
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => onPickDay(d.day)}>
                  {d.day.slice(5)}
                </button>
                {d.conflict_count > 0 && (
                  <Badge variant="warning" className="ml-1">
                    {d.conflict_count}
                  </Badge>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {locations.map((loc) => (
            <tr key={loc.id} className="border-t border-border align-top">
              <td className="p-1 font-medium">{loc.name}</td>
              {days.map((d) => (
                <td key={d.day} className="p-1">
                  {d.placements
                    .filter((p) => p.location_id === loc.id)
                    .map((p) => (
                      <div key={p.id} className={clsx('mb-0.5 truncate rounded border-l-4 bg-surface-secondary px-1', p.status ? STATUS_CLASS[p.status] : 'border-l-border')} title={p.label}>
                        {p.label}
                      </div>
                    ))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UtilisationView({ day }: { day: string }) {
  const { t } = useTranslation();
  const [range, setRange] = useState<'week' | 'month'>('week');
  const start = range === 'week' ? mondayOf(day) : `${day.slice(0, 8)}01`;
  const end = range === 'week' ? addDays(start, 6) : addDays(addDays(`${day.slice(0, 8)}01`, 31).slice(0, 8) + '01', -1);
  const util = useQuery({ queryKey: ['dispatch', 'util', start, end], queryFn: () => fetchUtilisation(start, end) });
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-content-secondary">
          {t('dispatch.util_hint', { defaultValue: 'Working days on a site against idle days. Idle rentals are money to save.' })}
        </span>
        <select value={range} onChange={(e) => setRange(e.target.value as 'week' | 'month')} className="ml-auto rounded border border-border bg-surface-primary px-2 py-1">
          <option value="week">{t('dispatch.this_week', { defaultValue: 'This week' })}</option>
          <option value="month">{t('dispatch.this_month', { defaultValue: 'This month' })}</option>
        </select>
      </div>
      <ul className="space-y-1">
        {(util.data?.items ?? []).map((r) => (
          <li key={r.unit_ref} className="flex items-center gap-2 text-xs">
            <span className="w-56 truncate" title={r.label}>
              {r.card_kind === 'rental' && <Badge variant="warning" className="mr-1">{t('dispatch.rented', { defaultValue: 'Rented' })}</Badge>}
              {r.label}
            </span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-surface-secondary" role="img" aria-label={`${r.percent}%`}>
              <div className={clsx('h-full', r.percent < 50 ? 'bg-amber-500' : 'bg-oe-blue')} style={{ width: `${r.percent}%` }} />
            </div>
            <span className="w-40 text-right text-content-secondary">
              {t('dispatch.util_days', {
                defaultValue: '{{assigned}} on site, {{idle}} idle',
                assigned: r.days_assigned,
                idle: r.days_idle,
              })}
            </span>
          </li>
        ))}
      </ul>
      {!util.isLoading && !(util.data?.items ?? []).length && (
        <p className="text-sm text-content-tertiary">{t('dispatch.util_empty', { defaultValue: 'No machines in the register yet.' })}</p>
      )}
    </div>
  );
}

export default DispatchPage;
