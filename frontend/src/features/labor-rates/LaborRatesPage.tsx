// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import {
  Plus,
  Trash2,
  Save,
  Users,
  Calculator,
  ArrowDownToLine,
  Database,
  FilePlus,
} from 'lucide-react';

import { Button, ConfirmDialog } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { getErrorMessage } from '@/shared/lib/api';
import {
  laborRatesApi,
  buildComputeRequest,
  canSaveTemplate,
  isPositiveAmount,
  newOnCost,
  newCrewMember,
  type OnCostKind,
  type OnCostRowInput,
  type CrewRowInput,
  readInUseRefusal,
  type LaborRateTemplate,
  type CostItemPayload,
  type InUseReference,
} from './api';
import { fmtList, fmtPercent } from '@/shared/lib/formatters';

/** Debounce any value so the live compute does not fire on every keystroke. */
function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

const inputClass =
  'w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary ' +
  'placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue';

const cardClass =
  'rounded-xl border border-border bg-surface-elevated p-4 sm:p-5 shadow-sm';

// Composition-bar palette: the base wage is brand blue, each on-cost cycles a
// distinct muted hue so the stacked "where the rate goes" bar reads clearly.
const BASE_COLOR = 'var(--oe-blue)';
const ONCOST_COLORS = ['#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#14b8a6', '#64748b'];

/**
 * All-in labor and crew rate build-up.
 *
 * The estimator enters a base wage and a list of on-costs (statutory charges,
 * insurance, leave, overtime, supervision, small tools); the backend computes
 * a fully loaded hourly rate live. A crew composer blends several trades into a
 * composite crew rate. Every displayed figure is the authoritative Decimal the
 * backend returns - the page never does money arithmetic itself.
 */
export function LaborRatesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const confirmState = useConfirm();
  const { confirm } = confirmState;

  const [baseWage, setBaseWage] = useState('30');
  const [currency, setCurrency] = useState('');
  // Seed a fresh build-up with common on-cost labels (editable by the user).
  const [onCosts, setOnCosts] = useState<OnCostRowInput[]>(() => [
    newOnCost(t('laborRates.seed.statutory', { defaultValue: 'Statutory charges' }), 'percentage'),
    newOnCost(t('laborRates.seed.insurance', { defaultValue: 'Insurance' }), 'percentage'),
    newOnCost(t('laborRates.seed.leave', { defaultValue: 'Leave & holiday provision' }), 'percentage'),
    newOnCost(t('laborRates.seed.overtime', { defaultValue: 'Overtime uplift' }), 'percentage'),
    newOnCost(t('laborRates.seed.supervision', { defaultValue: 'Supervision' }), 'percentage'),
    newOnCost(t('laborRates.seed.small_tools', { defaultValue: 'Small tools & consumables' }), 'fixed'),
  ]);
  const [crew, setCrew] = useState<CrewRowInput[]>(() => [newCrewMember()]);
  const [templateName, setTemplateName] = useState('');
  // The saved template currently open for correction. Null means the editor is
  // building a brand new rate, so saving creates rather than overwrites.
  const [editingId, setEditingId] = useState<string | null>(null);

  // ── Live build-up (authoritative, from the backend) ───────────────────────
  const request = useMemo(
    () => buildComputeRequest({ base_wage: baseWage, currency, onCosts, crew }),
    [baseWage, currency, onCosts, crew],
  );
  const debouncedRequest = useDebounced(request, 300);
  const computeQuery = useQuery({
    queryKey: ['labor-rates', 'compute', JSON.stringify(debouncedRequest)],
    queryFn: () => laborRatesApi.compute(debouncedRequest),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
  const breakdown = computeQuery.data;
  const allInRate = breakdown?.all_in_rate ?? '0';
  // The build-up preview is happy with a blank wage (it reads as zero), the
  // template endpoint is not: it refuses a wage of zero outright. Saving is
  // gated on the same rule here so an unfilled field is answered in the user's
  // language instead of as a validation error from the server.
  const baseWageOk = isPositiveAmount(baseWage);

  // ── Templates ─────────────────────────────────────────────────────────────
  const templatesQuery = useQuery({
    queryKey: ['labor-rates', 'templates'],
    queryFn: laborRatesApi.listTemplates,
  });

  /** Open a saved template for correction: its values fill the editor. */
  const loadTemplate = (template: LaborRateTemplate) => {
    setBaseWage(template.base_wage ?? '0');
    setCurrency(template.currency ?? '');
    setOnCosts(
      (template.components ?? []).map((c) => newOnCost(c.label, c.kind, c.value)),
    );
    setTemplateName(template.name ?? '');
    setEditingId(template.id);
  };

  /** Leave the saved template alone and start a fresh build-up. */
  const startNewTemplate = () => {
    setEditingId(null);
    setTemplateName('');
  };

  const editingTemplate = useMemo(
    () => (templatesQuery.data ?? []).find((tpl) => tpl.id === editingId) ?? null,
    [templatesQuery.data, editingId],
  );

  const saveMutation = useMutation({
    mutationFn: () =>
      laborRatesApi.createTemplate({
        name: templateName.trim(),
        base_wage: request.base_wage,
        currency: request.currency,
        components: request.components,
      }),
    onSuccess: (created: LaborRateTemplate) => {
      addToast({
        type: 'success',
        title: t('laborRates.saved_title', { defaultValue: 'Template saved' }),
        message: t('laborRates.saved_msg', {
          defaultValue: '"{{name}}" is available to reuse.',
          name: created?.name ?? templateName,
        }),
      });
      // A "save as new" from an open template leaves the new row selected, so
      // a follow-up correction edits the copy the user just made.
      if (created?.id) setEditingId(created.id);
      queryClient.invalidateQueries({ queryKey: ['labor-rates', 'templates'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('laborRates.save_failed', { defaultValue: 'Could not save template' }),
        message: getErrorMessage(err),
      });
    },
  });

  // ── Correcting a saved template ───────────────────────────────────────────
  // The name, the base wage, the currency and the whole on-cost list are sent
  // back, so a rename and a wrong-figure correction are the same operation.
  const updateMutation = useMutation({
    mutationFn: (id: string) =>
      laborRatesApi.updateTemplate(id, {
        name: templateName.trim(),
        base_wage: request.base_wage,
        currency: request.currency,
        components: request.components,
      }),
    onSuccess: (updated: LaborRateTemplate) => {
      addToast({
        type: 'success',
        title: t('laborRates.updated_title', { defaultValue: 'Template updated' }),
        message: t('laborRates.updated_msg', {
          defaultValue: '"{{name}}" now carries your changes.',
          name: updated?.name ?? templateName,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['labor-rates', 'templates'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('laborRates.update_failed', { defaultValue: 'Could not update template' }),
        message: getErrorMessage(err),
      });
    },
  });

  // ── Deleting a saved template ─────────────────────────────────────────────
  // The backend refuses with 409 while a published cost item or a priced
  // assembly still references the template, and names the holders. That answer
  // is worth reading, so it is turned into the sentence below instead of the
  // generic conflict fallback an unhandled ApiError would show.

  /** Name one holder in the user's language, e.g. "published cost items: 3". */
  const holderLabel = (reference: InUseReference): string | null => {
    const n = Number(reference.count) || 0;
    if (reference.kind === 'cost_item') {
      return t('laborRates.holder_cost_items', {
        defaultValue: 'published cost items: {{n}}',
        n,
      });
    }
    if (reference.kind === 'assembly') {
      return t('laborRates.holder_assemblies', {
        defaultValue: 'priced assemblies: {{n}}',
        n,
      });
    }
    return null;
  };

  const deleteMutation = useMutation({
    mutationFn: (id: string) => laborRatesApi.deleteTemplate(id),
    onSuccess: (_result, id: string) => {
      const name = (templatesQuery.data ?? []).find((tpl) => tpl.id === id)?.name ?? '';
      addToast({
        type: 'success',
        title: t('laborRates.deleted_title', { defaultValue: 'Template deleted' }),
        message: t('laborRates.deleted_msg', {
          defaultValue: '"{{name}}" is no longer in the list.',
          name,
        }),
      });
      if (editingId === id) startNewTemplate();
      queryClient.invalidateQueries({ queryKey: ['labor-rates', 'templates'] });
    },
    onError: (err: unknown) => {
      const references = readInUseRefusal(err);
      if (references) {
        const holders = fmtList(
          references
            .map(holderLabel)
            .filter((label): label is string => label !== null),
        );
        addToast({
          type: 'error',
          title: t('laborRates.delete_blocked_title', {
            defaultValue: 'Template still in use',
          }),
          // With an unrecognised holder kind the list comes back empty, so the
          // backend's own English sentence is shown rather than a blank clause.
          message: holders
            ? t('laborRates.delete_blocked_msg', {
                defaultValue:
                  'This template cannot be deleted while other records use it. Still using it: {{holders}}. Remove them first, then delete the template.',
                holders,
              })
            : getErrorMessage(err),
        });
        return;
      }
      addToast({
        type: 'error',
        title: t('laborRates.delete_failed', { defaultValue: 'Could not delete template' }),
        message: getErrorMessage(err),
      });
    },
  });

  /** Confirm what is about to go, then delete it. */
  const onDeleteTemplate = async (template: LaborRateTemplate) => {
    const ok = await confirm({
      title: t('laborRates.delete_template_q', { defaultValue: 'Delete this rate template?' }),
      message: t('laborRates.delete_template_msg', {
        defaultValue:
          'This permanently deletes "{{name}}", its {{onCosts}} on-costs and its saved all-in rate of {{rate}}. It cannot be undone.',
        name: template.name,
        onCosts: (template.components ?? []).length,
        rate: formatCurrency(template.all_in_rate, template.currency),
      }),
      confirmLabel: t('laborRates.delete_confirm', { defaultValue: 'Delete template' }),
    });
    if (ok) deleteMutation.mutate(template.id);
  };

  // ── On-cost row editing ───────────────────────────────────────────────────
  const updateOnCost = (key: string, patch: Partial<OnCostRowInput>) =>
    setOnCosts((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const removeOnCost = (key: string) =>
    setOnCosts((rows) => rows.filter((r) => r.key !== key));
  const addOnCost = () => setOnCosts((rows) => [...rows, newOnCost()]);

  // ── Crew row editing ──────────────────────────────────────────────────────
  const updateCrew = (key: string, patch: Partial<CrewRowInput>) =>
    setCrew((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const removeCrew = (key: string) => setCrew((rows) => rows.filter((r) => r.key !== key));
  const addCrew = () => setCrew((rows) => [...rows, newCrewMember()]);
  const useAllInFor = (key: string) => updateCrew(key, { all_in_rate: allInRate });

  const crewBreakdown = breakdown?.crew ?? null;

  // Display-only ratios for the headline + composition bar. These drive a CSS
  // width and a percentage label, never a money figure, so Number() is safe
  // here (the authoritative Decimals still come from the backend everywhere a
  // currency value is shown via formatCurrency).
  // The backend figure is already a dot-decimal string; the fallback is the
  // raw text the user is still typing, so it needs the locale-aware parse.
  const baseNum =
    breakdown?.base_wage != null ? Number(breakdown.base_wage) : (parseDecimalInput(baseWage) ?? 0);
  const allInNum = Number(allInRate);
  const burdenPct =
    baseNum > 0 && allInNum > 0 ? ((allInNum - baseNum) / baseNum) * 100 : null;

  // ── Publish computed rates as reusable cost items ──────────────────────────
  // The all-in rate (and, when a crew is composed, the blended crew rate) can
  // be saved into the cost catalogue as COST ITEMS, so they flow onward into
  // BOQ / assemblies via the existing costs->BOQ path. Money stays a
  // Decimal-string end to end: the authoritative Decimals the compute endpoint
  // returned are forwarded verbatim; the client never re-derives a rate with
  // float math.
  const saveCostItemMutation = useMutation({
    mutationFn: (args: { variant: 'all_in' | 'crew'; payload: CostItemPayload }) =>
      laborRatesApi.saveAsCostItem(args.payload),
    onSuccess: (created) => {
      addToast({
        type: 'success',
        title: t('laborRates.cost_item_saved_title', {
          defaultValue: 'Saved to cost catalogue',
        }),
        message: t('laborRates.cost_item_saved_msg', {
          defaultValue: '"{{code}}" is now a cost item you can add to a BOQ.',
          code: created?.code ?? '',
        }),
      });
      // Best-effort refresh of any mounted cost-database view.
      queryClient.invalidateQueries({ queryKey: ['costs'] });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('laborRates.cost_item_failed', {
          defaultValue: 'Could not save cost item',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  // A bounded, catalogue-safe, unique code derived from the template name (or a
  // default prefix). The base-36 timestamp suffix keeps repeated saves from
  // colliding on the cost item's unique-code constraint.
  const buildCostItemCode = (prefix: string): string => {
    const slug = templateName
      .trim()
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40);
    const suffix = Date.now().toString(36).toUpperCase();
    return slug ? `${prefix}-${slug}-${suffix}` : `${prefix}-${suffix}`;
  };

  const saveAllInAsCostItem = () => {
    if (!(allInNum > 0)) return;
    const name = templateName.trim();
    // Components mirror the build-up: the base wage plus each on-cost line, so
    // the component costs sum to the all-in rate and the downstream BOQ
    // unit_rate (Σ of resource totals) matches this item's rate. Money values
    // are the backend's Decimal-strings, passed through untouched.
    const components: CostItemPayload['components'] = [
      {
        name: t('laborRates.base_wage', { defaultValue: 'Base hourly wage' }),
        type: 'labor',
        unit: 'h',
        quantity: 1,
        unit_rate: breakdown?.base_wage ?? allInRate,
        cost: breakdown?.base_wage ?? allInRate,
      },
      ...(breakdown?.lines ?? []).map((line) => ({
        name: line.label,
        type: 'labor',
        unit: 'h',
        quantity: 1,
        unit_rate: line.amount,
        cost: line.amount,
      })),
    ];
    saveCostItemMutation.mutate({
      variant: 'all_in',
      payload: {
        code: buildCostItemCode('LABOR'),
        description:
          name ||
          t('laborRates.cost_item_default_desc', { defaultValue: 'All-in labor rate' }),
        unit: 'h',
        rate: allInRate,
        currency,
        source: 'manual',
        region: 'CUSTOM',
        classification: { collection: 'Labor' },
        components,
        tags: ['labor', 'labor-rate'],
      },
    });
  };

  const saveCrewAsCostItem = () => {
    if (!crewBreakdown || crewBreakdown.headcount <= 0) return;
    const name = templateName.trim();
    saveCostItemMutation.mutate({
      variant: 'crew',
      payload: {
        code: buildCostItemCode('CREW'),
        description: name
          ? t('laborRates.crew_cost_item_named_desc', {
              defaultValue: '{{name}} - blended crew rate',
              name,
            })
          : t('laborRates.crew_cost_item_desc', { defaultValue: 'Blended crew rate' }),
        unit: 'h',
        // Blended per-person-hour rate (crew total / headcount), an authoritative
        // Decimal-string from the backend. Saved as a flat rate item (no
        // components) so the downstream BOQ unit_rate equals the blended rate.
        rate: crewBreakdown.blended_hourly_rate,
        currency,
        source: 'manual',
        region: 'CUSTOM',
        classification: { collection: 'Labor' },
        tags: ['labor', 'crew-rate'],
      },
    });
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
            <Calculator size={22} />
          </span>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold text-content-primary">
              {t('laborRates.title', { defaultValue: 'Labor & crew rate build-up' })}
            </h1>
            <p className="max-w-2xl text-sm text-content-secondary">
              {t('laborRates.subtitle', {
                defaultValue:
                  'Build a fully loaded hourly rate from a base wage plus on-costs, then blend trades into a crew rate.',
              })}
            </p>
          </div>
        </div>
        {/* Live headline - all-in rate + labour burden, always in view */}
        <div className="flex items-center gap-4 rounded-xl border border-border bg-surface-elevated px-4 py-2.5 shadow-sm">
          <div className="text-right">
            <div className="text-[11px] font-medium uppercase tracking-wide text-content-tertiary">
              {t('laborRates.all_in_rate', { defaultValue: 'All-in hourly rate' })}
            </div>
            <div className="text-xl font-bold text-oe-blue-text">
              {formatCurrency(allInRate, currency)}
            </div>
          </div>
          {burdenPct !== null && (
            <div className="border-l border-border pl-4 text-right">
              <div className="text-[11px] font-medium uppercase tracking-wide text-content-tertiary">
                {t('laborRates.burden', { defaultValue: 'Labor burden' })}
              </div>
              <div className="text-xl font-bold text-content-primary">
                +{fmtPercent(burdenPct, 0)}
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Template picker */}
      <div className={cardClass}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-gray-700 dark:text-gray-300">
              {t('laborRates.load_template', { defaultValue: 'Load a saved template' })}
            </span>
            <select
              className={inputClass}
              style={{ minWidth: '16rem' }}
              value={editingId ?? ''}
              onChange={(e) => {
                if (e.target.value === '') {
                  startNewTemplate();
                  return;
                }
                const found = (templatesQuery.data ?? []).find((tpl) => tpl.id === e.target.value);
                if (found) loadTemplate(found);
              }}
            >
              <option value="">
                {templatesQuery.isLoading
                  ? t('laborRates.loading', { defaultValue: 'Loading…' })
                  : t('laborRates.choose_template', { defaultValue: 'Choose a template…' })}
              </option>
              {(templatesQuery.data ?? []).map((tpl) => (
                <option key={tpl.id} value={tpl.id}>
                  {tpl.name} · {formatCurrency(tpl.all_in_rate, tpl.currency)}
                </option>
              ))}
            </select>
          </label>
          {/* A saved template is not read-only: it can be corrected, renamed
              through the name field below, or removed outright. */}
          {editingTemplate && (
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<FilePlus size={14} />}
                onClick={startNewTemplate}
              >
                {t('laborRates.new_template', { defaultValue: 'New template' })}
              </Button>
              <Button
                variant="danger"
                size="sm"
                icon={<Trash2 size={14} />}
                loading={deleteMutation.isPending}
                disabled={deleteMutation.isPending}
                onClick={() => onDeleteTemplate(editingTemplate)}
              >
                {t('laborRates.delete_template', { defaultValue: 'Delete template' })}
              </Button>
            </div>
          )}
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {editingTemplate
              ? t('laborRates.editing_hint', {
                  defaultValue: 'Editing "{{name}}". Save changes to write your corrections back.',
                  name: editingTemplate.name,
                })
              : t('laborRates.template_hint', {
                  defaultValue: 'Loading a template fills the wage and on-costs below.',
                })}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
        {/* Editor column */}
        <div className="space-y-6 lg:col-span-3">
          {/* Base wage + currency */}
          <div className={cardClass}>
            <div className="flex flex-wrap gap-4">
              <label className="flex flex-1 flex-col gap-1 text-sm">
                <span className="font-medium text-gray-700 dark:text-gray-300">
                  {t('laborRates.base_wage', { defaultValue: 'Base hourly wage' })}
                </span>
                <input
                  className={inputClass}
                  inputMode="decimal"
                  value={baseWage}
                  onChange={(e) => setBaseWage(e.target.value)}
                  placeholder="0.00"
                  aria-label={t('laborRates.base_wage', { defaultValue: 'Base hourly wage' })}
                />
              </label>
              <label className="flex w-28 flex-col gap-1 text-sm">
                <span className="font-medium text-gray-700 dark:text-gray-300">
                  {t('laborRates.currency', { defaultValue: 'Currency' })}
                </span>
                <input
                  className={inputClass}
                  maxLength={3}
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                  placeholder="EUR"
                  aria-label={t('laborRates.currency', { defaultValue: 'Currency' })}
                />
              </label>
            </div>
          </div>

          {/* On-cost list */}
          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                {t('laborRates.oncosts', { defaultValue: 'On-costs' })}
              </h2>
              <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addOnCost}>
                {t('laborRates.add_oncost', { defaultValue: 'Add on-cost' })}
              </Button>
            </div>

            {/* What the block is for, in one line. The three columns used to
                carry their meaning only in aria-label and a placeholder reading
                "Label", so a sighted estimator faced an empty row and no way to
                know that the left cell wants the name of a payroll cost
                (founder report). The heading, the hint and the visible column
                titles all answer the same question in different places. */}
            <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
              {t('laborRates.oncosts_hint', {
                defaultValue:
                  'Everything the employer pays on top of the bare wage: social insurance, holiday pay, site allowances.',
              })}
            </p>

            <div className="space-y-2">
              {onCosts.length === 0 && (
                <p className="py-2 text-sm text-gray-400 dark:text-gray-500">
                  {t('laborRates.no_oncosts', {
                    defaultValue: 'No on-costs yet. The base wage is the all-in rate.',
                  })}
                </p>
              )}
              {onCosts.length > 0 && (
                // Widths mirror the row below exactly (flex-1 / w-32 / w-28 plus
                // the delete button's footprint), so the titles stay over their
                // own cells at every viewport.
                <div className="flex items-center gap-2 px-1 text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
                  <span className="flex-1">
                    {t('laborRates.oncost_col_what', { defaultValue: 'What it covers' })}
                  </span>
                  <span className="w-32">
                    {t('laborRates.oncost_col_how', { defaultValue: 'How it is charged' })}
                  </span>
                  <span className="w-28 text-right">
                    {t('laborRates.oncost_col_amount', { defaultValue: 'Amount' })}
                  </span>
                  <span className="w-7" aria-hidden />
                </div>
              )}
              {onCosts.map((row) => (
                <div key={row.key} className="flex items-center gap-2">
                  <input
                    className={`${inputClass} flex-1`}
                    value={row.label}
                    onChange={(e) => updateOnCost(row.key, { label: e.target.value })}
                    placeholder={t('laborRates.oncost_label_placeholder', {
                      defaultValue: 'e.g. social insurance',
                    })}
                    aria-label={t('laborRates.oncost_col_what', { defaultValue: 'What it covers' })}
                  />
                  <select
                    className={`${inputClass} w-32`}
                    value={row.kind}
                    onChange={(e) =>
                      updateOnCost(row.key, { kind: e.target.value as OnCostKind })
                    }
                    aria-label={t('laborRates.oncost_kind', { defaultValue: 'Kind' })}
                  >
                    <option value="percentage">
                      {t('laborRates.kind_percentage', { defaultValue: '% of wage' })}
                    </option>
                    <option value="fixed">
                      {t('laborRates.kind_fixed', { defaultValue: 'Fixed /h' })}
                    </option>
                  </select>
                  <div className="relative w-28">
                    <input
                      className={`${inputClass} pr-6 text-right`}
                      inputMode="decimal"
                      value={row.value}
                      onChange={(e) => updateOnCost(row.key, { value: e.target.value })}
                      placeholder="0"
                      aria-label={t('laborRates.oncost_value', { defaultValue: 'Value' })}
                    />
                    <span className="pointer-events-none absolute right-2 top-1.5 text-xs text-gray-400">
                      {row.kind === 'percentage' ? '%' : currency || '/h'}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeOnCost(row.key)}
                    className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-800"
                    aria-label={t('laborRates.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Crew composer */}
          <div className={cardClass}>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                <Users size={16} className="text-gray-500" />
                {t('laborRates.crew', { defaultValue: 'Crew composer' })}
              </h2>
              <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={addCrew}>
                {t('laborRates.add_trade', { defaultValue: 'Add trade' })}
              </Button>
            </div>

            <div className="space-y-2">
              {crew.map((row) => (
                <div key={row.key} className="flex items-center gap-2">
                  <input
                    className={`${inputClass} flex-1`}
                    value={row.trade}
                    onChange={(e) => updateCrew(row.key, { trade: e.target.value })}
                    placeholder={t('laborRates.trade', { defaultValue: 'Trade' })}
                    aria-label={t('laborRates.trade', { defaultValue: 'Trade' })}
                  />
                  <input
                    className={`${inputClass} w-20 text-right`}
                    type="number"
                    min={0}
                    step={1}
                    value={String(row.count)}
                    onChange={(e) => updateCrew(row.key, { count: Number(e.target.value) })}
                    aria-label={t('laborRates.count', { defaultValue: 'Count' })}
                  />
                  <div className="relative w-28">
                    <input
                      className={`${inputClass} text-right`}
                      inputMode="decimal"
                      value={row.all_in_rate}
                      onChange={(e) => updateCrew(row.key, { all_in_rate: e.target.value })}
                      placeholder={t('laborRates.rate', { defaultValue: 'Rate /h' })}
                      aria-label={t('laborRates.rate', { defaultValue: 'Rate /h' })}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => useAllInFor(row.key)}
                    className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-blue-600 dark:hover:bg-gray-800"
                    title={t('laborRates.use_all_in', {
                      defaultValue: 'Use the all-in rate above',
                    })}
                    aria-label={t('laborRates.use_all_in', {
                      defaultValue: 'Use the all-in rate above',
                    })}
                  >
                    <ArrowDownToLine size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => removeCrew(row.key)}
                    className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:bg-gray-800"
                    aria-label={t('laborRates.remove', { defaultValue: 'Remove' })}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>

            {crewBreakdown && crewBreakdown.headcount > 0 && (
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-gray-50 px-3 py-2 text-sm dark:bg-gray-800/60">
                <span className="text-gray-600 dark:text-gray-300">
                  {t('laborRates.crew_summary', {
                    defaultValue: '{{count}} people · {{total}}/h total',
                    count: crewBreakdown.headcount,
                    total: formatCurrency(crewBreakdown.total_cost_per_hour, currency),
                  })}
                </span>
                <span className="font-semibold text-gray-900 dark:text-gray-100">
                  {t('laborRates.blended', { defaultValue: 'Blended: {{rate}}/h', rate: formatCurrency(crewBreakdown.blended_hourly_rate, currency) })}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Breakdown column */}
        <div className="lg:col-span-2">
          <div className={`${cardClass} lg:sticky lg:top-4`}>
            <h2 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
              {t('laborRates.breakdown', { defaultValue: 'Rate build-up' })}
            </h2>

            <dl className="space-y-1.5 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-gray-600 dark:text-gray-300">
                  {t('laborRates.base_wage', { defaultValue: 'Base hourly wage' })}
                </dt>
                <dd className="font-medium text-gray-900 dark:text-gray-100">
                  {formatCurrency(breakdown?.base_wage ?? baseWage, currency)}
                </dd>
              </div>

              {(breakdown?.lines ?? []).map((line, i) => (
                <div
                  key={`${line.label}-${i}`}
                  className="flex items-center justify-between text-gray-500 dark:text-gray-400"
                >
                  <dt className="truncate pr-2">
                    {line.label}
                    <span className="ml-1 text-xs">
                      {line.kind === 'percentage' ? `(${line.value}%)` : ''}
                    </span>
                  </dt>
                  <dd>+ {formatCurrency(line.amount, currency)}</dd>
                </div>
              ))}

              <div className="mt-2 flex items-center justify-between border-t border-gray-200 pt-3 dark:border-gray-800">
                <dt className="font-semibold text-gray-900 dark:text-gray-100">
                  {t('laborRates.all_in_rate', { defaultValue: 'All-in hourly rate' })}
                </dt>
                <dd className="text-lg font-bold text-blue-600 dark:text-blue-400">
                  {formatCurrency(allInRate, currency)}
                </dd>
              </div>
            </dl>

            {/* Composition bar - what share of the all-in rate is wage vs each
                on-cost. Widths are display-only ratios of the backend Decimals. */}
            {breakdown && allInNum > 0 && (
              <div className="mt-4">
                <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                  {[
                    { label: t('laborRates.base_wage', { defaultValue: 'Base hourly wage' }), amount: breakdown.base_wage, color: BASE_COLOR },
                    ...(breakdown.lines ?? []).map((line, i) => ({
                      label: line.label,
                      amount: line.amount,
                      color: ONCOST_COLORS[i % ONCOST_COLORS.length]!,
                    })),
                  ].map((seg, i) => {
                    const pct = (Number(seg.amount) / allInNum) * 100;
                    if (!(pct > 0)) return null;
                    return (
                      <div
                        key={`${seg.label}-${i}`}
                        style={{ width: `${pct}%`, backgroundColor: seg.color }}
                        title={`${seg.label} · ${fmtPercent(pct, 0)}`}
                      />
                    );
                  })}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-content-tertiary">
                  {[
                    { label: t('laborRates.base_wage', { defaultValue: 'Base hourly wage' }), color: BASE_COLOR },
                    ...(breakdown.lines ?? []).map((line, i) => ({
                      label: line.label,
                      color: ONCOST_COLORS[i % ONCOST_COLORS.length]!,
                    })),
                  ].map((seg, i) => (
                    <span key={`${seg.label}-lg-${i}`} className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: seg.color }} />
                      {seg.label}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {computeQuery.isError && (
              <p className="mt-3 text-xs text-red-600 dark:text-red-400">
                {t('laborRates.compute_error', {
                  defaultValue: 'Could not compute the rate. Check your inputs.',
                })}
              </p>
            )}

            {/* Save as template */}
            <div className="mt-4 space-y-2 border-t border-gray-200 pt-4 dark:border-gray-800">
              <input
                className={inputClass}
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder={t('laborRates.template_name', {
                  defaultValue: 'Template name',
                })}
                aria-label={t('laborRates.template_name', { defaultValue: 'Template name' })}
              />
              <div className="flex flex-wrap gap-2">
                {editingId ? (
                  <>
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Save size={14} />}
                      loading={updateMutation.isPending}
                      disabled={
                        !canSaveTemplate({
                          templateName,
                          baseWage,
                          pending: updateMutation.isPending,
                        })
                      }
                      onClick={() => updateMutation.mutate(editingId)}
                    >
                      {t('laborRates.save_changes', { defaultValue: 'Save changes' })}
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<FilePlus size={14} />}
                      loading={saveMutation.isPending}
                      disabled={
                        !canSaveTemplate({
                          templateName,
                          baseWage,
                          pending: saveMutation.isPending,
                        })
                      }
                      onClick={() => saveMutation.mutate()}
                    >
                      {t('laborRates.save_as_new', { defaultValue: 'Save as new template' })}
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Save size={14} />}
                    loading={saveMutation.isPending}
                    disabled={
                      !canSaveTemplate({
                        templateName,
                        baseWage,
                        pending: saveMutation.isPending,
                      })
                    }
                    onClick={() => saveMutation.mutate()}
                  >
                    {t('laborRates.save_template', { defaultValue: 'Save as template' })}
                  </Button>
                )}
              </div>
              {!baseWageOk && (
                <p className="text-xs text-red-600 dark:text-red-400">
                  {t('laborRates.base_wage_required', {
                    defaultValue:
                      'Enter a base hourly wage above zero to save this build-up as a template.',
                  })}
                </p>
              )}
            </div>

            {/* Save as cost item: publish the computed rate(s) into the cost
                catalogue so they flow into BOQ / assemblies via costs to BOQ. */}
            <div className="mt-4 space-y-2 border-t border-gray-200 pt-4 dark:border-gray-800">
              <p className="text-xs text-gray-500 dark:text-gray-400">
                {t('laborRates.publish_hint', {
                  defaultValue:
                    'Publish this rate to the cost catalogue so it can be applied in a BOQ or assembly.',
                })}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Database size={14} />}
                  loading={
                    saveCostItemMutation.isPending &&
                    saveCostItemMutation.variables?.variant === 'all_in'
                  }
                  disabled={!(allInNum > 0) || saveCostItemMutation.isPending}
                  onClick={saveAllInAsCostItem}
                >
                  {t('laborRates.save_cost_item', { defaultValue: 'Save as cost item' })}
                </Button>
                {crewBreakdown &&
                  crewBreakdown.headcount > 0 &&
                  Number(crewBreakdown.blended_hourly_rate) > 0 && (
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<Database size={14} />}
                      loading={
                        saveCostItemMutation.isPending &&
                        saveCostItemMutation.variables?.variant === 'crew'
                      }
                      disabled={saveCostItemMutation.isPending}
                      onClick={saveCrewAsCostItem}
                    >
                      {t('laborRates.save_crew_cost_item', {
                        defaultValue: 'Save crew rate as cost item',
                      })}
                    </Button>
                  )}
              </div>
            </div>
          </div>
        </div>
      </div>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        confirmLabel={confirmState.confirmLabel}
        cancelLabel={confirmState.cancelLabel}
        variant={confirmState.variant}
        loading={confirmState.loading}
        onConfirm={confirmState.onConfirm}
        onCancel={confirmState.onCancel}
      />
    </div>
  );
}
