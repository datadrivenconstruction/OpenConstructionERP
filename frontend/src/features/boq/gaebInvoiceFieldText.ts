// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';

/** The preview and a refused download name the same missing invoice fields. */
export function missingInvoiceFieldLabel(t: TFunction, field: string): string {
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
