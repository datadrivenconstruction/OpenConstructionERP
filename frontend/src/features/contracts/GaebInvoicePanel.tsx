// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The GAEB X89 invoice (Rechnung) of one progress claim.
 *
 * Collapsed until opened, so a claim page that never needs GAEB does not
 * ask for it. Opened, it shows the figures the file will carry, where the
 * VAT rate came from, both parties, and every mandatory field that is still
 * unknown. The download is refused by the server while anything is missing,
 * and the button says so before it is pressed.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, ChevronDown, ChevronRight, Download, FileCode2 } from 'lucide-react';
import { Button, Card, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import {
  downloadClaimInvoice,
  previewClaimInvoice,
  type InvoiceParty,
} from '@/features/boq/gaebSiteExchangeApi';

function vatSourceLabel(t: TFunction, source: string): string {
  switch (source) {
    case 'request':
      return t('contracts.gaeb_invoice.vat_source_request', { defaultValue: 'rate entered here' });
    case 'boq_tax_markup':
      return t('contracts.gaeb_invoice.vat_source_boq', { defaultValue: 'tax markup of the bill' });
    case 'project_default':
      return t('contracts.gaeb_invoice.vat_source_project', { defaultValue: 'project default VAT rate' });
    case 'country_standard':
      return t('contracts.gaeb_invoice.vat_source_country', { defaultValue: 'standard rate of the country' });
    default:
      return t('contracts.gaeb_invoice.vat_source_none', { defaultValue: 'no rate known, 0 % used' });
  }
}

function missingLabel(t: TFunction, field: string): string {
  const [role, attr] = field.includes('.') ? field.split('.', 2) : ['', field];
  const who =
    role === 'creator'
      ? t('contracts.gaeb_invoice.creator', { defaultValue: 'Invoicing party' })
      : role === 'recipient'
        ? t('contracts.gaeb_invoice.recipient', { defaultValue: 'Invoice recipient' })
        : '';
  let what: string;
  switch (attr) {
    case 'name':
      what = t('contracts.gaeb_invoice.field_name', { defaultValue: 'name' });
      break;
    case 'street':
      what = t('contracts.gaeb_invoice.field_street', { defaultValue: 'street' });
      break;
    case 'postcode':
      what = t('contracts.gaeb_invoice.field_postcode', { defaultValue: 'postcode' });
      break;
    case 'city':
      what = t('contracts.gaeb_invoice.field_city', { defaultValue: 'city' });
      break;
    case 'tax_no':
      what = t('contracts.gaeb_invoice.field_tax_no', { defaultValue: 'tax number or VAT ID' });
      break;
    case 'invoice_no':
      what = t('contracts.gaeb_invoice.field_invoice_no', { defaultValue: 'claim number' });
      break;
    case 'invoice_date':
      what = t('contracts.gaeb_invoice.field_invoice_date', { defaultValue: 'application date' });
      break;
    case 'period_start':
      what = t('contracts.gaeb_invoice.field_period_start', { defaultValue: 'period start' });
      break;
    case 'period_end':
      what = t('contracts.gaeb_invoice.field_period_end', { defaultValue: 'period end' });
      break;
    case 'lines':
      what = t('contracts.gaeb_invoice.field_lines', { defaultValue: 'claim lines with a value this period' });
      break;
    default:
      what = attr ?? field;
  }
  return who ? t('contracts.gaeb_invoice.missing_field', { defaultValue: '{{who}}: {{what}}', who, what }) : what;
}

function differenceReason(t: TFunction, reason: string | undefined): string {
  switch (reason) {
    case 'stored_materials':
      return t('contracts.gaeb_invoice.reason_stored_materials', {
        defaultValue: 'The claim includes materials stored on site, which an X89 does not bill.',
      });
    case 'claim_gross_differs_from_lines':
      return t('contracts.gaeb_invoice.reason_gross_differs', {
        defaultValue: 'The claim gross is not the sum of its lines.',
      });
    case 'certified_to_date':
      return t('contracts.gaeb_invoice.reason_certified_to_date', {
        defaultValue:
          'The claim works its net due out from everything certified to date, including money no schedule line carries.',
      });
    default:
      return t('contracts.gaeb_invoice.reason_other', {
        defaultValue: 'The claim figures were changed by hand or are out of date. Recalculate the claim.',
      });
  }
}

function warningLabel(t: TFunction, code: string, detail: string, reason?: string): string {
  switch (code) {
    case 'outstanding_differs_from_net_due':
      return t('contracts.gaeb_invoice.warn_outstanding_differs', {
        defaultValue: 'The invoice does not ask for the net due of the claim. {{reason}}',
        reason: differenceReason(t, reason),
      });
    case 'subcontract_reverse_charge_de':
      return t('contracts.gaeb_invoice.warn_reverse_charge_de', {
        defaultValue:
          "The invoice is issued in the subcontractor's name. Check whether reverse charge (section 13b UStG) applies before it is sent; if it does, no VAT may be stated.",
      });
    case 'claim_gross_differs_from_lines':
      return t('contracts.gaeb_invoice.warn_gross_differs', {
        defaultValue: 'The claim gross is not the sum of its lines. The invoice uses the lines.',
      });
    case 'no_vat_rate':
      return t('contracts.gaeb_invoice.warn_no_vat', {
        defaultValue: 'No VAT rate is known for this claim. Enter one above.',
      });
    case 'several_tax_markups':
      return t('contracts.gaeb_invoice.warn_several_tax', {
        defaultValue: 'The bill has several tax markups. Their rates were added into one VAT rate.',
      });
    case 'fixed_tax_markup_ignored':
      return t('contracts.gaeb_invoice.warn_fixed_tax', {
        defaultValue: 'A fixed-amount tax markup of the bill has no rate and was not used.',
      });
    default:
      return detail;
  }
}

function remapReason(t: TFunction, reason: string): string {
  switch (reason) {
    case 'duplicate_ordinal':
      return t('contracts.gaeb_invoice.remap_duplicate', {
        defaultValue: 'another line bills the same OZ at another price or unit',
      });
    case 'ordinal_not_representable':
      return t('contracts.gaeb_invoice.remap_not_representable', {
        defaultValue: 'the OZ has characters GAEB cannot write',
      });
    case 'ordinal_depth_mismatch':
      return t('contracts.gaeb_invoice.remap_depth', {
        defaultValue: 'the OZ has another number of levels than the rest of the bill',
      });
    case 'ordinal_too_deep':
      return t('contracts.gaeb_invoice.remap_too_deep', { defaultValue: 'the OZ has more levels than GAEB allows' });
    case 'empty_ordinal':
      return t('contracts.gaeb_invoice.remap_empty', { defaultValue: 'the line has no OZ' });
    default:
      return reason;
  }
}

function hasAmount(value: string | undefined): boolean {
  return value !== undefined && value !== '' && Number(value) !== 0;
}

function partyText(party: InvoiceParty): string {
  const place = [party.postcode, party.city].filter(Boolean).join(' ');
  return fmtList([party.name, party.street, place, party.country]) || '-';
}

export function GaebInvoicePanel({ claimId, claimNumber }: { claimId: string; claimNumber: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [vatRate, setVatRate] = useState('');
  const [downloading, setDownloading] = useState(false);

  const previewQ = useQuery({
    queryKey: ['claim-gaeb-x89-preview', claimId, vatRate.trim()],
    queryFn: () => previewClaimInvoice(claimId, vatRate),
    enabled: open && Boolean(claimId),
  });
  const preview = previewQ.data;
  const missing = preview?.missing ?? [];
  const remapped = preview?.remapped ?? [];

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await downloadClaimInvoice(claimId, claimNumber || 'claim', vatRate);
    } catch (err) {
      addToast({
        type: 'error',
        title: t('contracts.gaeb_invoice.download_failed', { defaultValue: 'X89 export failed' }),
        message: getErrorMessage(err),
      });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <Card padding="sm" data-testid="gaeb-invoice-panel">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <FileCode2 size={16} className="text-oe-blue" />
        <h2 className="text-sm font-semibold text-content-primary">
          {t('contracts.gaeb_invoice.title', { defaultValue: 'GAEB X89 invoice' })}
        </h2>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          <p className="text-xs text-content-secondary leading-relaxed">
            {t('contracts.gaeb_invoice.intro', {
              defaultValue:
                'Writes this claim as a GAEB DA XML 3.3 X89 invoice: the quantities and values of this period per OZ, VAT on the net, and retention as a counter claim.',
            })}
          </p>

          <label className="flex items-center gap-2 text-xs text-content-secondary">
            {t('contracts.gaeb_invoice.vat_override', { defaultValue: 'VAT rate %' })}
            <input
              type="text"
              inputMode="decimal"
              value={vatRate}
              onChange={(e) => setVatRate(e.target.value)}
              placeholder={preview?.figures.vat_rate ?? ''}
              className="w-20 rounded border border-border-light bg-surface-primary px-2 py-1 text-xs"
            />
          </label>

          {previewQ.isLoading && <SkeletonTable rows={4} columns={2} />}
          {previewQ.isError && <RecoveryCard error={previewQ.error} onRetry={() => void previewQ.refetch()} />}

          {preview && (
            <>
              <dl className="divide-y divide-border-light rounded-lg border border-border-light text-xs">
                <div className="flex justify-between px-3 py-1.5">
                  <dt className="text-content-secondary">
                    {t('contracts.gaeb_invoice.net', { defaultValue: 'Net this period' })}
                  </dt>
                  <dd>
                    <MoneyDisplay amount={preview.figures.net} currency={preview.currency} />
                  </dd>
                </div>
                <div className="flex justify-between px-3 py-1.5">
                  <dt className="text-content-secondary">
                    {t('contracts.gaeb_invoice.vat', {
                      defaultValue: 'VAT {{rate}} % ({{source}})',
                      rate: preview.figures.vat_rate,
                      source: vatSourceLabel(t, preview.vat_source),
                    })}
                  </dt>
                  <dd>
                    <MoneyDisplay amount={preview.figures.vat_amount} currency={preview.currency} />
                  </dd>
                </div>
                <div className="flex justify-between px-3 py-1.5 font-semibold">
                  <dt>{t('contracts.gaeb_invoice.gross', { defaultValue: 'Gross' })}</dt>
                  <dd>
                    <MoneyDisplay amount={preview.figures.gross} currency={preview.currency} />
                  </dd>
                </div>
                <div className="flex justify-between px-3 py-1.5">
                  <dt className="text-content-secondary">
                    {t('contracts.gaeb_invoice.retention', { defaultValue: 'Retention (counter claim)' })}
                  </dt>
                  <dd>
                    <MoneyDisplay amount={preview.figures.retention} currency={preview.currency} />
                  </dd>
                </div>
                {hasAmount(preview.figures.release) && (
                  <div className="flex justify-between px-3 py-1.5">
                    <dt className="text-content-secondary">
                      {t('contracts.gaeb_invoice.release', { defaultValue: 'Retention released on this claim' })}
                    </dt>
                    <dd>
                      <MoneyDisplay amount={preview.figures.release ?? '0'} currency={preview.currency} />
                    </dd>
                  </div>
                )}
                <div className="flex justify-between px-3 py-1.5">
                  <dt className="text-content-secondary">
                    {t('contracts.gaeb_invoice.payable', { defaultValue: 'Outstanding amount' })}
                  </dt>
                  <dd>
                    <MoneyDisplay amount={preview.figures.payable} currency={preview.currency} />
                  </dd>
                </div>
                {preview.figures.outstanding_before_vat !== undefined && preview.claim_net_due !== undefined && (
                  <div className="flex justify-between px-3 py-1.5" data-testid="gaeb-invoice-reconcile">
                    <dt className="text-content-secondary">
                      {t('contracts.gaeb_invoice.outstanding_vs_net_due', {
                        defaultValue: 'Outstanding before VAT / net due of the claim',
                      })}
                    </dt>
                    <dd className="flex items-center gap-1">
                      <MoneyDisplay amount={preview.figures.outstanding_before_vat} currency={preview.currency} />
                      <span className="text-content-tertiary">/</span>
                      <MoneyDisplay amount={preview.claim_net_due} currency={preview.currency} />
                    </dd>
                  </div>
                )}
              </dl>

              <div className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
                <div>
                  <div className="text-content-tertiary">
                    {t('contracts.gaeb_invoice.creator', { defaultValue: 'Invoicing party' })}
                  </div>
                  <div>{partyText(preview.creator)}</div>
                </div>
                <div>
                  <div className="text-content-tertiary">
                    {t('contracts.gaeb_invoice.recipient', { defaultValue: 'Invoice recipient' })}
                  </div>
                  <div>{partyText(preview.recipient)}</div>
                </div>
              </div>

              {missing.length > 0 && (
                <div className="rounded-lg bg-semantic-warning-bg p-3 text-xs" data-testid="gaeb-invoice-missing">
                  <div className="mb-1 flex items-center gap-1.5 font-medium text-content-primary">
                    <AlertTriangle size={13} className="text-semantic-warning" />
                    {t('contracts.gaeb_invoice.missing_title', {
                      defaultValue: 'The invoice cannot be written until these are filled in:',
                    })}
                  </div>
                  <ul className="list-disc pl-5 text-content-secondary">
                    {missing.map((field) => (
                      <li key={field}>{missingLabel(t, field)}</li>
                    ))}
                  </ul>
                  <p className="mt-1 text-content-tertiary">
                    {t('contracts.gaeb_invoice.missing_hint', {
                      defaultValue:
                        'Your own address and tax number come from the e-invoice settings, the other party from the contract counterparty.',
                    })}
                  </p>
                </div>
              )}

              {preview.warnings.length > 0 && (
                <ul className="text-xs text-semantic-warning" data-testid="gaeb-invoice-warnings">
                  {preview.warnings.map((w) => (
                    <li key={w.code}>{warningLabel(t, w.code, w.detail, w.reason)}</li>
                  ))}
                </ul>
              )}

              {remapped.length > 0 && (
                <div className="rounded-lg bg-semantic-warning-bg p-3 text-xs" data-testid="gaeb-invoice-remapped">
                  <div className="mb-1 font-medium text-content-primary">
                    {t('contracts.gaeb_invoice.remapped_title', {
                      defaultValue: 'These lines cannot keep their own OZ and are written under another one:',
                    })}
                  </div>
                  <ul className="list-disc pl-5 text-content-secondary">
                    {remapped.map((r) => (
                      <li key={`${r.ordinal}-${r.written_as}`}>
                        {t('contracts.gaeb_invoice.remapped_line', {
                          defaultValue: '{{ordinal}} is written as {{written}} ({{reason}})',
                          ordinal: r.ordinal || '-',
                          written: r.written_as,
                          reason: remapReason(t, r.reason),
                        })}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <Button
                variant="secondary"
                icon={<Download size={14} />}
                onClick={() => void handleDownload()}
                disabled={downloading || missing.length > 0}
                data-testid="gaeb-invoice-download"
              >
                {t('contracts.gaeb_invoice.download', { defaultValue: 'Download X89' })}
              </Button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

export default GaebInvoicePanel;
