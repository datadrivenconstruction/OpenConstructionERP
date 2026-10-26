// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Company-wide guarantee exposure: totals, by bank and type, credit-line headroom, expiries and the credit-line editor. */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft, Pencil, Plus, Trash2 } from 'lucide-react';
import { Button, Card, ConfirmDialog, EmptyState, WideModal, WideModalField } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  barWidth,
  compactBody,
  createFacility,
  deleteFacility,
  updateFacility,
  useExposure,
  useFacilities,
  useGuaranteeMutation,
  utilisationPercent,
  type Facility,
  type FacilityInput,
  type MoneyTotal,
} from './api';
import { typeLabel } from './labels';
import { AlertBadge, Money, inputCls, textareaCls } from './ui';

function BarList({ rows }: { rows: (MoneyTotal & { label: string })[] }) {
  // Bars compare amounts of the same currency only; a sum across currencies means nothing.
  const maxByCurrency = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows) m.set(r.currency, Math.max(m.get(r.currency) ?? 0, Number(r.amount) || 0));
    return m;
  }, [rows]);
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={`${r.label}-${r.currency}`}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="truncate text-content-secondary">{r.label}</span>
            <Money value={r.amount} currency={r.currency} />
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-secondary">
            <div className="h-full rounded-full bg-oe-blue" style={{ width: `${barWidth(r.amount, maxByCurrency.get(r.currency) ?? 0)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

const EMPTY_FACILITY: FacilityInput = {
  name: '',
  bank_name: '',
  currency: '',
  limit_amount: '',
  expiry_date: null,
  notes: null,
};

function FacilityModal({
  editing,
  isPending,
  onClose,
  onSubmit,
}: {
  editing: Facility | null;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (body: FacilityInput) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<FacilityInput>(
    editing
      ? { name: editing.name, bank_name: editing.bank_name, currency: editing.currency, limit_amount: editing.limit_amount, expiry_date: editing.expiry_date, notes: editing.notes }
      : EMPTY_FACILITY,
  );
  const set = <K extends keyof FacilityInput>(k: K, v: FacilityInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const valid =
    form.name.trim() !== '' &&
    form.bank_name.trim() !== '' &&
    /^[A-Za-z]{3}$/.test(form.currency.trim()) &&
    /^\d+(\.\d+)?$/.test(form.limit_amount.trim());
  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="md"
      title={editing ? t('guarantees.facility_edit', { defaultValue: 'Edit credit line' }) : t('guarantees.facility_new', { defaultValue: 'New credit line' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button
            variant="primary"
            loading={isPending}
            disabled={!valid}
            onClick={() =>
              onSubmit({
                name: form.name.trim(),
                bank_name: form.bank_name.trim(),
                currency: form.currency.trim().toUpperCase(),
                limit_amount: form.limit_amount.trim(),
                expiry_date: form.expiry_date || null,
                notes: form.notes?.trim() || null,
              })
            }
          >
            {t('guarantees.facility_save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <WideModalField label={t('guarantees.facility_name', { defaultValue: 'Name' })} required>
          <input className={inputCls} value={form.name} onChange={(e) => set('name', e.target.value)} autoFocus />
        </WideModalField>
        <WideModalField label={t('guarantees.facility_bank', { defaultValue: 'Bank' })} required>
          <input className={inputCls} value={form.bank_name} onChange={(e) => set('bank_name', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_currency', { defaultValue: 'Currency' })} required>
          <input className={inputCls} maxLength={3} value={form.currency} onChange={(e) => set('currency', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.facility_limit', { defaultValue: 'Limit' })} required>
          <input className={inputCls} inputMode="decimal" value={form.limit_amount} onChange={(e) => set('limit_amount', e.target.value)} />
        </WideModalField>
        <WideModalField label={t('guarantees.facility_expiry', { defaultValue: 'Valid until' })}>
          <input type="date" className={inputCls} value={form.expiry_date ?? ''} onChange={(e) => set('expiry_date', e.target.value || null)} />
        </WideModalField>
        <WideModalField label={t('guarantees.field_notes', { defaultValue: 'Notes' })} span={2}>
          <textarea className={textareaCls} rows={2} value={form.notes ?? ''} onChange={(e) => set('notes', e.target.value)} />
        </WideModalField>
      </div>
    </WideModal>
  );
}

export function GuaranteesExposurePage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const exposureQ = useExposure();
  const facilitiesQ = useFacilities();
  const [facilityModal, setFacilityModal] = useState<{ editing: Facility | null } | null>(null);

  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('guarantees.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const saveMut = useGuaranteeMutation((vars: { id: string | null; body: FacilityInput }) =>
    vars.id ? updateFacility(vars.id, compactBody(vars.body) as Partial<FacilityInput>) : createFacility(vars.body),
  );
  const deleteMut = useGuaranteeMutation((id: string) => deleteFacility(id));

  const ex = exposureQ.data;
  const bankRows = (ex?.by_bank ?? []).map((r) => ({ ...r, label: r.bank || t('guarantees.insights.no_bank', { defaultValue: 'No bank' }) }));
  const typeRows = (ex?.by_type ?? []).map((r) => ({ ...r, label: typeLabel(t, r.guarantee_type) }));

  const handleDelete = async (f: Facility) => {
    const ok = await confirm({
      title: t('guarantees.facility_delete_title', { defaultValue: 'Delete credit line?' }),
      message: t('guarantees.facility_delete_msg', { defaultValue: 'Guarantees keep their history; they are no longer counted against this line.' }),
      confirmLabel: t('guarantees.confirm_delete_label', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (ok) deleteMut.mutate(f.id, { onError });
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('guarantees.exposure_title', { defaultValue: 'Guarantee exposure' })}
        subtitle={t('guarantees.exposure_subtitle', { defaultValue: 'Live guarantees across all projects, by currency, bank and type' })}
        actions={
          <Link to="/portfolio/guarantees/register">
            <Button variant="secondary" size="sm" icon={<ArrowLeft size={14} />}>
              {t('guarantees.back', { defaultValue: 'Register' })}
            </Button>
          </Link>
        }
      />

      {exposureQ.isLoading ? (
        <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('guarantees.loading', { defaultValue: 'Loading...' })}</Card>
      ) : !ex || ex.live_count === 0 ? (
        <EmptyState title={t('guarantees.exposure_empty', { defaultValue: 'No live guarantees' })} description={t('guarantees.exposure_empty_hint', { defaultValue: 'Exposure appears once a guarantee is issued.' })} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="guarantees-totals">
            <Card padding="md">
              <div className="text-2xs uppercase tracking-wide text-content-tertiary">{t('guarantees.live_count', { defaultValue: 'Live guarantees' })}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums text-content-primary">{ex.live_count}</div>
            </Card>
            {ex.totals.map((tot) => (
              <Card key={tot.currency} padding="md">
                <div className="text-2xs uppercase tracking-wide text-content-tertiary">{t('guarantees.total_in', { defaultValue: 'Total in {{currency}}', currency: tot.currency })}</div>
                <div className="mt-1 text-xl font-semibold text-content-primary"><Money value={tot.amount} currency={tot.currency} /></div>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card padding="md">
              <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('guarantees.by_bank', { defaultValue: 'By bank' })}</h3>
              <BarList rows={bankRows} />
            </Card>
            <Card padding="md">
              <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('guarantees.by_type', { defaultValue: 'By type' })}</h3>
              <BarList rows={typeRows} />
            </Card>
          </div>

          <Card padding="md">
            <h3 className="mb-3 text-sm font-semibold text-content-primary">{t('guarantees.expiring_title', { defaultValue: 'Expiring soon' })}</h3>
            {ex.expiring.length === 0 ? (
              <p className="text-sm text-content-tertiary">{t('guarantees.expiring_empty', { defaultValue: 'Nothing expires in the next 60 days' })}</p>
            ) : (
              <ul className="divide-y divide-border-light">
                {ex.expiring.map((g) => (
                  <li key={g.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                    <Link to={`/projects/${g.project_id}/guarantees/${g.id}`} className="font-medium text-oe-blue-text hover:underline">{g.reference}</Link>
                    <span className="text-content-secondary">{g.issuer_bank || '—'}</span>
                    <Money value={g.amount} currency={g.currency} />
                    <span className="ml-auto flex items-center gap-2 text-content-secondary">
                      <DateDisplay value={g.expiry_date} />
                      <AlertBadge band={g.alert_band} days={g.days_to_expiry} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      <Card padding="md">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-content-primary">{t('guarantees.credit_lines', { defaultValue: 'Bank credit lines' })}</h3>
          <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setFacilityModal({ editing: null })}>
            {t('guarantees.facility_new', { defaultValue: 'New credit line' })}
          </Button>
        </div>
        {(facilitiesQ.data ?? []).length === 0 ? (
          <p className="text-sm text-content-tertiary">{t('guarantees.credit_lines_empty', { defaultValue: 'No credit lines yet. Add the limits your banks granted to see how much headroom is left.' })}</p>
        ) : (
          <ul className="space-y-4">
            {(facilitiesQ.data ?? []).map((f) => {
              const usage = ex?.credit_lines.find((c) => c.facility_id === f.id);
              const pct = usage ? utilisationPercent(usage) : null;
              return (
                <li key={f.id}>
                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="font-medium text-content-primary">{f.name}</span>
                    <span className="text-content-secondary">{f.bank_name}</span>
                    {f.expiry_date && (
                      <span className="text-2xs text-content-tertiary">
                        {t('guarantees.facility_valid_until', { defaultValue: 'valid until' })} <DateDisplay value={f.expiry_date} />
                      </span>
                    )}
                    <span className="ml-auto flex gap-1">
                      <Button variant="ghost" size="sm" icon={<Pencil size={14} />} aria-label={t('guarantees.facility_edit', { defaultValue: 'Edit credit line' })} onClick={() => setFacilityModal({ editing: f })} />
                      <Button variant="ghost" size="sm" icon={<Trash2 size={14} />} aria-label={t('guarantees.delete', { defaultValue: 'Delete' })} onClick={() => handleDelete(f)} />
                    </span>
                  </div>
                  <div className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-surface-secondary">
                    <div
                      className={pct !== null && pct >= 90 ? 'h-full bg-rose-500' : pct !== null && pct >= 70 ? 'h-full bg-amber-500' : 'h-full bg-emerald-500'}
                      style={{ width: `${Math.min(100, pct ?? 0)}%` }}
                    />
                  </div>
                  <div className="mt-1 flex flex-wrap justify-between gap-2 text-2xs text-content-tertiary">
                    <span>
                      {t('guarantees.facility_used', { defaultValue: 'Used' })} <Money value={usage?.used_amount ?? '0'} currency={f.currency} />
                      {pct !== null && ` (${Math.round(pct)}%)`}
                    </span>
                    <span>
                      {t('guarantees.facility_available', { defaultValue: 'Available' })} <Money value={usage?.available_amount ?? f.limit_amount} currency={f.currency} />
                      {' / '}
                      <Money value={f.limit_amount} currency={f.currency} />
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {facilityModal && (
        <FacilityModal
          editing={facilityModal.editing}
          isPending={saveMut.isPending}
          onClose={() => setFacilityModal(null)}
          onSubmit={(body) =>
            saveMut.mutate({ id: facilityModal.editing?.id ?? null, body }, { onSuccess: () => setFacilityModal(null), onError })
          }
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
