// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Translated labels for lease codes, spelled out so every key is a literal. */
import type { useTranslation } from 'react-i18next';
import type { ArrearsRow, EscalationKind, Frequency, LeaseStatus } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

export function statusLabel(s: LeaseStatus, t: Translate): string {
  switch (s) {
    case 'draft':
      return t('leasing.status_draft', { defaultValue: 'Draft' });
    case 'active':
      return t('leasing.status_active', { defaultValue: 'Active' });
    case 'notice':
      return t('leasing.status_notice', { defaultValue: 'Under notice' });
    default:
      return t('leasing.status_ended', { defaultValue: 'Ended' });
  }
}

export function frequencyLabel(f: Frequency, t: Translate): string {
  switch (f) {
    case 'monthly':
      return t('leasing.freq_monthly', { defaultValue: 'Monthly' });
    case 'quarterly':
      return t('leasing.freq_quarterly', { defaultValue: 'Quarterly' });
    case 'semiannual':
      return t('leasing.freq_semiannual', { defaultValue: 'Every six months' });
    default:
      return t('leasing.freq_annual', { defaultValue: 'Yearly' });
  }
}

export function escalationLabel(k: EscalationKind, t: Translate): string {
  switch (k) {
    case 'fixed':
      return t('leasing.esc_fixed', { defaultValue: 'Fixed percent' });
    case 'index':
      return t('leasing.esc_index', { defaultValue: 'Linked to an index' });
    default:
      return t('leasing.esc_none', { defaultValue: 'No escalation' });
  }
}

export function bucketLabel(b: ArrearsRow['bucket'], t: Translate): string {
  switch (b) {
    case '1_30':
      return t('leasing.bucket_1_30', { defaultValue: '1-30 days' });
    case '31_60':
      return t('leasing.bucket_31_60', { defaultValue: '31-60 days' });
    case '61_90':
      return t('leasing.bucket_61_90', { defaultValue: '61-90 days' });
    case 'over_90':
      return t('leasing.bucket_over_90', { defaultValue: 'Over 90 days' });
    default:
      return t('leasing.bucket_current', { defaultValue: 'Not yet due' });
  }
}

export function eventLabel(kind: string, t: Translate): string {
  switch (kind) {
    case 'created':
      return t('leasing.ev_created', { defaultValue: 'Created' });
    case 'updated':
      return t('leasing.ev_updated', { defaultValue: 'Edited' });
    case 'activated':
      return t('leasing.ev_activated', { defaultValue: 'Activated' });
    case 'termination':
      return t('leasing.ev_termination', { defaultValue: 'Notice or termination' });
    case 'renewal':
      return t('leasing.ev_renewal', { defaultValue: 'Renewed' });
    case 'review':
      return t('leasing.ev_review', { defaultValue: 'Rent review' });
    case 'schedule_run':
      return t('leasing.ev_schedule_run', { defaultValue: 'Rent invoices raised' });
    case 'document_linked':
      return t('leasing.ev_document_linked', { defaultValue: 'Document attached' });
    case 'document_unlinked':
      return t('leasing.ev_document_unlinked', { defaultValue: 'Document removed' });
    default:
      return kind;
  }
}

/** Rule results arrive in English; show them in the reader's language by rule id. */
export function ruleLabel(ruleId: string, fallback: string, t: Translate): string {
  switch (ruleId) {
    case 'leasing.end_after_start':
      return t('leasing.rule_end_after_start', { defaultValue: 'The lease must end after it starts.' });
    case 'leasing.no_overlap':
      return t('leasing.rule_no_overlap', { defaultValue: 'Another lease already holds this unit in this period.' });
    case 'leasing.deposit_non_negative':
      return t('leasing.rule_deposit_non_negative', { defaultValue: 'The deposit cannot be negative.' });
    case 'leasing.deposit_within_cap':
      return t('leasing.rule_deposit_within_cap', { defaultValue: 'The deposit exceeds the cap the country sets.' });
    case 'leasing.currency_matches_entity':
      return t('leasing.rule_currency_matches_entity', {
        defaultValue: 'The lease currency differs from the currency the landlord keeps its books in.',
      });
    case 'leasing.tenant_identifier':
      return t('leasing.rule_tenant_identifier', {
        defaultValue: 'The tenant needs the identifier the country requires.',
      });
    default:
      return fallback;
  }
}
