// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * EInvoiceTrSection - what an accountant fills in for an e-Fatura that the
 * invoice itself does not say.
 *
 * Shown by EInvoiceModal for the UBL-TR profile only. It draws the fields and
 * nothing else: the modal owns the values, the save and the report, so the
 * same state decides what is on screen, what is sent and whether the download
 * is open.
 *
 * Nothing here is defaulted on the user's behalf. An empty scenario stays
 * empty and the report says so, because which of the three applies depends on
 * whether the buyer is a registered e-Fatura user, and a guess that looks like
 * a choice is how a wrong one gets signed.
 */
import { useTranslation } from 'react-i18next';
import { WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import {
  EXEMPTION_REASON_MAX,
  ORIGINAL_DOCUMENT_ID_MAX,
  TR_INVOICE_TYPES,
  TR_PARTY_KEYS,
  TR_PARTY_ROLES,
  TR_RETURN_TYPE,
  TR_SCENARIOS,
  trFieldId,
  trPartyField,
} from './einvoiceTr';
import type {
  TrFieldError,
  TrFieldName,
  TrFormState,
  TrPartyFieldName,
  TrPartyFormState,
} from './einvoiceTr';

/** An invoice of the same project a return can answer. */
export interface EInvoiceReturnCandidate {
  id: string;
  invoice_number: string;
}

export interface EInvoiceTrSectionProps {
  form: TrFormState;
  parties: TrPartyFormState;
  errors: Partial<Record<TrFieldName, TrFieldError>>;
  onField: (name: TrFieldName, value: string) => void;
  onParty: (name: TrPartyFieldName, value: string) => void;
  /** The invoice currency when it is not Turkish lira, otherwise empty. */
  foreignCurrency: string;
  /** The UUID (ETTN) the export writes; stable for the invoice. */
  ettn: string;
  returnCandidates: EInvoiceReturnCandidate[];
  disabled: boolean;
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm ' +
  'text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue disabled:opacity-60';

const codeCls = `${inputCls} font-mono uppercase`;

export function EInvoiceTrSection({
  form,
  parties,
  errors,
  onField,
  onParty,
  foreignCurrency,
  ettn,
  returnCandidates,
  disabled,
}: EInvoiceTrSectionProps) {
  const { t } = useTranslation();

  const errorText = (name: TrFieldName): string | undefined => {
    const code = errors[name];
    return code ? t(`einvoice.tr.error.${code}`) : undefined;
  };

  // The stored original may be an invoice outside the page of invoices the
  // caller loaded. It still has to be selectable, or opening the screen and
  // saving would silently drop the link.
  const originalKnown = returnCandidates.some((c) => c.id === form.original_invoice_id);

  // The block for the returned invoice stays visible while it holds anything,
  // whatever the type says, so a value never sits in a field nobody can see.
  const showOriginal =
    form.invoice_type === TR_RETURN_TYPE ||
    Boolean(form.original_invoice_id || form.original_document_id || form.original_issue_date);

  return (
    <>
      <WideModalSection title={t('einvoice.tr.fields.title')} columns={2}>
        <WideModalField
          label={t('einvoice.tr.fields.profile_id')}
          htmlFor={trFieldId('profile_id')}
          hint={t('einvoice.tr.fields.profile_id_hint')}
        >
          <select
            id={trFieldId('profile_id')}
            value={form.profile_id}
            onChange={(e) => onField('profile_id', e.target.value)}
            className={inputCls}
            disabled={disabled}
          >
            <option value="">{t('einvoice.tr.fields.profile_id_unset')}</option>
            {TR_SCENARIOS.map((code) => (
              <option key={code} value={code}>
                {t(`einvoice.tr.scenario.${code}`)}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('einvoice.tr.fields.invoice_type')}
          htmlFor={trFieldId('invoice_type')}
          hint={t('einvoice.tr.fields.invoice_type_hint')}
        >
          <select
            id={trFieldId('invoice_type')}
            value={form.invoice_type}
            onChange={(e) => onField('invoice_type', e.target.value)}
            className={inputCls}
            disabled={disabled}
          >
            <option value="">{t('einvoice.tr.fields.invoice_type_auto')}</option>
            {TR_INVOICE_TYPES.map((code) => (
              <option key={code} value={code}>
                {t(`einvoice.tr.invoice_type.${code}`)}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('einvoice.tr.fields.document_id')}
          htmlFor={trFieldId('document_id')}
          hint={t('einvoice.tr.fields.document_id_hint')}
          error={errorText('document_id')}
        >
          <input
            id={trFieldId('document_id')}
            type="text"
            value={form.document_id}
            onChange={(e) => onField('document_id', e.target.value)}
            className={codeCls}
            maxLength={16}
            // The shape the format prescribes, not prose.
            placeholder="ABC2026000000001"
            disabled={disabled}
          />
        </WideModalField>

        <WideModalField
          label={t('einvoice.tr.fields.series')}
          htmlFor={trFieldId('series')}
          hint={t('einvoice.tr.fields.series_hint')}
          error={errorText('series')}
        >
          <input
            id={trFieldId('series')}
            type="text"
            value={form.series}
            onChange={(e) => onField('series', e.target.value)}
            className={codeCls}
            maxLength={3}
            placeholder="ABC"
            disabled={disabled}
          />
        </WideModalField>

        <WideModalField
          label={t('einvoice.tr.fields.issue_time')}
          htmlFor={trFieldId('issue_time')}
          error={errorText('issue_time')}
        >
          <input
            id={trFieldId('issue_time')}
            type="time"
            step={1}
            value={form.issue_time}
            onChange={(e) => onField('issue_time', e.target.value)}
            className={inputCls}
            disabled={disabled}
          />
        </WideModalField>

        <WideModalField label={t('einvoice.tr.uuid')}>
          <p className="flex h-10 items-center break-all font-mono text-xs text-content-secondary">{ettn}</p>
        </WideModalField>

        {/* A lira invoice has no rate to state, and a field that cannot apply
            invites a value the file would then have to carry. */}
        {foreignCurrency && (
          <>
            <WideModalField
              label={t('einvoice.tr.fields.exchange_rate')}
              htmlFor={trFieldId('exchange_rate')}
              hint={t('einvoice.tr.fields.exchange_rate_hint', { currency: foreignCurrency })}
              error={errorText('exchange_rate')}
            >
              <input
                id={trFieldId('exchange_rate')}
                type="text"
                inputMode="decimal"
                value={form.exchange_rate}
                onChange={(e) => onField('exchange_rate', e.target.value)}
                className={`${inputCls} font-mono`}
                disabled={disabled}
              />
            </WideModalField>

            <WideModalField
              label={t('einvoice.tr.fields.exchange_rate_date')}
              htmlFor={trFieldId('exchange_rate_date')}
              hint={t('einvoice.tr.fields.exchange_rate_date_hint')}
              error={errorText('exchange_rate_date')}
            >
              <input
                id={trFieldId('exchange_rate_date')}
                type="date"
                value={form.exchange_rate_date}
                onChange={(e) => onField('exchange_rate_date', e.target.value)}
                className={inputCls}
                disabled={disabled}
              />
            </WideModalField>
          </>
        )}

        <WideModalField
          label={t('einvoice.tr.fields.exemption_reason_code')}
          htmlFor={trFieldId('exemption_reason_code')}
          hint={t('einvoice.tr.fields.exemption_reason_code_hint')}
        >
          <input
            id={trFieldId('exemption_reason_code')}
            type="text"
            inputMode="numeric"
            value={form.exemption_reason_code}
            onChange={(e) => onField('exemption_reason_code', e.target.value)}
            className={codeCls}
            maxLength={3}
            disabled={disabled}
          />
        </WideModalField>

        <WideModalField
          label={t('einvoice.tr.fields.exemption_reason')}
          htmlFor={trFieldId('exemption_reason')}
          error={errorText('exemption_reason')}
        >
          <input
            id={trFieldId('exemption_reason')}
            type="text"
            value={form.exemption_reason}
            onChange={(e) => onField('exemption_reason', e.target.value)}
            className={inputCls}
            maxLength={EXEMPTION_REASON_MAX}
            disabled={disabled}
          />
        </WideModalField>
      </WideModalSection>

      {showOriginal && (
        <WideModalSection
          title={t('einvoice.tr.fields.original_invoice')}
          description={t('einvoice.tr.fields.original_invoice_hint')}
          columns={3}
        >
          <WideModalField
            label={t('einvoice.tr.fields.original_invoice_id')}
            htmlFor={trFieldId('original_invoice_id')}
          >
            <select
              id={trFieldId('original_invoice_id')}
              value={form.original_invoice_id}
              onChange={(e) => onField('original_invoice_id', e.target.value)}
              className={inputCls}
              disabled={disabled}
            >
              <option value="">{t('einvoice.tr.fields.original_invoice_none')}</option>
              {form.original_invoice_id && !originalKnown && (
                <option value={form.original_invoice_id}>{form.original_invoice_id}</option>
              )}
              {returnCandidates.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.invoice_number}
                </option>
              ))}
            </select>
          </WideModalField>

          <WideModalField
            label={t('einvoice.tr.fields.original_invoice_document_id')}
            htmlFor={trFieldId('original_document_id')}
            error={errorText('original_document_id')}
          >
            <input
              id={trFieldId('original_document_id')}
              type="text"
              value={form.original_document_id}
              onChange={(e) => onField('original_document_id', e.target.value)}
              className={`${inputCls} font-mono`}
              maxLength={ORIGINAL_DOCUMENT_ID_MAX}
              disabled={disabled}
            />
          </WideModalField>

          <WideModalField
            label={t('einvoice.tr.fields.original_invoice_issue_date')}
            htmlFor={trFieldId('original_issue_date')}
            error={errorText('original_issue_date')}
          >
            <input
              id={trFieldId('original_issue_date')}
              type="date"
              value={form.original_issue_date}
              onChange={(e) => onField('original_issue_date', e.target.value)}
              className={inputCls}
              disabled={disabled}
            />
          </WideModalField>
        </WideModalSection>
      )}

      <WideModalSection
        title={t('einvoice.tr.parties.title')}
        description={t('einvoice.tr.parties.hint')}
        columns={3}
      >
        {TR_PARTY_ROLES.flatMap((role) =>
          TR_PARTY_KEYS.map((key) => {
            const name = trPartyField(role, key);
            return (
              <WideModalField key={name} label={t(`einvoice.tr.parties.${name}`)} htmlFor={trFieldId(name)}>
                <input
                  id={trFieldId(name)}
                  type="text"
                  value={parties[name]}
                  onChange={(e) => onParty(name, e.target.value)}
                  className={inputCls}
                  maxLength={100}
                  disabled={disabled}
                />
              </WideModalField>
            );
          }),
        )}
      </WideModalSection>
    </>
  );
}
