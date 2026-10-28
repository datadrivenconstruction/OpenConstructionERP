// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Activity timeline for the Coordination Hub.
 *
 * Renders the 50 most-recent events as a vertical list. Each event row
 * carries an icon picked by ``event.type``, a relative-time label, the
 * server-formatted summary and an optional click-through deep link.
 */

import {
  Radar,
  Layers,
  ClipboardCheck,
  Download,
  Activity,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { EmptyState } from '@/shared/ui/EmptyState';
import type {
  CoordinationTimelineEvent,
  CoordinationTimelineResponse,
} from './types';

export interface CoordinationTimelineProps {
  data: CoordinationTimelineResponse | undefined;
  isLoading?: boolean;
  /**
   * When `true` the component drops its own card chrome (outer border /
   * padding / shadow) and inner title — it is being rendered inside a
   * `GlassPanel` that already supplies them, so the standalone wrapper
   * would double the title and nest a card-in-a-card. Standalone callers
   * leave it `false` to keep the self-contained card.
   */
  embedded?: boolean;
}

function IconForType({ type }: { type: string }) {
  switch (type) {
    case 'clash_run':
      return <Radar size={16} className="text-amber-600" />;
    case 'federation_created':
      return <Layers size={16} className="text-blue-600" />;
    case 'rule_pack_installed':
      return <ClipboardCheck size={16} className="text-emerald-600" />;
    case 'bcf_export':
      return <Download size={16} className="text-purple-600" />;
    default:
      return <Activity size={16} className="text-content-secondary" />;
  }
}

type TFn = (key: string, opts?: Record<string, unknown>) => string;

/**
 * Build the localised event label from the structured `type` + `params`
 * payload (the server no longer ships a pre-rendered English string).
 * Falls back to `event.summary` for any unknown event type so a new
 * server-side event kind still renders something readable.
 */
function buildLabel(event: CoordinationTimelineEvent, t: TFn): string {
  const p = event.params ?? {};
  // Back-compat: an event without structured params (older payload or a
  // non-UI source) keeps its pre-rendered English summary rather than
  // rendering an empty template.
  if (Object.keys(p).length === 0) return event.summary;
  const name = p.name ?? '';
  switch (event.type) {
    case 'clash_run':
      return p.kind === 'completed'
        ? t('coordination.tl_clash_completed', {
            defaultValue: "Clash run '{{name}}' completed - {{total}} clashes",
            name,
            total: p.total ?? 0,
          })
        : t('coordination.tl_clash_pending', {
            defaultValue: "Clash run '{{name}}' - {{status}}",
            name,
            status: p.status ?? 'pending',
          });
    case 'federation_created':
      return t('coordination.tl_federation_created', {
        defaultValue: "Federation '{{name}}' created",
        name,
      });
    case 'rule_pack_installed':
      return t('coordination.tl_rule_pack_installed', {
        defaultValue: "Rule pack '{{name}}' installed",
        name,
      });
    case 'bcf_export':
      return t('coordination.tl_bcf_topic', {
        defaultValue: "BCF topic '{{name}}' ({{status}})",
        name,
        status: p.status ?? '',
      });
    default:
      return event.summary;
  }
}

function TimelineRow({ event }: { event: CoordinationTimelineEvent }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const clickable = Boolean(event.target);
  const label = buildLabel(event, t);
  const handleClick = () => {
    if (event.target) navigate(event.target);
  };
  return (
    <li
      data-testid={`timeline-event-${event.type}`}
      className="flex items-start gap-3 border-b border-border py-3 last:border-b-0"
    >
      <div className="mt-0.5 flex-shrink-0">
        <IconForType type={event.type} />
      </div>
      <div className="min-w-0 flex-1">
        <button
          type="button"
          disabled={!clickable}
          onClick={handleClick}
          className={
            clickable
              ? 'text-left text-sm font-medium text-content-primary hover:text-blue-600 focus:outline-none focus-visible:underline'
              : 'cursor-default text-left text-sm font-medium text-content-primary'
          }
        >
          {label}
        </button>
        <div className="mt-0.5 text-xs text-content-tertiary">
          <DateDisplay value={event.ts} format="relative" />
        </div>
      </div>
    </li>
  );
}

function SkeletonRow() {
  return (
    <li className="flex animate-pulse items-start gap-3 border-b border-border py-3 last:border-b-0">
      <div className="h-4 w-4 rounded bg-slate-200" />
      <div className="flex-1">
        <div className="h-3 w-2/3 rounded bg-slate-200" />
        <div className="mt-2 h-3 w-1/4 rounded bg-slate-100" />
      </div>
    </li>
  );
}

export function CoordinationTimeline({
  data,
  isLoading,
  embedded = false,
}: CoordinationTimelineProps) {
  const { t } = useTranslation();

  const body =
    isLoading || !data ? (
      <ul>
        <SkeletonRow />
        <SkeletonRow />
        <SkeletonRow />
      </ul>
    ) : data.events.length === 0 ? (
      <EmptyState
        title={t('coordination.timeline_empty', {
          defaultValue: 'No coordination activity yet.',
        })}
        description=""
      />
    ) : (
      <ul>
        {data.events.map((event, idx) => (
          <TimelineRow key={`${event.ts}-${event.type}-${idx}`} event={event} />
        ))}
      </ul>
    );

  // Embedded inside a GlassPanel: it already paints the card + title, so
  // we drop our own chrome to avoid a card-in-a-card with a doubled title.
  if (embedded) {
    return <div data-testid="coordination-timeline">{body}</div>;
  }

  return (
    <div
      data-testid="coordination-timeline"
      className="rounded-xl border border-border bg-surface p-4 shadow-sm"
    >
      <h3 className="mb-3 text-base font-semibold text-content-primary">
        {t('coordination.timeline_title', {
          defaultValue: 'Recent Activity',
        })}
      </h3>
      {body}
    </div>
  );
}
