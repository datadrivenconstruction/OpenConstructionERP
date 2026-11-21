// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Inspector: measurement, the selected feature's properties, live findings, edit history. */

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, AlertTriangle, Copy, History, Info, RotateCcw } from 'lucide-react';
import { planApi, planKeys } from '../api';
import { pathLength, ringArea, xy } from '../engine/geometry';
import type { LiveFinding } from '../engine/liveChecks';
import { formatArea, formatCoordPair, formatDistance } from '../units/linear';
import type { PlanConventions } from '../units/conventions';
import type { MeasureResult, PlanFeature } from '../types';
import { getIntlLocale } from '@/shared/lib/intlLocale';

interface Props {
  projectId: string;
  conventions: PlanConventions;
  measure: MeasureResult | null;
  selected: PlanFeature[];
  editable: boolean;
  onEdit: (before: PlanFeature, after: PlanFeature) => void;
  findings: LiveFinding[];
  onFocusFinding: (f: LiveFinding) => void;
  slot?: ReactNode;
}

function Section({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section className="space-y-2 border-b border-border-light px-3 py-3 last:border-b-0" data-testid={testId}>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-content-secondary">{label}</span>
      <span className="min-w-0 truncate text-end font-mono tabular-nums text-content-primary">{children}</span>
    </div>
  );
}

const EDITABLE_PROPS: [string, string, string][] = [
  ['label', 'plan.prop.label', 'Name'],
  ['code', 'plan.prop.code', 'Code'],
  ['text', 'plan.prop.text', 'Text'],
];

function PropertyField({ f, name, title, onEdit }: { f: PlanFeature; name: string; title: string; onEdit: Props['onEdit'] }) {
  const current = String(f.properties[name] ?? '');
  const [value, setValue] = useState(current);
  const [seen, setSeen] = useState(current);
  if (seen !== current) {
    setSeen(current);
    setValue(current);
  }
  const save = () => {
    if (value === current) return;
    onEdit(f, { ...f, properties: { ...f.properties, [name]: value } });
  };
  return (
    <label className="flex items-center justify-between gap-3 text-sm">
      <span className="text-content-secondary">{title}</span>
      <input
        className="oe-input w-40 font-mono text-sm"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === 'Enter') save();
        }}
        data-testid={`plan-prop-${name}`}
      />
    </label>
  );
}

function HistoryList({ projectId, f }: { projectId: string; f: PlanFeature }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const entityType = f.entityType ?? 'sketch';
  const entityId = f.entityId ?? '';
  const q = useQuery({
    queryKey: planKeys.edits(projectId, entityType, entityId),
    queryFn: () => planApi.edits(projectId, entityType, entityId),
    enabled: !!entityId,
  });
  const restore = useMutation({
    mutationFn: (editId: string) => planApi.restore(editId),
    onSuccess: () => qc.invalidateQueries({ queryKey: planKeys.all(projectId) }),
  });
  if (!entityId) return <p className="text-xs text-content-tertiary">{t('plan.history.unsaved', { defaultValue: 'Not saved yet' })}</p>;
  const items = q.data?.items ?? [];
  if (items.length === 0) return <p className="text-xs text-content-tertiary">{t('plan.history.none', { defaultValue: 'No edits on the plan yet' })}</p>;
  return (
    <ol className="space-y-1" data-testid="plan-history">
      {items.map((e, i) => (
        <li key={e.id} className="flex items-center gap-2 text-xs">
          <span className="font-mono text-content-tertiary">r{e.rev}</span>
          <span className="min-w-0 flex-1 truncate text-content-secondary">
            {t(`plan.history.op_${e.op}`, { defaultValue: e.op })}
            {e.summary ? ` ${e.summary}` : ''} · {e.author_name || t('plan.history.someone', { defaultValue: 'someone' })} ·{' '}
            {new Date(e.created_at).toLocaleString(getIntlLocale())}
          </span>
          {i > 0 && (
            <button
              type="button"
              className="inline-flex h-7 items-center gap-1 rounded px-1.5 text-content-secondary hover:bg-surface-secondary"
              onClick={() => restore.mutate(e.id)}
              disabled={restore.isPending}
              title={t('plan.history.restore', { defaultValue: 'Restore this version' })}
            >
              <RotateCcw size={12} aria-hidden />
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}

const SEVERITY_ICON = { error: AlertCircle, warning: AlertTriangle, info: Info } as const;
const SEVERITY_CLASS = { error: 'text-semantic-error', warning: 'text-semantic-warning', info: 'text-content-tertiary' } as const;

export function Inspector({ projectId, conventions, measure, selected, editable, onEdit, findings, onFocusFinding, slot }: Props) {
  const { t } = useTranslation();
  const one = selected.length === 1 ? selected[0]! : null;
  return (
    <div className="flex h-full flex-col overflow-y-auto" data-testid="plan-inspector">
      {measure && (
        <Section title={t('plan.inspector.measure', { defaultValue: 'Measurement' })} testId="plan-measure">
          <div className="flex items-center justify-between gap-2">
            <bdi dir="ltr" className="font-mono text-base font-semibold tabular-nums text-content-primary" data-testid="plan-measure-value">
              {measure.text}
            </bdi>
            <button
              type="button"
              onClick={() => void navigator.clipboard?.writeText(measure.text)}
              className="inline-flex h-8 w-8 items-center justify-center rounded text-content-secondary hover:bg-surface-secondary"
              aria-label={t('plan.inspector.copy', { defaultValue: 'Copy (Ctrl+C)' })}
            >
              <Copy size={14} aria-hidden />
            </button>
          </div>
          <p className="text-xs text-content-tertiary">{t('plan.inspector.grid_note', { defaultValue: 'Grid values on the project coordinate system' })}</p>
        </Section>
      )}
      {one ? (
        <Section title={t('plan.inspector.properties', { defaultValue: 'Properties' })} testId="plan-properties">
          <Row label={t('plan.prop.layer', { defaultValue: 'Layer' })}>{t(`plan.layer.${one.layer}`, { defaultValue: one.layer })}</Row>
          {one.geometry.type === 'Point' && (
            <>
              <Row label={t('plan.prop.position', { defaultValue: 'Position' })}>
                <bdi dir="ltr">{formatCoordPair(one.geometry.coordinates[0], one.geometry.coordinates[1], conventions)}</bdi>
              </Row>
              {one.geometry.coordinates[2] != null && (
                <Row label={t('plan.prop.height', { defaultValue: 'Height' })}>
                  <bdi dir="ltr">{formatDistance(one.geometry.coordinates[2], conventions)}</bdi>
                </Row>
              )}
            </>
          )}
          {one.geometry.type === 'LineString' && (
            <Row label={t('plan.prop.length', { defaultValue: 'Length' })}>
              <bdi dir="ltr">{formatDistance(pathLength(one.geometry.coordinates.map(xy)), conventions)}</bdi>
            </Row>
          )}
          {one.geometry.type === 'Polygon' && (
            <>
              <Row label={t('plan.prop.area', { defaultValue: 'Area' })}>
                <bdi dir="ltr">{formatArea(ringArea(one.geometry.coordinates[0] ?? []), conventions)}</bdi>
              </Row>
              <Row label={t('plan.prop.perimeter', { defaultValue: 'Perimeter' })}>
                <bdi dir="ltr">{formatDistance(pathLength((one.geometry.coordinates[0] ?? []).map(xy)), conventions)}</bdi>
              </Row>
            </>
          )}
          {editable
            ? EDITABLE_PROPS.filter(([k]) => k !== 'text' || 'text' in one.properties).map(([k, key, def]) => (
                <PropertyField key={`${one.id}-${k}`} f={one} name={k} title={t(key, { defaultValue: def })} onEdit={onEdit} />
              ))
            : EDITABLE_PROPS.filter(([k]) => one.properties[k] != null && one.properties[k] !== '').map(([k, key, def]) => (
                <Row key={k} label={t(key, { defaultValue: def })}>
                  {String(one.properties[k])}
                </Row>
              ))}
        </Section>
      ) : selected.length > 1 ? (
        <Section title={t('plan.inspector.properties', { defaultValue: 'Properties' })}>
          <p className="text-sm text-content-secondary">{t('plan.status.selected', { defaultValue: '{{count}} selected', count: selected.length })}</p>
        </Section>
      ) : null}
      {slot}
      {findings.length > 0 && (
        <Section title={t('plan.inspector.checks', { defaultValue: 'Checks' })} testId="plan-findings">
          <ul className="space-y-1">
            {findings.slice(0, 50).map((f, i) => {
              const Icon = SEVERITY_ICON[f.severity];
              return (
                <li key={`${f.ruleId}-${i}`}>
                  <button
                    type="button"
                    onClick={() => onFocusFinding(f)}
                    className="flex w-full items-start gap-2 rounded px-1 py-1 text-start text-xs hover:bg-surface-secondary"
                  >
                    <Icon size={13} className={`mt-px shrink-0 ${SEVERITY_CLASS[f.severity]}`} aria-hidden />
                    <span className="text-content-secondary">
                      <span className="font-mono text-content-tertiary">{f.ruleId}</span> {t(f.messageKey, { defaultValue: f.defaultMessage, ...f.params })}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </Section>
      )}
      {one && (
        <Section title={t('plan.inspector.history', { defaultValue: 'History' })}>
          <div className="flex items-center gap-1 text-xs text-content-tertiary">
            <History size={12} aria-hidden />
          </div>
          <HistoryList projectId={projectId} f={one} />
        </Section>
      )}
      {!measure && selected.length === 0 && findings.length === 0 && !slot && (
        <p className="p-4 text-sm text-content-tertiary">
          {t('plan.inspector.empty', { defaultValue: 'Select something on the plan to see its properties, or pick a measure tool.' })}
        </p>
      )}
    </div>
  );
}
