// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Market & standards: the tenant's primary market, other markets,
 * and the standards and units system that follow from them.
 *
 * Everyone can read it; only package admins can save (the server decides,
 * `can_edit` mirrors it). Saving never uninstalls anything: modules of a
 * market that is removed are hidden, and their data stays.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Plus, X } from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { COUNTRIES } from '@/shared/lib/countries';
import { regionDisplayName } from '@/features/cases/regions';
import { MarketPreviewModal } from './MarketPreviewModal';
import { EInvoiceSetupCard } from '@/features/einvoice-clearance/EInvoiceSetupCard';
import { einvoiceScopeMarkets } from '@/features/einvoice-clearance/useEInvoiceMarkets';
import { MARKET_QUERY_KEY, saveMarketProfile, useMarketScope, type MarketProfile } from './api';

const UNITS_OPTIONS = [
  { value: 'metric', key: 'market.units_metric', fallback: 'Metric' },
  { value: 'imperial', key: 'market.units_imperial', fallback: 'Imperial' },
  { value: 'both', key: 'market.units_both', fallback: 'Metric and imperial' },
] as const;

const selectClass =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

function emptyProfile(): MarketProfile {
  return {
    primary: null,
    extra_markets: [],
    company_type: null,
    standards: { classification: '', measurement: '', contract_family: '', tax_profile: '', units: '' },
    keep_modules: [],
  };
}

export function MarketSettings() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { data: scope, isLoading, isError, refetch } = useMarketScope();
  const [draft, setDraft] = useState<MarketProfile>(emptyProfile);
  const [adding, setAdding] = useState('');
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<{ profile: MarketProfile; country: string; adding: boolean } | null>(null);

  useEffect(() => {
    if (scope?.profile) setDraft(scope.profile);
  }, [scope]);

  const countries = useMemo(() => {
    const collator = new Intl.Collator(i18n.language);
    return COUNTRIES.map((c) => ({ code: c.code, name: regionDisplayName(c.code, i18n.language) })).sort((a, b) =>
      collator.compare(a.name, b.name),
    );
  }, [i18n.language]);

  const canEdit = !!scope?.can_edit;
  const dirty = !!scope && JSON.stringify(scope.profile) !== JSON.stringify(draft);
  const primaryCode = draft.primary?.country ?? '';
  const primaryName = primaryCode ? regionDisplayName(primaryCode, i18n.language) : '';
  const defaultMarker = primaryName
    ? ` ${t('market.default_for', { defaultValue: '(default for {{country}})', country: primaryName })}`
    : '';

  const setStandard = (key: keyof MarketProfile['standards'], value: string) =>
    setDraft((d) => ({ ...d, standards: { ...d.standards, [key]: value } }));

  async function handleSave(profile: MarketProfile = draft) {
    setSaving(true);
    try {
      const next = await saveMarketProfile(profile);
      setDraft(next.profile ?? profile);
      queryClient.setQueryData([...MARKET_QUERY_KEY, null], next);
      void queryClient.invalidateQueries({ queryKey: MARKET_QUERY_KEY });
      addToast({ type: 'success', title: t('common.saved', { defaultValue: 'Saved' }) });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('market.load_error', { defaultValue: 'Could not load market settings' }),
        message: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  }

  if (isError) {
    return (
      <Card className="lg:col-span-2">
        <CardContent>
          <div role="alert" className="flex items-center gap-3 text-sm text-content-secondary">
            <AlertTriangle size={16} className="shrink-0 text-semantic-warning" aria-hidden />
            <span className="flex-1">{t('market.load_error', { defaultValue: 'Could not load market settings' })}</span>
            <Button variant="secondary" size="sm" onClick={() => void refetch()}>
              {t('common.retry', { defaultValue: 'Retry' })}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isLoading || !scope) {
    return (
      <div className="space-y-3 lg:col-span-2" aria-busy="true">
        <div className="h-28 animate-pulse rounded-xl bg-surface-secondary" />
        <div className="h-20 animate-pulse rounded-xl bg-surface-secondary" />
        <div className="h-36 animate-pulse rounded-xl bg-surface-secondary" />
      </div>
    );
  }

  const readOnly = !canEdit || saving;

  return (
    <div className="space-y-4 lg:col-span-2" data-testid="market-settings">
      <div className="flex justify-end">
        <Button variant="primary" size="sm" disabled={!canEdit || !dirty || saving || !draft.primary} onClick={() => void handleSave()}>
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>

      <Card>
        <CardHeader title={t('market.primary', { defaultValue: 'Primary market' })} />
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-content-secondary">
              {t('market.primary', { defaultValue: 'Primary market' })}
              <select
                aria-label={t('market.primary', { defaultValue: 'Primary market' })}
                className={`mt-1 ${selectClass}`}
                value={primaryCode}
                disabled={readOnly}
                data-testid="market-primary"
                onChange={(e) => setDraft((d) => ({ ...d, primary: { country: e.target.value, subdivision: '' } }))}
              >
                <option value="">—</option>
                {countries.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="text-xs font-medium text-content-secondary">
              {t('market.company_type', { defaultValue: 'Company type' })}
              <p className="mt-2 text-sm text-content-primary">{draft.company_type ?? '—'}</p>
            </div>
          </div>
          <div className="mt-4">
            <p className="text-xs font-medium text-content-secondary">
              {t('market.active_packs', { defaultValue: 'Active packs' })}
            </p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {(scope.packs ?? []).length === 0 ? (
                <span className="text-xs text-content-tertiary">
                  {t('market.regional_empty', { defaultValue: 'No regional pack for your market yet.' })}
                </span>
              ) : (
                (scope.packs ?? []).map((slug) => (
                  <Badge key={slug} variant="blue" size="sm">
                    {slug}
                  </Badge>
                ))
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader title={t('market.other_markets', { defaultValue: 'Other markets' })} />
        <CardContent>
          <div className="flex flex-wrap items-center gap-2">
            {draft.extra_markets.length === 0 && (
              <span className="text-xs text-content-tertiary">
                {t('market.add_empty', { defaultValue: 'Working abroad? Add a market.' })}
              </span>
            )}
            {draft.extra_markets.map((m) => (
              <span
                key={m.country}
                className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2.5 py-1 text-xs text-content-primary"
              >
                {regionDisplayName(m.country, i18n.language)}
                {canEdit && (
                  <button
                    type="button"
                    aria-label={t('market.remove', { defaultValue: 'Remove market' })}
                    onClick={() =>
                      setPending({
                        profile: { ...draft, extra_markets: draft.extra_markets.filter((x) => x.country !== m.country) },
                        country: m.country,
                        adding: false,
                      })
                    }
                  >
                    <X size={12} aria-hidden />
                  </button>
                )}
              </span>
            ))}
          </div>
          {canEdit && (
            <div className="mt-3 flex items-end gap-2">
              <label className="block flex-1 text-xs font-medium text-content-secondary">
                {t('market.add', { defaultValue: 'Add market' })}
                <select
                  aria-label={t('market.add', { defaultValue: 'Add market' })}
                  className={`mt-1 ${selectClass}`}
                  value={adding}
                  disabled={saving}
                  data-testid="market-add-select"
                  onChange={(e) => setAdding(e.target.value)}
                >
                  <option value="">—</option>
                  {countries
                    .filter((c) => c.code !== primaryCode && !draft.extra_markets.some((m) => m.country === c.code))
                    .map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </label>
              <Button
                variant="secondary"
                size="sm"
                disabled={!adding}
                onClick={() => {
                  setPending({
                    profile: { ...draft, extra_markets: [...draft.extra_markets, { country: adding, subdivision: '' }] },
                    country: adding,
                    adding: true,
                  });
                  setAdding('');
                }}
              >
                <Plus size={14} className="me-1" aria-hidden />
                {adding
                  ? t('market.add_confirm', {
                      defaultValue: 'Add {{country}}',
                      country: regionDisplayName(adding, i18n.language),
                    })
                  : t('market.add', { defaultValue: 'Add market' })}
              </Button>
            </div>
          )}
          <p className="mt-3 text-xs text-content-tertiary">
            {t('market.data_safe', { defaultValue: 'Your data is never deleted; hidden modules can be shown again.' })}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader title={t('market.standards', { defaultValue: 'Standards' })} />
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="block text-xs font-medium text-content-secondary">
              {t('market.classification', { defaultValue: 'Classification' })}
              <select
                aria-label={t('market.classification', { defaultValue: 'Classification' })}
                className={`mt-1 ${selectClass}`}
                value={draft.standards.classification}
                disabled={readOnly}
                onChange={(e) => setStandard('classification', e.target.value)}
              >
                <option value="">{`—${defaultMarker}`}</option>
                {(scope.options?.standards ?? []).map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-medium text-content-secondary">
              {t('market.contract_family', { defaultValue: 'Contract forms' })}
              <select
                aria-label={t('market.contract_family', { defaultValue: 'Contract forms' })}
                className={`mt-1 ${selectClass}`}
                value={draft.standards.contract_family}
                disabled={readOnly}
                onChange={(e) => setStandard('contract_family', e.target.value)}
              >
                <option value="">{`—${defaultMarker}`}</option>
                {(scope.options?.contract_forms ?? []).map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-medium text-content-secondary">
              {t('market.units', { defaultValue: 'Units system' })}
              <select
                aria-label={t('market.units', { defaultValue: 'Units system' })}
                className={`mt-1 ${selectClass}`}
                value={draft.standards.units}
                disabled={readOnly}
                data-testid="market-units"
                onChange={(e) => setStandard('units', e.target.value)}
              >
                <option value="">
                  {`${t(UNITS_OPTIONS.find((u) => u.value === scope.units_system)?.key ?? 'market.units_both', {
                    defaultValue: UNITS_OPTIONS.find((u) => u.value === scope.units_system)?.fallback ?? 'Metric',
                  })}${defaultMarker}`}
                </option>
                {UNITS_OPTIONS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {t(u.key, { defaultValue: u.fallback })}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {Object.values(draft.standards).some(Boolean) && canEdit && (
            <button
              type="button"
              className="mt-3 text-xs text-oe-blue hover:underline"
              onClick={() => setDraft((d) => ({ ...d, standards: emptyProfile().standards }))}
            >
              {t('market.reset_default', { defaultValue: 'Reset to default' })}
            </button>
          )}
        </CardContent>
      </Card>
      {einvoiceScopeMarkets(scope).length > 0 && <EInvoiceSetupCard canEdit={canEdit} />}
      {pending && scope && (
        <MarketPreviewModal
          open
          current={scope}
          next={pending.profile}
          title={
            pending.adding
              ? t('market.add_confirm', {
                  defaultValue: 'Add {{country}}',
                  country: regionDisplayName(pending.country, i18n.language),
                })
              : t('market.remove', { defaultValue: 'Remove market' })
          }
          confirmLabel={t('common.save', { defaultValue: 'Save' })}
          onClose={() => setPending(null)}
          onConfirm={async () => {
            await handleSave(pending.profile);
            setPending(null);
          }}
        />
      )}
    </div>
  );
}
