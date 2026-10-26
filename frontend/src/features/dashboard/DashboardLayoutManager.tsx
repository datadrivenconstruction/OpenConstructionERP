// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DashboardLayoutManager — drag-to-reorder + show/hide control for the
 * dashboard widgets. One shared component, used in two places:
 *   • inline on the dashboard (the "Customize" panel), applying live
 *   • in Settings → Dashboard
 *
 * State lives in `useDashboardLayoutStore` (localStorage-persisted), so a
 * change here is reflected on the dashboard immediately and survives reloads.
 */
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { GripVertical, Eye, EyeOff, RotateCcw, Check } from 'lucide-react';
import { Button } from '@/shared/ui';
import {
  useDashboardLayoutStore,
  reconcileOrder,
} from '@/stores/useDashboardLayoutStore';
import {
  DASHBOARD_WIDGET_IDS,
  DASHBOARD_WIDGET_BY_ID,
} from './widgetRegistry';
import { DASHBOARD_SETS, dashboardSetLayout } from './dashboardSets';

interface RowProps {
  id: string;
  hidden: boolean;
  onToggle: (id: string) => void;
  /** Current resolved grid span (2/3/4/6) for this widget. */
  span: number;
  onSetSpan: (id: string, span: number) => void;
}

function WidgetRow({ id, hidden, onToggle, span, onSetSpan }: RowProps) {
  const { t } = useTranslation();
  const meta = DASHBOARD_WIDGET_BY_ID[id];
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id });

  if (!meta) return null;
  const Icon = meta.icon;

  // Segmented width control. Values map to grid column spans on the 6-col
  // dashboard grid (2=third, 3=half, 4=two-thirds, 6=full).
  const widthOptions: { value: number; label: string; title: string }[] = [
    {
      value: 2,
      label: '1/3',
      title: t('dashboard.layout.width_third', { defaultValue: 'Third width (3 per row)' }),
    },
    {
      value: 3,
      label: '1/2',
      title: t('dashboard.layout.width_half', { defaultValue: 'Half width (2 per row)' }),
    },
    {
      value: 4,
      label: '2/3',
      title: t('dashboard.layout.width_twothirds', { defaultValue: 'Two-thirds width' }),
    },
    {
      value: 6,
      label: 'Full',
      title: t('dashboard.layout.width_full', { defaultValue: 'Full width' }),
    },
  ];

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.55 : undefined,
      }}
      className={`group flex items-center gap-3 rounded-lg border bg-surface-primary px-3 py-2.5 transition-colors ${
        isDragging
          ? 'border-oe-blue/50 shadow-md'
          : 'border-border-light hover:border-border-medium'
      } ${hidden ? 'opacity-60' : ''}`}
      data-testid={`dash-widget-row-${id}`}
    >
      {/* Drag handle */}
      <button
        type="button"
        aria-label={t('dashboard.layout.drag', { defaultValue: 'Drag to reorder' })}
        className="shrink-0 cursor-grab touch-none rounded-md p-1 text-content-quaternary hover:bg-surface-secondary hover:text-content-secondary active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVertical size={16} strokeWidth={2} />
      </button>

      {/* Icon */}
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
          hidden
            ? 'bg-surface-secondary text-content-quaternary'
            : 'bg-oe-blue/10 text-oe-blue'
        }`}
      >
        <Icon size={16} strokeWidth={2} />
      </span>

      {/* Label + description */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-content-primary">
          {t(meta.labelKey, { defaultValue: meta.labelDefault })}
        </p>
        <p className="truncate text-xs text-content-tertiary">
          {t(meta.descKey, { defaultValue: meta.descDefault })}
        </p>
      </div>

      {/* Width control - sets grid column span (affects desktop layout only) */}
      <div className="flex shrink-0 items-center gap-1.5">
        <span className="hidden text-2xs font-medium text-content-quaternary sm:inline">
          {t('dashboard.layout.width', { defaultValue: 'Width' })}
        </span>
        <div className="inline-flex overflow-hidden rounded-md border border-border-light">
          {widthOptions.map((opt) => {
            const active = span === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => onSetSpan(id, opt.value)}
                aria-label={opt.title}
                aria-pressed={active}
                title={opt.title}
                className={`px-1.5 py-1 text-[11px] font-medium transition-colors ${
                  active
                    ? 'bg-oe-blue text-white'
                    : 'text-content-tertiary hover:bg-surface-secondary'
                }`}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Show / hide toggle */}
      <button
        type="button"
        onClick={() => onToggle(id)}
        aria-pressed={!hidden}
        aria-label={
          hidden
            ? t('dashboard.layout.show', { defaultValue: 'Show widget' })
            : t('dashboard.layout.hide', { defaultValue: 'Hide widget' })
        }
        title={
          hidden
            ? t('dashboard.layout.show', { defaultValue: 'Show widget' })
            : t('dashboard.layout.hide', { defaultValue: 'Hide widget' })
        }
        className={`shrink-0 rounded-md p-1.5 transition-colors ${
          hidden
            ? 'text-content-quaternary hover:bg-surface-secondary hover:text-content-secondary'
            : 'text-oe-blue hover:bg-oe-blue/10'
        }`}
      >
        {hidden ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}

interface ManagerProps {
  /** Render a "Done" button that calls this (used by the inline panel). */
  onClose?: () => void;
  className?: string;
}

export function DashboardLayoutManager({ onClose, className }: ManagerProps) {
  const { t } = useTranslation();
  const order = useDashboardLayoutStore((s) => s.order);
  const hidden = useDashboardLayoutStore((s) => s.hidden);
  const spans = useDashboardLayoutStore((s) => s.spans);
  const setOrder = useDashboardLayoutStore((s) => s.setOrder);
  const toggleHidden = useDashboardLayoutStore((s) => s.toggleHidden);
  const setSpan = useDashboardLayoutStore((s) => s.setSpan);
  const reset = useDashboardLayoutStore((s) => s.reset);

  const resolved = useMemo(
    () => reconcileOrder(order, DASHBOARD_WIDGET_IDS),
    [order],
  );

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const hiddenCount = resolved.filter((id) => hidden.includes(id)).length;
  const isCustomised = order.length > 0 || hidden.length > 0;

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = resolved.indexOf(String(active.id));
    const to = resolved.indexOf(String(over.id));
    if (from === -1 || to === -1) return;
    setOrder(arrayMove(resolved, from, to));
  }

  return (
    <div className={className}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-xs text-content-tertiary">
          {t('dashboard.layout.help', {
            defaultValue:
              'Drag to reorder. Toggle the eye to show or hide a section. Changes apply instantly and are saved to this browser.',
          })}
        </p>
        {onClose && (
          <Button
            variant="primary"
            size="sm"
            icon={<Check size={14} />}
            onClick={onClose}
          >
            {t('common.done', { defaultValue: 'Done' })}
          </Button>
        )}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2" data-testid="dash-sets">
        <span className="text-xs font-medium text-content-secondary">
          {t('dashboard.layout.sets', { defaultValue: 'Ready-made sets' })}
        </span>
        {DASHBOARD_SETS.map((set) => (
          <Button
            key={set.id}
            variant="secondary"
            size="sm"
            onClick={() => useDashboardLayoutStore.setState(dashboardSetLayout(set, DASHBOARD_WIDGET_IDS))}
          >
            {t(set.labelKey, { defaultValue: set.labelDefault })}
          </Button>
        ))}
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={resolved} strategy={verticalListSortingStrategy}>
          <div className="flex flex-col gap-2">
            {resolved.map((id) => (
              <WidgetRow
                key={id}
                id={id}
                hidden={hidden.includes(id)}
                onToggle={toggleHidden}
                span={spans[id] ?? DASHBOARD_WIDGET_BY_ID[id]?.defaultSpan ?? 6}
                onSetSpan={setSpan}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      <div className="mt-4 flex items-center justify-between gap-3 border-t border-border-light pt-3">
        <span className="text-xs text-content-tertiary">
          {hiddenCount > 0
            ? t('dashboard.layout.hidden_count', {
                defaultValue: '{{count}} hidden',
                count: hiddenCount,
              })
            : t('dashboard.layout.all_visible', {
                defaultValue: 'All sections visible',
              })}
        </span>
        <Button
          variant="ghost"
          size="sm"
          icon={<RotateCcw size={14} />}
          disabled={!isCustomised}
          onClick={reset}
        >
          {t('dashboard.layout.reset', { defaultValue: 'Reset to default' })}
        </Button>
      </div>
    </div>
  );
}

export default DashboardLayoutManager;
