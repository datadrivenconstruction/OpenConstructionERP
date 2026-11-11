// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Expansion preview for a parametric assembly (Issue #365).
//
// Renders one input box per `input` parameter (prefilled with its stored
// default), asks the server to expand the recipe at those values
// (`expand-preview`), and shows the resolved parameter values, a per-line
// before → after quantity table with unit cost and line total, the rolled-up
// total rate, and any structured errors. All money / quantity fields are
// Decimal-exact strings from the server and are displayed verbatim so the
// preview stays penny-accurate.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Play, AlertTriangle, Loader2 } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { assembliesApi, type AssemblyParameter } from './api';
import { parameterErrorText } from './parameterErrors';

export interface ExpandPreviewModalProps {
  assemblyId: string;
  parameters: AssemblyParameter[];
  unit: string;
  currency: string;
  onClose: () => void;
}

const toNumber = (raw: string | null | undefined, fallback = 0): number => {
  if (raw === null || raw === undefined || raw.trim() === '') return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
};

export function ExpandPreviewModal({
  assemblyId,
  parameters,
  unit,
  currency,
  onClose,
}: ExpandPreviewModalProps) {
  const { t } = useTranslation();

  const inputParams = useMemo(
    () => parameters.filter((p) => p.kind === 'input'),
    [parameters],
  );

  // Editable per-input values (text) and the committed numeric values the
  // query actually runs against. Seeding both from the stored defaults means
  // the modal shows a real expansion the moment it opens.
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(inputParams.map((p) => [p.name, p.value ?? ''])),
  );
  const [applied, setApplied] = useState<Record<string, number>>(() =>
    Object.fromEntries(inputParams.map((p) => [p.name, toNumber(p.value)])),
  );

  const preview = useQuery({
    queryKey: ['assembly-expand', assemblyId, applied],
    queryFn: () => assembliesApi.expandPreview(assemblyId, applied),
    retry: false,
  });

  const runPreview = () => {
    const next: Record<string, number> = {};
    for (const p of inputParams) {
      const raw = values[p.name];
      next[p.name] = toNumber(raw, toNumber(p.value));
    }
    setApplied(next);
  };

  const data = preview.data;
  const resolvedEntries = Object.entries(data?.resolved_parameters ?? {});

  const footer = (
    <>
      <Button variant="secondary" onClick={onClose}>
        {t('common.close', { defaultValue: 'Close' })}
      </Button>
      <Button
        variant="primary"
        icon={<Play size={16} />}
        onClick={runPreview}
        loading={preview.isFetching}
      >
        {t('assembly.preview.run', { defaultValue: 'Preview' })}
      </Button>
    </>
  );

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      title={t('assembly.preview.title', { defaultValue: 'Expansion preview' })}
      subtitle={t('assembly.preview.subtitle', {
        defaultValue:
          'Enter the input values and see the exact per-line quantities and rate the server computes.',
      })}
      footer={footer}
    >
      {/* Inputs */}
      <section className="mb-5">
        <h3 className="oe-card-title mb-2">
          {t('assembly.preview.inputs_title', { defaultValue: 'Input parameters' })}
        </h3>
        {inputParams.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('assembly.preview.no_inputs', {
              defaultValue:
                'This assembly has no input parameters; the preview uses its constants and calculated values.',
            })}
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {inputParams.map((p) => (
              <label key={p.name} className="block">
                <div className="text-2xs font-medium text-content-secondary mb-1 flex items-center gap-1">
                  <span className="font-mono">{p.name}</span>
                  {p.unit && <span className="text-content-tertiary">({p.unit})</span>}
                </div>
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  value={values[p.name] ?? ''}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [p.name]: e.target.value }))
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') runPreview();
                  }}
                  placeholder={p.value ?? '0'}
                  className="oe-input w-full text-right tabular-nums"
                />
                {p.description && (
                  <div className="text-2xs text-content-tertiary mt-1 leading-snug">
                    {p.description}
                  </div>
                )}
              </label>
            ))}
          </div>
        )}
      </section>

      {/* Errors */}
      {data && data.errors.length > 0 && (
        <div className="mb-4 rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-3 py-2.5">
          <ul className="space-y-1">
            {data.errors.map((err, i) => {
              const mapped = parameterErrorText(err.code);
              const text = mapped ? t(mapped.key, { defaultValue: mapped.defaultValue }) : err.message;
              return (
                <li
                  key={`${err.scope}-${err.name}-${err.code}-${i}`}
                  className="flex items-start gap-1.5 text-xs text-semantic-error"
                >
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <span>
                    {err.name && <span className="font-mono font-semibold">{err.name}</span>}
                    {err.name ? ' - ' : ''}
                    {text}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Resolved parameters */}
      {resolvedEntries.length > 0 && (
        <section className="mb-4">
          <div className="oe-overline mb-1.5">
            {t('assembly.preview.resolved_title', { defaultValue: 'Resolved parameters' })}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {resolvedEntries.map(([name, value]) => (
              <span
                key={name}
                className="inline-flex items-center gap-1 rounded-md bg-surface-tertiary px-2 py-0.5 text-2xs"
              >
                <span className="font-mono text-content-secondary">{name}</span>
                <span className="tabular-nums font-semibold text-content-primary">{value}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Lines */}
      <section>
        <h3 className="oe-card-title mb-2">
          {t('assembly.preview.lines_title', { defaultValue: 'Expanded lines' })}
        </h3>
        {preview.isLoading ? (
          <div className="flex items-center gap-2 py-8 justify-center text-xs text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
            {t('assembly.preview.loading', { defaultValue: 'Computing preview…' })}
          </div>
        ) : preview.isError ? (
          <p className="py-6 text-center text-xs text-semantic-error">
            {t('assembly.preview.failed', { defaultValue: 'Could not compute the preview.' })}
          </p>
        ) : !data || data.lines.length === 0 ? (
          <p className="py-6 text-center text-xs text-content-tertiary">
            {t('assembly.preview.no_lines', { defaultValue: 'No component lines to expand yet.' })}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-light">
            <table className="oe-table w-full">
              <thead>
                <tr className="bg-surface-tertiary text-left">
                  <th className="min-w-[200px]">
                    {t('boq.description', { defaultValue: 'Description' })}
                  </th>
                  <th className="w-16 text-center">
                    {t('boq.unit', { defaultValue: 'Unit' })}
                  </th>
                  <th className="w-40 text-right">
                    {t('assembly.preview.col_qty', { defaultValue: 'Qty (static -> computed)' })}
                  </th>
                  <th className="w-28 text-right">
                    {t('assemblies.unit_cost', { defaultValue: 'Unit Cost' })}
                  </th>
                  <th className="w-28 text-right">
                    {t('boq.total', { defaultValue: 'Total' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((line, i) => {
                  const changed = line.static_quantity !== line.computed_quantity;
                  return (
                    <tr key={line.component_id ?? `line-${i}`} className="hover:bg-surface-secondary/40">
                      <td>{line.description}</td>
                      <td className="text-center text-content-secondary">
                        {line.unit}
                      </td>
                      <td className="text-right tabular-nums">
                        <span className="inline-flex items-center justify-end gap-1">
                          <span className={changed ? 'text-content-tertiary line-through' : 'text-content-secondary'}>
                            {line.static_quantity}
                          </span>
                          {changed && (
                            <>
                              <ArrowRight size={12} className="text-content-quaternary" />
                              <span className="font-semibold text-oe-blue">
                                {line.computed_quantity}
                              </span>
                            </>
                          )}
                        </span>
                      </td>
                      <td className="text-right tabular-nums text-content-secondary">
                        {line.unit_cost}
                      </td>
                      <td className="text-right tabular-nums font-semibold">
                        {line.total}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="bg-surface-tertiary">
                  <td colSpan={4} className="text-right">
                    {t('assembly.preview.total_rate', { defaultValue: 'Total rate' })}
                  </td>
                  <td className="text-right tabular-nums">
                    {data.total_rate}
                    <span className="ml-1 text-xs font-normal text-content-tertiary">
                      {currency} / {unit}
                    </span>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>
    </WideModal>
  );
}
