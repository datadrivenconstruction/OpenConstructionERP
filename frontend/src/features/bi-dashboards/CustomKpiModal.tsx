// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Define a custom KPI without writing Python - issue #441.
 *
 * The backend accepts a declarative spec over a whitelisted vocabulary
 * (entities, fields, aggregations, filter operators) and refuses anything
 * outside it at creation time. This dialog is that vocabulary as pickers:
 * every option comes from `GET /kpis/spec-catalog`, so the form can only
 * offer what the server will accept, and a field the server drops stops
 * being offered without a frontend release.
 *
 * Nothing here is free text that reaches a query. The only typed values are
 * the KPI's own name / code / description and filter values, and the last of
 * those are type-checked against the field's kind on the server before the
 * definition is stored.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Loader2, Plus, Trash2 } from 'lucide-react';
import { Button, WideModal, WideModalSection, WideModalField } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  createKpi,
  getKpiSpecCatalog,
  type KpiCategory,
  type KpiScope,
  type KpiSpec,
  type KpiSpecCatalog,
  type KpiSpecEntity,
  type KpiSpecFilter,
} from './api';
import { defaultLabelField } from './breakdownLabel';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** The trend roll-up vocabulary, which is not the spec's aggregation. */
const TREND_AGGREGATIONS = ['last', 'sum', 'avg', 'min', 'max', 'derive'] as const;
const UNITS = ['ratio', 'percent', 'currency', 'count', 'days', 'hours', 'm2', 'm3'] as const;
const CATEGORIES: KpiCategory[] = [
  'financial',
  'schedule',
  'quality',
  'safety',
  'sustainability',
  'operational',
];

/** Operators that take no value at all. */
const VALUELESS_OPS = ['is_null', 'not_null'];

/** A filter as the form holds it, before it is turned into spec shape. */
interface FilterDraft {
  field: string;
  op: string;
  value: string;
}

/**
 * Humanise a snake_case token for display, e.g. `unit_rate` -> `Unit rate`.
 *
 * Field names come from the server's catalog and are a data dictionary
 * rather than UI copy: they are the same words in every language, the same
 * way the source-module chips in the KPI library already render them. Only
 * the words this dialog writes itself are translated.
 */
function humanizeToken(key: string): string {
  const spaced = key.replace(/_/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Turn a typed name into a legal KPI code, so nobody has to invent one. */
function slugifyCode(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/^([0-9])/, 'k$1')
    .slice(0, 64);
}

const CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * A typed filter value for a numeric field, as a number when it is one.
 *
 * What is typed is text, and text that is not a number has to travel as
 * itself. `Number('abc')` is NaN, `JSON.stringify` turns NaN into null, and
 * the server would then answer "this operator needs a value" to somebody who
 * did give one. Sent as written, the refusal names the field, the value and
 * why it was refused.
 */
function asNumberOrRaw(text: string): number | string {
  const parsed = Number(text);
  return text.trim() !== '' && Number.isFinite(parsed) ? parsed : text;
}

export function CustomKpiModal({
  projectId,
  projectName,
  onClose,
}: {
  /**
   * The project in the address bar, when there is one. The KPI is pinned to
   * it, exactly as a dashboard created on a project route is; the plain
   * module route creates a company-wide definition.
   */
  projectId?: string;
  projectName?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const catalogQ = useQuery({
    queryKey: ['bi', 'kpi-spec-catalog'],
    queryFn: getKpiSpecCatalog,
    staleTime: 10 * 60_000,
  });
  const catalog: KpiSpecCatalog | undefined = catalogQ.data;

  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [codeTouched, setCodeTouched] = useState(false);
  const [description, setDescription] = useState('');
  const [unit, setUnit] = useState<string>('ratio');
  const [category, setCategory] = useState<KpiCategory>('operational');
  const [trend, setTrend] = useState<string>('last');
  const [target, setTarget] = useState('');

  const [scope, setScope] = useState<KpiScope>('project');
  const [entityName, setEntityName] = useState('');
  const [aggregation, setAggregation] = useState('');
  const [fieldName, setFieldName] = useState('');
  const [weightField, setWeightField] = useState('');
  const [groupBy, setGroupBy] = useState('');
  const [labelField, setLabelField] = useState('');
  const [filters, setFilters] = useState<FilterDraft[]>([]);

  // The catalog decides the defaults, so the dialog opens on a spec that is
  // already valid instead of on empty pickers the user has to guess at.
  const entities = catalog?.entities ?? [];
  const entity: KpiSpecEntity | undefined =
    entities.find((e) => e.name === entityName) ?? entities[0];
  const effectiveEntity = entity?.name ?? '';
  const aggregations = catalog?.aggregations ?? [];
  const effectiveAggregation = aggregations.includes(aggregation)
    ? aggregation
    : (aggregations[0] ?? '');
  const operators = catalog?.filter_operators ?? [];

  // Not every entity has an estimate of its own. A project has one row per
  // building, which is what makes its floor area worth measuring and what
  // stops an estimate owning it; the cost-item ledger records which project a
  // rate was applied to and not which bill. Reading the effective value here
  // rather than resetting the state means switching between two entities that
  // both support it keeps the choice, while switching to one that does not
  // shows - and sends - what will actually happen.
  const canScopeToEstimate = entity?.narrows_to_estimate ?? false;
  const effectiveScope: KpiScope = canScopeToEstimate ? scope : 'project';
  const numericFields = entity?.numeric_fields ?? [];
  const groupableFields = entity?.groupable_fields ?? [];
  const allFields = entity?.fields ?? [];

  const needsField = effectiveAggregation !== 'count' && effectiveAggregation !== '';
  const needsWeight = effectiveAggregation === 'weighted_avg';
  // A label names the rows of a breakdown, so it needs rows: either a
  // grouping, or `top_by`, which returns the single highest row.
  const canLabel = effectiveAggregation === 'top_by' || groupBy !== '';

  const effectiveField = needsField
    ? numericFields.includes(fieldName)
      ? fieldName
      : (numericFields[0] ?? '')
    : '';
  const effectiveWeight = needsWeight
    ? numericFields.includes(weightField)
      ? weightField
      : (numericFields[0] ?? '')
    : '';
  // The field the server fills the label in with when the spec leaves it
  // out, because grouping by an id and reading back ids is nobody's
  // question. Shown pre-selected rather than left blank: a picker reading
  // "leave the group value as it is" beside a server that will not leave
  // it is a form disagreeing with what it submits.
  const defaultLabel = canLabel ? defaultLabelField(entity, groupBy) : '';
  const effectiveLabel = canLabel && groupableFields.includes(labelField) ? labelField : defaultLabel;

  const kindOf = (field: string): string =>
    allFields.find((f) => f.name === field)?.kind ?? 'text';

  /**
   * The value a fresh filter on this field starts holding.
   *
   * A boolean filter renders as a Yes / No pair with no empty option, so an
   * empty draft shows "Yes" while the row is dropped for carrying no value -
   * the filter on screen and the definition below it disagree, and the one
   * that travels is the one nobody read. What the picker displays is what
   * the draft holds.
   */
  const initialFilterValue = (field: string): string => (kindOf(field) === 'bool' ? 'true' : '');

  const aggregationLabels: Record<string, string> = {
    count: t('bi.kpi_agg_count', { defaultValue: 'Count of rows' }),
    sum: t('bi.kpi_agg_sum', { defaultValue: 'Sum' }),
    avg: t('bi.kpi_agg_avg', { defaultValue: 'Average' }),
    min: t('bi.kpi_agg_min', { defaultValue: 'Lowest' }),
    max: t('bi.kpi_agg_max', { defaultValue: 'Highest' }),
    weighted_avg: t('bi.kpi_agg_weighted_avg', { defaultValue: 'Weighted average' }),
    top_by: t('bi.kpi_agg_top_by', { defaultValue: 'Largest single row' }),
  };
  const operatorLabels: Record<string, string> = {
    eq: t('bi.kpi_op_eq', { defaultValue: 'is' }),
    ne: t('bi.kpi_op_ne', { defaultValue: 'is not' }),
    lt: t('bi.kpi_op_lt', { defaultValue: 'is less than' }),
    lte: t('bi.kpi_op_lte', { defaultValue: 'is at most' }),
    gt: t('bi.kpi_op_gt', { defaultValue: 'is more than' }),
    gte: t('bi.kpi_op_gte', { defaultValue: 'is at least' }),
    in: t('bi.kpi_op_in', { defaultValue: 'is one of' }),
    is_null: t('bi.kpi_op_is_null', { defaultValue: 'is not set' }),
    not_null: t('bi.kpi_op_not_null', { defaultValue: 'is set' }),
  };
  const unitLabels: Record<string, string> = {
    ratio: t('bi.kpi_unit_ratio', { defaultValue: 'Ratio' }),
    percent: t('bi.kpi_unit_percent', { defaultValue: 'Percent' }),
    currency: t('bi.kpi_unit_currency', { defaultValue: 'Money' }),
    count: t('bi.kpi_unit_count', { defaultValue: 'Count' }),
    days: t('bi.kpi_unit_days', { defaultValue: 'Days' }),
    hours: t('bi.kpi_unit_hours', { defaultValue: 'Hours' }),
    m2: t('bi.kpi_unit_m2', { defaultValue: 'Square metres' }),
    m3: t('bi.kpi_unit_m3', { defaultValue: 'Cubic metres' }),
  };
  const categoryLabels: Record<KpiCategory, string> = {
    financial: t('bi.kpi_category_financial', { defaultValue: 'Financial' }),
    schedule: t('bi.kpi_category_schedule', { defaultValue: 'Schedule' }),
    quality: t('bi.kpi_category_quality', { defaultValue: 'Quality' }),
    safety: t('bi.kpi_category_safety', { defaultValue: 'Safety' }),
    sustainability: t('bi.kpi_category_sustainability', { defaultValue: 'Sustainability' }),
    operational: t('bi.kpi_category_operational', { defaultValue: 'Operational' }),
  };
  const trendLabels: Record<string, string> = {
    last: t('bi.kpi_trend_last', { defaultValue: 'Latest value' }),
    sum: t('bi.kpi_trend_sum', { defaultValue: 'Sum of the period' }),
    avg: t('bi.kpi_trend_avg', { defaultValue: 'Average of the period' }),
    min: t('bi.kpi_trend_min', { defaultValue: 'Lowest of the period' }),
    max: t('bi.kpi_trend_max', { defaultValue: 'Highest of the period' }),
    derive: t('bi.kpi_trend_derive', { defaultValue: 'Recomputed each period' }),
  };

  /** The filters that are complete enough to send. */
  const builtFilters = useMemo<KpiSpecFilter[]>(() => {
    const kindLookup = (field: string): string =>
      allFields.find((f) => f.name === field)?.kind ?? 'text';
    const out: KpiSpecFilter[] = [];
    for (const draft of filters) {
      if (!draft.field || !draft.op) continue;
      if (VALUELESS_OPS.includes(draft.op)) {
        out.push({ field: draft.field, op: draft.op });
        continue;
      }
      if (draft.value.trim() === '') continue;
      const kind = kindLookup(draft.field);
      if (draft.op === 'in') {
        const members = draft.value
          .split(',')
          .map((part) => part.trim())
          .filter((part) => part !== '');
        if (members.length === 0) continue;
        out.push({
          field: draft.field,
          op: draft.op,
          value: kind === 'numeric' ? members.map(asNumberOrRaw) : members,
        });
        continue;
      }
      const raw = draft.value.trim();
      const value =
        kind === 'numeric' ? asNumberOrRaw(raw) : kind === 'bool' ? raw === 'true' : raw;
      out.push({ field: draft.field, op: draft.op, value });
    }
    return out;
  }, [filters, allFields]);

  const spec: KpiSpec = useMemo(() => {
    const built: KpiSpec = { entity: effectiveEntity, aggregation: effectiveAggregation };
    if (needsField && effectiveField) built.field = effectiveField;
    if (needsWeight && effectiveWeight) built.weight_field = effectiveWeight;
    if (groupBy) built.group_by = groupBy;
    if (canLabel && effectiveLabel) built.label_field = effectiveLabel;
    if (builtFilters.length > 0) built.filters = builtFilters;
    return built;
  }, [
    effectiveEntity,
    effectiveAggregation,
    needsField,
    effectiveField,
    needsWeight,
    effectiveWeight,
    groupBy,
    canLabel,
    effectiveLabel,
    builtFilters,
  ]);

  const effectiveCode = codeTouched ? code : slugifyCode(name);
  const codeError =
    effectiveCode !== '' && !CODE_PATTERN.test(effectiveCode)
      ? t('bi.kpi_code_invalid', {
          defaultValue:
            'A code starts with a letter and holds only lower case letters, digits and underscores.',
        })
      : undefined;

  const canSubmit =
    name.trim() !== '' &&
    effectiveCode !== '' &&
    codeError === undefined &&
    effectiveEntity !== '' &&
    effectiveAggregation !== '' &&
    (!needsField || effectiveField !== '') &&
    (!needsWeight || effectiveWeight !== '');

  const createMut = useMutation({
    mutationFn: () =>
      createKpi({
        code: effectiveCode,
        name: name.trim(),
        description: description.trim(),
        unit,
        category,
        aggregation: trend,
        target_default: target.trim() === '' ? null : Number(target),
        ...(projectId ? { project_id: projectId } : {}),
        scope: effectiveScope,
        spec,
      }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['bi', 'kpis'] });
      addToast({
        type: 'success',
        title: t('bi.kpi_created', { defaultValue: 'KPI created' }),
        message: t('bi.kpi_created_body', {
          defaultValue: '{{name}} is in the library. Compute it to read its first value.',
          name: created.name,
        }),
      });
      onClose();
    },
    // A refusal names the part of the spec it refused ("spec.field: unknown
    // field ..."), so it is shown as it comes rather than replaced by a
    // generic failure line.
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('bi.kpi_create_failed', { defaultValue: 'The KPI was not created' }),
        message: getErrorMessage(err),
      }),
  });

  const subtitle = t('bi.new_kpi_subtitle', {
    defaultValue:
      'Pick what to measure and the platform computes it. The options below are the whole vocabulary the server accepts, so a definition that fits in this form is one that will produce a number.',
  });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('bi.new_kpi_title', { defaultValue: 'New KPI' })}
      subtitle={
        projectId && projectName
          ? `${subtitle} ${t('common.creating_in_project', {
              defaultValue: 'In {{project}}',
              project: projectName,
            })}`
          : subtitle
      }
      size="lg"
      busy={createMut.isPending}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={createMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            loading={createMut.isPending}
            disabled={!canSubmit || createMut.isPending || catalogQ.isLoading}
            icon={createMut.isPending ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      {catalogQ.isError ? (
        <p className="text-sm text-semantic-error">
          {t('bi.kpi_catalog_failed', {
            defaultValue:
              'The list of things a KPI can measure could not be loaded, so the form has nothing to offer.',
          })}{' '}
          {getErrorMessage(catalogQ.error)}
        </p>
      ) : (
        <>
          <WideModalSection
            title={t('bi.kpi_identity_section', { defaultValue: 'The KPI itself' })}
            columns={2}
          >
            <WideModalField label={t('bi.name', { defaultValue: 'Name' })} required span={2}>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={inputCls}
                placeholder={t('bi.kpi_name_placeholder', {
                  defaultValue: 'Amount-weighted bid confidence',
                })}
              />
            </WideModalField>
            <WideModalField
              label={t('bi.kpi_code', { defaultValue: 'Code' })}
              required
              error={codeError}
              hint={t('bi.kpi_code_hint', {
                defaultValue:
                  'How widgets, alerts and reports name this KPI. Filled in from the name; change it before creating, because it cannot be renamed afterwards.',
              })}
            >
              <input
                value={effectiveCode}
                onChange={(e) => {
                  setCodeTouched(true);
                  setCode(e.target.value);
                }}
                className={clsx(inputCls, 'font-mono')}
                placeholder="bid_confidence"
              />
            </WideModalField>
            <WideModalField label={t('bi.kpi_unit', { defaultValue: 'Unit' })}>
              <select value={unit} onChange={(e) => setUnit(e.target.value)} className={inputCls}>
                {UNITS.map((u) => (
                  <option key={u} value={u}>
                    {unitLabels[u] ?? humanizeToken(u)}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField label={t('bi.kpi_category', { defaultValue: 'Category' })}>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as KpiCategory)}
                className={inputCls}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {categoryLabels[c]}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('bi.kpi_trend_aggregation', { defaultValue: 'Trend roll-up' })}
              hint={t('bi.kpi_trend_aggregation_hint', {
                defaultValue:
                  'How saved readings of this KPI roll up over a period on a chart. It is not what the KPI measures.',
              })}
            >
              <select value={trend} onChange={(e) => setTrend(e.target.value)} className={inputCls}>
                {TREND_AGGREGATIONS.map((a) => (
                  <option key={a} value={a}>
                    {trendLabels[a] ?? humanizeToken(a)}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('bi.kpi_target', { defaultValue: 'Target' })}
              hint={t('bi.kpi_target_hint', {
                defaultValue: 'Optional. The value this KPI is aiming at.',
              })}
            >
              <input
                type="number"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className={inputCls}
              />
            </WideModalField>
            <WideModalField label={t('bi.description', { defaultValue: 'Description' })} span={2}>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className={clsx(inputCls, 'h-auto py-2 resize-y')}
                placeholder={t('bi.kpi_description_placeholder', {
                  defaultValue: 'What this number tells the reader, in one line.',
                })}
              />
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('bi.kpi_measure_section', { defaultValue: 'What it measures' })}
            columns={2}
          >
            <WideModalField
              label={t('bi.kpi_entity', { defaultValue: 'Data' })}
              hint={t('bi.kpi_entity_hint', {
                defaultValue: 'The records this KPI is computed over.',
              })}
            >
              <select
                value={effectiveEntity}
                onChange={(e) => {
                  setEntityName(e.target.value);
                  // Field names belong to an entity, so nothing chosen for
                  // the previous one survives the switch.
                  setFieldName('');
                  setWeightField('');
                  setGroupBy('');
                  setLabelField('');
                  setFilters([]);
                }}
                className={inputCls}
                disabled={catalogQ.isLoading}
              >
                {entities.map((e) => (
                  <option key={e.name} value={e.name}>
                    {humanizeToken(e.name)}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('bi.kpi_scope', { defaultValue: 'Read it per' })}
              hint={
                canScopeToEstimate
                  ? t('bi.kpi_scope_hint', {
                      defaultValue:
                        'A project holding several estimates gets one figure per estimate. Money adds up across them; a rate, an area or a margin does not.',
                    })
                  : t('bi.kpi_scope_hint_project_only', {
                      defaultValue:
                        'This data has no estimate of its own, so it can only be read per project.',
                    })
              }
            >
              <select
                value={effectiveScope}
                onChange={(e) => setScope(e.target.value as KpiScope)}
                className={inputCls}
                disabled={!canScopeToEstimate}
              >
                <option value="project">
                  {t('bi.kpi_scope_project', { defaultValue: 'Project' })}
                </option>
                <option value="estimate">
                  {t('bi.kpi_scope_estimate', { defaultValue: 'Estimate' })}
                </option>
              </select>
            </WideModalField>
            <WideModalField label={t('bi.kpi_aggregation', { defaultValue: 'Aggregation' })}>
              <select
                value={effectiveAggregation}
                onChange={(e) => setAggregation(e.target.value)}
                className={inputCls}
                disabled={catalogQ.isLoading}
              >
                {aggregations.map((a) => (
                  <option key={a} value={a}>
                    {aggregationLabels[a] ?? humanizeToken(a)}
                  </option>
                ))}
              </select>
            </WideModalField>
            {needsField && (
              <WideModalField
                label={t('bi.kpi_field', { defaultValue: 'Field' })}
                required
                hint={t('bi.kpi_field_hint', {
                  defaultValue: 'Only fields holding a number can be measured.',
                })}
              >
                <select
                  value={effectiveField}
                  onChange={(e) => setFieldName(e.target.value)}
                  className={inputCls}
                >
                  {numericFields.map((f) => (
                    <option key={f} value={f}>
                      {humanizeToken(f)}
                    </option>
                  ))}
                </select>
              </WideModalField>
            )}
            {needsWeight && (
              <WideModalField
                label={t('bi.kpi_weight_field', { defaultValue: 'Weighted by' })}
                required
                hint={t('bi.kpi_weight_field_hint', {
                  defaultValue: 'Each row counts in proportion to this field.',
                })}
              >
                <select
                  value={effectiveWeight}
                  onChange={(e) => setWeightField(e.target.value)}
                  className={inputCls}
                >
                  {numericFields.map((f) => (
                    <option key={f} value={f}>
                      {humanizeToken(f)}
                    </option>
                  ))}
                </select>
              </WideModalField>
            )}
            <WideModalField
              label={t('bi.kpi_group_by', { defaultValue: 'Break down by' })}
              hint={t('bi.kpi_group_by_hint', {
                defaultValue:
                  'Optional. Splits the headline number into one reading per value, up to {{max}} groups.',
                max: catalog?.max_breakdown_groups ?? 200,
              })}
            >
              <select
                value={groupBy}
                onChange={(e) => setGroupBy(e.target.value)}
                className={inputCls}
              >
                <option value="">{t('bi.kpi_group_by_none', { defaultValue: 'No breakdown' })}</option>
                {groupableFields.map((f) => (
                  <option key={f} value={f}>
                    {humanizeToken(f)}
                  </option>
                ))}
              </select>
            </WideModalField>
            {canLabel && (
              <WideModalField
                label={t('bi.kpi_label_field', { defaultValue: 'Name each group by' })}
                hint={
                  defaultLabel !== ''
                    ? t('bi.kpi_label_field_hint_defaulted', {
                        defaultValue:
                          'A breakdown keyed by an id reads as a column of ids, so it is named by {{field}} unless you pick another field here.',
                        field: humanizeToken(defaultLabel),
                      })
                    : t('bi.kpi_label_field_hint', {
                        defaultValue:
                          'Optional. A breakdown keyed by an id reads as a column of ids; this is the field that gives each one a name.',
                      })
                }
              >
                <select
                  value={effectiveLabel}
                  onChange={(e) => setLabelField(e.target.value)}
                  className={inputCls}
                >
                  {defaultLabel === '' && (
                    <option value="">
                      {t('bi.kpi_label_field_none', { defaultValue: 'Leave the group value as it is' })}
                    </option>
                  )}
                  {groupableFields.map((f) => (
                    <option key={f} value={f}>
                      {humanizeToken(f)}
                    </option>
                  ))}
                </select>
              </WideModalField>
            )}
          </WideModalSection>

          <WideModalSection
            title={t('bi.kpi_filters_section', { defaultValue: 'Only count rows where' })}
            columns={1}
          >
            <WideModalField span={1}>
              <div className="space-y-2">
                {filters.length === 0 && (
                  <p className="text-xs text-content-tertiary">
                    {t('bi.kpi_filters_empty', {
                      defaultValue: 'No filters, so every row is counted.',
                    })}
                  </p>
                )}
                {filters.map((draft, index) => {
                  const kind = kindOf(draft.field);
                  const valueless = VALUELESS_OPS.includes(draft.op);
                  const update = (patch: Partial<FilterDraft>) =>
                    setFilters(filters.map((f, i) => (i === index ? { ...f, ...patch } : f)));
                  return (
                    <div key={index} className="flex flex-wrap items-center gap-2">
                      <select
                        value={draft.field}
                        onChange={(e) =>
                          update({ field: e.target.value, value: initialFilterValue(e.target.value) })
                        }
                        className={clsx(inputCls, 'w-auto min-w-[9rem] flex-1')}
                        aria-label={t('bi.kpi_filter_field', { defaultValue: 'Filter field' })}
                      >
                        {allFields.map((f) => (
                          <option key={f.name} value={f.name}>
                            {humanizeToken(f.name)}
                          </option>
                        ))}
                      </select>
                      <select
                        value={draft.op}
                        onChange={(e) =>
                          update({ op: e.target.value, value: initialFilterValue(draft.field) })
                        }
                        className={clsx(inputCls, 'w-auto min-w-[8rem]')}
                        aria-label={t('bi.kpi_filter_op', { defaultValue: 'Filter operator' })}
                      >
                        {operators.map((op) => (
                          <option key={op} value={op}>
                            {operatorLabels[op] ?? humanizeToken(op)}
                          </option>
                        ))}
                      </select>
                      {!valueless &&
                        (kind === 'bool' ? (
                          <select
                            value={draft.value || 'true'}
                            onChange={(e) => update({ value: e.target.value })}
                            className={clsx(inputCls, 'w-auto min-w-[7rem]')}
                            aria-label={t('bi.kpi_filter_value', { defaultValue: 'Filter value' })}
                          >
                            <option value="true">{t('common.yes', { defaultValue: 'Yes' })}</option>
                            <option value="false">{t('common.no', { defaultValue: 'No' })}</option>
                          </select>
                        ) : (
                          <input
                            value={draft.value}
                            onChange={(e) => update({ value: e.target.value })}
                            className={clsx(inputCls, 'w-auto min-w-[9rem] flex-1')}
                            inputMode={kind === 'numeric' && draft.op !== 'in' ? 'decimal' : 'text'}
                            aria-label={t('bi.kpi_filter_value', { defaultValue: 'Filter value' })}
                            placeholder={
                              draft.op === 'in'
                                ? t('bi.kpi_filter_value_list_placeholder', {
                                    defaultValue: 'One value per comma',
                                  })
                                : ''
                            }
                          />
                        ))}
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Trash2 size={12} />}
                        onClick={() => setFilters(filters.filter((_f, i) => i !== index))}
                        title={t('bi.kpi_remove_filter', { defaultValue: 'Remove this filter' })}
                        aria-label={t('bi.kpi_remove_filter', {
                          defaultValue: 'Remove this filter',
                        })}
                      />
                    </div>
                  );
                })}
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Plus size={12} />}
                  disabled={allFields.length === 0 || operators.length === 0}
                  onClick={() => {
                    const field = allFields[0]?.name ?? '';
                    setFilters([
                      ...filters,
                      {
                        field,
                        op: operators[0] ?? 'eq',
                        value: initialFilterValue(field),
                      },
                    ]);
                  }}
                >
                  {t('bi.kpi_add_filter', { defaultValue: 'Add a filter' })}
                </Button>
              </div>
            </WideModalField>
          </WideModalSection>

          {/* The definition as it will be sent. It is data, not code, and
              showing it is how somebody checks their own KPI before it goes
              in - and how they report one that reads wrong. */}
          <WideModalSection columns={1}>
            <WideModalField
              label={t('bi.kpi_spec_preview', { defaultValue: 'The definition' })}
              span={1}
            >
              <pre className="overflow-x-auto rounded-lg bg-surface-secondary p-3 text-2xs leading-relaxed text-content-secondary">
                {JSON.stringify(spec, null, 2)}
              </pre>
            </WideModalField>
          </WideModalSection>
        </>
      )}
    </WideModal>
  );
}
