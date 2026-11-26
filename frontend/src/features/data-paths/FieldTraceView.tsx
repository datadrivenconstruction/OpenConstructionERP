// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Field trace tab: one parameter of the module, where it comes from (source),
// what it computes inside the module (derived) and which modules read it
// (consumers), with what breaks when it is missing and the freshness rules.

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Clock, Route, TriangleAlert } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Skeleton } from '@/shared/ui/Skeleton';

import { useModulePaths } from './api';
import { moduleLabel } from './flowModel';
import { ImportanceBadge, ModuleIcon } from './ModulePathsView';
import { traceField } from './pathsModel';

interface Props {
  module: string;
  projectId: string | null;
  field: string | null;
  onField: (field: string) => void;
}

export function FieldTraceView({ module, projectId, field, onField }: Props) {
  const { t } = useTranslation();
  const query = useModulePaths(module, projectId);
  const data = query.data;

  if (query.isLoading) return <Skeleton height={360} className="rounded-xl" />;
  if (query.isError || !data) {
    return <ErrorState title={t('data_paths.load_failed', { defaultValue: 'The data paths could not be loaded.' })} onRetry={() => void query.refetch()} />;
  }
  if (!data.parameters.length) {
    return (
      <EmptyState
        icon={<Route size={40} />}
        title={t('data_paths.v2.trace_empty', { defaultValue: '{{module}} declares no fields to trace', module: moduleLabel(t, module) })}
        description={t('data_paths.v2.trace_empty_body', { defaultValue: 'A field shows here once the module names what it drives in other modules.' })}
      />
    );
  }
  const current = field && data.parameters.some((p) => p.field === field) ? field : (data.parameters[0]?.field ?? '');
  const trace = traceField(data, current);
  if (!trace) return null;

  const fieldLabel = (key: string, fallback: string) => (key ? String(t(key, { defaultValue: fallback })) : fallback);
  const steps = [
    t('data_paths.v2.step_source', { defaultValue: 'Source' }),
    t('data_paths.v2.step_parameter', { defaultValue: 'Parameter' }),
    t('data_paths.v2.step_derived', { defaultValue: 'Derived' }),
    t('data_paths.v2.step_consumers', { defaultValue: 'Consumers' }),
  ];
  const none = (text: string) => <p className="rounded-xl border border-dashed border-border-light p-4 text-xs text-content-tertiary">{text}</p>;
  const missing = trace.consumers.filter((c) => c.path?.breaks).map((c) => c.path!);

  return (
    <div className="space-y-5" data-testid="dp-field-trace">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('data_paths.v2.pick_field', { defaultValue: 'Field to trace' })}>
        {data.parameters.map((p) => (
          <button
            key={p.field}
            type="button"
            aria-pressed={p.field === current}
            onClick={() => onField(p.field)}
            className={clsx(
              'h-7 rounded-full border px-3 text-xs transition-colors duration-150',
              p.field === current ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary hover:bg-surface-secondary',
            )}
          >
            {fieldLabel(p.label, p.field)}
          </button>
        ))}
      </div>

      <ol className="grid gap-4 lg:grid-cols-4">
        {steps.map((s, i) => (
          <li key={s} className="flex items-center gap-2 border-b border-border-light pb-2 text-sm font-medium text-content-primary">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-content-primary text-2xs text-surface-primary">{i + 1}</span>
            {s}
          </li>
        ))}
      </ol>

      <div className="grid items-start gap-4 lg:grid-cols-4">
        <div className="space-y-3">
          {trace.sources.length
            ? trace.sources.map((p) => (
                <Card key={p.id} module={p.module} badge={<ImportanceBadge importance={p.importance} />}>
                  <Code>{p.via}</Code>
                  {p.label && <p className="mt-2 text-xs text-content-secondary">{t(p.label, { defaultValue: p.entity })}</p>}
                </Card>
              ))
            : none(t('data_paths.v2.no_source', { defaultValue: 'No declared source: the value is entered in this module.' }))}
        </div>
        <div>
          <Card module={module} accent>
            <Code strong>{trace.param.field}</Code>
            {trace.param.label && <p className="mt-2 text-xs text-content-secondary">{fieldLabel(trace.param.label, '')}</p>}
          </Card>
        </div>
        <div>
          {trace.derived.length ? (
            <Card module={module}>
              <div className="space-y-1.5">
                {trace.derived.map((d) => (
                  <Code key={d}>{d}</Code>
                ))}
              </div>
            </Card>
          ) : (
            none(t('data_paths.v2.no_derived', { defaultValue: 'Nothing is derived from it inside this module.' }))
          )}
        </div>
        <div className="space-y-3">
          {trace.consumers.length
            ? trace.consumers.map((c) => (
                <Card key={c.module} module={c.module} badge={c.path ? <ImportanceBadge importance={c.path.importance} /> : null}>
                  <div className="space-y-1.5">
                    {(c.refs.length ? c.refs : [c.path?.via ?? '']).map((r) => (
                      <Code key={r}>{r}</Code>
                    ))}
                  </div>
                </Card>
              ))
            : none(t('data_paths.v2.no_consumer', { defaultValue: 'No other module reads it yet.' }))}
        </div>
      </div>

      {(missing.length > 0 || trace.stale.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {missing.length > 0 && (
            <section className="rounded-xl border border-border-light bg-surface-primary p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                <TriangleAlert size={16} className="text-semantic-warning" aria-hidden />
                {t('data_paths.v2.if_missing', { defaultValue: 'If it is missing' })}
              </h3>
              <ul className="mt-2 space-y-1.5 text-sm text-content-secondary">
                {missing.map((p) => (
                  <li key={p.id}>
                    <span className="font-medium text-content-primary">{moduleLabel(t, p.module)}: </span>
                    {t(p.breaks, { defaultValue: '' })}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {trace.stale.length > 0 && (
            <section className="rounded-xl border border-border-light bg-surface-primary p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                <Clock size={16} className="text-semantic-warning" aria-hidden />
                {t('data_paths.v2.stale_rule', { defaultValue: 'Changed after it was sent' })}
              </h3>
              <ul className="mt-2 space-y-1.5 text-sm text-content-secondary">
                {trace.stale.map((s) => (
                  <li key={`${s.source}-${s.copy_field}`}>
                    {t('data_paths.v2.stale_sentence', {
                      defaultValue: 'When {{source}} is later than {{copy}}, the copy is flagged.',
                      source: s.source,
                      copy: s.copy_field,
                    })}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function Card({ module, accent = false, badge, children }: { module: string; accent?: boolean; badge?: ReactNode; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <section className={clsx('rounded-xl border bg-surface-primary p-4', accent ? 'border-oe-blue/50 shadow-sm' : 'border-border-light')}>
      <div className="mb-3 flex items-start gap-2.5">
        <ModuleIcon module={module} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-content-primary">{moduleLabel(t, module)}</p>
          <p className="truncate font-mono text-2xs text-content-tertiary">{module}</p>
        </div>
        {badge}
      </div>
      {children}
    </section>
  );
}

function Code({ children, strong = false }: { children: ReactNode; strong?: boolean }) {
  return (
    <p className={clsx('break-all rounded-lg px-2.5 py-2 font-mono text-xs', strong ? 'bg-oe-blue text-content-inverse' : 'bg-surface-secondary text-content-primary')}>
      {children}
    </p>
  );
}
