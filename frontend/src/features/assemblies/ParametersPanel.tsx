// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Parameters editor for a parametric assembly (Issue #365).
//
// Lists the assembly's named parameters and lets the user add / edit /
// remove them: a name, a kind (input / constant / calculated), a numeric
// value (input + constant) OR a formula (calculated), plus an optional unit
// and description. Saving persists the whole set via
// `assembliesApi.update(id, { parameters })` and invalidates the assembly
// query. A structural check (`validate-parameters`) runs against the SAVED
// graph and surfaces cycles / bad references / duplicates / syntax errors
// inline, together with the resolved default values.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Calculator, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { assembliesApi, type AssemblyParameter, type ParameterKind } from './api';
import { parameterErrorText } from './parameterErrors';

/* -- Draft model ---------------------------------------------------------- */

/**
 * A locally-editable parameter row. `value` and `formula` are always held as
 * text while editing; the save step converts `value` to a real number for
 * input/constant (the backend Decimal field rejects an empty string).
 */
interface DraftParam {
  _id: string;
  name: string;
  kind: ParameterKind;
  value: string;
  formula: string;
  unit: string;
  description: string;
}

let _seq = 0;
const newDraftId = (): string => `p${Date.now().toString(36)}_${(_seq++).toString(36)}`;

const toDraft = (p: AssemblyParameter): DraftParam => ({
  _id: newDraftId(),
  name: p.name,
  kind: p.kind,
  value: p.value ?? '',
  formula: p.formula ?? '',
  unit: p.unit,
  description: p.description,
});

/**
 * Canonical signature of a set of rows, used both for dirty-tracking and to
 * decide whether incoming server parameters should re-seed local edits.
 * Ignores the client-only `_id` and the field irrelevant to the row's kind.
 */
const canonRows = (
  rows: Array<{
    name: string;
    kind: ParameterKind;
    value: string;
    formula: string;
    unit: string;
    description: string;
  }>,
): string =>
  JSON.stringify(
    rows.map((r) => ({
      name: r.name.trim(),
      kind: r.kind,
      value: r.kind === 'calculated' ? '' : r.value.trim(),
      formula: r.kind === 'calculated' ? r.formula.trim() : '',
      unit: r.unit.trim(),
      description: r.description.trim(),
    })),
  );

/**
 * Build the wire payload. input/constant carry a numeric-string `value`
 * (Decimal-in / Decimal-as-string out, so `0.1` stays exact; empty → "0")
 * and a null formula; calculated carries a non-empty `formula` string and a
 * null value. The raw user text is sent verbatim when it is a finite number
 * so the server keeps full Decimal precision.
 */
const buildPayload = (rows: DraftParam[]): AssemblyParameter[] =>
  rows
    .filter((r) => r.name.trim() !== '')
    .map((r): AssemblyParameter => {
      const base = {
        name: r.name.trim(),
        unit: r.unit.trim(),
        description: r.description.trim(),
      };
      if (r.kind === 'calculated') {
        return { ...base, kind: 'calculated', value: null, formula: r.formula.trim() };
      }
      const raw = r.value.trim();
      const value = raw === '' || !Number.isFinite(Number(raw)) ? '0' : raw;
      return { ...base, kind: r.kind, value, formula: null };
    });

/* -- Component ------------------------------------------------------------ */

export interface ParametersPanelProps {
  assemblyId: string;
  parameters: AssemblyParameter[];
}

export function ParametersPanel({ assemblyId, parameters }: ParametersPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [drafts, setDrafts] = useState<DraftParam[]>(() => parameters.map(toDraft));

  // Re-seed local drafts only when the SAVED graph actually changes (e.g.
  // after our own save round-trips through react-query). A stable signature
  // means the user's in-progress edits survive unrelated re-renders.
  const serverCanon = useMemo(
    () =>
      canonRows(
        parameters.map((p) => ({
          name: p.name,
          kind: p.kind,
          value: p.value ?? '',
          formula: p.formula ?? '',
          unit: p.unit,
          description: p.description,
        })),
      ),
    [parameters],
  );
  const lastServerCanonRef = useRef(serverCanon);
  useEffect(() => {
    if (serverCanon !== lastServerCanonRef.current) {
      lastServerCanonRef.current = serverCanon;
      setDrafts(parameters.map(toDraft));
    }
  }, [serverCanon, parameters]);

  const dirty = canonRows(drafts) !== serverCanon;

  const validation = useQuery({
    queryKey: ['assembly-validate-params', assemblyId, serverCanon],
    queryFn: () => assembliesApi.validateParameters(assemblyId),
    enabled: parameters.length > 0,
    retry: false,
  });

  const saveMutation = useMutation({
    mutationFn: () => assembliesApi.update(assemblyId, { parameters: buildPayload(drafts) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] });
      addToast({
        type: 'success',
        title: t('assembly.params.saved', { defaultValue: 'Parameters saved' }),
      });
    },
    onError: (error: Error) => {
      addToast({
        type: 'error',
        title: t('assembly.params.save_failed', { defaultValue: 'Could not save parameters' }),
        message: error.message,
      });
    },
  });

  const patchDraft = (id: string, patch: Partial<DraftParam>) => {
    setDrafts((prev) => prev.map((d) => (d._id === id ? { ...d, ...patch } : d)));
  };

  const addDraft = () => {
    setDrafts((prev) => [
      ...prev,
      {
        _id: newDraftId(),
        name: '',
        kind: 'input',
        value: '',
        formula: '',
        unit: '',
        description: '',
      },
    ]);
  };

  const removeDraft = (id: string) => {
    setDrafts((prev) => prev.filter((d) => d._id !== id));
  };

  const kindOptions: Array<{ value: ParameterKind; label: string }> = [
    { value: 'input', label: t('assembly.params.kind_input', { defaultValue: 'Input' }) },
    { value: 'constant', label: t('assembly.params.kind_constant', { defaultValue: 'Constant' }) },
    {
      value: 'calculated',
      label: t('assembly.params.kind_calculated', { defaultValue: 'Calculated' }),
    },
  ];

  const fieldClass =
    'w-full h-9 px-2.5 rounded-lg border border-border-light bg-surface-primary text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue/40';

  const resolvedEntries = Object.entries(validation.data?.resolved ?? {});

  return (
    <Card padding="md">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Calculator size={16} className="text-oe-blue shrink-0" />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('assembly.params.title', { defaultValue: 'Parameters' })}
            </h3>
            <p className="text-xs text-content-tertiary leading-snug">
              {t('assembly.params.subtitle', {
                defaultValue:
                  "Name the values that drive this recipe, then reference them from each line's quantity formula.",
              })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addDraft}>
            {t('assembly.params.add', { defaultValue: 'Add parameter' })}
          </Button>
          {dirty && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => saveMutation.mutate()}
              loading={saveMutation.isPending}
            >
              {t('assembly.params.save', { defaultValue: 'Save' })}
            </Button>
          )}
        </div>
      </div>

      {drafts.length === 0 ? (
        <p className="text-xs text-content-tertiary py-3 border-t border-border-light">
          {t('assembly.params.empty', {
            defaultValue:
              'No parameters yet. Add one (e.g. wall_area, rebar_ratio) to drive component quantities from a formula.',
          })}
        </p>
      ) : (
        <div className="space-y-2 border-t border-border-light pt-3">
          {/* Column labels (>= lg) */}
          <div className="hidden lg:grid lg:grid-cols-[minmax(0,1.4fr)_120px_minmax(0,1.8fr)_84px_minmax(0,1.6fr)_32px] gap-2 px-0.5 text-[10px] uppercase tracking-wider text-content-tertiary font-semibold">
            <span>{t('assembly.params.col_name', { defaultValue: 'Name' })}</span>
            <span>{t('assembly.params.col_kind', { defaultValue: 'Kind' })}</span>
            <span>{t('assembly.params.col_value', { defaultValue: 'Value / formula' })}</span>
            <span>{t('assembly.params.col_unit', { defaultValue: 'Unit' })}</span>
            <span>{t('assembly.params.col_desc', { defaultValue: 'Description' })}</span>
            <span className="sr-only">
              {t('assembly.params.col_actions', { defaultValue: 'Actions' })}
            </span>
          </div>

          {drafts.map((d) => (
            <div
              key={d._id}
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.4fr)_120px_minmax(0,1.8fr)_84px_minmax(0,1.6fr)_32px] gap-2 items-start"
            >
              <input
                type="text"
                value={d.name}
                onChange={(e) => patchDraft(d._id, { name: e.target.value })}
                placeholder={t('assembly.params.name_ph', { defaultValue: 'e.g. wall_area' })}
                className={`${fieldClass} font-mono`}
                aria-label={t('assembly.params.col_name', { defaultValue: 'Name' })}
              />
              <select
                value={d.kind}
                onChange={(e) => patchDraft(d._id, { kind: e.target.value as ParameterKind })}
                className={`${fieldClass} cursor-pointer`}
                aria-label={t('assembly.params.col_kind', { defaultValue: 'Kind' })}
              >
                {kindOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {d.kind === 'calculated' ? (
                <input
                  type="text"
                  value={d.formula}
                  onChange={(e) => patchDraft(d._id, { formula: e.target.value })}
                  placeholder={t('assembly.params.formula_ph', {
                    defaultValue: 'e.g. length * height',
                  })}
                  className={`${fieldClass} font-mono`}
                  aria-label={t('assembly.params.col_value', { defaultValue: 'Value / formula' })}
                />
              ) : (
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  value={d.value}
                  onChange={(e) => patchDraft(d._id, { value: e.target.value })}
                  placeholder={t('assembly.params.value_ph', { defaultValue: 'e.g. 0.5' })}
                  className={`${fieldClass} text-right tabular-nums`}
                  aria-label={t('assembly.params.col_value', { defaultValue: 'Value / formula' })}
                />
              )}
              <input
                type="text"
                value={d.unit}
                onChange={(e) => patchDraft(d._id, { unit: e.target.value })}
                placeholder={t('assembly.params.unit_ph', { defaultValue: 'unit' })}
                className={fieldClass}
                aria-label={t('assembly.params.col_unit', { defaultValue: 'Unit' })}
              />
              <input
                type="text"
                value={d.description}
                onChange={(e) => patchDraft(d._id, { description: e.target.value })}
                placeholder={t('assembly.params.desc_ph', { defaultValue: 'Optional note' })}
                className={fieldClass}
                aria-label={t('assembly.params.col_desc', { defaultValue: 'Description' })}
              />
              <button
                type="button"
                onClick={() => removeDraft(d._id)}
                aria-label={t('assembly.params.remove', { defaultValue: 'Remove parameter' })}
                title={t('assembly.params.remove', { defaultValue: 'Remove parameter' })}
                className="flex h-9 w-8 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-colors justify-self-start"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Structural validation + resolved defaults (against the SAVED graph) */}
      {parameters.length > 0 && (
        <div className="mt-4 pt-3 border-t border-border-light">
          {validation.isLoading ? (
            <div className="flex items-center gap-2 text-xs text-content-tertiary">
              <Loader2 size={13} className="animate-spin" />
              {t('assembly.params.checking', { defaultValue: 'Checking parameters…' })}
            </div>
          ) : validation.data ? (
            <div className="space-y-2">
              {validation.data.ok ? (
                <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 size={13} />
                  {t('assembly.params.ok', { defaultValue: 'Parameters resolve cleanly' })}
                </div>
              ) : (
                <ul className="space-y-1">
                  {validation.data.errors.map((err, i) => {
                    const mapped = parameterErrorText(err.code);
                    const text = mapped
                      ? t(mapped.key, { defaultValue: mapped.defaultValue })
                      : err.message;
                    return (
                      <li
                        key={`${err.scope}-${err.name}-${err.code}-${i}`}
                        className="flex items-start gap-1.5 text-xs text-semantic-error"
                      >
                        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                        <span>
                          {err.name && (
                            <span className="font-mono font-semibold">{err.name}</span>
                          )}
                          {err.name ? ' - ' : ''}
                          {text}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}

              {resolvedEntries.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-content-tertiary font-semibold mb-1">
                    {t('assembly.params.resolved_title', { defaultValue: 'Resolved defaults' })}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {resolvedEntries.map(([name, value]) => (
                      <span
                        key={name}
                        className="inline-flex items-center gap-1 rounded-md bg-surface-tertiary px-1.5 py-0.5 text-[11px]"
                      >
                        <span className="font-mono text-content-secondary">{name}</span>
                        <span className="tabular-nums font-semibold text-content-primary">
                          {value}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {dirty && (
                <p className="text-[11px] text-content-tertiary">
                  {t('assembly.params.dirty_hint', {
                    defaultValue: 'Unsaved edits are not checked yet - save to re-validate.',
                  })}
                </p>
              )}
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
