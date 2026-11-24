// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The one-minute reading of a module's data: a story line in plain words, a
// health strip that names each gap and what it breaks, then inputs, the module
// and outputs side by side with live counts and sums. Empty paths stay visible
// as gaps with a link to the module that fills them.

import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, SlidersHorizontal } from 'lucide-react';

import { fmtList, formatNumber } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';

import { stateText, type CentreRow, type FlowCard, type FlowModel } from './flowModel';
import { byImportance, findGaps, gapOf, liveCards, moduleNames, type Gap, type GapKind } from './storyModel';

function amount(value: string | null, isMoney: boolean, currency: string): string | null {
  if (!isMoney || value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? formatCurrency(n, currency || null, undefined, { maximumFractionDigits: 0, minimumFractionDigits: 0 }) : null;
}

function names(t: TFunction, cards: FlowCard[]): string {
  const { names: list, more } = moduleNames(cards);
  const base = fmtList(list);
  return more ? String(t('data_paths.ov_and_more', { defaultValue: '{{list}} +{{count}}', list: base, count: more })) : base;
}

const GAP_KEYS: Record<GapKind, [string, string]> = {
  empty: ['data_paths.ov_gap_empty', '{{module}}: {{entity}} is empty'],
  broken: ['data_paths.ov_gap_broken', 'The link to {{module}} ({{entity}}) is broken'],
  not_installed: ['data_paths.ov_gap_not_installed', '{{module}} is not installed, so {{entity}} cannot flow'],
  no_access: ['data_paths.ov_gap_no_access', 'You have no access to {{entity}} in {{module}}'],
  stale: ['data_paths.ov_gap_stale', '{{entity}} in {{module}} changed after copying: {{count}}'],
};

function gapText(t: TFunction, g: Gap): string {
  const [key, def] = GAP_KEYS[g.kind];
  return String(t(key, { defaultValue: def, entity: g.card.entityLabel, module: g.card.moduleLabel, count: g.card.staleCount ?? 0 }));
}

export function DataPathsOverview({ model }: { model: FlowModel }) {
  const { t } = useTranslation();
  const gaps = findGaps(model);
  const liveIn = liveCards(model.inputs, model.hasProject);
  const liveOut = liveCards(model.outputs, model.hasProject);
  const held = model.entities.filter((e) => (e.count ?? 0) > 0);

  const from = model.inputs.length
    ? String(t('data_paths.ov_story_from', { defaultValue: 'Numbers come from {{list}}', list: names(t, liveIn.length ? liveIn : model.inputs) }))
    : String(t('data_paths.ov_story_from_none', { defaultValue: 'Data is entered here first' }));
  const here = held.length
    ? String(
        t('data_paths.ov_story_here', {
          defaultValue: '{{module}} holds {{list}}',
          module: model.moduleLabel,
          list: fmtList(held.slice(0, 3).map((e) => `${formatNumber(e.count ?? 0)} ${e.label}`)),
        }),
      )
    : String(t('data_paths.ov_story_here_empty', { defaultValue: '{{module}} has no records in this project yet', module: model.moduleLabel }));
  const next = model.outputs.length
    ? String(t('data_paths.ov_story_to', { defaultValue: 'Used next by {{list}}', list: names(t, liveOut.length ? liveOut : model.outputs) }))
    : String(t('data_paths.ov_story_to_none', { defaultValue: 'No other module reads this data' }));

  const critical = gaps.filter((g) => g.card.importance === 'critical').length;
  // A module with nothing recorded is a gap of its own, even when its paths have nothing to carry.
  const moduleEmpty = model.hasProject && model.entities.length > 0 && held.length === 0;
  const warn = gaps.length > 0 || moduleEmpty;

  return (
    <div className="space-y-4" data-testid="dp-overview">
      <ol className="flex flex-col gap-2 rounded-xl border border-border-light bg-surface-secondary p-3 text-sm lg:flex-row lg:items-center" aria-label={t('data_paths.ov_story_aria', { defaultValue: 'How data moves through this module' })} data-testid="dp-story">
        {[from, here, next].map((s, i) => (
          <li key={i} className="flex items-center gap-2 lg:flex-1">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-primary text-xs font-semibold text-content-secondary">{i + 1}</span>
            <span className={i === 1 ? 'font-semibold text-content-primary' : 'text-content-secondary'}>{s}</span>
            {i < 2 && <ArrowRight size={16} className="ms-auto hidden shrink-0 text-content-quaternary lg:block" aria-hidden />}
          </li>
        ))}
      </ol>

      {model.hasProject && (
        <section
          className={`rounded-xl border p-3 ${warn ? 'border-semantic-warning/40 bg-semantic-warning/5' : 'border-semantic-success/40 bg-semantic-success/5'}`}
          aria-labelledby="dp-health-title"
          data-testid="dp-health"
        >
          <h4 id="dp-health-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            {warn ? <AlertTriangle size={16} className="text-semantic-warning" aria-hidden /> : <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />}
            {gaps.length
              ? t('data_paths.ov_health_gaps', { defaultValue: 'Gaps: {{total}}, critical: {{critical}}', total: gaps.length, critical })
              : moduleEmpty
                ? here
                : t('data_paths.ov_health_ok', { defaultValue: 'Every important path carries data' })}
          </h4>
          {gaps.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {gaps.slice(0, 6).map((g) => (
                <li key={g.card.id} className="flex flex-wrap items-baseline gap-x-2 text-sm">
                  <span className={g.card.importance === 'critical' ? 'font-semibold text-content-primary' : 'text-content-primary'}>{gapText(t, g)}</span>
                  {g.card.breaksText && (
                    <span className="text-content-tertiary">
                      {t('data_paths.ov_breaks', { defaultValue: 'Breaks: {{what}}', what: g.card.breaksText })}
                    </span>
                  )}
                  {g.card.href && (
                    <Link to={g.card.href} className="ms-auto font-medium text-oe-blue hover:underline focus-visible:underline">
                      {t('data_paths.ov_fix', { defaultValue: 'Fix in {{module}}', module: g.card.moduleLabel })}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(220px,0.8fr)_minmax(0,1fr)]">
        <Column title={t('data_paths.ov_inputs', { defaultValue: 'Comes in from' })} cards={model.inputs} model={model} empty={t('data_paths.ov_no_inputs', { defaultValue: 'Nothing flows in: data starts here' })} />
        <Centre model={model} />
        <Column title={t('data_paths.ov_outputs', { defaultValue: 'Goes out to' })} cards={model.outputs} model={model} empty={t('data_paths.ov_no_outputs', { defaultValue: 'No module reads this data yet' })} />
      </div>

      {model.params.length > 0 && (
        <section className="rounded-xl border border-border-light p-3" data-testid="dp-params">
          <h4 className="mb-1 flex items-center gap-2 text-sm font-semibold text-content-primary">
            <SlidersHorizontal size={14} aria-hidden />
            {t('data_paths.ov_params', { defaultValue: 'Settings that change these numbers' })}
          </h4>
          <ul className="space-y-1 text-sm text-content-secondary">
            {model.params.map((p) => (
              <li key={p.id}>{p.note}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Column({ title, cards, model, empty }: { title: string; cards: FlowCard[]; model: FlowModel; empty: string }) {
  const sorted = [...cards].sort(byImportance);
  return (
    <section aria-label={title}>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">{title}</h4>
      {sorted.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border-light px-3 py-4 text-sm text-content-tertiary">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {sorted.map((c) => (
            <PathCard key={c.id} card={c} model={model} />
          ))}
        </ul>
      )}
    </section>
  );
}

const WEIGHT: Record<FlowCard['importance'], string> = {
  critical: 'border-s-4 border-s-content-primary',
  high: 'border-s-2 border-s-content-secondary',
  supporting: 'border-s border-s-border-light',
};

function PathCard({ card, model }: { card: FlowCard; model: FlowModel }) {
  const { t } = useTranslation();
  const gap = gapOf(card, model.hasProject);
  const money = amount(card.value, card.isMoney, model.currency);
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <span className={`truncate ${card.importance === 'supporting' ? 'text-sm text-content-secondary' : 'text-sm font-semibold text-content-primary'}`}>{card.moduleLabel}</span>
        {card.importance !== 'supporting' && <span className="shrink-0 text-2xs uppercase tracking-wide text-content-tertiary">{card.importanceLabel}</span>}
      </div>
      <div className="text-xs text-content-tertiary">{card.entityLabel}</div>
      {gap ? (
        <div className="mt-1 flex items-center gap-1 text-xs text-semantic-warning">
          <CircleDashed size={12} aria-hidden />
          {gap === 'empty' ? t('data_paths.ov_empty_card', { defaultValue: 'Empty: add records to fill this path' }) : gap === 'stale' ? card.staleLabel : stateText(t, card.state)}
        </div>
      ) : card.count !== null ? (
        <div className="mt-1 flex items-baseline gap-3 tabular-nums">
          <span className="text-base font-semibold text-content-primary">{formatNumber(card.count)}</span>
          {money && <span className="text-sm text-content-secondary">{money}</span>}
        </div>
      ) : null}
    </>
  );
  const cls = `block rounded-lg border border-border-light bg-surface-primary px-3 py-2 ${WEIGHT[card.importance]} ${gap ? 'border-dashed' : ''}`;
  return (
    <li data-testid={`dp-card-${card.id}`} data-gap={gap ?? undefined}>
      {card.href ? (
        <Link to={card.href} className={`${cls} hover:bg-surface-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue`} aria-label={card.sentence}>
          {body}
        </Link>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}

function Centre({ model }: { model: FlowModel }) {
  const { t } = useTranslation();
  return (
    <section className="rounded-xl border-2 border-oe-blue/40 bg-oe-blue/5 p-3" aria-label={model.moduleLabel}>
      <h4 className="text-base font-semibold text-content-primary">{model.moduleLabel}</h4>
      {model.why && <p className="mt-1 text-sm text-content-secondary">{model.why}</p>}
      {model.entities.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {model.entities.map((e: CentreRow) => {
            const money = amount(e.value, !!e.valueText, model.currency);
            const row = (
              <span className="flex items-baseline justify-between gap-2 text-sm">
                <span className="truncate text-content-secondary">{e.label}</span>
                <span className="shrink-0 tabular-nums text-content-primary">
                  {e.count === null ? '' : formatNumber(e.count)}
                  {money && <span className="ms-2 text-content-secondary">{money}</span>}
                </span>
              </span>
            );
            return <li key={e.id}>{e.href ? <Link to={e.href} className="block rounded px-1 hover:bg-surface-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue">{row}</Link> : row}</li>;
          })}
        </ul>
      )}
      {!model.hasProject && (
        <p className="mt-3 text-xs text-content-tertiary">{t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })}</p>
      )}
    </section>
  );
}
