// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The drawer's picture: sources -> this module -> consumers, three fixed
// columns, HTML cards over one SVG of curves. No layout library: at most ~15
// cards, so fixed geometry stays readable and cheap. Columns mirror in RTL.

import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowDown, TriangleAlert } from 'lucide-react';

import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useIsRTL } from '@/shared/hooks/useIsRTL';
import { formatNumber } from '@/shared/lib/formatters';

import type { FlowCard, FlowModel } from './flowModel';
import { stateText } from './flowModel';
import { useNarrow, useReducedMotion } from './motion';

const CARD_H = 76;
const GAP = 12;
const ROW_H = 30;

function edgeClass(card: FlowCard, dimmed: boolean, lit: boolean): string {
  if (card.state === 'broken' || card.state === 'not_installed') return 'text-semantic-error';
  if (card.state === 'stale') return 'text-semantic-warning';
  if (card.state === 'no_access' || card.count === 0) return 'text-content-quaternary';
  if (lit) return 'text-oe-blue';
  return dimmed ? 'text-border' : 'text-border';
}

function strokeWidth(card: FlowCard): number {
  return card.importance === 'critical' ? 2.5 : card.importance === 'high' ? 1.75 : 1.25;
}

function PathCard({
  card,
  currency,
  hasProject,
  dimmed,
  lit,
  onHover,
}: {
  card: FlowCard;
  currency: string;
  hasProject: boolean;
  dimmed: boolean;
  lit: boolean;
  onHover: (id: string | null) => void;
}) {
  const { t } = useTranslation();
  const masked = card.state === 'no_access';
  const problem = card.state === 'broken' || card.state === 'not_installed' || card.state === 'unknown';
  const body = (
    <div
      className={clsx(
        'flex h-full flex-col justify-between rounded-xl border bg-surface-primary p-3 transition-opacity duration-150',
        lit ? 'border-oe-blue' : 'border-border-light',
        dimmed && 'opacity-40',
        card.href && 'hover:shadow-sm',
      )}
      style={{ borderInlineStartWidth: 3, borderInlineStartColor: card.tone }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-content-secondary" title={card.moduleLabel}>
          {card.moduleLabel}
        </span>
        {card.importance !== 'supporting' && (
          <span
            className={clsx(
              'shrink-0 rounded-full px-1.5 text-2xs font-medium',
              card.importance === 'critical' ? 'bg-semantic-error-bg text-semantic-error' : 'bg-oe-blue-subtle text-oe-blue-text',
            )}
            title={card.breaksText ?? undefined}
          >
            {card.importanceLabel}
          </span>
        )}
      </div>
      {masked ? (
        <span className="text-xs text-content-tertiary">{stateText(t, 'no_access')}</span>
      ) : problem ? (
        <span className={clsx('text-xs', card.state === 'unknown' ? 'text-content-tertiary' : 'text-semantic-error')}>
          {stateText(t, card.state)}
        </span>
      ) : (
        <div className="flex min-w-0 items-baseline gap-2">
          {hasProject && card.count !== null ? (
            card.count === 0 ? (
              <span
                className="text-lg font-semibold tabular-nums text-content-quaternary"
                title={t('data_paths.no_records', { defaultValue: 'No records yet' })}
              >
                0
              </span>
            ) : (
              <span className="text-lg font-semibold tabular-nums text-content-primary">{formatNumber(card.count)}</span>
            )
          ) : null}
          <span className="truncate text-xs text-content-tertiary">{card.entityLabel}</span>
          {card.isMoney && card.value !== null && card.count ? (
            <MoneyDisplay amount={card.value} currency={currency || undefined} compact className="ms-auto text-xs" />
          ) : null}
        </div>
      )}
      {card.staleLabel && card.staleCount ? (
        <span className="flex items-center gap-1 text-2xs text-semantic-warning">
          <TriangleAlert size={12} aria-hidden />
          {card.staleLabel} · {formatNumber(card.staleCount)}
        </span>
      ) : null}
    </div>
  );
  const common = {
    onMouseEnter: () => onHover(card.id),
    onMouseLeave: () => onHover(null),
    onFocus: () => onHover(card.id),
    onBlur: () => onHover(null),
    style: { height: CARD_H },
    'data-testid': `dp-card-${card.direction}`,
  };
  if (card.href && !masked) {
    return (
      <Link to={card.href} className="block rounded-xl focus-visible:outline-none" {...common} title={card.sentence}>
        {body}
      </Link>
    );
  }
  return (
    <div tabIndex={0} {...common} title={card.sentence} className="rounded-xl">
      {body}
    </div>
  );
}

export interface DataPathsFlowProps {
  model: FlowModel;
  describedBy?: string;
}

export function DataPathsFlow({ model, describedBy }: DataPathsFlowProps) {
  const { t } = useTranslation();
  const rtl = useIsRTL();
  const narrow = useNarrow();
  const reduce = useReducedMotion();
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(680);
  const [hoverCard, setHoverCard] = useState<string | null>(null);
  const [hoverParam, setHoverParam] = useState<string | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width || 680));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const param = model.params.find((p) => p.id === hoverParam) ?? null;
  const litIds = useMemo(() => {
    if (param) return new Set(param.drivesPaths);
    if (hoverCard) return new Set([hoverCard]);
    return null;
  }, [param, hoverCard]);

  const sideW = Math.max(150, (width - 2 * 40) / 3.4);
  const centreW = sideW * 1.4;
  const leftX = 0;
  const centreX = sideW + 40;
  const rightX = centreX + centreW + 40;
  const centreH = 48 + model.entities.length * ROW_H + (model.params.length ? 28 + model.params.length * ROW_H : 0);
  const rows = Math.max(model.inputs.length, model.outputs.length);
  const height = Math.max(rows * (CARD_H + GAP) - GAP, centreH, CARD_H);
  const centreTop = (height - centreH) / 2;
  const sideTop = (n: number) => (height - (n * (CARD_H + GAP) - GAP)) / 2;

  const mirror = (x: number, w = 0) => (rtl ? width - x - w : x);

  if (narrow) {
    return (
      <div className="space-y-2" aria-describedby={describedBy}>
        {model.inputs.map((c) => (
          <PathCard key={c.id} card={c} currency={model.currency} hasProject={model.hasProject} dimmed={false} lit={false} onHover={() => undefined} />
        ))}
        {model.inputs.length > 0 && <ArrowDown size={16} className="mx-auto text-content-quaternary" aria-hidden />}
        <CentreCard model={model} onParam={setHoverParam} activeParam={hoverParam} />
        {model.outputs.length > 0 && <ArrowDown size={16} className="mx-auto text-content-quaternary" aria-hidden />}
        {model.outputs.map((c) => (
          <PathCard key={c.id} card={c} currency={model.currency} hasProject={model.hasProject} dimmed={false} lit={false} onHover={() => undefined} />
        ))}
      </div>
    );
  }

  const curve = (x1: number, y1: number, x2: number, y2: number) => {
    const mx = (x1 + x2) / 2;
    return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;
  };
  const anchors = (n: number, i: number) => centreTop + 24 + ((i + 1) * (centreH - 48)) / (n + 1);

  const edges = [
    ...model.inputs.map((c, i) => {
      const y1 = sideTop(model.inputs.length) + i * (CARD_H + GAP) + CARD_H / 2;
      const y2 = anchors(model.inputs.length, i);
      const x1 = rtl ? width - (leftX + sideW) : leftX + sideW;
      const x2 = rtl ? width - centreX : centreX;
      return { c, d: curve(x1, y1, x2, y2) };
    }),
    ...model.outputs.map((c, i) => {
      const y1 = anchors(model.outputs.length, i);
      const y2 = sideTop(model.outputs.length) + i * (CARD_H + GAP) + CARD_H / 2;
      const x1 = rtl ? width - (centreX + centreW) : centreX + centreW;
      const x2 = rtl ? width - rightX : rightX;
      return { c, d: curve(x1, y1, x2, y2) };
    }),
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
        <span>{t('data_paths.sources', { defaultValue: 'Sources' })}</span>
        <span className="text-center">{t('data_paths.this_module', { defaultValue: 'This module' })}</span>
        <span className="text-end">{t('data_paths.consumers', { defaultValue: 'Consumers' })}</span>
      </div>
      <div ref={box} className="relative" style={{ height }}>
        <svg
          className="pointer-events-none absolute inset-0 overflow-visible"
          width={width}
          height={height}
          role="img"
          aria-label={t('data_paths.flow_aria', { defaultValue: 'Data paths of {{module}}', module: model.moduleLabel })}
          aria-describedby={describedBy}
          data-testid="dp-flow-svg"
        >
          {edges.map(({ c, d }) => {
            const lit = !!litIds?.has(c.id);
            const dimmed = !!litIds && !lit;
            const dashed = c.state === 'stale' || c.state === 'not_installed';
            return (
              <g key={c.id} className={clsx(edgeClass(c, dimmed, lit), 'transition-opacity duration-150')} opacity={dimmed ? 0.25 : 1}>
                <path d={d} fill="none" stroke="currentColor" strokeWidth={strokeWidth(c) + (lit ? 0.75 : 0)} strokeDasharray={dashed ? '6 4' : undefined} />
                {c.active && !reduce && c.state === 'ok' && (
                  <path d={d} fill="none" stroke="currentColor" className="text-oe-blue" strokeOpacity={0.3} strokeWidth={strokeWidth(c) + 1} strokeDasharray="4 10">
                    <animate attributeName="stroke-dashoffset" from={rtl ? '-28' : '28'} to="0" dur="2.4s" repeatCount="indefinite" />
                  </path>
                )}
              </g>
            );
          })}
        </svg>
        {model.inputs.map((c, i) => (
          <div key={c.id} className="absolute" style={{ left: mirror(leftX, sideW), top: sideTop(model.inputs.length) + i * (CARD_H + GAP), width: sideW }}>
            <PathCard card={c} currency={model.currency} hasProject={model.hasProject} dimmed={!!litIds && !litIds.has(c.id)} lit={!!litIds?.has(c.id)} onHover={setHoverCard} />
          </div>
        ))}
        <div className="absolute" style={{ left: mirror(centreX, centreW), top: centreTop, width: centreW }}>
          <CentreCard model={model} onParam={setHoverParam} activeParam={hoverParam} />
        </div>
        {model.outputs.map((c, i) => (
          <div key={c.id} className="absolute" style={{ left: mirror(rightX, sideW), top: sideTop(model.outputs.length) + i * (CARD_H + GAP), width: sideW }}>
            <PathCard card={c} currency={model.currency} hasProject={model.hasProject} dimmed={!!litIds && !litIds.has(c.id)} lit={!!litIds?.has(c.id)} onHover={setHoverCard} />
          </div>
        ))}
      </div>
      <p className="min-h-5 text-xs text-content-secondary" aria-live="polite" data-testid="dp-param-note">
        {param ? param.note : ''}
      </p>
    </div>
  );
}

function CentreCard({
  model,
  onParam,
  activeParam,
}: {
  model: FlowModel;
  onParam: (id: string | null) => void;
  activeParam: string | null;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-3 shadow-sm" style={{ borderTopWidth: 3, borderTopColor: model.tone }}>
      <div className="mb-2 truncate text-sm font-semibold text-content-primary">{model.moduleLabel}</div>
      <ul className="space-y-0.5">
        {model.entities.map((e) => (
          <li key={e.id} className="flex h-7 items-center justify-between gap-2 text-xs">
            {e.href ? (
              <Link to={e.href} className="truncate text-content-secondary hover:text-oe-blue">
                {e.label}
              </Link>
            ) : (
              <span className="truncate text-content-secondary">{e.label}</span>
            )}
            <span className="flex shrink-0 items-baseline gap-2 tabular-nums text-content-primary">
              {e.count !== null && <span className="font-medium">{formatNumber(e.count)}</span>}
              {e.valueText && e.value !== null && e.count ? (
                <MoneyDisplay amount={e.value} currency={model.currency || undefined} compact className="text-content-tertiary" />
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      {model.params.length > 0 && (
        <div className="mt-2 border-t border-border-light pt-2">
          <div className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('data_paths.parameters', { defaultValue: 'Parameters' })}
          </div>
          <ul className="space-y-0.5">
            {model.params.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className={clsx(
                    'flex h-7 w-full items-center gap-1.5 rounded-sm px-1 text-start text-xs transition-colors duration-150',
                    activeParam === p.id ? 'bg-oe-blue-subtle text-oe-blue-text' : 'text-content-secondary hover:bg-surface-secondary',
                  )}
                  onMouseEnter={() => onParam(p.id)}
                  onMouseLeave={() => onParam(null)}
                  onFocus={() => onParam(p.id)}
                  onBlur={() => onParam(null)}
                  aria-describedby="dp-param-note"
                >
                  <span className="text-oe-blue" aria-hidden>
                    *
                  </span>
                  <span className="truncate">{p.label}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
