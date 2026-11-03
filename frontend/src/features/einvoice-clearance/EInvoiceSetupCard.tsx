// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Market & standards > "E-invoicing": one row per market with the
 * transport mode, seller id, certificate reference and Peppol id. Ready to be
 * mounted on the Market & standards page; admins edit, others read.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { fmtList } from '@/shared/lib/formatters';
import { WideModal } from '@/shared/ui/WideModal';
import { listProfiles, updateProfile, type ClearanceProfile, type ProfileWriteBody } from './api';
import { EINVOICE_SETUP_QUERY_KEY, useEInvoiceMarkets } from './useEInvoiceMarkets';

type Mode = 'export' | 'sandbox' | 'live';

function toBody(p: ClearanceProfile, patch: Partial<ProfileWriteBody>): ProfileWriteBody {
  return {
    company_key: p.company_key,
    country: p.country,
    tax_registration_id: p.tax_registration_id,
    network_participant_id: p.network_participant_id,
    certificate_reference: p.certificate_reference,
    adapter_key: p.adapter_key,
    sandbox: p.sandbox,
    mode: (p.mode as Mode) || 'export',
    is_active: p.is_active,
    settings: p.settings,
    notes: p.notes,
    ...patch,
  };
}

export function EInvoiceSetupCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const markets = useEInvoiceMarkets();
  const profiles = useQuery({ queryKey: ['einvoice-clearance', 'profiles'], queryFn: () => listProfiles({}) });
  const [liveFor, setLiveFor] = useState<ClearanceProfile | null>(null);

  const save = useMutation({
    mutationFn: ({ p, patch }: { p: ClearanceProfile; patch: Partial<ProfileWriteBody> }) =>
      updateProfile(p.id, toBody(p, patch)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['einvoice-clearance', 'profiles'] });
      queryClient.invalidateQueries({ queryKey: EINVOICE_SETUP_QUERY_KEY });
    },
  });

  const byCountry = new Map((profiles.data ?? []).map((p) => [p.country, p]));
  const modeLabel = (m: Mode) => t(`einvoice.mode.${m}`, { defaultValue: m });

  return (
    <Card className="p-4 space-y-3">
      <h3 className="text-sm font-semibold">{t('einvoice.setup.title', { defaultValue: 'E-invoicing' })}</h3>
      {markets.rows.map((row) => {
        const p = byCountry.get(row.country);
        if (!p) return null;
        const mode = ((p.mode as Mode) || 'export') as Mode;
        const sandboxOk = Boolean((p.settings as Record<string, unknown>)?.sandbox_success_at);
        return (
          <div key={row.country} className="flex flex-wrap items-center gap-3 text-sm">
            <span className="font-medium w-48">
              [{row.country}] {row.platform}
            </span>
            <label className="flex items-center gap-1">
              {t('einvoice.setup.mode', { defaultValue: 'Mode' })}
              <select
                value={mode}
                disabled={!canEdit}
                onChange={(e) => {
                  const next = e.target.value as Mode;
                  if (next === 'live') setLiveFor(p);
                  else save.mutate({ p, patch: { mode: next } });
                }}
                className="rounded border border-border-light bg-surface-primary px-2 py-1"
              >
                <option value="export">{modeLabel('export')}</option>
                <option value="sandbox">{modeLabel('sandbox')}</option>
                <option value="live" disabled={!sandboxOk || !p.certificate_reference}>
                  {modeLabel('live')}
                </option>
              </select>
            </label>
            <label className="flex items-center gap-1">
              {t('einvoice.setup.sellerId', { defaultValue: 'Seller tax ID' })}
              <input
                dir="ltr"
                defaultValue={p.tax_registration_id}
                disabled={!canEdit}
                onBlur={(e) =>
                  e.target.value !== p.tax_registration_id &&
                  save.mutate({ p, patch: { tax_registration_id: e.target.value } })
                }
                className="rounded border border-border-light bg-surface-primary px-2 py-1 w-40"
              />
            </label>
            <span className="text-xs text-content-secondary" dir="ltr">
              {t('einvoice.setup.certificate', { defaultValue: 'Certificate' })}:{' '}
              {p.certificate_reference ? '••••' + p.certificate_reference.slice(-4) : '-'}
            </span>
            {row.ready ? (
              <span className="flex items-center gap-1 text-semantic-success">
                <CheckCircle2 size={14} aria-hidden="true" />
                {t('einvoice.setup.ready', { defaultValue: 'Ready' })}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-semantic-warning">
                <AlertTriangle size={14} aria-hidden="true" />
                {t('einvoice.setup.missing', { defaultValue: 'Missing: {{fields}}', fields: fmtList(row.missing) })}
              </span>
            )}
          </div>
        );
      })}

      {liveFor && (
        <WideModal
          open
          size="sm"
          initialFocusSelector="[data-initial-focus]"
          onClose={() => setLiveFor(null)}
          title={modeLabel('live')}
          footer={
            <div className="flex justify-end gap-2">
              <Button variant="secondary" data-initial-focus onClick={() => setLiveFor(null)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  save.mutate({ p: liveFor, patch: { mode: 'live' } });
                  setLiveFor(null);
                }}
              >
                {modeLabel('live')}
              </Button>
            </div>
          }
        >
          <p className="text-sm">
            {t('einvoice.mode.liveConfirm', {
              defaultValue: 'Live sends legally binding invoices to {{platform}}. Test in Sandbox first.',
              platform: liveFor.platform,
            })}
          </p>
        </WideModal>
      )}
    </Card>
  );
}
