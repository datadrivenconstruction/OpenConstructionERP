import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Coins,
  Pencil,
  Percent,
  Plus,
  Ruler,
  Save,
  Trash2,
  X,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Input,
  Skeleton,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi, type Project, type ProjectFxRate } from './api';
import { CURRENCY_GROUPS } from './CreateProjectPage';
import { getVatRate } from '../boq/boqHelpers';

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Decimal-string validator. Accepts "1.5", "1200.50", "0.01". Rejects empty,
 *  zero, negative, NaN, non-numeric. We keep the stored shape as a string to
 *  preserve precision (matches RFC 37 §3.1). */
function isPositiveDecimalString(value: string): boolean {
  if (!value || !value.trim()) return false;
  const trimmed = value.trim();
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return false;
  const n = Number(trimmed);
  return Number.isFinite(n) && n > 0;
}

/** Build a flat list `{value, label}` from the grouped CURRENCY_GROUPS so we
 *  can render a single <select>. Drops the synthetic `__custom__` option — for
 *  FX rate rows the user picks a real ISO code (or types a 3-letter custom). */
function flattenCurrencies(): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  for (const group of CURRENCY_GROUPS) {
    for (const opt of group.options) {
      if (opt.value === '__custom__') continue;
      out.push(opt);
    }
  }
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// FX Rate Modal — add / edit one currency row
// ─────────────────────────────────────────────────────────────────────────────

interface FxRateModalProps {
  open: boolean;
  baseCurrency: string;
  initial: ProjectFxRate | null; // null = create, else edit
  takenCodes: string[]; // codes already in fx_rates (excluding initial.code on edit)
  onCancel: () => void;
  onSave: (row: ProjectFxRate) => void;
}

function FxRateModal({
  open,
  baseCurrency,
  initial,
  takenCodes,
  onCancel,
  onSave,
}: FxRateModalProps) {
  const { t } = useTranslation();
  const isEdit = !!initial;

  const [code, setCode] = useState('');
  const [label, setLabel] = useState('');
  const [rate, setRate] = useState('');
  const [customCode, setCustomCode] = useState('');

  const flat = useMemo(flattenCurrencies, []);

  useEffect(() => {
    if (!open) return;
    if (initial) {
      setCode(initial.code);
      setLabel(initial.label ?? '');
      setRate(initial.rate);
      setCustomCode('');
    } else {
      setCode('');
      setLabel('');
      setRate('');
      setCustomCode('');
    }
  }, [open, initial]);

  if (!open) return null;

  const effectiveCode = code === '__custom__' ? customCode.trim().toUpperCase() : code;
  const codeLooksValid = /^[A-Z0-9]{3,10}$/.test(effectiveCode);
  const codeIsTaken =
    !!effectiveCode &&
    takenCodes.includes(effectiveCode) &&
    (!isEdit || initial?.code !== effectiveCode);
  const rateLooksValid = isPositiveDecimalString(rate);
  const isSameAsBase = effectiveCode === baseCurrency;

  const canSave = codeLooksValid && rateLooksValid && !codeIsTaken && !isSameAsBase;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    // Auto-fill label from picker option if user left it blank
    let resolvedLabel = label.trim();
    if (!resolvedLabel) {
      const opt = flat.find((o) => o.value === effectiveCode);
      // Picker labels look like "USD ($) — US Dollar" — strip the prefix.
      if (opt) {
        const dash = opt.label.indexOf('\u2014');
        resolvedLabel = dash >= 0 ? opt.label.slice(dash + 1).trim() : opt.label;
      }
    }
    onSave({
      code: effectiveCode,
      rate: rate.trim(),
      label: resolvedLabel || null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"
        onClick={onCancel}
      />
      <div className="relative w-full max-w-md mx-4 rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in">
        <div className="flex items-center justify-between px-6 pt-6 pb-2">
          <h3 className="text-lg font-semibold text-content-primary">
            {isEdit
              ? t('project.settings.fx.edit_title', { defaultValue: 'Edit currency' })
              : t('project.settings.fx.add_title', { defaultValue: 'Add currency' })}
          </h3>
          <button
            onClick={onCancel}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 pb-6 pt-2 space-y-4">
          {/* Currency picker */}
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('project.settings.fx.currency', { defaultValue: 'Currency' })}
            </label>
            <select
              value={code}
              onChange={(e) => setCode(e.target.value)}
              disabled={isEdit}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <option value="" disabled>
                {t('project.settings.fx.select_currency', {
                  defaultValue: '-- Select currency --',
                })}
              </option>
              {CURRENCY_GROUPS.map((g) => (
                <optgroup key={g.group} label={g.group}>
                  {g.options.map((o) =>
                    o.value === '__custom__' ? (
                      <option key={o.value} value={o.value}>
                        {t('project.settings.fx.custom_code', {
                          defaultValue: 'Custom code...',
                        })}
                      </option>
                    ) : (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ),
                  )}
                </optgroup>
              ))}
            </select>
            {code === '__custom__' && (
              <input
                type="text"
                value={customCode}
                onChange={(e) => setCustomCode(e.target.value.toUpperCase())}
                placeholder={t('project.settings.fx.custom_code_placeholder', {
                  defaultValue: 'e.g. XAF',
                })}
                maxLength={10}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary uppercase focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              />
            )}
            {isSameAsBase && (
              <p className="text-xs text-semantic-error">
                {t('project.settings.fx.cannot_be_base', {
                  defaultValue: 'Additional currencies must differ from the base currency.',
                })}
              </p>
            )}
            {codeIsTaken && (
              <p className="text-xs text-semantic-error">
                {t('project.settings.fx.code_taken', {
                  defaultValue: 'This currency is already in the list.',
                })}
              </p>
            )}
          </div>

          {/* Optional label */}
          <Input
            label={t('project.settings.fx.label', { defaultValue: 'Label (optional)' })}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t('project.settings.fx.label_placeholder', {
              defaultValue: 'e.g. US Dollar',
            })}
          />

          {/* Rate */}
          <div className="flex flex-col gap-1.5">
            <Input
              label={t('project.settings.fx.rate_label', {
                defaultValue: 'Rate (1 unit of this currency = X {{base}})',
                base: baseCurrency || '—',
              })}
              type="text"
              inputMode="decimal"
              value={rate}
              onChange={(e) => setRate(e.target.value)}
              placeholder="1200.50"
              error={
                rate && !rateLooksValid
                  ? t('project.settings.fx.rate_invalid', {
                      defaultValue: 'Enter a positive decimal (e.g. 1200.50).',
                    })
                  : undefined
              }
            />
            <p className="text-xs text-content-tertiary">
              {t('project.settings.fx.rate_hint', {
                defaultValue:
                  'Used to convert per-resource currency amounts back to the base currency for rollup totals.',
              })}
            </p>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={onCancel}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button variant="primary" type="submit" disabled={!canSave}>
              {isEdit
                ? t('common.save', { defaultValue: 'Save' })
                : t('common.add', { defaultValue: 'Add' })}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Project Settings Page
// ─────────────────────────────────────────────────────────────────────────────

export function ProjectSettingsPage() {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: project, isLoading } = useQuery<Project>({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

  // ── Local edit state per section ───────────────────────────────────────
  const [fxRates, setFxRates] = useState<ProjectFxRate[]>([]);
  const [vatInput, setVatInput] = useState<string>('');
  const [unitInput, setUnitInput] = useState<string>('');
  const [customUnits, setCustomUnits] = useState<string[]>([]);
  const [fxModal, setFxModal] = useState<{
    open: boolean;
    initial: ProjectFxRate | null;
  }>({ open: false, initial: null });

  // Sync local state with server state once (and when projectId changes)
  useEffect(() => {
    if (!project) return;
    setFxRates(project.fx_rates ?? []);
    setVatInput(project.default_vat_rate ?? '');
    setCustomUnits(project.custom_units ?? []);
  }, [project]);

  const updateMutation = useMutation({
    mutationFn: (payload: Partial<Project>) => projectsApi.update(projectId!, payload),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      // Re-sync local state from server response (authoritative)
      setFxRates(updated.fx_rates ?? []);
      setVatInput(updated.default_vat_rate ?? '');
      setCustomUnits(updated.custom_units ?? []);
      addToast({
        type: 'success',
        title: t('project.settings.saved', { defaultValue: 'Project settings saved' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('project.settings.save_failed', { defaultValue: 'Failed to save settings' }),
        message: err.message,
      });
    },
  });

  // ── Loading / not-found states ────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="w-full space-y-4 animate-fade-in">
        <Skeleton height={20} width={140} />
        <Skeleton height={48} className="w-full" />
        <Skeleton height={200} className="w-full" />
        <Skeleton height={200} className="w-full" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="w-full">
        <EmptyState
          title={t('project.settings.not_found', { defaultValue: 'Project not found' })}
          description={t('project.settings.not_found_desc', {
            defaultValue: 'This project may have been archived or deleted.',
          })}
          action={
            <Button variant="primary" onClick={() => navigate('/projects')}>
              {t('common.back', { defaultValue: 'Back' })}
            </Button>
          }
        />
      </div>
    );
  }

  const baseCurrency = project.currency || '';
  const regionalVatPct = Math.round(getVatRate(project.region) * 100); // e.g. 19, 20

  // ── Save handlers ─────────────────────────────────────────────────────

  const saveFxRates = (next: ProjectFxRate[]) => {
    setFxRates(next);
    updateMutation.mutate({ fx_rates: next } as Partial<Project>);
  };

  const handleFxModalSave = (row: ProjectFxRate) => {
    let next: ProjectFxRate[];
    if (fxModal.initial) {
      // Edit — preserve order
      next = fxRates.map((r) => (r.code === fxModal.initial!.code ? row : r));
    } else {
      next = [...fxRates, row];
    }
    setFxModal({ open: false, initial: null });
    saveFxRates(next);
  };

  const handleFxDelete = (code: string) => {
    saveFxRates(fxRates.filter((r) => r.code !== code));
  };

  const handleVatSave = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = vatInput.trim();
    if (trimmed === '') {
      // Empty → clear override (use regional default)
      updateMutation.mutate({ default_vat_rate: null } as Partial<Project>);
      return;
    }
    if (!/^\d+(\.\d+)?$/.test(trimmed)) {
      addToast({
        type: 'error',
        title: t('project.settings.vat.invalid', {
          defaultValue: 'VAT must be a non-negative number (e.g. 21).',
        }),
      });
      return;
    }
    updateMutation.mutate({ default_vat_rate: trimmed } as Partial<Project>);
  };

  const handleAddUnit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = unitInput.trim();
    if (!trimmed) return;
    if (customUnits.includes(trimmed)) {
      setUnitInput('');
      return;
    }
    const next = [...customUnits, trimmed];
    setCustomUnits(next);
    setUnitInput('');
    updateMutation.mutate({ custom_units: next } as Partial<Project>);
  };

  const handleRemoveUnit = (unit: string) => {
    const next = customUnits.filter((u) => u !== unit);
    setCustomUnits(next);
    updateMutation.mutate({ custom_units: next } as Partial<Project>);
  };

  const overrideActive = (project.default_vat_rate ?? '').toString().trim() !== '';
  const effectiveVat = overrideActive
    ? `${project.default_vat_rate}%`
    : `${regionalVatPct}% (${t('project.settings.vat.regional', {
        defaultValue: 'regional default',
      })})`;

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div className="w-full space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.projects', { defaultValue: 'Projects' }), to: '/projects' },
          {
            label: project.name,
            to: `/projects/${project.id}`,
          },
          { label: t('project.settings.title', { defaultValue: 'Settings' }) },
        ]}
      />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">
            {t('project.settings.title', { defaultValue: 'Project Settings' })}
          </h1>
          <p className="text-sm text-content-tertiary mt-0.5">
            {t('project.settings.subtitle', {
              defaultValue:
                'Currencies, VAT, and custom units that apply to this project only.',
            })}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          icon={<ArrowLeft size={14} />}
          onClick={() => navigate(`/projects/${project.id}`)}
        >
          {t('common.back_to_project', { defaultValue: 'Back to project' })}
        </Button>
      </div>

      {/* ── Base currency ───────────────────────────────────────────────── */}
      <Card padding="lg">
        <CardHeader
          title={t('project.settings.base_currency.title', { defaultValue: 'Base currency' })}
          subtitle={t('project.settings.base_currency.subtitle', {
            defaultValue:
              'Set when the project was created. All BOQ totals roll up to this currency.',
          })}
        />
        <div className="mt-4 inline-flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
          <Coins size={16} className="text-oe-blue" />
          <span className="text-sm font-medium text-content-primary tabular-nums">
            {baseCurrency || t('project.settings.base_currency.unset', { defaultValue: 'Not set' })}
          </span>
        </div>
      </Card>

      {/* ── Additional currencies (#88) ─────────────────────────────────── */}
      <Card padding="lg">
        <CardHeader
          title={t('project.settings.fx.title', { defaultValue: 'Additional currencies' })}
          subtitle={t('project.settings.fx.subtitle', {
            defaultValue:
              'Currencies you can use on individual resources. Rates convert back to the base currency for rollup totals.',
          })}
          action={
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setFxModal({ open: true, initial: null })}
              disabled={!baseCurrency}
            >
              {t('project.settings.fx.add', { defaultValue: 'Add currency' })}
            </Button>
          }
        />
        <div className="mt-4">
          {fxRates.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border-light bg-surface-secondary/30 px-4 py-6 text-center">
              <p className="text-sm text-content-tertiary">
                {t('project.settings.fx.empty', {
                  defaultValue: 'No additional currencies. Click "Add currency" to set one up.',
                })}
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border-light">
              <table className="min-w-full text-sm">
                <thead className="bg-surface-secondary/40">
                  <tr className="text-left text-xs uppercase tracking-wide text-content-tertiary">
                    <th className="px-4 py-2 font-medium">
                      {t('project.settings.fx.col_code', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-4 py-2 font-medium">
                      {t('project.settings.fx.col_label', { defaultValue: 'Label' })}
                    </th>
                    <th className="px-4 py-2 font-medium text-right">
                      {t('project.settings.fx.col_rate', {
                        defaultValue: 'Rate to {{base}}',
                        base: baseCurrency || '—',
                      })}
                    </th>
                    <th className="px-4 py-2 w-24" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {fxRates.map((row) => (
                    <tr key={row.code} className="hover:bg-surface-hover/40">
                      <td className="px-4 py-2.5 font-medium text-content-primary tabular-nums">
                        {row.code}
                      </td>
                      <td className="px-4 py-2.5 text-content-secondary">
                        {row.label || (
                          <span className="text-content-tertiary italic">
                            {t('project.settings.fx.no_label', { defaultValue: '—' })}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-content-primary">
                        {row.rate}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => setFxModal({ open: true, initial: row })}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors"
                            aria-label={t('common.edit', { defaultValue: 'Edit' })}
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleFxDelete(row.code)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error/10 transition-colors"
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      {/* ── Default VAT rate (#89) ──────────────────────────────────────── */}
      <Card padding="lg">
        <CardHeader
          title={t('project.settings.vat.title', { defaultValue: 'Default VAT rate' })}
          subtitle={t('project.settings.vat.subtitle', {
            defaultValue: 'Used when seeding markups for new BOQs in this project.',
          })}
          action={
            <Badge variant={overrideActive ? 'blue' : 'neutral'} size="sm">
              {t('project.settings.vat.effective', {
                defaultValue: 'Effective: {{value}}',
                value: effectiveVat,
              })}
            </Badge>
          }
        />
        <form onSubmit={handleVatSave} className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('project.settings.vat.input_label', { defaultValue: 'VAT %' })}
            </label>
            <div className="relative">
              <input
                type="text"
                inputMode="decimal"
                value={vatInput}
                onChange={(e) => setVatInput(e.target.value)}
                placeholder={String(regionalVatPct)}
                className="h-9 w-32 rounded-lg border border-border bg-surface-primary px-3 pr-7 text-sm text-content-primary tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
              <Percent
                size={13}
                className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
            </div>
          </div>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            icon={<Save size={14} />}
            loading={updateMutation.isPending}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
          <p className="text-xs text-content-tertiary max-w-md">
            {t('project.settings.vat.helper', {
              defaultValue:
                'Used when seeding markups for new BOQs. Leave blank to use the regional default ({{regional}}%).',
              regional: regionalVatPct,
            })}
          </p>
        </form>
      </Card>

      {/* ── Custom units (#93 item 3) ───────────────────────────────────── */}
      <Card padding="lg">
        <CardHeader
          title={t('project.settings.units.title', { defaultValue: 'Custom units' })}
          subtitle={t('project.settings.units.subtitle', {
            defaultValue:
              'Project-scoped units (in addition to standard m, m², m³, kg, pcs, lsum). Synced across browsers.',
          })}
        />
        <div className="mt-4 space-y-3">
          {customUnits.length === 0 ? (
            <p className="text-sm text-content-tertiary italic">
              {t('project.settings.units.empty', {
                defaultValue: 'No custom units yet.',
              })}
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {customUnits.map((unit) => (
                <span
                  key={unit}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-secondary/40 pl-3 pr-1 py-1 text-sm text-content-primary"
                >
                  <Ruler size={12} className="text-content-tertiary" />
                  <span className="tabular-nums">{unit}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveUnit(unit)}
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full text-content-tertiary hover:text-semantic-error hover:bg-semantic-error/10 transition-colors"
                    aria-label={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}

          <form onSubmit={handleAddUnit} className="flex items-end gap-2">
            <div className="flex-1 max-w-xs">
              <Input
                label={t('project.settings.units.add_label', { defaultValue: 'Add unit' })}
                value={unitInput}
                onChange={(e) => setUnitInput(e.target.value)}
                placeholder={t('project.settings.units.placeholder', {
                  defaultValue: 'e.g. ton, set, lf',
                })}
                maxLength={32}
              />
            </div>
            <Button
              variant="secondary"
              size="sm"
              type="submit"
              icon={<Plus size={14} />}
              disabled={!unitInput.trim()}
            >
              {t('common.add', { defaultValue: 'Add' })}
            </Button>
          </form>
        </div>
      </Card>

      {/* ── FX Modal ────────────────────────────────────────────────────── */}
      <FxRateModal
        open={fxModal.open}
        baseCurrency={baseCurrency}
        initial={fxModal.initial}
        takenCodes={fxRates.map((r) => r.code)}
        onCancel={() => setFxModal({ open: false, initial: null })}
        onSave={handleFxModalSave}
      />
    </div>
  );
}
