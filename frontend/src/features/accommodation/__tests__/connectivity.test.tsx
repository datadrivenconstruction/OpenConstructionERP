// @ts-nocheck
/**
 * Accommodation connectivity wins (CONN-69, CONN-70).
 *
 * CONN-69 — charge rows expose a Finance deep link: pending charges get an
 *   "Invoice in Finance" action, invoiced/paid charges get a "View in
 *   Finance" link. Both route to the project's Finance invoices register.
 * CONN-70 — the Settings tab replaces the two raw UUID inputs (BIM model id,
 *   PropDev block id) with real pickers driven by the BIM models list and a
 *   Development -> Phase -> Block cascade.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const navigateMock = vi.fn();

vi.mock('../api', () => ({
  getAccommodation: vi.fn(),
  listAccommodationBookings: vi.fn(),
  getBooking: vi.fn(),
  createBooking: vi.fn(),
  createCharge: vi.fn(),
  updateBooking: vi.fn(),
  updateAccommodation: vi.fn(),
  deleteAccommodation: vi.fn(),
  bootstrapFromPropDev: vi.fn(),
  allowedBookingTransitions: () => [],
  isBookingTerminal: () => false,
  listRoomBookings: vi.fn(),
}));

vi.mock('@/features/bim/api', () => ({
  fetchBIMModels: vi.fn(),
}));

vi.mock('@/features/property-dev/api', () => ({
  listDevelopments: vi.fn(),
  listPhases: vi.fn(),
  listBlocks: vi.fn(),
}));

vi.mock('@/shared/ui/ModuleHelpButton', () => ({
  ModuleHelpButton: () => null,
}));

vi.mock('@/shared/ui/ContactSearchInput', () => ({
  ContactSearchInput: () => <input data-testid="contact-search-stub" />,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useParams: () => ({ id: 'acc-1' }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

import { getAccommodation, listAccommodationBookings, getBooking } from '../api';
import { fetchBIMModels } from '@/features/bim/api';
import {
  listDevelopments,
  listPhases,
  listBlocks,
} from '@/features/property-dev/api';
import { AccommodationDetailPage } from '../AccommodationDetailPage';

function renderWithProviders(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const ROOM = {
  id: 'room-1',
  accommodation_id: 'acc-1',
  label: 'B-201',
  capacity: 2,
  bim_element_id: null,
  base_rate: '0',
  base_rate_currency: '',
  status: 'available',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  metadata: {},
};

function detail(over = {}) {
  return {
    id: 'acc-1',
    project_id: 'proj-9',
    name: 'Camp North',
    kind: 'worker_camp',
    address: null,
    geo_lat: null,
    geo_lon: null,
    bim_model_id: null,
    property_dev_block_id: null,
    capacity_total: 24,
    notes: null,
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    metadata: {},
    rooms: [ROOM],
    active_bookings_count: 1,
    ...over,
  };
}

const BOOKING = {
  id: 'bk-1',
  room_id: 'room-1',
  room_label: 'B-201',
  occupant_contact_id: null,
  occupant_name: 'Alice',
  check_in: '2026-05-01',
  check_out: '2026-05-10',
  status: 'reserved',
  source: 'manual',
  created_by: null,
  created_at: '2026-04-30',
  updated_at: '2026-04-30',
  metadata: {},
};

describe('Accommodation charges - Finance deep links (CONN-69)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchBIMModels as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
    });
    (listDevelopments as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  });

  it('pending charge shows an Invoice in Finance action routing to the project invoices register', async () => {
    (getAccommodation as ReturnType<typeof vi.fn>).mockResolvedValue(detail());
    (listAccommodationBookings as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [BOOKING],
      total: 1,
      limit: 200,
      offset: 0,
    });
    (getBooking as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BOOKING,
      charges: [
        {
          id: 'ch-1',
          booking_id: 'bk-1',
          kind: 'base_rent',
          description: 'May rent',
          amount: '500.00',
          currency: 'EUR',
          period_start: null,
          period_end: null,
          status: 'pending',
          created_at: '2026-05-01',
          updated_at: '2026-05-01',
          metadata: {},
        },
      ],
    });

    renderWithProviders(<AccommodationDetailPage />);

    fireEvent.click(
      await screen.findByTestId('accommodation-detail-tab-billing'),
    );

    const invoiceBtn = await screen.findByTestId('charge-invoice-ch-1');
    fireEvent.click(invoiceBtn);
    expect(navigateMock).toHaveBeenCalledWith(
      '/projects/proj-9/finance?tab=invoices',
    );
  });

  it('invoiced charge shows a View in Finance link', async () => {
    (getAccommodation as ReturnType<typeof vi.fn>).mockResolvedValue(detail());
    (listAccommodationBookings as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [BOOKING],
      total: 1,
      limit: 200,
      offset: 0,
    });
    (getBooking as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...BOOKING,
      charges: [
        {
          id: 'ch-2',
          booking_id: 'bk-1',
          kind: 'extra',
          description: 'Cleaning',
          amount: '50.00',
          currency: 'EUR',
          period_start: null,
          period_end: null,
          status: 'invoiced',
          created_at: '2026-05-01',
          updated_at: '2026-05-01',
          metadata: {},
        },
      ],
    });

    renderWithProviders(<AccommodationDetailPage />);
    fireEvent.click(
      await screen.findByTestId('accommodation-detail-tab-billing'),
    );

    expect(
      await screen.findByTestId('charge-view-invoice-ch-2'),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('charge-invoice-ch-2'),
    ).not.toBeInTheDocument();
  });
});

describe('Accommodation settings - pickers replace UUID inputs (CONN-70)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (listAccommodationBookings as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    });
  });

  it('renders a BIM model select and a Development->Phase->Block cascade instead of raw UUID inputs', async () => {
    (getAccommodation as ReturnType<typeof vi.fn>).mockResolvedValue(detail());
    (fetchBIMModels as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [
        { id: 'm-1', name: 'Tower A', filename: 'a.ifc' },
        { id: 'm-2', name: 'Tower B', filename: 'b.ifc' },
      ],
      total: 2,
    });
    (listDevelopments as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        id: 'd-1',
        code: 'DV1',
        name: 'Riverside',
      },
    ]);
    (listPhases as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (listBlocks as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderWithProviders(<AccommodationDetailPage />);

    fireEvent.click(
      await screen.findByTestId('accommodation-detail-tab-settings'),
    );

    // BIM model picker is a select, not a free-text id field.
    const bimSelect = (await screen.findByTestId(
      'accommodation-bim-model-select',
    )) as HTMLSelectElement;
    expect(bimSelect).toBeInTheDocument();
    // The fetched models are rendered as <option> entries once the query
    // resolves.
    await waitFor(() => {
      const optionLabels = Array.from(bimSelect.options).map(
        (o) => o.textContent,
      );
      expect(optionLabels).toContain('Tower A');
      expect(optionLabels).toContain('Tower B');
    });

    // Block picker cascade is present (3 selects) - no raw UUID input.
    expect(
      await screen.findByTestId('accommodation-block-dev-select'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('accommodation-block-phase-select'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('accommodation-block-block-select'),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('accommodation-bootstrap-block-id'),
    ).not.toBeInTheDocument();
  });
});
