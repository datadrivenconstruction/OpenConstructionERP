// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * EInvoiceModal — issue one invoice as an EN 16931 electronic invoice.
 *
 * The exporter has been able to write CII (ZUGFeRD 2.1, Factur-X 1.0,
 * XRechnung 3.0) and UBL (Peppol BIS Billing 3.0 and the national CIUS
 * flavours) for some time, but no screen reached it, so the capability was
 * only usable by hand against the API.
 *
 * The screen is built around the dry run rather than the download. A receiver
 * rejects an e-invoice by quoting a rule identifier back at the sender, so the
 * panel shows those identifiers verbatim: BR-61, BR-DE-15, PEPPOL-EN16931-R003
 * are what a tax portal or a Peppol access point will say, and a user who can
 * read them here can search for them anywhere. Severity is kept apart from the
 * message because the two answer different questions: a fatal violation stops
 * the export, an advisory does not, and collapsing them into one list would
 * make a perfectly issuable invoice look broken.
 *
 * One profile is not EN 16931 at all. UBL-TR is the Turkish e-Fatura, and it
 * needs things no other profile asks for: a scenario, a document number the
 * integrator usually assigns, an exchange rate on a foreign currency invoice.
 * Those fields appear for that profile only, are saved to the invoice, and the
 * same check then reads them back. The file it produces is unsigned, and the
 * screen says so where the download is.
 *
 * Self-contained; FinancePage only opens it.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Download, Info, ShieldAlert } from 'lucide-react';
import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui';
import { downloadWithAuth, getErrorMessage } from '@/shared/lib/api';
import {
  dryRunEInvoice,
  getInvoiceMetadata,
  getTrEInvoiceFields,
  listEInvoiceProfiles,
  patchInvoiceMetadata,
  putTrEInvoiceFields,
} from './api';
import type { EInvoiceProfile, EInvoiceViolation, InvoiceMetadataRead, TrEInvoiceFieldsRead } from './api';
import { EInvoiceTrSection } from './EInvoiceTrSection';
import type { EInvoiceReturnCandidate } from './EInvoiceTrSection';
import {
  EMPTY_TR_FORM,
  EMPTY_TR_PARTIES,
  TR_HOME_CURRENCY,
  focusTargetFor,
  metadataWithTrParties,
  missingPlaceholders,
  ruleKey,
  sameForm,
  trFieldId,
  trFieldsFromForm,
  trFormFromFields,
  trPartiesFromMetadata,
  validateTrForm,
} from './einvoiceTr';
import type { TrFieldName, TrFocusTarget, TrFormState, TrPartyFieldName, TrPartyFormState } from './einvoiceTr';

export interface EInvoiceModalProps {
  open: boolean;
  onClose: () => void;
  invoiceId: string;
  /** Shown in the title so the user knows which invoice is being issued. */
  invoiceNumber: string;
  /**
   * Other invoices of the same project, offered as the original of a return
   * (UBL-TR only). The caller passes what it already has loaded.
   */
  returnCandidates?: EInvoiceReturnCandidate[];
}

/** The profile checked when the registry names none for the seller's country. */
const FALLBACK_PROFILE = 'xrechnung';

/** The registry syntax of the Turkish e-Fatura, which is not an EN 16931 one. */
const SYNTAX_UBL_TR = 'ubl_tr';

const NO_CANDIDATES: EInvoiceReturnCandidate[] = [];

const selectCls =
  'h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm ' +
  'text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue';

export function EInvoiceModal({
  open,
  onClose,
  invoiceId,
  invoiceNumber,
  returnCandidates = NO_CANDIDATES,
}: EInvoiceModalProps) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();

  // What the user picked. Until they pick, the profile is whatever the
  // registry offers first for this seller, so it is derived below rather than
  // copied into state, where it would go stale the moment the registry answers.
  const [chosen, setChosen] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<'xml' | 'pdf' | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // The registry is the single source of truth for which flavours exist, so
  // the picker asks for it instead of carrying a copy that goes stale the
  // next time a country is added.
  const profilesQuery = useQuery({
    queryKey: ['finance', 'einvoice-profiles'],
    queryFn: listEInvoiceProfiles,
    enabled: open,
    staleTime: 60 * 60 * 1000,
  });

  // A seller whose country has a national format outside EN 16931 is offered
  // that format first: the registry names it, and it is moved to the head of
  // the list and preselected. Everything else keeps the registry's order.
  const profiles = useMemo((): EInvoiceProfile[] => {
    const listed = profilesQuery.data?.profiles ?? [];
    const first = profilesQuery.data?.default;
    const offered = first ? listed.find((p) => p.key === first) : undefined;
    return offered ? [offered, ...listed.filter((p) => p !== offered)] : listed;
  }, [profilesQuery.data]);
  const offeredFirst = profilesQuery.data?.default;
  const profile =
    chosen ?? (offeredFirst && profiles.some((p) => p.key === offeredFirst) ? offeredFirst : FALLBACK_PROFILE);

  const dryRunQuery = useQuery({
    queryKey: ['finance', 'einvoice-dry-run', invoiceId, profile],
    queryFn: () => dryRunEInvoice(invoiceId, profile),
    // Held until the registry has answered, so a Turkish seller's invoice is
    // not first checked against a German profile it will never be issued in.
    enabled: open && !profilesQuery.isPending,
  });

  // A new check is about to answer; do not let the previous failure linger.
  useEffect(() => setDownloadError(null), [profile]);

  const dryRun = dryRunQuery.data;

  const { blocking, advisory, informative } = useMemo(() => {
    const all = dryRun?.violations ?? [];
    return {
      blocking: all.filter((v) => v.severity === 'fatal'),
      advisory: all.filter((v) => v.severity !== 'fatal' && v.severity !== 'info'),
      informative: all.filter((v) => v.severity === 'info'),
    };
  }, [dryRun]);

  // Only a CII profile has a hybrid form. Read it off the registry entry
  // rather than listing the CII profile keys here, so a country added to the
  // registry gets the right buttons without a second edit in this file.
  const activeProfile = profiles.find((p) => p.key === profile);
  const hybridAvailable = activeProfile?.syntax === 'cii';
  const isTr = activeProfile?.syntax === SYNTAX_UBL_TR;

  // UBL-TR: the fields of this invoice, and the party details it states for
  // itself above the e-invoice settings and the linked contact.
  const [form, setForm] = useState<TrFormState>(EMPTY_TR_FORM);
  const [parties, setParties] = useState<TrPartyFormState>(EMPTY_TR_PARTIES);
  const [saveError, setSaveError] = useState<string | null>(null);

  const trQuery = useQuery({
    queryKey: ['finance', 'einvoice-tr', invoiceId],
    queryFn: () => getTrEInvoiceFields(invoiceId),
    enabled: open && isTr,
  });
  const metadataQuery = useQuery({
    queryKey: ['finance', 'einvoice-tr-parties', invoiceId],
    queryFn: () => getInvoiceMetadata(invoiceId),
    enabled: open && isTr,
  });

  // Seeded while rendering and remembered, for the reason EInvoiceSettings
  // gives: an effect would paint one frame in which the answer has arrived,
  // the form is still empty, and the screen believes it holds unsaved edits.
  const [seededFields, setSeededFields] = useState<TrEInvoiceFieldsRead | null>(null);
  if (trQuery.data && trQuery.data !== seededFields) {
    setSeededFields(trQuery.data);
    setForm(trFormFromFields(trQuery.data.fields));
  }
  const [seededMetadata, setSeededMetadata] = useState<InvoiceMetadataRead | null>(null);
  if (metadataQuery.data && metadataQuery.data !== seededMetadata) {
    setSeededMetadata(metadataQuery.data);
    setParties(trPartiesFromMetadata(metadataQuery.data.metadata));
  }

  const fieldErrors = useMemo(() => validateTrForm(form), [form]);
  const hasFieldErrors = Object.keys(fieldErrors).length > 0;

  const fieldsDirty = useMemo(
    () => (seededFields ? !sameForm(form, trFormFromFields(seededFields.fields)) : false),
    [form, seededFields],
  );
  const partiesDirty = useMemo(
    () => (seededMetadata ? !sameForm(parties, trPartiesFromMetadata(seededMetadata.metadata)) : false),
    [parties, seededMetadata],
  );
  // A stored block the server could not read is rewritten by the next save
  // even when nothing was typed: that is the fix the report asks for.
  const fieldsUnreadable = Boolean(seededFields?.unreadable);
  const unsaved = isTr && (fieldsDirty || partiesDirty);

  const saveAndCheck = useMutation({
    mutationFn: async () => {
      if (seededFields && (fieldsDirty || fieldsUnreadable)) {
        await putTrEInvoiceFields(invoiceId, trFieldsFromForm(form, seededFields.fields));
      }
      if (partiesDirty) {
        // The metadata column is replaced whole, so it is read again right
        // before the write instead of being rebuilt from what this screen saw
        // when it opened.
        const fresh = await getInvoiceMetadata(invoiceId);
        await patchInvoiceMetadata(invoiceId, metadataWithTrParties(fresh.metadata, parties));
      }
    },
    onSuccess: () => {
      setSaveError(null);
      queryClient.invalidateQueries({ queryKey: ['finance', 'einvoice-tr', invoiceId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'einvoice-tr-parties', invoiceId] });
      queryClient.invalidateQueries({ queryKey: ['finance', 'einvoice-dry-run', invoiceId] });
      // The invoice register holds each invoice's metadata, and the edit form
      // sends that object back whole. Left stale, the next edit of this
      // invoice would write the old metadata over what was just saved here.
      queryClient.invalidateQueries({ queryKey: ['finance-invoices'] });
    },
    onError: (err: unknown) => setSaveError(getErrorMessage(err)),
  });

  const setField = (name: TrFieldName, value: string) => setForm((prev) => ({ ...prev, [name]: value }));
  const setParty = (name: TrPartyFieldName, value: string) => setParties((prev) => ({ ...prev, [name]: value }));

  // The file is written from what is stored and judged by the last report. A
  // report still on its way, or fields typed and not saved, mean the verdict
  // on screen is about a different document than the one a click would fetch.
  const canExport = Boolean(dryRun?.valid) && !dryRunQuery.isFetching && !unsaved && !saveAndCheck.isPending;

  // Said in words beside the button, because a greyed button alone does not
  // tell an accountant whether to wait, to save or to go and fix something.
  const blockedReason = !isTr
    ? null
    : unsaved
      ? t('einvoice.tr.blocked_unsaved')
      : blocking.length > 0
        ? t('einvoice.tr.blocked_errors')
        : null;

  const trDocument = isTr ? (dryRun?.document ?? null) : null;
  const taxSource = isTr ? dryRun?.tax_source : undefined;
  const trCurrency = (trDocument?.currency || taxSource?.currency_code || '').toUpperCase();
  const foreignCurrency = trCurrency && trCurrency !== TR_HOME_CURRENCY ? trCurrency : '';

  // Amounts are printed as the server wrote them. Nothing here adds, rounds
  // or reformats a figure: the report is what an accountant checks against
  // the certificate, and a second arithmetic on this side could disagree.
  const money = (amount: string) =>
    `${amount} ${trCurrency === TR_HOME_CURRENCY ? t('einvoice.tr.currency_tl') : trCurrency}`;

  const jumpTo = (target: TrFocusTarget) => {
    const el = document.getElementById(trFieldId(target));
    if (!el) return;
    if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'center' });
    el.focus();
  };

  // The jump is offered only when its field is on screen: the exchange rate,
  // for one, is not drawn on a lira invoice.
  const jumpTargetFor = (v: EInvoiceViolation): TrFocusTarget | null => {
    if (!isTr) return null;
    const target = focusTargetFor(v);
    if (target === 'exchange_rate' && !foreignCurrency) return null;
    return target;
  };

  // A finding's identifier (BR-DE-15) is quoted verbatim - that is the
  // argument of the panel - but the sentence beside it is guidance and must
  // speak the UI language. One key per rule id; a rule the locale has no key
  // for keeps the engine's English sentence, so nothing ever goes blank.
  // {{label}} feeds the one message that names the selected profile, and the
  // engine's own params carry the rest: which line, which amount, which code.
  // A param naming an enumerated value (party) is itself translated, because
  // printing the engine's "seller" into a German sentence is the very defect
  // the catalogue exists to remove.
  //
  // Two things follow from a rule being raised from more than one place. Some
  // ids carry two sentences, and the values say which one was meant. And a
  // sentence can name a value this particular finding does not have; printing
  // it with a hole would say less than the engine's own sentence, so that one
  // is shown instead.
  const ruleText = (v: EInvoiceViolation): string => {
    const params = { ...(v.params ?? {}) };
    if (params.party) params.party = t(`einvoice.party.${params.party}`, { defaultValue: params.party });
    if (params.role) params.role = t(`einvoice.tr.role.${params.role}`, { defaultValue: params.role });
    const key = ruleKey(v);
    const values = { ...params, label: activeProfile?.label ?? profile };
    const template = t(key, { defaultValue: '', skipInterpolation: true });
    if (template && missingPlaceholders(template, values).length > 0) return v.message;
    return t(key, { ...values, defaultValue: v.message });
  };

  const jumpButton = (v: EInvoiceViolation) => {
    const target = jumpTargetFor(v);
    if (!target) return null;
    return (
      <button
        type="button"
        onClick={() => jumpTo(target)}
        className="text-xs font-medium text-oe-blue underline-offset-2 hover:underline"
      >
        {t('einvoice.tr.go_to_field')}
      </button>
    );
  };

  // The standard's name is a proper noun and stays as the registry writes it,
  // but four entries append a country in English (Netherlands, Norway,
  // Australia / New Zealand, Singapore), and one region reads "international".
  // Those are ordinary words sitting under a translated heading, so they go
  // through the catalogue while the proper noun rides along inside the value.
  const profileName = (p: EInvoiceProfile) => t(`einvoice.profile.${p.key}`, { defaultValue: p.label });

  // Every other region is an ISO country code, correct unchanged in every
  // language, so the fallback here is the right answer rather than a gap: only
  // a region that is a word needs an entry at all. The key is normalised
  // because a region can name two countries ("DE/FR").
  const regionName = (p: EInvoiceProfile) =>
    t(`einvoice.region.${p.region.replace(/[^A-Za-z0-9]+/g, '_')}`, { defaultValue: p.region });

  async function download(embed: boolean) {
    const kind = embed ? 'pdf' : 'xml';
    setDownloading(kind);
    setDownloadError(null);
    try {
      // The hybrid PDF's readable page follows the UI language; the XML (and
      // the XML inside the hybrid) is locale-independent by the standard.
      const localeParam = embed ? `&locale=${encodeURIComponent(i18n.language)}` : '';
      await downloadWithAuth(
        `/api/v1/finance/invoices/${encodeURIComponent(invoiceId)}/einvoice?format=${encodeURIComponent(profile)}&embed=${embed ? 'true' : 'false'}${localeParam}`,
        // The server names the file; this is only what is used when a proxy
        // strips the header that says so.
        `einvoice_${invoiceNumber}_${profile}.${kind}`,
      );
    } catch (e: unknown) {
      setDownloadError(getErrorMessage(e));
    } finally {
      setDownloading(null);
    }
  }

  if (!open) return null;

  return (
    <WideModal
      open={open}
      title={t('finance.einvoice.title', { number: invoiceNumber })}
      subtitle={t('finance.einvoice.subtitle')}
      onClose={onClose}
      busy={downloading !== null}
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {downloadError && (
            <span role="alert" className="mr-auto text-sm text-semantic-error">
              {downloadError}
            </span>
          )}
          {!downloadError && blockedReason && (
            <span id="einvoice-blocked-reason" className="mr-auto text-sm text-content-secondary">
              {blockedReason}
            </span>
          )}
          <Button variant="ghost" onClick={onClose}>
            {t('finance.einvoice.close')}
          </Button>
          {/* The hybrid PDF is a CII construct: the XML rides inside the PDF
              as a Factur-X attachment, and there is no such carrier defined
              for UBL. The server refuses it, so offering the button on a UBL
              profile would only hand the user an error they cannot act on. */}
          {hybridAvailable && (
            <Button
              variant="secondary"
              onClick={() => download(true)}
              disabled={!canExport}
              loading={downloading === 'pdf'}
            >
              <Download size={14} className="mr-1.5" />
              {t('finance.einvoice.downloadPdf')}
            </Button>
          )}
          <Button
            variant="primary"
            onClick={() => download(false)}
            disabled={!canExport}
            loading={downloading === 'xml'}
            aria-describedby={blockedReason ? 'einvoice-blocked-reason' : undefined}
          >
            <Download size={14} className="mr-1.5" />
            {isTr ? t('einvoice.tr.download') : t('finance.einvoice.downloadXml')}
          </Button>
        </div>
      }
    >
      <WideModalSection title={t('finance.einvoice.formatSection')}>
        <p className="mb-3 text-xs text-content-tertiary">{t('finance.einvoice.formatHint')}</p>
        <WideModalField label={t('finance.einvoice.profile')}>
          <select
            value={profile}
            onChange={(e) => setChosen(e.target.value)}
            className={selectCls}
            disabled={profilesQuery.isLoading}
            aria-label={t('finance.einvoice.profile')}
          >
            {profiles.map((p) => (
              <option key={p.key} value={p.key}>
                {`${profileName(p)} - ${regionName(p)} - ${p.syntax.toUpperCase()}`}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      {isTr && (
        <>
          {seededFields?.unreadable && (
            <WideModalSection>
              <p role="alert" className="text-sm text-semantic-error">
                {t('einvoice.tr.unreadable')}
              </p>
            </WideModalSection>
          )}
          <EInvoiceTrSection
            form={form}
            parties={parties}
            errors={fieldErrors}
            onField={setField}
            onParty={setParty}
            foreignCurrency={foreignCurrency}
            ettn={seededFields?.uuid ?? trDocument?.uuid ?? ''}
            returnCandidates={returnCandidates}
            disabled={trQuery.isPending || saveAndCheck.isPending}
          />
          <WideModalSection>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                onClick={() => saveAndCheck.mutate()}
                disabled={hasFieldErrors || trQuery.isPending}
                loading={saveAndCheck.isPending}
              >
                {unsaved || fieldsUnreadable ? t('einvoice.tr.save_and_check') : t('einvoice.tr.check')}
              </Button>
              <p className="text-xs text-content-tertiary">{t('einvoice.tr.check_hint')}</p>
            </div>
            {saveError && (
              <p role="alert" className="mt-2 text-sm text-semantic-error">
                {saveError}
              </p>
            )}
          </WideModalSection>
        </>
      )}

      <WideModalSection title={t('finance.einvoice.checkSection')}>
        {dryRunQuery.isLoading && (
          <p className="text-sm text-content-tertiary">{t('finance.einvoice.checking')}</p>
        )}

        {dryRunQuery.isError && (
          <p className="text-sm text-semantic-error">{getErrorMessage(dryRunQuery.error)}</p>
        )}

        {dryRun && canExport && blocking.length === 0 && (
          <div className="flex items-start gap-2 rounded-lg border border-semantic-success bg-semantic-success-bg p-3">
            <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-semantic-success" />
            <p className="text-sm text-content-primary">{t('finance.einvoice.compliant')}</p>
          </div>
        )}

        {blocking.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <AlertTriangle size={16} className="shrink-0 text-semantic-error" />
              {/* The count rides in its own badge rather than inside the
                  heading: a number interpolated into a countable noun needs a
                  plural form per CLDR category of every language, and the ones
                  that lack it fall through to English. */}
              <h4 className="text-sm font-semibold text-content-primary">
                {t('finance.einvoice.blockingTitle')}
              </h4>
              <span className="rounded-full bg-semantic-error px-2 py-0.5 text-xs font-semibold text-content-inverse">
                {blocking.length}
              </span>
            </div>
            <p className="text-xs text-content-tertiary">{t('finance.einvoice.blockingHint')}</p>
            <ul className="space-y-2">
              {blocking.map((v) => (
                <li
                  key={`${v.rule_id}-${v.message}`}
                  className="flex flex-wrap items-baseline gap-2 rounded-lg border border-semantic-error bg-semantic-error-bg p-3"
                >
                  <code className="font-mono text-xs font-semibold text-semantic-error">{v.rule_id}</code>
                  <span className="text-sm text-content-primary">{ruleText(v)}</span>
                  {v.term && (
                    <code className="font-mono text-[11px] text-content-tertiary">{v.term}</code>
                  )}
                  {jumpButton(v)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {advisory.length > 0 && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <Info size={16} className="shrink-0 text-semantic-warning" />
              <h4 className="text-sm font-semibold text-content-primary">
                {t('finance.einvoice.advisoryTitle')}
              </h4>
              <span className="rounded-full bg-semantic-warning px-2 py-0.5 text-xs font-semibold text-content-inverse">
                {advisory.length}
              </span>
            </div>
            <p className="text-xs text-content-tertiary">{t('finance.einvoice.advisoryHint')}</p>
            <ul className="space-y-2">
              {advisory.map((v) => (
                <li
                  key={`${v.rule_id}-${v.message}`}
                  className="flex flex-wrap items-baseline gap-2 rounded-lg border border-border bg-surface-secondary p-3"
                >
                  <code className="font-mono text-xs font-semibold text-semantic-warning">{v.rule_id}</code>
                  <span className="text-sm text-content-primary">{ruleText(v)}</span>
                  {jumpButton(v)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* A third strength, which only the Turkish rules use: something the
            accountant should know that asks for nothing. Kept out of the
            advisory list so "recommended" keeps meaning there is something
            to do. */}
        {informative.length > 0 && (
          <div className="mt-3 space-y-2">
            <div className="flex items-center gap-2">
              <Info size={16} className="shrink-0 text-content-tertiary" />
              <h4 className="text-sm font-semibold text-content-primary">{t('einvoice.tr.info_title')}</h4>
              <span className="rounded-full bg-surface-secondary px-2 py-0.5 text-xs font-semibold text-content-secondary">
                {informative.length}
              </span>
            </div>
            <ul className="space-y-2">
              {informative.map((v) => (
                <li
                  key={`${v.rule_id}-${v.message}`}
                  className="flex flex-wrap items-baseline gap-2 rounded-lg border border-border bg-surface-secondary p-3"
                >
                  <code className="font-mono text-xs font-semibold text-content-secondary">{v.rule_id}</code>
                  <span className="text-sm text-content-primary">{ruleText(v)}</span>
                  {jumpButton(v)}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="mt-3 text-xs text-content-tertiary">
          {isTr ? t('einvoice.tr.settings_hint') : t('finance.einvoice.settingsHint')}
        </p>
      </WideModalSection>

      {isTr && trDocument && (
        <WideModalSection title={t('einvoice.tr.figures.title')}>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div className="flex justify-between gap-3">
              <dt className="text-content-secondary">{t('einvoice.tr.fields.profile_id')}</dt>
              <dd className="font-mono text-content-primary">
                {trDocument.profile_id || t('einvoice.tr.figures.unset')}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-content-secondary">{t('einvoice.tr.fields.invoice_type')}</dt>
              <dd className="font-mono text-content-primary">
                {trDocument.invoice_type}
                {trDocument.inferred.invoice_type && (
                  <span className="ml-2 font-sans text-xs text-content-tertiary">
                    {t('einvoice.tr.figures.inferred')}
                  </span>
                )}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-content-secondary">{t('einvoice.tr.figures.line_extension')}</dt>
              <dd className="font-mono text-content-primary">{money(trDocument.line_extension)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-content-secondary">{t('einvoice.tr.figures.tax_inclusive')}</dt>
              <dd className="font-mono text-content-primary">{money(trDocument.tax_inclusive)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-content-secondary">{t('einvoice.tr.figures.payable')}</dt>
              <dd className="font-mono font-semibold text-content-primary">{money(trDocument.payable)}</dd>
            </div>
            {taxSource?.net_amount && (
              <div className="flex justify-between gap-3">
                <dt className="text-content-secondary">{t('einvoice.tr.figures.taxed_amount')}</dt>
                <dd className="font-mono text-content-primary">{money(taxSource.net_amount)}</dd>
              </div>
            )}
            {taxSource?.vat_rate_pct && (
              <div className="flex justify-between gap-3">
                <dt className="text-content-secondary">{t('einvoice.tr.figures.vat_rate')}</dt>
                <dd className="font-mono text-content-primary">{`${taxSource.vat_rate_pct} %`}</dd>
              </div>
            )}
          </dl>
          {taxSource?.status && (
            <p className="mt-3 text-xs text-content-secondary">{t(`einvoice.tr.tax_source.${taxSource.status}`)}</p>
          )}
          {/* The VAT of an invoice raised from a payment certificate is the
              certificate's confirmed figure, not one computed from the lines
              here, and an accountant comparing the two documents needs to be
              told which of them is the source. */}
          {taxSource?.source_kind === 'progress_claim' && (
            <p className="mt-1 text-xs text-content-secondary">{t('einvoice.tr.figures.from_certificate')}</p>
          )}
        </WideModalSection>
      )}

      <WideModalSection title={t('finance.einvoice.downloadSection')}>
        {isTr ? (
          <div className="flex items-start gap-2 rounded-lg border border-semantic-warning bg-semantic-warning-bg p-3">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
            <p className="text-sm text-content-primary">{t('einvoice.tr.unsigned_notice')}</p>
          </div>
        ) : (
          <p className="text-xs text-content-tertiary">{t('finance.einvoice.downloadHint')}</p>
        )}
      </WideModalSection>
    </WideModal>
  );
}
