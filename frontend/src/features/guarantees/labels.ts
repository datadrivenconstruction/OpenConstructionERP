// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Label tables for the guarantees vocabularies. Each entry pairs a locale key
 * with its English text, so a label is never built from a template literal and
 * the key set stays greppable.
 */
import type { TFunction } from 'i18next';
import type {
  GuaranteeDirection,
  GuaranteeEventAction,
  GuaranteeStatus,
  GuaranteeType,
} from './api';
import type { BadgeVariant } from '@/shared/ui/Badge';

interface Label {
  key: string;
  en: string;
}

const TYPE_LABELS: Record<GuaranteeType, Label> = {
  bid_bond: { key: 'guarantees.type_bid_bond', en: 'Bid bond' },
  performance_bond: { key: 'guarantees.type_performance_bond', en: 'Performance bond' },
  advance_payment: { key: 'guarantees.type_advance_payment', en: 'Advance payment guarantee' },
  retention_bond: { key: 'guarantees.type_retention_bond', en: 'Retention bond' },
  warranty_bond: { key: 'guarantees.type_warranty_bond', en: 'Warranty bond' },
  parent_company: { key: 'guarantees.type_parent_company', en: 'Parent company guarantee' },
};

const STATUS_LABELS: Record<GuaranteeStatus, Label> = {
  draft: { key: 'guarantees.status_draft', en: 'Draft' },
  requested: { key: 'guarantees.status_requested', en: 'Requested' },
  issued: { key: 'guarantees.status_issued', en: 'Issued' },
  extended: { key: 'guarantees.status_extended', en: 'Extended' },
  reduced: { key: 'guarantees.status_reduced', en: 'Reduced' },
  released: { key: 'guarantees.status_released', en: 'Released' },
  called: { key: 'guarantees.status_called', en: 'Called' },
  expired: { key: 'guarantees.status_expired', en: 'Expired' },
};

const DIRECTION_LABELS: Record<GuaranteeDirection, Label> = {
  given: { key: 'guarantees.direction_given', en: 'Given (we provide)' },
  received: { key: 'guarantees.direction_received', en: 'Received (we hold)' },
};

/** Button wording per target status (the action, not the state). */
const ACTION_LABELS: Record<GuaranteeStatus, Label> = {
  draft: { key: 'guarantees.action_draft', en: 'Back to draft' },
  requested: { key: 'guarantees.action_requested', en: 'Mark as requested' },
  issued: { key: 'guarantees.action_issued', en: 'Mark as issued' },
  extended: { key: 'guarantees.action_extended', en: 'Extend' },
  reduced: { key: 'guarantees.action_reduced', en: 'Reduce' },
  released: { key: 'guarantees.action_released', en: 'Release' },
  called: { key: 'guarantees.action_called', en: 'Record call' },
  expired: { key: 'guarantees.action_expired', en: 'Mark expired' },
};

const EVENT_LABELS: Record<GuaranteeEventAction, Label> = {
  created: { key: 'guarantees.event_created', en: 'Created' },
  updated: { key: 'guarantees.event_updated', en: 'Updated' },
  status_changed: { key: 'guarantees.event_status_changed', en: 'Status changed' },
  extended: { key: 'guarantees.event_extended', en: 'Extended' },
  reduced: { key: 'guarantees.event_reduced', en: 'Reduced' },
  released: { key: 'guarantees.event_released', en: 'Released' },
  called: { key: 'guarantees.event_called', en: 'Called' },
  document_linked: { key: 'guarantees.event_document_linked', en: 'Document linked' },
  document_unlinked: { key: 'guarantees.event_document_unlinked', en: 'Document unlinked' },
};

const RULE_LABELS: Record<string, Label> = {
  'guarantees.performance_bond_before_first_payment': {
    key: 'guarantees.rule_performance_bond_before_first_payment',
    en: 'Performance bond before first payment',
  },
  'guarantees.expiry_covers_defects_period': {
    key: 'guarantees.rule_expiry_covers_defects_period',
    en: 'Expiry covers the defects period',
  },
  'guarantees.advance_covers_outstanding': {
    key: 'guarantees.rule_advance_covers_outstanding',
    en: 'Advance guarantee covers the outstanding advance',
  },
  'guarantees.amount_matches_contract_percent': {
    key: 'guarantees.rule_amount_matches_contract_percent',
    en: 'Amount matches the contract percentage',
  },
};

const SOURCE_LABELS: Record<string, Label> = {
  progress_claim: { key: 'guarantees.source_progress_claim', en: 'Progress claim' },
  manual: { key: 'guarantees.source_manual', en: 'Manual' },
  alert: { key: 'guarantees.source_alert', en: 'Expiry alert' },
};

function humanize(code: string): string {
  const s = code.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function typeLabel(t: TFunction, v: GuaranteeType): string {
  const l = TYPE_LABELS[v];
  return t(l.key, { defaultValue: l.en });
}

export function statusLabel(t: TFunction, v: GuaranteeStatus): string {
  const l = STATUS_LABELS[v];
  return t(l.key, { defaultValue: l.en });
}

export function directionLabel(t: TFunction, v: GuaranteeDirection): string {
  const l = DIRECTION_LABELS[v];
  return t(l.key, { defaultValue: l.en });
}

export function actionLabel(t: TFunction, v: GuaranteeStatus): string {
  const l = ACTION_LABELS[v];
  return t(l.key, { defaultValue: l.en });
}

export function eventLabel(t: TFunction, v: GuaranteeEventAction): string {
  const l = EVENT_LABELS[v];
  return l ? t(l.key, { defaultValue: l.en }) : humanize(v);
}

export function ruleLabel(t: TFunction, ruleId: string): string {
  const l = RULE_LABELS[ruleId];
  return l ? t(l.key, { defaultValue: l.en }) : humanize(ruleId.split('.').pop() ?? ruleId);
}

export function sourceLabel(t: TFunction, source: string): string {
  const l = SOURCE_LABELS[source];
  return l ? t(l.key, { defaultValue: l.en }) : humanize(source);
}

export function statusVariant(s: GuaranteeStatus): BadgeVariant {
  switch (s) {
    case 'issued':
      return 'success';
    case 'extended':
    case 'reduced':
      return 'blue';
    case 'requested':
      return 'warning';
    case 'called':
    case 'expired':
      return 'error';
    default:
      return 'neutral';
  }
}
