// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One row of each list the document picker reads, with the field names of
// the response model of the module that owns it, and the envelope that list
// answers in. A picker that reads a field these rows do not carry reads
// nothing in production, so the tests build their answers from here.
//
// Source of each row (backend/app/modules):
//   contract         contracts/schemas.py        ContractResponse, page ContractListResponse
//   contract line    contracts/schemas.py        ContractLineResponse, bare list
//   purchase_order   procurement/schemas.py      POResponse, page POListResponse
//   change_order     changeorders/schemas.py     ChangeOrderResponse, bare list
//   variation_order  variations/schemas.py       VariationOrderResponse, page VariationOrderListResponse
//   tender_package   tendering/schemas.py        PackageResponse, bare list
//   bid_package      bid_management/schemas.py   BidPackageResponse, bare list
//   rfq              rfq_bidding/schemas.py      RFQResponse, page RFQListResponse

import type { ListedKind } from '../documents';

const STAMP = { created_at: '2026-09-01T08:00:00Z', updated_at: '2026-09-02T08:00:00Z' };

export const CONTRACT_ROW = {
  id: 'c1',
  code: 'SC-014',
  title: 'Structural works',
  contract_type: 'lump_sum',
  counterparty_type: 'subcontractor',
  counterparty_id: null,
  project_id: 'p1',
  parent_contract_id: null,
  start_date: '2026-10-01',
  end_date: null,
  total_value: '1700000.00',
  original_contract_value: '1650000.00',
  currency: 'EUR',
  retention_percent: '5.00',
  retention_release_event: 'practical_completion',
  status: 'active',
  signed_at: '2026-09-20',
  terms: {},
  template_code: null,
  template_version: null,
  created_by: null,
  metadata: {},
  ...STAMP,
};

export const CONTRACT_LINE_ROW = {
  id: 'cl1',
  contract_id: 'c1',
  parent_line_id: null,
  code: '1.2',
  description: 'Concrete frame, levels 1 to 4',
  scope_section: null,
  line_type: 'lump_sum',
  unit: 'lsum',
  quantity: '1',
  unit_rate: '640000.00',
  total_value: '640000.00',
  order_index: 2,
  metadata: {},
  billed: false,
  ...STAMP,
};

export const PURCHASE_ORDER_ROW = {
  id: 'po1',
  project_id: 'p1',
  vendor_contact_id: null,
  vendor_name: 'Lift supplier',
  po_number: 'PO-0007',
  po_type: 'standard',
  issue_date: '2026-09-12',
  delivery_date: null,
  currency_code: 'EUR',
  amount_subtotal: '95000.00',
  tax_amount: '18050.00',
  amount_total: '113050.00',
  status: 'issued',
  supplier_acknowledged_at: null,
  supplier_acknowledged_by: null,
  supplier_reference: null,
  supplier_confirmed_delivery_date: null,
  invoice_tolerance_pct: null,
  invoice_tolerance_abs: null,
  payment_terms: null,
  notes: null,
  created_by: null,
  metadata: {},
  items: [],
  retention_percent: '0.00',
  retain_on_receipt: false,
  retainage_amount: '0',
  retainage_held: '0',
  vendor_warnings: [],
  invoiced_net: '0',
  invoice_count: 0,
  ...STAMP,
};

export const CHANGE_ORDER_ROW = {
  id: 'co1',
  project_id: 'p1',
  code: 'CO-003',
  title: 'Extra piling',
  description: 'Ground conditions on the north side',
  reason_category: 'site_condition',
  variation_type: null,
  status: 'approved',
  submitted_by: null,
  submitted_by_name: null,
  approved_by: null,
  approved_by_name: null,
  rejected_by: null,
  rejected_by_name: null,
  submitted_at: null,
  approved_at: null,
  rejected_at: null,
  cost_impact: '42000.00',
  schedule_impact_days: 6,
  currency: 'EUR',
  metadata: {},
  ...STAMP,
  item_count: 2,
  linked_po_ids: [],
  linked_rfi_ids: [],
  current_approval_step: null,
  ball_in_court: null,
  response_due_date: null,
};

export const VARIATION_ORDER_ROW = {
  id: 'vo1',
  project_id: 'p1',
  variation_request_id: null,
  code: 'VO-002',
  title: 'Facade upgrade',
  final_cost_impact: '88000.00',
  final_schedule_days: 0,
  currency: 'EUR',
  agreed_at: null,
  signed_by: null,
  status: 'issued',
  reference_change_order_id: null,
  affected_contract_id: 'c1',
  contract_standard: '',
  contract_clause_ref: '',
  implementation_started_at: null,
  implementation_completed_at: null,
  ball_in_court: null,
  response_due_date: null,
  metadata: {},
  ...STAMP,
};

export const TENDER_PACKAGE_ROW = {
  id: 'tp1',
  project_id: 'p1',
  boq_id: null,
  name: 'Facade package',
  description: 'Curtain wall and cladding',
  status: 'draft',
  deadline: null,
  metadata: {},
  ...STAMP,
  bid_count: 0,
};

export const BID_PACKAGE_ROW = {
  id: 'bp1',
  project_id: 'p1',
  tender_id: null,
  code: 'BP-004',
  title: 'Mechanical services',
  scope_description: '',
  instructions_to_bidders: '',
  submission_deadline: null,
  decision_due_by: null,
  currency: 'EUR',
  total_budget_estimate: '450000.00',
  status: 'draft',
  confidentiality_level: 'limited',
  published_at: null,
  closed_at: null,
  awarded_at: null,
  created_by: null,
  metadata: {},
  ...STAMP,
};

export const RFQ_ROW = {
  id: 'rfq1',
  project_id: 'p1',
  rfq_number: 'RFQ-0003',
  title: 'Lifts',
  description: null,
  scope_of_work: null,
  submission_deadline: null,
  currency_code: 'EUR',
  status: 'draft',
  issued_to_contacts: [],
  evaluation_method: 'lowest_price',
  technical_weight: '0',
  require_full_scope: true,
  created_by: null,
  metadata: {},
  lines: [],
  bids: [],
  ...STAMP,
};

const paged = <T,>(row: T) => ({ items: [row], total: 1, offset: 0, limit: 100 });

/** What each list answers for a project with one document of the kind, and the line the picker shows for it. */
export const LIST_ANSWERS: Record<ListedKind, { path: string; payload: unknown; id: string; label: string; currency: string | null }> = {
  contract: {
    path: '/v1/contracts/contracts/?project_id=p1&limit=100',
    payload: paged(CONTRACT_ROW),
    id: 'c1',
    label: 'SC-014 Structural works',
    currency: 'EUR',
  },
  purchase_order: {
    path: '/v1/procurement/?project_id=p1&limit=100',
    payload: paged(PURCHASE_ORDER_ROW),
    id: 'po1',
    label: 'PO-0007 Lift supplier',
    currency: 'EUR',
  },
  change_order: {
    path: '/v1/changeorders/?project_id=p1&limit=100',
    payload: [CHANGE_ORDER_ROW],
    id: 'co1',
    label: 'CO-003 Extra piling',
    currency: 'EUR',
  },
  variation_order: {
    path: '/v1/variations/variation-orders/?project_id=p1&limit=100',
    payload: paged(VARIATION_ORDER_ROW),
    id: 'vo1',
    label: 'VO-002 Facade upgrade',
    currency: 'EUR',
  },
  tender_package: {
    path: '/v1/bid-management/tenders/main-contract/packages/?project_id=p1&limit=100',
    payload: [TENDER_PACKAGE_ROW],
    id: 'tp1',
    label: 'Facade package',
    currency: null,
  },
  bid_package: {
    path: '/v1/bid-management/bid-packages/?project_id=p1&limit=100',
    payload: [BID_PACKAGE_ROW],
    id: 'bp1',
    label: 'BP-004 Mechanical services',
    currency: 'EUR',
  },
  rfq: {
    path: '/v1/bid-management/tenders/rfq/?project_id=p1&limit=100',
    payload: paged(RFQ_ROW),
    id: 'rfq1',
    label: 'RFQ-0003 Lifts',
    currency: 'EUR',
  },
};
