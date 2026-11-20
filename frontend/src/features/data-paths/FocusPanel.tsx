// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The right panel of the data paths window for the focused module: what it
// is for, how far its data reaches (impact ring and level), who works in it,
// where it sits on the whole platform, what goes in and which validation
// rules guard that, the data traces through it (playable) and what changed
// here and downstream in the last 30 days.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, ChevronLeft, ChevronRight, Info, Pause, Play, ShieldCheck, Users } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { fmtList, formatNumber } from '@/shared/lib/formatters';

import { useModuleChanges, type EdgeOut, type MapModule, type ModuleFocus, type Trace } from './api';
import { humanize, moduleLabel } from './flowModel';
import { layeredLayout } from './layout';
import { moduleMeta } from './moduleMeta';
import { RoleHex, roleName } from './RoleHex';
import { flowEdges, impactOf, type FlowEdge, type ImpactLevel } from './swimlane';

export interface TraceState {
  id: string;
  step: number;
  playing: boolean;
}

export interface FocusPanelProps {
  focus: string;
  info: ModuleFocus | undefined;
  modules: MapModule[];
  edges: EdgeOut[];
  technical: boolean;
  projectId: string | null;
  /** Downstream modules in the window, nearest first (for the changes list). */
  downstream: string[];
  trace: TraceState | null;
  onTrace: (next: TraceState | null) => void;
  onOpen: (module: string) => void;
  onRefocus: (module: string) => void;
  onPeople?: () => void;
}

const LEVEL: Record<ImpactLevel, { key: string; def: string; tone: string }> = {
  high: { key: 'data_paths.impact_high', def: 'High impact', tone: 'var(--oe-error)' },
  medium: { key: 'data_paths.impact_medium', def: 'Medium impact', tone: 'var(--oe-blue)' },
  endpoint: { key: 'data_paths.impact_endpoint', def: 'Endpoint', tone: 'var(--oe-text-tertiary)' },
};

function Section({ title, children, aside, testId }: { title: string; children: React.ReactNode; aside?: React.ReactNode; testId?: string }) {
  return (
    <section className="rounded-2xl border border-border-light bg-surface-primary p-4 shadow-xs" data-testid={testId}>
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="text-2xs font-semibold uppercase tracking-widest text-content-tertiary">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ImpactRing({ percent, tone, label }: { percent: number; tone: string; label: string }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const shown = Math.max(0, Math.min(100, percent));
  return (
    <svg width={76} height={76} viewBox="0 0 76 76" role="img" aria-label={label} className="shrink-0">
      <circle cx={38} cy={38} r={r} fill="none" stroke="var(--oe-border-light)" strokeWidth={7} />
      <circle
        cx={38}
        cy={38}
        r={r}
        fill="none"
        stroke={tone}
        strokeWidth={7}
        strokeLinecap="round"
        strokeDasharray={`${(shown / 100) * c} ${c}`}
        transform="rotate(-90 38 38)"
        className="transition-[stroke-dasharray] duration-500 motion-reduce:transition-none"
      />
      <text x={38} y={43} textAnchor="middle" fontSize={15} fontWeight={600} fill="var(--oe-text-primary)">
        {formatNumber(shown)}%
      </text>
    </svg>
  );
}

/** The whole platform in a thumbnail: blue feeds this module, dark is here, orange is what it affects. */
function OverallPicture({ focus, modules, fe, onRefocus }: { focus: string; modules: MapModule[]; fe: FlowEdge[]; onRefocus: (m: string) => void }) {
  const { t } = useTranslation();
  const { pos, role, w, h } = useMemo(() => {
    const linked = new Set<string>();
    for (const e of fe) {
      linked.add(e.source);
      linked.add(e.target);
    }
    const shown = modules.filter((m) => linked.has(m.name) || m.name === focus);
    const p = layeredLayout(
      shown.map((m) => ({ id: m.name, stage: moduleMeta(m.name).stage, sortKey: `${moduleMeta(m.name).familyId}:${m.name}` })),
      fe,
      { nodeWidth: 20, nodeHeight: 7, columnGap: 10, rowGap: 3, bandColumns: 10, sweeps: 4 },
    );
    const out = new Map<string, 'source' | 'here' | 'impact'>();
    const walk = (forward: boolean) => {
      const stack = [focus];
      const seen = new Set([focus]);
      while (stack.length) {
        const cur = stack.pop()!;
        for (const e of fe) {
          const [a, b] = forward ? [e.source, e.target] : [e.target, e.source];
          if (a === cur && !seen.has(b)) {
            seen.add(b);
            stack.push(b);
            if (!out.has(b)) out.set(b, forward ? 'impact' : 'source');
          }
        }
      }
    };
    walk(true);
    walk(false);
    out.set(focus, 'here');
    let mw = 0;
    let mh = 0;
    for (const v of p.values()) {
      mw = Math.max(mw, v.x + 20);
      mh = Math.max(mh, v.y + 7);
    }
    return { pos: p, role: out, w: Math.max(1, mw), h: Math.max(1, mh) };
  }, [focus, modules, fe]);
  const fill = { source: 'var(--oe-blue)', here: 'var(--oe-text-primary)', impact: 'var(--oe-warning)' } as const;
  const dependent = [...role.values()].filter((v) => v === 'impact').length;
  return (
    <Section
      title={t('data_paths.overall_title', { defaultValue: 'Overall picture' })}
      aside={
        <span className="text-xs text-content-tertiary">
          {t('data_paths.overall_dependent', { defaultValue: 'Dependent modules: {{count}}', count: dependent })}
        </span>
      }
      testId="dp-overall"
    >
      <svg viewBox={`-2 -2 ${w + 4} ${h + 4}`} className="h-auto w-full rounded-lg bg-surface-secondary" role="img" aria-label={t('data_paths.overall_title', { defaultValue: 'Overall picture' })}>
        {[...pos].map(([id, p]) => {
          const r = role.get(id);
          return (
            <rect
              key={id}
              x={p.x}
              y={p.y}
              width={20}
              height={7}
              rx={1.5}
              fill={r ? fill[r] : 'var(--oe-border)'}
              opacity={r ? 1 : 0.55}
              className="cursor-pointer"
              onClick={() => onRefocus(id)}
            >
              <title>{moduleLabel(t, id)}</title>
            </rect>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-content-secondary">
        {(
          [
            ['source', 'data_paths.legend_source', 'Source'],
            ['here', 'data_paths.legend_here', 'Here'],
            ['impact', 'data_paths.legend_impact', 'Impact'],
          ] as const
        ).map(([k, key, def]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: fill[k] }} aria-hidden />
            {t(key, { defaultValue: def })}
          </span>
        ))}
      </div>
    </Section>
  );
}

function TraceRow({ trace, state, onTrace }: { trace: Trace; state: TraceState | null; onTrace: (s: TraceState | null) => void }) {
  const { t } = useTranslation();
  const active = state?.id === trace.id;
  const step = active ? state!.step : (trace.at[0] ?? 0);
  const total = trace.steps.length;
  return (
    <li className={clsx('rounded-xl border p-3 transition-colors duration-150', active ? 'border-oe-blue/50 bg-oe-blue-subtle/40' : 'border-border-light')} data-testid="dp-trace">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">{t(trace.label, { defaultValue: humanize(trace.id) })}</p>
          <p className="text-xs text-content-tertiary">{t(trace.summary, { defaultValue: '' })}</p>
        </div>
        <span className="shrink-0 rounded-full bg-surface-secondary px-2 py-0.5 text-2xs font-medium tabular-nums text-content-secondary">
          {t('data_paths.trace_step', { defaultValue: 'Step {{n}} of {{m}}', n: step + 1, m: total })}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-1">
        <button
          type="button"
          className="flex h-7 w-7 items-center justify-center rounded-full bg-oe-blue text-white hover:bg-oe-blue-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1"
          onClick={() =>
            active && state!.playing
              ? onTrace({ ...state!, playing: false })
              : onTrace({ id: trace.id, step: active && step < total - 1 ? step : 0, playing: true })
          }
          aria-label={active && state!.playing ? t('data_paths.trace_pause', { defaultValue: 'Pause' }) : t('data_paths.trace_play', { defaultValue: 'Play' })}
          data-testid="dp-trace-play"
        >
          {active && state!.playing ? <Pause size={13} /> : <Play size={13} className="ms-px" />}
        </button>
        <button
          type="button"
          className="flex h-7 w-7 items-center justify-center rounded-full text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          disabled={step <= 0}
          onClick={() => onTrace({ id: trace.id, step: Math.max(0, step - 1), playing: false })}
          aria-label={t('data_paths.trace_prev', { defaultValue: 'Previous step' })}
        >
          <ChevronLeft size={14} />
        </button>
        <button
          type="button"
          className="flex h-7 w-7 items-center justify-center rounded-full text-content-secondary hover:bg-surface-secondary disabled:opacity-40"
          disabled={step >= total - 1}
          onClick={() => onTrace({ id: trace.id, step: Math.min(total - 1, step + 1), playing: false })}
          aria-label={t('data_paths.trace_next', { defaultValue: 'Next step' })}
        >
          <ChevronRight size={14} />
        </button>
      </div>
      {active && (
        <ol className="mt-2 space-y-1">
          {trace.steps.map((s, i) => (
            <li
              key={`${s.module}-${i}`}
              className={clsx('flex items-center gap-2 text-xs', i === step ? 'font-medium text-content-primary' : i < step ? 'text-content-secondary' : 'text-content-quaternary')}
            >
              <span
                className={clsx(
                  'flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-2xs tabular-nums',
                  i <= step ? 'bg-oe-blue text-white' : 'bg-surface-secondary text-content-tertiary',
                )}
              >
                {i + 1}
              </span>
              <span className="truncate">
                {t(s.label, { defaultValue: humanize(s.label.split('.').pop() ?? s.label) })}
                <span className="text-content-tertiary"> · {moduleLabel(t, s.module)}</span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}

const ACTION_KEYS: Record<string, [string, string]> = {
  create: ['data_paths.action_create', 'created'],
  update: ['data_paths.action_update', 'changed'],
  delete: ['data_paths.action_delete', 'deleted'],
};

export function FocusPanel(props: FocusPanelProps) {
  const { focus, info, modules, edges, technical, projectId, downstream, trace, onTrace, onOpen, onRefocus, onPeople } = props;
  const { t } = useTranslation();
  const meta = moduleMeta(focus);
  const mod = modules.find((m) => m.name === focus);
  const fe = useMemo(() => flowEdges(edges, { technical }), [edges, technical]);
  const impact = useMemo(() => impactOf(focus, fe, modules.length), [focus, fe, modules.length]);
  const level = LEVEL[impact.level];
  const inputs = useMemo(() => [...new Set(fe.filter((e) => e.target === focus).map((e) => e.source))], [fe, focus]);
  const changes = useModuleChanges(focus, projectId, downstream);
  const roles = info?.roles.length ? info.roles : (mod?.roles ?? []);
  const why = info?.why || mod?.why || '';

  const byModule = useMemo(() => {
    const out = new Map<string, NonNullable<typeof changes.data>['changes']>();
    for (const c of changes.data?.changes ?? []) out.set(c.module, [...(out.get(c.module) ?? []), c]);
    return out;
  }, [changes.data]);

  return (
    <aside className="flex flex-col gap-3" aria-label={t('data_paths.panel_aria', { defaultValue: 'About this module' })} data-testid="dp-focus-panel">
      <section
        className="rounded-2xl border p-4 shadow-xs"
        style={{
          borderColor: `color-mix(in srgb, ${meta.tone} 30%, transparent)`,
          background: `color-mix(in srgb, ${meta.tone} 6%, var(--oe-bg))`,
        }}
      >
        {meta.familyLabelKey && (
          <p className="text-2xs font-semibold uppercase tracking-widest" style={{ color: meta.tone }}>
            {t(meta.familyLabelKey, { defaultValue: meta.familyDefaultLabel ?? '' })}
          </p>
        )}
        <h2 className="mt-1 text-xl font-semibold leading-tight text-content-primary">{moduleLabel(t, focus, mod?.display_name)}</h2>
        {why && <p className="mt-1.5 text-sm text-content-secondary">{t(why, { defaultValue: '' })}</p>}
        {meta.route && (
          <Button className="mt-3" size="sm" icon={<ArrowRight size={14} />} onClick={() => onOpen(focus)} data-testid="dp-open-module">
            {t('data_paths.open_module', { defaultValue: 'Open module' })}
          </Button>
        )}
      </section>

      <section className="flex items-center gap-4 rounded-2xl border border-border-light bg-surface-primary p-4 shadow-xs" data-testid="dp-impact">
        <ImpactRing
          percent={impact.percent}
          tone={level.tone}
          label={t('data_paths.impact_ring_aria', { defaultValue: 'Reaches {{percent}}% of the platform', percent: impact.percent })}
        />
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-base font-semibold" style={{ color: level.tone }}>
            {t(level.key, { defaultValue: level.def })}
            <span
              title={t('data_paths.impact_rule', {
                defaultValue: 'High: reaches 3 or more end results or 6 or more modules. Endpoint: nothing reads its data.',
              })}
              className="text-content-tertiary"
            >
              <Info size={13} aria-hidden />
            </span>
          </p>
          <p className="text-sm text-content-secondary">
            {t('data_paths.impact_affects', { defaultValue: 'Modules downstream: {{count}}', count: impact.affected })}
          </p>
          {impact.roots.length > 0 && (
            <p className="truncate text-xs text-content-tertiary">
              {t('data_paths.impact_from', {
                defaultValue: 'From: {{list}}',
                list: fmtList(impact.roots.slice(0, 3).map((r) => moduleLabel(t, r))),
              })}
            </p>
          )}
        </div>
      </section>

      <Section
        title={t('data_paths.who_title', { defaultValue: 'Who is involved' })}
        aside={
          onPeople ? (
            <button type="button" onClick={onPeople} className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline">
              <Users size={12} aria-hidden />
              {t('data_paths.who_people', { defaultValue: 'People' })}
            </button>
          ) : null
        }
        testId="dp-who"
      >
        {roles.length === 0 ? (
          <p className="text-sm text-content-tertiary">{t('data_paths.who_empty', { defaultValue: 'No roles described yet' })}</p>
        ) : (
          <ul className="space-y-2.5">
            {roles.map((r) => {
              const duty = info?.duties.find((d) => d.role === r);
              return (
                <li key={r} className="flex items-start gap-2.5">
                  <RoleHex role={r} size={24} onClick={onPeople} />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-content-primary">{roleName(t, r)}</p>
                    {duty && <p className="text-xs text-content-secondary">{t(duty.label, { defaultValue: '' })}</p>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <OverallPicture focus={focus} modules={modules} fe={fe} onRefocus={onRefocus} />

      <Section title={t('data_paths.inputs_title', { defaultValue: 'What goes in here' })} testId="dp-inputs">
        {inputs.length === 0 && !(info?.external.length ?? 0) ? (
          <p className="text-sm text-content-tertiary">{t('data_paths.inputs_empty', { defaultValue: 'Nothing flows in from other modules' })}</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {(info?.external ?? []).map((x) => (
              <li key={x.label} className="rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-content-secondary">
                {t(x.label, { defaultValue: '' })}
              </li>
            ))}
            {inputs.map((m) => (
              <li key={m}>
                <button
                  type="button"
                  onClick={() => onRefocus(m)}
                  className="rounded-full border border-border-light bg-surface-secondary px-2.5 py-1 text-xs text-content-primary hover:border-oe-blue/50"
                >
                  {moduleLabel(t, m)}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3">
          {info?.rules.length ? (
            <div className="rounded-xl bg-semantic-success-bg px-3 py-2" data-testid="dp-checked">
              <p className="flex items-center gap-1.5 text-xs font-semibold text-semantic-success">
                <ShieldCheck size={14} aria-hidden />
                {t('data_paths.checked_by', { defaultValue: 'Checked by validation' })}
                <span className="font-medium tabular-nums">({formatNumber(info.rules.length)})</span>
              </p>
              <ul className="mt-1 space-y-0.5">
                {info.rules.slice(0, 5).map((r) => (
                  <li key={r.rule_id} className="truncate text-xs text-content-secondary" title={r.rule_id}>
                    {r.name}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-content-tertiary">{t('data_paths.no_rules', { defaultValue: 'No validation rule guards these inputs yet' })}</p>
          )}
        </div>
      </Section>

      <Section title={t('data_paths.traces_title', { defaultValue: 'Data traces' })} testId="dp-traces">
        {info?.traces.length ? (
          <ul className="space-y-2">
            {info.traces.map((tr) => (
              <TraceRow key={tr.id} trace={tr} state={trace} onTrace={onTrace} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-content-tertiary">{t('data_paths.traces_empty', { defaultValue: 'No named trace passes through this module yet' })}</p>
        )}
      </Section>

      <Section
        title={t('data_paths.changes_title', { defaultValue: 'Recently changed, here and downstream' })}
        aside={<span className="text-xs text-content-tertiary">{t('data_paths.changes_days', { defaultValue: '{{days}} days', days: 30 })}</span>}
        testId="dp-changes"
      >
        {!projectId ? (
          <p className="text-sm text-content-tertiary">{t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })}</p>
        ) : changes.isLoading ? (
          <div className="h-16 animate-pulse rounded-lg bg-surface-secondary" />
        ) : byModule.size === 0 ? (
          <p className="text-sm text-content-tertiary">{t('data_paths.changes_empty', { defaultValue: 'Nothing changed in the last {{days}} days', days: 30 })}</p>
        ) : (
          <ul className="space-y-3">
            {[...byModule].map(([m, list]) => (
              <li key={m}>
                <p className="text-xs font-semibold text-content-primary">{moduleLabel(t, m)}</p>
                <ul className="mt-1 space-y-1">
                  {list.slice(0, 4).map((c, i) => {
                    const [ak, adef] = ACTION_KEYS[c.action] ?? ['', c.action];
                    return (
                      <li key={`${c.entity_id}-${i}`} className="flex items-baseline gap-1.5 text-xs text-content-secondary">
                        <span className="min-w-0 flex-1 truncate">
                          {humanize(c.entity)} {ak ? t(ak, { defaultValue: adef }) : adef}
                          {c.user && <span className="text-content-tertiary"> · {c.user}</span>}
                        </span>
                        <DateDisplay value={c.at} format="relative" className="shrink-0 text-content-tertiary" />
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </aside>
  );
}
