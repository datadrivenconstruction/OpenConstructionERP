import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Coins,
  Pencil,
  Percent,
  Plus,
  Ruler,
  Save,
  ShieldCheck,
  SlidersHorizontal,
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
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo } from '@/shared/ui/DismissibleInfo';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi, type Project, type ProjectFxRate } from './api';
import { CURRENCY_GROUPS, CreateProjectModal } from './CreateProjectPage';
import { getVatRate } from '../boq/boqHelpers';
import { TranslationSettingsTab } from '../translation';
import {
  listComplianceRulePacks,
  type ComplianceRulePack,
} from '../contracts/api';

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
        className="absolute inset-0 bg-black/70 backdrop-blur-lg animate-fade-in"
        onClick={onCancel}
      />
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in">
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
            {/* Issue #111 — live preview of both conversion directions.
             * Pre-2.9.34 users had no visual confirmation of what their
             * rate meant; e.g. someone entering 1415 thinking "1 USD =
             * 1415 ARS" would silently get 1 ARS = 1415 USD. Showing
             * both directions catches the inversion before save. */}
            {rateLooksValid && effectiveCode && baseCurrency && !isSameAsBase && (() => {
              const rateNum = parseFloat(rate);
              if (!Number.isFinite(rateNum) || rateNum <= 0) return null;
              const inverseRate = 1 / rateNum;
              const fmt = (n: number) =>
                n >= 1000 || n < 0.001
                  ? n.toLocaleString(undefined, { maximumSignificantDigits: 6 })
                  : n.toLocaleString(undefined, { maximumFractionDigits: 6 });
              return (
                <div className="rounded-lg bg-surface-tertiary px-3 py-2 text-xs text-content-secondary space-y-0.5">
                  <div>
                    {t('project.settings.fx.preview_forward', {
                      defaultValue: '1 {{code}} = {{value}} {{base}}',
                      code: effectiveCode,
                      value: fmt(rateNum),
                      base: baseCurrency,
                    })}
                  </div>
                  <div className="text-content-tertiary">
                    {t('project.settings.fx.preview_inverse', {
                      defaultValue: '1 {{base}} = {{value}} {{code}}',
                      base: baseCurrency,
                      value: fmt(inverseRate),
                      code: effectiveCode,
                    })}
                  </div>
                </div>
              );
            })()}
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
// Compliance rule packs (Item #27)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Lets the project owner choose which jurisdiction compliance rule packs the
 * contract-signature gate enforces. Toggling a pack and hitting Save calls the
 * dedicated PATCH /{id}/compliance-rule-packs endpoint (validated server-side
 * against the pack catalogue).
 */
function ComplianceRulePacksCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const packsQ = useQuery<ComplianceRulePack[]>({
    queryKey: ['compliance-rule-packs'],
    queryFn: listComplianceRulePacks,
    staleTime: 60 * 60 * 1000,
  });

  const [selected, setSelected] = useState<string[]>(
    project.compliance_rule_packs ?? ['universal'],
  );

  useEffect(() => {
    setSelected(project.compliance_rule_packs ?? ['universal']);
  }, [project.compliance_rule_packs]);

  const saveMut = useMutation({
    mutationFn: (ids: string[]) =>
      projectsApi.setComplianceRulePacks(project.id, ids),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      setSelected(updated.compliance_rule_packs ?? ['universal']);
      addToast({
        type: 'success',
        title: t('project.settings.compliance.saved', {
          defaultValue: 'Compliance rule packs saved',
        }),
      });
    },
    onError: (err) =>
      addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id],
    );
  };

  const current = project.compliance_rule_packs ?? ['universal'];
  const dirty =
    selected.length !== current.length ||
    selected.some((p) => !current.includes(p));

  return (
    <Card padding="lg" id="compliance-rule-packs">
      <CardHeader
        title={t('project.settings.compliance.title', {
          defaultValue: 'Compliance rule packs',
        })}
        subtitle={t('project.settings.compliance.subtitle', {
          defaultValue:
            'Jurisdiction rule bundles enforced when a contract is signed (draft → active). A contract cannot be signed while a selected pack reports a blocking error.',
        })}
      />
      <div className="mt-3 space-y-3">
        {packsQ.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : (packsQ.data ?? []).length === 0 ? (
          <p className="text-sm text-content-tertiary italic">
            {t('project.settings.compliance.empty', {
              defaultValue: 'No compliance rule packs are available.',
            })}
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {(packsQ.data ?? []).map((pack) => {
              const on = selected.includes(pack.id);
              return (
                <button
                  key={pack.id}
                  type="button"
                  onClick={() => toggle(pack.id)}
                  aria-pressed={on}
                  className={
                    'flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ' +
                    (on
                      ? 'border-oe-blue bg-oe-blue/5 ring-1 ring-inset ring-oe-blue/30'
                      : 'border-border-light hover:bg-surface-secondary')
                  }
                >
                  <ShieldCheck
                    size={16}
                    className={
                      'mt-0.5 shrink-0 ' +
                      (on ? 'text-oe-blue' : 'text-content-tertiary')
                    }
                  />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-content-primary">
                        {pack.name}
                      </span>
                      {pack.jurisdiction && (
                        <Badge variant="neutral">{pack.jurisdiction}</Badge>
                      )}
                    </div>
                    {pack.description && (
                      <p className="mt-0.5 text-xs text-content-secondary">
                        {pack.description}
                      </p>
                    )}
                    {pack.rule_sets.length > 0 && (
                      <p className="mt-1 font-mono text-[11px] text-content-tertiary">
                        {pack.rule_sets.join(' · ')}
                      </p>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        <div className="flex items-center justify-end">
          <Button
            variant="primary"
            size="sm"
            icon={<Save size={14} />}
            disabled={!dirty}
            loading={saveMut.isPending}
            onClick={() => saveMut.mutate(selected)}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </Card>
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
  // Base currency draft - '__custom__' switches to the free-text code input.
  const [baseCurrencyDraft, setBaseCurrencyDraft] = useState<string>('');
  const [baseCurrencyCustom, setBaseCurrencyCustom] = useState<string>('');
  const [vatInput, setVatInput] = useState<string>('');
  const [unitInput, setUnitInput] = useState<string>('');
  const [customUnits, setCustomUnits] = useState<string[]>([]);
  const [fxModal, setFxModal] = useState<{
    open: boolean;
    initial: ProjectFxRate | null;
  }>({ open: false, initial: null });
  // Slice 4 — re-open the setup wizard for this project in EDIT mode.
  const [editSetupOpen, setEditSetupOpen] = useState(false);

  // Sync local state with server state once (and when projectId changes)
  useEffect(() => {
    if (!project) return;
    setFxRates(project.fx_rates ?? []);
    setBaseCurrencyDraft(project.currency ?? '');
    setBaseCurrencyCustom('');
    setVatInput(project.default_vat_rate ?? '');
    setCustomUnits(project.custom_units ?? []);
  }, [project]);

  // Issue #105 — when navigated here with a hash (e.g. /settings#fx-rates),
  // scroll the matching Card into view and pulse it briefly so the user
  // immediately sees where the FX-rate setup lives. Uses requestAnimationFrame
  // to wait for the page layout to settle (the project query may still be
  // resolving, in which case the target Card hasn't rendered yet).
  const location = useLocation();
  useEffect(() => {
    if (!location.hash) return;
    if (!project) return;
    const id = location.hash.replace(/^#/, '');
    if (!id) return;
    requestAnimationFrame(() => {
      const el = document.getElementById(id);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      el.classList.add('ring-2', 'ring-oe-blue', 'ring-offset-2', 'transition-all');
      window.setTimeout(() => {
        el.classList.remove('ring-2', 'ring-oe-blue', 'ring-offset-2');
      }, 2200);
    });
  }, [location.hash, project]);

  const updateMutation = useMutation({
    mutationFn: (payload: Partial<Project>) => projectsApi.update(projectId!, payload),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      // Re-sync local state from server response (authoritative)
      setFxRates(updated.fx_rates ?? []);
      setBaseCurrencyDraft(updated.currency ?? '');
      setBaseCurrencyCustom('');
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
      <div className="space-y-5 animate-fade-in">
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

  // ── Base currency edit (#editable base currency) ──────────────────────
  // The base currency is changeable after creation. Saving it RELABELS
  // existing amounts (quantities and rates keep their numeric values) -
  // it never converts them, so the warning below the field is explicit.
  const effectiveBaseDraft =
    baseCurrencyDraft === '__custom__'
      ? baseCurrencyCustom.trim().toUpperCase()
      : baseCurrencyDraft;
  const baseDraftValid = /^[A-Z0-9]{3,10}$/.test(effectiveBaseDraft);
  const baseDraftConflict = fxRates.some((r) => r.code === effectiveBaseDraft);
  const canSaveBaseCurrency =
    baseDraftValid &&
    !baseDraftConflict &&
    effectiveBaseDraft !== baseCurrency &&
    !updateMutation.isPending;
  // Keep a not-in-list current value selectable (custom codes saved earlier).
  // Plain computation (cheap, static list) - this sits below the early
  // returns above, so a hook here would break the rules of hooks.
  const knownCurrencyCodes = new Set(flattenCurrencies().map((o) => o.value));

  const handleBaseCurrencySave = () => {
    if (!canSaveBaseCurrency) return;
    // The backend rejects a currency change with 409 once BOQ positions
    // exist unless the patch acknowledges the impact via
    // metadata.allow_currency_change. The warning under this field IS that
    // acknowledgment (relabel, not convert), so pass the flag - merged
    // into the existing metadata because the PATCH replaces the whole
    // metadata object (a bare flag would wipe demo/flagship tags).
    updateMutation.mutate({
      currency: effectiveBaseDraft,
      metadata: { ...(project.metadata ?? {}), allow_currency_change: true },
    } as Partial<Project>);
  };

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
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          {
            label: project.name,
            to: `/projects/${project.id}`,
          },
          { label: t('project.settings.title', { defaultValue: 'Settings' }) },
        ]}
      />

      <PageHeader
        srTitle={t('project.settings.title', { defaultValue: 'Project Settings' })}
        subtitle={t('project.settings.subtitle', {
          defaultValue:
            'Currencies, VAT, and custom units that apply to this project only.',
        })}
        actions={
          <Button
            variant="ghost"
            size="sm"
            icon={<ArrowLeft size={14} />}
            onClick={() => navigate(`/projects/${project.id}`)}
          >
            {t('common.back_to_project', { defaultValue: 'Back to project' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="project-settings"
        title={t('projects.settings_intro_title', {
          defaultValue: 'Project rules, set in one place',
        })}
        links={[
          {
            label: t('nav.validation', { defaultValue: 'Validation' }),
            onClick: () => navigate('/validation'),
          },
          {
            label: t('nav.boq', { defaultValue: 'BOQ' }),
            onClick: () => navigate(`/projects/${project.id}/boq`),
          },
        ]}
      >
        {t('projects.settings_intro_body', {
          defaultValue:
            'Set the project currency, VAT, units, classification standard and compliance rule sets here, and re-run the setup wizard to change which modules are active. These choices are the source of truth that BOQ pricing, validation and reports read from, so fixing them once keeps every downstream number consistent. Compliance rule sets chosen here are enforced in Validation.',
        })}
      </DismissibleInfo>

      {/* ── Project setup (Slice 4 — re-wizard entry) ───────────────────── */}
      <Card padding="lg">
        <CardHeader
          title={t('project.settings.setup.title', {
            defaultValue: 'Project setup',
          })}
          subtitle={t('project.settings.setup.subtitle', {
            defaultValue:
              'Re-run the guided wizard to change the preset, scope and which modules are emphasised in the sidebar.',
          })}
          action={
            <Button
              variant="primary"
              size="sm"
              icon={<SlidersHorizontal size={14} />}
              onClick={() => setEditSetupOpen(true)}
            >
              {t('project.settings.setup.edit', {
                defaultValue: 'Edit project setup',
              })}
            </Button>
          }
        />
      </Card>
      <CreateProjectModal
        open={editSetupOpen}
        onClose={() => setEditSetupOpen(false)}
        editProjectId={project.id}
      />

      {/* ── Currencies — base + additional rates merged (#88, #105) ──────── */}
      {/* The id="fx-rates" anchor is the deep-link target for the BOQ
          editor's "set FX" warning badge (Issue #105). Removing it would
          break that quick-access flow. */}
      <Card padding="lg" id="fx-rates">
        <CardHeader
          title={t('project.settings.currency.title', { defaultValue: 'Currencies' })}
          subtitle={t('project.settings.currency.subtitle_editable', {
            defaultValue:
              'Set the base currency for this project, and add additional currencies to use on individual resources - rates convert back to the base for rollup totals.',
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

        {/* ── Base currency (editable) ──────────────────────────────────── */}
        <div className="mt-4 rounded-lg border border-border-light bg-surface-secondary/20 px-4 py-3">
          <label
            htmlFor="base-currency-select"
            className="block text-sm font-medium text-content-primary"
          >
            {t('project.settings.base_currency.field', { defaultValue: 'Base currency' })}
          </label>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <select
              id="base-currency-select"
              value={baseCurrencyDraft}
              onChange={(e) => setBaseCurrencyDraft(e.target.value)}
              className="h-9 min-w-[16rem] rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
            >
              <option value="" disabled>
                {t('project.settings.fx.select_currency', {
                  defaultValue: '-- Select currency --',
                })}
              </option>
              {baseCurrency && !knownCurrencyCodes.has(baseCurrency) && (
                <option value={baseCurrency}>{baseCurrency}</option>
              )}
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
            {baseCurrencyDraft === '__custom__' && (
              <Input
                value={baseCurrencyCustom}
                onChange={(e) => setBaseCurrencyCustom(e.target.value)}
                placeholder={t('project.settings.base_currency.custom_placeholder', {
                  defaultValue: 'e.g. CHF',
                })}
                maxLength={10}
                className="w-28"
                aria-label={t('project.settings.fx.custom_code', {
                  defaultValue: 'Custom code...',
                })}
              />
            )}
            <Button
              size="sm"
              icon={<Save size={14} />}
              disabled={!canSaveBaseCurrency}
              loading={updateMutation.isPending}
              onClick={handleBaseCurrencySave}
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
          </div>
          {baseDraftConflict && (
            <p className="mt-1.5 text-xs text-semantic-error">
              {t('project.settings.base_currency.conflict', {
                defaultValue:
                  '{{code}} is already listed as an additional currency. Remove it from the list below before making it the base.',
                code: effectiveBaseDraft,
              })}
            </p>
          )}
          <p className="mt-1.5 text-xs text-content-tertiary">
            {t('project.settings.base_currency.warning', {
              defaultValue:
                'Changing the base currency relabels existing amounts - it does not convert them. Rates and totals keep their numeric values under the new currency.',
            })}
          </p>
        </div>

        <div className="mt-4 overflow-hidden rounded-lg border border-border-light">
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
              {/* Base currency row — locked, displayed first, shows rate 1.0000 */}
              <tr className="bg-surface-secondary/30">
                <td className="px-4 py-2.5 font-medium text-content-primary tabular-nums">
                  <span className="inline-flex items-center gap-2">
                    <Coins size={14} className="text-oe-blue" />
                    {baseCurrency || (
                      <span className="text-content-tertiary italic">
                        {t('project.settings.base_currency.unset', { defaultValue: 'Not set' })}
                      </span>
                    )}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-content-secondary">
                  <Badge variant="blue" size="sm">
                    {t('project.settings.base_currency.label', { defaultValue: 'Base' })}
                  </Badge>
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-content-tertiary">
                  1.0000
                </td>
                <td className="px-4 py-2.5" />
              </tr>
              {fxRates.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-4 text-center text-sm text-content-tertiary">
                    {t('project.settings.fx.empty', {
                      defaultValue: 'No additional currencies. Click "Add currency" to set one up.',
                    })}
                  </td>
                </tr>
              ) : (
                fxRates.map((row) => (
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
                ))
              )}
            </tbody>
          </table>
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
        <form onSubmit={handleVatSave} className="mt-4 flex flex-col gap-3 md:flex-row md:flex-wrap md:items-end">
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
          <p className="text-xs text-content-tertiary md:basis-full md:max-w-md md:mt-0 mt-1">
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
        <div className="mt-3 space-y-3">
          {customUnits.length === 0 ? (
            <p className="text-sm text-content-tertiary italic">
              {t('project.settings.units.empty', {
                defaultValue: 'No custom units yet - add one below.',
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

      {/* ── Compliance rule packs (Item #27) ───────────────────────────── */}
      <ComplianceRulePacksCard project={project} />

      {/* ── Translation (#translation deep-link) ─────────────────────────
          Mounted as a Card section so the existing hash-pulse effect in
          this page (originally introduced for #fx-rates) auto-scrolls and
          highlights it on /projects/:id/settings#translation.  Linked
          from the MatchSuggestionsPanel fallback hint. */}
      <TranslationSettingsTab projectId={project.id} />

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
