// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Compliance-docs feature types (hand-written; backend is owner of truth).

export const COMPLIANCE_DOC_TYPES = [
  'insurance_general_liability',
  'insurance_workers_comp',
  'insurance_auto',
  'insurance_umbrella',
  'permit_building',
  'permit_electrical',
  'permit_plumbing',
  'permit_other',
  'bond_payment',
  'bond_performance',
  'bond_bid',
  'certification_safety',
  'certification_other',
  'other',
] as const;
export type ComplianceDocType = (typeof COMPLIANCE_DOC_TYPES)[number];

export const COMPLIANCE_STATUSES = [
  'active',
  // Uploaded ahead of time: effective_date is still in the future, so the
  // document is on file but is not live cover yet.
  'not_yet_effective',
  'expiring_soon',
  'expired',
  'cancelled',
  'void',
] as const;
export type ComplianceStatus = (typeof COMPLIANCE_STATUSES)[number];

export interface ComplianceDoc {
  id: string;
  project_id: string;
  doc_type: ComplianceDocType;
  name: string;
  issuer: string | null;
  policy_number: string | null;
  coverage_amount: string | null;
  currency: string;
  effective_date: string; // ISO date
  expires_at: string; // ISO date
  notify_days_before: number;
  status: ComplianceStatus;
  attachment_document_id: string | null;
  notes: string;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  days_until_expiry: number;
}

export interface ComplianceDocCreate {
  project_id: string;
  doc_type: ComplianceDocType;
  name: string;
  issuer?: string | null;
  policy_number?: string | null;
  coverage_amount?: string | null;
  currency?: string;
  effective_date: string;
  expires_at: string;
  notify_days_before?: number;
  status?: ComplianceStatus;
  attachment_document_id?: string | null;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface ComplianceDocUpdate {
  doc_type?: ComplianceDocType;
  name?: string;
  issuer?: string | null;
  policy_number?: string | null;
  coverage_amount?: string | null;
  currency?: string;
  effective_date?: string;
  expires_at?: string;
  notify_days_before?: number;
  status?: ComplianceStatus;
  attachment_document_id?: string | null;
  notes?: string;
  metadata?: Record<string, unknown>;
}
