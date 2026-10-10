// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// EditBuyerModal — partial-edit a Property Development buyer.
//
// Wires the frontend up to ``PATCH /api/v1/property-dev/buyers/{id}``.
// The backend was already feature-complete (see #134 root cause notes in
// R6_PROPDEV_BUYER_EDIT_REPORT.md): only the UI was missing the edit
// flow. The modal mirrors the BuyerUpdate Pydantic schema and only
// exposes status transitions that the FSM in
// ``backend/app/modules/property_dev/service.py::allowed_buyer_transitions``
// considers valid for the buyer's current state — illegal options are
// not even rendered, while the server remains the source of truth and
// re-checks on PATCH (returns 409 if a race lets an invalid option slip
// through).

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Save } from 'lucide-react';

import { Button } from '@/shared/ui';
import {
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError } from '@/shared/lib/api';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';
import { sortLanguagesByName } from '@/shared/lib/languageOrder';

import {
  allowedBuyerTransitions,
  listJurisdictions,
  updateBuyer,
  type Buyer,
  type BuyerStatus,
  type Plot,
  type UpdateBuyerPayload,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const ISO_CURRENCY_RE = /^[A-Z]{3}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DECIMAL_RE = /^-?\d+(\.\d+)?$/;

const BUYER_STATUS_LABELS: Record<BuyerStatus, { defaultValue: string; key: string }> = {
  lead: { key: 'propdev.stage_lead', defaultValue: 'Lead' },
  reserved: { key: 'propdev.stage_reserved', defaultValue: 'Reserved' },
  contracted: { key: 'propdev.stage_contracted', defaultValue: 'Contracted' },
  completed: { key: 'propdev.stage_handover', defaultValue: 'Handover' },
  cancelled: { key: 'propdev.stage_cancelled', defaultValue: 'Cancelled' },
};

export interface EditBuyerModalProps {
  open: boolean;
  buyer: Buyer;
  plots: Plot[];
  developmentId: string;
  onClose: () => void;
  onSaved?: (next: Buyer) => void;
}

type FormState = {
  full_name: string;
  email: string;
  phone: string;
  language: string;
  jurisdiction: string;
  plot_id: string;
  status: BuyerStatus;
  contract_value: string;
  currency: string;
  deposit_amount: string;
};

function buyerToForm(buyer: Buyer): FormState {
  return {
    full_name: buyer.full_name ?? '',
    email: buyer.email ?? '',
    phone: buyer.phone ?? '',
    language: buyer.language || 'en',
    jurisdiction: (buyer as Buyer & { jurisdiction?: string }).jurisdiction ?? '',
    plot_id: buyer.plot_id ?? '',
    status: buyer.status,
    contract_value:
      buyer.contract_value === null || buyer.contract_value === undefined
        ? '0'
        : String(buyer.contract_value),
    currency: buyer.currency ?? '',
    deposit_amount: String(
      (buyer as Buyer & { deposit_amount?: number | string }).deposit_amount ?? '0',
    ),
  };
}

function buildPayload(
  initial: FormState,
  next: FormState,
): UpdateBuyerPayload {
  const payload: UpdateBuyerPayload = {};
  if (initial.full_name !== next.full_name) payload.full_name = next.full_name;
  if (initial.email !== next.email) payload.email = next.email;
  if (initial.phone !== next.phone) payload.phone = next.phone || null;
  if (initial.language !== next.language) payload.language = next.language;
  // jurisdiction is a derived field on the backend; we expose it on the
  // partial payload so editors can fix typos from the contract step.
  if (initial.jurisdiction !== next.jurisdiction) {
    (payload as UpdateBuyerPayload & { jurisdiction?: string }).jurisdiction =
      next.jurisdiction;
  }
  if (initial.plot_id !== next.plot_id)
    payload.plot_id = next.plot_id ? next.plot_id : null;
  if (initial.status !== next.status) payload.status = next.status;
  if (initial.contract_value !== next.contract_value) {
    payload.contract_value = roundMoney(next.contract_value);
  }
  if (initial.currency !== next.currency) payload.currency = next.currency;
  if (initial.deposit_amount !== next.deposit_amount) {
    (payload as UpdateBuyerPayload & { deposit_amount?: string }).deposit_amount =
      roundMoney(next.deposit_amount);
  }
  return payload;
}

function roundMoney(raw: string): string {
  if (!raw) return '0';
  const n = Number(raw);
  if (Number.isNaN(n)) return raw;
  return fmtFixed(n, 2);
}

function validate(form: FormState, t: (k: string, o?: { defaultValue: string }) => string): Record<string, string> {
  const errs: Record<string, string> = {};
  if (!form.full_name.trim()) {
    errs.full_name = t('propdev.edit.error_full_name_required', {
      defaultValue: 'Full name is required',
    });
  }
  if (form.email && !EMAIL_RE.test(form.email)) {
    errs.email = t('propdev.edit.error_email_invalid', {
      defaultValue: 'Enter a valid email address',
    });
  }
  if (form.currency && !ISO_CURRENCY_RE.test(form.currency)) {
    errs.currency = t('propdev.edit.error_currency_iso', {
      defaultValue: 'Currency must be a 3-letter ISO code (e.g. EUR)',
    });
  }
  if (form.contract_value && !DECIMAL_RE.test(form.contract_value)) {
    errs.contract_value = t('propdev.edit.error_decimal', {
      defaultValue: 'Enter a number with up to 2 decimal places',
    });
  }
  if (form.deposit_amount && !DECIMAL_RE.test(form.deposit_amount)) {
    errs.deposit_amount = t('propdev.edit.error_decimal', {
      defaultValue: 'Enter a number with up to 2 decimal places',
    });
  }
  return errs;
}

export function EditBuyerModal({
  open,
  buyer,
  plots,
  developmentId,
  onClose,
  onSaved,
}: EditBuyerModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const initial = useMemo(() => buyerToForm(buyer), [buyer]);
  const [form, setForm] = useState<FormState>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);

  // Reset whenever a different buyer is opened or the modal is re-shown.
  useEffect(() => {
    if (open) {
      setForm(initial);
      setErrors({});
      setServerError(null);
    }
  }, [open, initial]);

  const jurisdictionsQ = useQuery({
    queryKey: ['propdev', 'jurisdictions'],
    queryFn: listJurisdictions,
    enabled: open,
    staleTime: 60_000,
  });
  const jurisdictionOptions = jurisdictionsQ.data ?? [];

  // FSM-allowed next states for the dropdown. Sourced from the same
  // transition map the backend enforces — see allowedBuyerTransitions
  // in ./api.ts. The current status is always included so the value
  // remains valid when no transition is being performed.
  const statusOptions = useMemo<BuyerStatus[]>(() => {
    const allowed = allowedBuyerTransitions[buyer.status] ?? [buyer.status];
    return Array.from(new Set([buyer.status, ...allowed])) as BuyerStatus[];
  }, [buyer.status]);

  const availablePlots = useMemo(
    () => plots.filter((p) => p.development_id === developmentId),
    [plots, developmentId],
  );

  const mutation = useMutation({
    mutationKey: ['propdev', 'buyers', 'update', buyer.id],
    // The global MutationCache error handler in main.tsx fires a generic
    // toast on every failure. We surface a contextual inline error
    // inside the modal instead — opt out of the global handler by
    // tagging the mutation with suppressGlobalErrorToast=true so
    // queryClient honours our explicit onError.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (payload: UpdateBuyerPayload) => updateBuyer(buyer.id, payload),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers'] });
      qc.invalidateQueries({ queryKey: ['propdev', 'buyers', developmentId] });
      qc.invalidateQueries({ queryKey: ['propdev', 'buyer', buyer.id] });
      addToast({
        type: 'success',
        title: t('propdev.edit.saved_title', { defaultValue: 'Buyer updated' }),
        message: updated.full_name || updated.email,
      });
      onSaved?.(updated);
      onClose();
    },
    onError: (err: unknown) => {
      // ApiError carries the parsed FastAPI ``detail`` (or fallback).
      // 409 = invalid FSM transition or duplicate email collision.
      // 422 = Pydantic validation (bad currency, non-existent plot, ...).
      // 403 = role gate (caller lacks property_dev.update).
      if (err instanceof ApiError) {
        setServerError(err.message);
      } else if (err instanceof Error) {
        setServerError(err.message);
      } else {
        setServerError(
          t('propdev.edit.error_unknown', {
            defaultValue: 'Could not save the buyer. Please try again.',
          }),
        );
      }
    },
  });

  const handleSubmit = () => {
    setServerError(null);
    const errs = validate(form, t);
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;
    const payload = buildPayload(initial, form);
    if (Object.keys(payload).length === 0) {
      // Nothing changed — just close the modal silently.
      onClose();
      return;
    }
    mutation.mutate(payload);
  };

  const titleName = buyer.full_name || buyer.email || buyer.id;

  return (
    <WideModal
      open={open}
      onClose={() => !mutation.isPending && onClose()}
      title={t('propdev.edit.title', { defaultValue: 'Edit buyer' })}
      subtitle={titleName}
      size="lg"
      busy={mutation.isPending}
      footer={
        <>
          <Button
            variant="ghost"
            onClick={() => !mutation.isPending && onClose()}
            disabled={mutation.isPending}
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            icon={mutation.isPending ? <Loader2 size={14} /> : <Save size={14} />}
            loading={mutation.isPending}
            onClick={handleSubmit}
            data-testid="edit-buyer-save"
          >
            {t('propdev.edit.save', { defaultValue: 'Save' })}
          </Button>
        </>
      }
    >
      {serverError && (
        <div
          role="alert"
          data-testid="edit-buyer-error"
          className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800"
        >
          {serverError}
        </div>
      )}
      <WideModalSection
        title={t('propdev.edit.contact_section', { defaultValue: 'Contact' })}
        columns={2}
      >
        <WideModalField
          label={t('propdev.edit.full_name', { defaultValue: 'Full name' })}
          required
          error={errors.full_name}
        >
          <input
            className={inputCls}
            value={form.full_name}
            onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            data-testid="edit-buyer-full-name"
            maxLength={255}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.email', { defaultValue: 'Email' })}
          error={errors.email}
        >
          <input
            type="email"
            className={inputCls}
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            data-testid="edit-buyer-email"
            maxLength={255}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.phone', { defaultValue: 'Phone' })}
          error={errors.phone}
        >
          <input
            type="tel"
            className={inputCls}
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            data-testid="edit-buyer-phone"
            maxLength={40}
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.language', { defaultValue: 'Language' })}
        >
          <select
            className={inputCls}
            value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value })}
            data-testid="edit-buyer-language"
          >
            {sortLanguagesByName(SUPPORTED_LANGUAGES).map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.name}
                {lang.english ? ` (${lang.english})` : ''}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('propdev.edit.lifecycle_section', { defaultValue: 'Plot & lifecycle' })}
        columns={2}
      >
        <WideModalField
          label={t('propdev.edit.plot', { defaultValue: 'Plot' })}
          hint={t('propdev.edit.plot_hint', {
            defaultValue: 'Only plots in this development are listed.',
          })}
        >
          <select
            className={inputCls}
            value={form.plot_id}
            onChange={(e) => setForm({ ...form, plot_id: e.target.value })}
            data-testid="edit-buyer-plot"
          >
            <option value="">
              {t('propdev.edit.plot_none', { defaultValue: 'Unassigned' })}
            </option>
            {availablePlots.map((p) => (
              <option key={p.id} value={p.id}>
                {p.plot_number} — {p.status}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.status', { defaultValue: 'Status' })}
          hint={t('propdev.edit.status_hint', {
            defaultValue: 'Only FSM-valid next states are shown.',
          })}
        >
          <select
            className={inputCls}
            value={form.status}
            onChange={(e) =>
              setForm({ ...form, status: e.target.value as BuyerStatus })
            }
            data-testid="edit-buyer-status"
          >
            {statusOptions.map((s) => (
              <option key={s} value={s}>
                {t(BUYER_STATUS_LABELS[s].key, {
                  defaultValue: BUYER_STATUS_LABELS[s].defaultValue,
                })}
                {s === buyer.status ? ` (${t('propdev.edit.current_status', { defaultValue: 'current' })})` : ''}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.jurisdiction', { defaultValue: 'Jurisdiction' })}
          hint={t('propdev.edit.jurisdiction_hint', {
            defaultValue: 'Used for deposit-forfeiture rules.',
          })}
        >
          <select
            className={inputCls}
            value={form.jurisdiction}
            onChange={(e) =>
              setForm({ ...form, jurisdiction: e.target.value.toUpperCase() })
            }
            data-testid="edit-buyer-jurisdiction"
          >
            <option value="">
              {t('propdev.edit.jurisdiction_none', { defaultValue: 'None' })}
            </option>
            {jurisdictionOptions.map((j) => (
              <option key={j} value={j}>
                {j}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('propdev.edit.financial_section', { defaultValue: 'Financial' })}
        columns={2}
      >
        <WideModalField
          label={t('propdev.edit.contract_value', { defaultValue: 'Contract value' })}
          error={errors.contract_value}
        >
          <input
            type="number"
            step="0.01"
            min="0"
            className={inputCls}
            value={form.contract_value}
            onChange={(e) =>
              setForm({ ...form, contract_value: e.target.value })
            }
            data-testid="edit-buyer-contract-value"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.currency', { defaultValue: 'Currency (ISO)' })}
          error={errors.currency}
        >
          <input
            className={inputCls}
            value={form.currency}
            onChange={(e) =>
              setForm({ ...form, currency: e.target.value.toUpperCase() })
            }
            maxLength={3}
            placeholder="EUR"
            data-testid="edit-buyer-currency"
          />
        </WideModalField>
        <WideModalField
          label={t('propdev.edit.deposit_amount', { defaultValue: 'Deposit amount' })}
          error={errors.deposit_amount}
        >
          <input
            type="number"
            step="0.01"
            min="0"
            className={inputCls}
            value={form.deposit_amount}
            onChange={(e) =>
              setForm({ ...form, deposit_amount: e.target.value })
            }
            data-testid="edit-buyer-deposit-amount"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

export default EditBuyerModal;
