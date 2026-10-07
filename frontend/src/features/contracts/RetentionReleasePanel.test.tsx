// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Component tests for <RetentionReleasePanel>.
//
// What these pin is the order of the three steps, which is the whole point of
// the panel:
//
//   * preview writes nothing. The figures a person reads before they commit
//     are the server's, including the withholding for open punch items, so
//     the panel must not compute an amount of its own;
//   * proposing is a second, deliberate press. A release that was proposed is
//     not money paid back, and the ledger above still counts it as held;
//   * approval is where the documents are, and billing is where a claim is
//     picked. The panel offers only a claim that can still be edited, the
//     same rule the server applies, so the button it shows is a button that
//     works.
//
// The api module is stubbed whole. Every figure the panel prints is a string
// off the wire, exactly as the Decimal columns serialise.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  getRetentionSummary: vi.fn(),
  previewRetentionRelease: vi.fn(),
  createRetentionRelease: vi.fn(),
  approveRetentionRelease: vi.fn(),
  billRetentionRelease: vi.fn(),
  voidRetentionRelease: vi.fn(),
  listContractDocuments: vi.fn(),
  createContractDocument: vi.fn(),
  listProgressClaims: vi.fn(),
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) =>
    sel({ addToast: vi.fn() }),
}));

import { RetentionReleasePanel } from './RetentionReleasePanel';
import * as api from './api';
import type {
  ContractDocument,
  ProgressClaimItem,
  RetentionRelease,
  RetentionReleasePreview,
  RetentionSummary,
} from './api';

const summaryMock = vi.mocked(api.getRetentionSummary);
const previewMock = vi.mocked(api.previewRetentionRelease);
const createMock = vi.mocked(api.createRetentionRelease);
const approveMock = vi.mocked(api.approveRetentionRelease);
const billMock = vi.mocked(api.billRetentionRelease);
const documentsMock = vi.mocked(api.listContractDocuments);
const claimsMock = vi.mocked(api.listProgressClaims);

const CONTRACT_ID = 'c-1';

function summary(over: Partial<RetentionSummary> = {}): RetentionSummary {
  return {
    contract_id: CONTRACT_ID,
    currency: 'USD',
    accrued: '5000.0000',
    released: '0',
    held: '5000.0000',
    pending_release: '0',
    available_for_release: '5000.0000',
    releases: [],
    ...over,
  };
}

function release(over: Partial<RetentionRelease> = {}): RetentionRelease {
  return {
    id: 'r-1',
    contract_id: CONTRACT_ID,
    event: 'substantial_completion',
    status: 'proposed',
    amount: '3500.00',
    withheld_for_open_items: '1500.00',
    released_on: null,
    progress_claim_id: null,
    document_ids: [],
    created_by: 'u-1',
    metadata: {
      required_documents: ['certificate_substantial_completion'],
      required_documents_when_bonded: [],
    },
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...over,
  };
}

function preview(
  over: Partial<RetentionReleasePreview> = {},
): RetentionReleasePreview {
  return {
    contract_id: CONTRACT_ID,
    event: 'substantial_completion',
    currency: 'USD',
    held: '5000.00',
    percent_of_held: '100',
    open_items_value: '1000.00',
    open_items_count: 1,
    open_items_without_cost: 0,
    open_items_source: 'punch_list',
    withheld_for_open_items: '1500.00',
    amount: '3500.00',
    remaining: '1500.00',
    rule_source: 'regional_pack',
    statute_reference: null,
    required_documents: ['certificate_substantial_completion'],
    bonded: false,
    already_released: false,
    ...over,
  };
}

function claim(over: Partial<ProgressClaimItem> = {}): ProgressClaimItem {
  return {
    id: 'pc-2',
    contract_id: CONTRACT_ID,
    claim_number: 'PC-2',
    period_start: '2026-02-01',
    period_end: '2026-02-28',
    claim_date: null,
    gross_amount: '0',
    retention_amount: '0',
    prior_claims_total: '45000.0000',
    net_due: '0',
    status: 'draft',
    submitted_at: null,
    approved_at: null,
    paid_at: null,
    currency: 'USD',
    metadata: {},
    created_at: '2026-02-01T00:00:00Z',
    updated_at: '2026-02-01T00:00:00Z',
    ...over,
  } as ProgressClaimItem;
}

function document_(over: Partial<ContractDocument> = {}): ContractDocument {
  return {
    id: 'd-1',
    contract_id: CONTRACT_ID,
    document_id: null,
    doc_role: 'certificate_substantial_completion',
    title: 'Certificate signed 12 Sep',
    version: '',
    metadata: {},
    created_at: '2026-09-12T00:00:00Z',
    updated_at: '2026-09-12T00:00:00Z',
    ...over,
  };
}

function renderPanel(status = 'active') {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <RetentionReleasePanel
        contractId={CONTRACT_ID}
        currency="USD"
        contractStatus={status}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  summaryMock.mockResolvedValue(summary());
  previewMock.mockResolvedValue(preview());
  createMock.mockResolvedValue(release());
  approveMock.mockResolvedValue(release({ status: 'approved' }));
  billMock.mockResolvedValue(release({ status: 'billed', progress_claim_id: 'pc-2' }));
  documentsMock.mockResolvedValue([]);
  claimsMock.mockResolvedValue({ items: [claim()], total: 1, offset: 0, limit: 50 });
});

describe('<RetentionReleasePanel>', () => {
  it('shows what is held and what is free to release', async () => {
    summaryMock.mockResolvedValue(
      summary({ released: '2000.00', held: '3000.0000', pending_release: '1000.00', available_for_release: '2000.0000' }),
    );
    renderPanel();

    expect(await screen.findByText('Free to release')).toBeInTheDocument();
    // A release nobody has paid yet is not money back and not money free.
    expect(document.body.textContent).toContain(
      'Committed to a release that is not paid yet',
    );
  });

  it('previews before anything is written, and proposes only on the second press', async () => {
    renderPanel();

    fireEvent.click(await screen.findByText('Release retainage'));
    fireEvent.click(screen.getByText('Preview'));

    expect(await screen.findByText('Propose this release')).toBeInTheDocument();
    // Previewing a possible release has not paid any retention back.
    expect(screen.getByText('Amount', { selector: 'dt' }).nextElementSibling)
      .toHaveTextContent('$3,500.00');
    expect(screen.getByText('Paid back', { selector: 'dt' }).nextElementSibling)
      .toHaveTextContent('$0.00');
    expect(screen.queryByText('Released', { selector: 'dt' })).not.toBeInTheDocument();
    expect(createMock).not.toHaveBeenCalled();
    // The withholding and the amount are the server's figures, printed as sent.
    expect(document.body.textContent).toContain('Withheld for open items');
    expect(document.body.textContent).toContain(
      '1 open items on the project, 0 of them without a cost.',
    );

    fireEvent.click(screen.getByText('Propose this release'));
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock).toHaveBeenCalledWith(CONTRACT_ID, {
      event: 'substantial_completion',
    });
  });

  it('names the document the event needs, and can register it on the contract', async () => {
    summaryMock.mockResolvedValue(summary({ releases: [release()] }));
    renderPanel();

    fireEvent.click(await screen.findByText('Approve'));
    expect(
      await screen.findByText('Certificate of substantial completion'),
    ).toBeInTheDocument();
    // Nothing is filed under that role yet, so the panel offers to file it
    // rather than approving against a document that does not exist.
    expect(screen.getByText('Register it on the contract')).toBeInTheDocument();
  });

  it('attaches a registered document and approves with it', async () => {
    summaryMock.mockResolvedValue(summary({ releases: [release()] }));
    documentsMock.mockResolvedValue([document_()]);
    renderPanel();

    fireEvent.click(await screen.findByText('Approve'));
    fireEvent.click(await screen.findByText('Certificate signed 12 Sep'));
    fireEvent.click(screen.getByText('Approve the release'));

    await waitFor(() => expect(approveMock).toHaveBeenCalledTimes(1));
    expect(approveMock).toHaveBeenCalledWith('r-1', ['d-1']);
  });

  it('bills an approved release on a claim that can still be edited', async () => {
    summaryMock.mockResolvedValue(
      summary({ releases: [release({ status: 'approved' })] }),
    );
    claimsMock.mockResolvedValue({
      items: [claim(), claim({ id: 'pc-1', claim_number: 'PC-1', status: 'paid' })],
      total: 2,
      offset: 0,
      limit: 50,
    });
    renderPanel();

    fireEvent.click(await screen.findByText('Bill on a claim'));
    // The paid claim is not offered: the server refuses it, and a button that
    // cannot work is worse than no button.
    expect(await screen.findByText('PC-2')).toBeInTheDocument();
    expect(screen.queryByText('PC-1')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('PC-2'));
    await waitFor(() => expect(billMock).toHaveBeenCalledWith('r-1', 'pc-2'));
  });

  it('offers no release on a draft contract', async () => {
    renderPanel('draft');

    await waitFor(() => expect(summaryMock).toHaveBeenCalled());
    expect(screen.queryByText('Release retainage')).not.toBeInTheDocument();
  });
});
