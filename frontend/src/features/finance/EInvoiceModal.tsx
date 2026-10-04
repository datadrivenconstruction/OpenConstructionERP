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
 * Self-contained; FinancePage only opens it.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Download, Info } from 'lucide-react';
import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui';
import { apiGet, downloadWithAuth, getErrorMessage } from '@/shared/lib/api';

export interface EInvoiceModalProps {
  open: boolean;
  onClose: () => void;
  invoiceId: string;
  /** Shown in the title so the user knows which invoice is being issued. */
  invoiceNumber: string;
}

/** One entry of the profile registry, as the backend publishes it. */
interface EInvoiceProfile {
  key: string;
  /** Standard name, a proper noun, so it is not translated. */
  label: string;
  syntax: string;
  region: string;
}

interface EInvoiceViolation {
  rule_id: string;
  severity: string;
  message: string;
  term: string | null;
  /** Values the engine's sentence interpolates, named as the catalogue uses them. */
  params?: Record<string, string>;
}

interface EInvoiceDryRun {
  format: string;
  valid: boolean;
  // The response also carries ``problems``, the fatal messages as bare strings.
  // It is not read here: those same findings arrive in ``violations`` with the
  // rule id and severity this panel is built around, and ``valid`` is already
  // defined as "no fatal finding", so declaring it would only invite a second
  // rendering of the same list without the identifiers.
  violations: EInvoiceViolation[];
}

const selectCls =
  'h-10 w-full appearance-none rounded-lg border border-border bg-surface-primary px-3 text-sm ' +
  'text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue';

export function EInvoiceModal({ open, onClose, invoiceId, invoiceNumber }: EInvoiceModalProps) {
  const { t, i18n } = useTranslation();

  const [profile, setProfile] = useState('xrechnung');
  const [downloading, setDownloading] = useState<'xml' | 'pdf' | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // The registry is the single source of truth for which flavours exist, so
  // the picker asks for it instead of carrying a copy that goes stale the
  // next time a country is added.
  const profilesQuery = useQuery({
    queryKey: ['finance', 'einvoice-profiles'],
    queryFn: () => apiGet<{ profiles: EInvoiceProfile[] }>('/api/v1/finance/einvoice-profiles'),
    enabled: open,
    staleTime: 60 * 60 * 1000,
  });

  const dryRunQuery = useQuery({
    queryKey: ['finance', 'einvoice-dry-run', invoiceId, profile],
    queryFn: () =>
      apiGet<EInvoiceDryRun>(
        `/api/v1/finance/invoices/${encodeURIComponent(invoiceId)}/einvoice?format=${encodeURIComponent(profile)}&dry_run=true`,
      ),
    enabled: open,
  });

  // A new check is about to answer; do not let the previous failure linger.
  useEffect(() => setDownloadError(null), [profile]);

  const profiles = profilesQuery.data?.profiles ?? [];
  const dryRun = dryRunQuery.data;

  const { blocking, advisory } = useMemo(() => {
    const all = dryRun?.violations ?? [];
    return {
      blocking: all.filter((v) => v.severity === 'fatal'),
      advisory: all.filter((v) => v.severity !== 'fatal'),
    };
  }, [dryRun]);

  const canExport = Boolean(dryRun?.valid);

  // Only a CII profile has a hybrid form. Read it off the registry entry
  // rather than listing the CII profile keys here, so a country added to the
  // registry gets the right buttons without a second edit in this file.
  const activeProfile = profiles.find((p) => p.key === profile);
  const hybridAvailable = activeProfile?.syntax === 'cii';

  // A finding's identifier (BR-DE-15) is quoted verbatim - that is the
  // argument of the panel - but the sentence beside it is guidance and must
  // speak the UI language. One key per rule id; a rule the locale has no key
  // for keeps the engine's English sentence, so nothing ever goes blank.
  // {{label}} feeds the one message that names the selected profile, and the
  // engine's own params carry the rest: which line, which amount, which code.
  // A param naming an enumerated value (party) is itself translated, because
  // printing the engine's "seller" into a German sentence is the very defect
  // the catalogue exists to remove.
  const ruleText = (v: EInvoiceViolation) => {
    const params = { ...(v.params ?? {}) };
    if (params.party) params.party = t(`einvoice.party.${params.party}`, { defaultValue: params.party });
    return t(`einvoice.rule.${v.rule_id}`, {
      ...params,
      defaultValue: v.message,
      label: activeProfile?.label ?? profile,
    });
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
            <span className="mr-auto text-sm text-semantic-error">{downloadError}</span>
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
          >
            <Download size={14} className="mr-1.5" />
            {t('finance.einvoice.downloadXml')}
          </Button>
        </div>
      }
    >
      <WideModalSection title={t('finance.einvoice.formatSection')}>
        <p className="mb-3 text-xs text-content-tertiary">{t('finance.einvoice.formatHint')}</p>
        <WideModalField label={t('finance.einvoice.profile')}>
          <select
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
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
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="mt-3 text-xs text-content-tertiary">{t('finance.einvoice.settingsHint')}</p>
      </WideModalSection>

      <WideModalSection title={t('finance.einvoice.downloadSection')}>
        <p className="text-xs text-content-tertiary">{t('finance.einvoice.downloadHint')}</p>
      </WideModalSection>
    </WideModal>
  );
}
