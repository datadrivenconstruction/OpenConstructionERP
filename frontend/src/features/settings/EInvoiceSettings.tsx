// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * EInvoiceSettings — seller identity and payment details for every e-invoice.
 *
 * The compliance panel on an invoice reports fatal EN 16931 violations for
 * seller master data and the bank account. Those are the same on every invoice
 * the company issues, so they are configured here once rather than retyped per
 * document, which is what the panel used to demand and no screen offered.
 *
 * Field-level errors come back from the API, which is deliberate: the IBAN
 * check digits and the VAT identifier shape are validated on the server so the
 * rule has one home, and this screen shows what that check said rather than
 * carrying a second copy of it.
 */

import { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, Landmark, AlertTriangle, Check } from 'lucide-react';
import { Card, CardHeader, CardContent, Button } from '@/shared/ui';
import { apiGet, apiPut, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtList } from '@/shared/lib/formatters';

// The stored fields, in the order they are shown. Kept as data so the form and
// the payload cannot disagree about which fields exist.
const SELLER_FIELDS = [
  'seller_name',
  'seller_vat_id',
  'seller_tax_number',
  'seller_legal_id',
  'seller_country_code',
  'seller_line1',
  'seller_postcode',
  'seller_city',
  // BG-6 SELLER CONTACT. XRechnung makes all three mandatory (BR-DE-2 and
  // BR-DE-5..7), and this screen is the only place they can be filled in.
  'seller_contact_name',
  'seller_contact_phone',
  'seller_contact_email',
  'seller_email',
  'seller_electronic_address',
  'seller_electronic_address_scheme',
] as const;

const PAYMENT_FIELDS = [
  'payee_iban',
  'payee_bic',
  'payee_account_name',
  'payment_means_code',
  'payment_terms',
] as const;

const ALL_FIELDS = [...SELLER_FIELDS, ...PAYMENT_FIELDS] as const;

type FieldName = (typeof ALL_FIELDS)[number];
type FormState = Record<FieldName, string>;

export interface EInvoiceSettingsPayload extends FormState {
  complete: boolean;
  missing: string[];
  // The countries paid through an IBAN, served by the API. Not held here: the
  // list that decides what the server will accept has to be the same list that
  // labels the field, or the screen asks for one thing and the save refuses it.
  iban_countries?: string[];
}

const EMPTY: FormState = ALL_FIELDS.reduce((acc, f) => ({ ...acc, [f]: '' }), {} as FormState);

// Notation, not prose. These are the shapes the standard itself prescribes, so
// they read the same in every language and stay out of the locale files.
const EXAMPLES: Partial<Record<FieldName, string>> = {
  seller_vat_id: 'DE123456789',
  seller_country_code: 'DE',
  seller_contact_phone: '+49 30 1234560',
  seller_electronic_address_scheme: '0204',
  payee_iban: 'DE02 1203 0000 0000 2020 51',
  payee_bic: 'COBADEFFXXX',
  payment_means_code: '30',
};

// Fields whose value is a code rather than prose, so they read better upper-cased
// and in a monospace column.
const CODE_FIELDS = new Set<FieldName>([
  'seller_vat_id',
  'seller_country_code',
  'payee_iban',
  'payee_bic',
  'payment_means_code',
  'seller_electronic_address_scheme',
]);

// Carried in the payload but not drawn. `seller_email` predates the contact
// group and holds the same business term as `seller_contact_email` (BT-43); the
// server reads it only when the newer column is empty. It stays in the request
// because a save writes the whole row, so dropping it here would blank an
// address the instance still relies on.
const HIDDEN_FIELDS = new Set<FieldName>(['seller_email']);

export function EInvoiceSettings() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [fieldError, setFieldError] = useState<string | null>(null);

  const { data, isLoading } = useQuery<EInvoiceSettingsPayload>({
    queryKey: ['finance', 'einvoice-settings'],
    queryFn: () => apiGet('/api/v1/finance/einvoice-settings'),
  });

  // The form is seeded while rendering rather than from an effect, and the state
  // it was seeded from is remembered so this runs once per answer. An effect runs
  // after the frame has been handed to the browser, and on that frame the answer
  // has arrived while the form is still empty, so every field differs, the panel
  // believes it holds unsaved edits, and it offers to save a change nobody made.
  // Adjusting the state here lets React re-run this component before it commits
  // anything, so that button is never painted. The same holds when the answer is
  // fetched again after a save.
  const [seededFrom, setSeededFrom] = useState<EInvoiceSettingsPayload | null>(null);
  if (data && data !== seededFrom) {
    setSeededFrom(data);
    setForm(ALL_FIELDS.reduce((acc, f) => ({ ...acc, [f]: data[f] ?? '' }), {} as FormState));
  }

  const save = useMutation({
    mutationFn: (body: FormState) => apiPut('/api/v1/finance/einvoice-settings', body),
    onSuccess: () => {
      setFieldError(null);
      queryClient.invalidateQueries({ queryKey: ['finance', 'einvoice-settings'] });
      // Every open compliance check was decided against the old configuration.
      queryClient.invalidateQueries({ queryKey: ['finance', 'einvoice-dry-run'] });
      addToast({ type: 'success', title: t('settings.einvoice.saved') });
    },
    onError: (err) => setFieldError(getErrorMessage(err)),
  });

  const setField = useCallback((name: FieldName, value: string) => {
    setForm((prev) => ({ ...prev, [name]: value }));
  }, []);

  const dirty = useMemo(
    () => (data ? ALL_FIELDS.some((f) => (data[f] ?? '') !== form[f]) : false),
    [data, form],
  );

  const missing = data?.missing ?? [];

  // Which instrument the payment fields name follows the seller's country, not
  // the reader's language. A German-speaking user filing under US law is paid
  // by routing and account number, and showing them "IBAN" in German names a
  // field their bank does not have. The country is read from the form rather
  // than from the saved row so the labels change as soon as it is typed, which
  // is the same moment the server starts judging the account against it.
  const paidByIban = useMemo(() => {
    const known = data?.iban_countries;
    const country = form.seller_country_code.trim().toUpperCase();
    // Before the list arrives, and for a country outside it, the neutral label
    // is the safe one: it is right everywhere and merely less specific in the
    // IBAN area, whereas the wrong specific label sends somebody to the wrong
    // field of their banking app.
    if (!known || !country) return false;
    return known.includes(country);
  }, [data?.iban_countries, form.seller_country_code]);

  // The two fields whose label is not a constant, mapped to the key that names
  // what the seller is actually asked for.
  const LABEL_KEY: Partial<Record<FieldName, string>> = {
    payee_iban: paidByIban ? 'settings.einvoice.field.payee_iban' : 'settings.einvoice.field.payee_account_number',
    payee_bic: paidByIban ? 'settings.einvoice.field.payee_bic' : 'settings.einvoice.field.payee_bank_code',
  };

  // The worked examples are IBAN-area notation. Outside it they would be an
  // instruction to type the wrong thing, and there is no one national format to
  // put in their place, so the field is simply left blank.
  const exampleFor = (name: FieldName): string => {
    if (!paidByIban && (name === 'payee_iban' || name === 'payee_bic')) return '';
    return EXAMPLES[name] ?? '';
  };

  const renderField = (name: FieldName) => (
    <div key={name}>
      <label htmlFor={name} className="block text-sm font-medium text-content-primary mb-1.5">
        {t(LABEL_KEY[name] ?? `settings.einvoice.field.${name}`)}
      </label>
      <input
        id={name}
        type="text"
        value={form[name]}
        onChange={(e) => setField(name, e.target.value)}
        // The example is the business term's own notation, not prose, so it is
        // the same in every language and does not belong in the locale files.
        placeholder={exampleFor(name)}
        className={
          'w-full rounded-md border border-border-light bg-surface-secondary px-2 py-1.5 text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-1 focus:ring-oe-blue/40' +
          (CODE_FIELDS.has(name) ? ' font-mono' : '')
        }
      />
    </div>
  );

  if (isLoading) {
    return (
      <Card>
        <CardContent>
          <p className="text-sm text-content-tertiary">{t('settings.einvoice.loading')}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-content-tertiary" aria-hidden="true" />
              {t('settings.einvoice.title')}
            </span>
          }
          subtitle={t('settings.einvoice.subtitle')}
        />
        <CardContent className="space-y-4">
          {missing.length > 0 && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-md border border-semantic-warning/40 bg-semantic-warning/10 px-3 py-2"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-warning" aria-hidden="true" />
              <div className="text-xs text-content-secondary">
                <p className="font-medium text-content-primary">{t('settings.einvoice.incomplete')}</p>
                <p>
                  {fmtList(missing.map((f) => t(`settings.einvoice.field.${f}`)))}
                </p>
              </div>
            </div>
          )}
          {missing.length === 0 && data && (
            <div
              role="status"
              className="flex items-center gap-2 rounded-md border border-semantic-success/40 bg-semantic-success/10 px-3 py-2"
            >
              <Check className="h-4 w-4 shrink-0 text-semantic-success" aria-hidden="true" />
              <p className="text-xs text-content-secondary">{t('settings.einvoice.ready')}</p>
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            {SELLER_FIELDS.filter((f) => !HIDDEN_FIELDS.has(f)).map(renderField)}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Landmark className="h-4 w-4 text-content-tertiary" aria-hidden="true" />
              {t('settings.einvoice.paymentTitle')}
            </span>
          }
          subtitle={t(paidByIban ? 'settings.einvoice.paymentSubtitle' : 'settings.einvoice.paymentSubtitleDomestic')}
        />
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">{PAYMENT_FIELDS.map(renderField)}</div>
        </CardContent>
      </Card>

      {fieldError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-semantic-error/40 bg-semantic-error/10 px-3 py-2"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-error" aria-hidden="true" />
          <p className="text-xs text-content-secondary">{fieldError}</p>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={() => save.mutate(form)} disabled={!dirty || save.isPending}>
          {save.isPending ? t('settings.einvoice.saving') : t('settings.einvoice.save')}
        </Button>
        <p className="text-xs text-content-tertiary">{t('settings.einvoice.scopeHint')}</p>
      </div>
    </div>
  );
}
