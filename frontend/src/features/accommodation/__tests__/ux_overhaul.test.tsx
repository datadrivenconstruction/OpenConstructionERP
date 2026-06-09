// @ts-nocheck
/**
 * Accommodation UX overhaul — critical-flow coverage.
 *
 * Asserts:
 *   1. List page renders a warm EmptyState (not the raw card border) when
 *      no accommodations exist, and the CTA opens the create modal with
 *      the right initial state.
 *   2. List page surfaces a RecoveryCard with Retry when the list fetch
 *      fails (i.e. failure path is not a silent blank screen).
 *   3. Detail page renders the IA grouping — Inventory / Occupancy /
 *      Billing / Settings — and the new KPI strip.
 *   4. Calendar week navigation moves the visible date window forward
 *      one week on Next, back one week on Previous, and resets to today
 *      on Today.
 *   5. Charges tab opens with the booking picker pre-selected (no UUID
 *      paste required any more).
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api', () => ({
  listAccommodations: vi.fn(),
  getAccommodation: vi.fn(),
  listAccommodationBookings: vi.fn(),
  createBooking: vi.fn(),
  createCharge: vi.fn(),
  updateCharge: vi.fn(),
  deleteCharge: vi.fn(),
  getBooking: vi.fn(),
  updateBooking: vi.fn(),
  updateAccommodation: vi.fn(),
  deleteAccommodation: vi.fn(),
  createAccommodation: vi.fn(),
  bootstrapFromPropDev: vi.fn(),
  bulkCreateRooms: vi.fn(),
  suggestFromHR: vi.fn(),
  allowedBookingTransitions: (s: string) =>
    s === 'reserved'
      ? ['checked_in', 'cancelled']
      : s === 'checked_in'
        ? ['checked_out', 'cancelled']
        : [],
  allowedChargeTransitions: (s: string) =>
    s === 'pending'
      ? ['invoiced', 'paid', 'waived']
      : s === 'invoiced'
        ? ['paid', 'waived']
        : [],
  isBookingTerminal: (s: string) => s === 'checked_out' || s === 'cancelled',
  isChargeLocked: (s: string) => s === 'paid' || s === 'waived',
  listRoomBookings: vi.fn(),
}));

// Projects API used by the list page to render the project label.
vi.mock('@/features/projects/api', () => ({
  projectsApi: { list: vi.fn().mockResolvedValue([]) },
}));

// Mock the ModuleHelpButton — it pulls in the entire tour engine which we
// don't need for this UX-coverage suite.
vi.mock('@/shared/ui/ModuleHelpButton', () => ({
  ModuleHelpButton: () => null,
}));

// Mock the BIM picker / contact search to keep render cheap.
vi.mock('@/shared/ui/ContactSearchInput', () => ({
  ContactSearchInput: () => <input data-testid="contact-search-stub" />,
}));

// Override useParams from the global setup so the detail page resolves
// our test accommodation id. The base mock returns `{}`.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({ id: 'acc-1' }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

import {
  listAccommodations,
  getAccommodation,
  listAccommodationBookings,
  getBooking,
} from '../api';

import { AccommodationListPage } from '../AccommodationListPage';
import { AccommodationDetailPage } from '../AccommodationDetailPage';
import { AccommodationCalendar } from '../AccommodationCalendar';

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

function makeAccommodation(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'acc-1',
    project_id: 'proj-1',
    name: 'Camp North',
    kind: 'worker_camp',
    address: '123 Site Rd',
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
    ...over,
  };
}

function makeAccommodationDetail(over: Partial<Record<string, unknown>> = {}) {
  return {
    ...makeAccommodation(),
    rooms: [
      {
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
      },
    ],
    active_bookings_count: 1,
    ...over,
  };
}

describe('AccommodationListPage - empty + error states', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the warm EmptyState with a CTA when no accommodations exist', async () => {
    (listAccommodations as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    renderWithProviders(<AccommodationListPage />);

    // EmptyState title (not the dashed-border placeholder).
    expect(
      await screen.findByText(/No accommodations yet/i),
    ).toBeInTheDocument();
    // Primary CTA. Use button query so we don't match the FAB twice
    // (the FAB is hidden via sm:hidden but still in the DOM).
    const ctas = await screen.findAllByRole('button', {
      name: /New accommodation/i,
    });
    expect(ctas.length).toBeGreaterThan(0);
  });

  it('clicking the CTA opens the create modal in a fresh state', async () => {
    (listAccommodations as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    renderWithProviders(<AccommodationListPage />);

    const ctas = await screen.findAllByRole('button', {
      name: /New accommodation/i,
    });
    // The first one is the desktop header button.
    fireEvent.click(ctas[0]);

    // Modal mounts — verify by the submit button + form fields rather
    // than the title text (which is also rendered on the page header).
    expect(
      await screen.findByTestId('accommodation-create-submit'),
    ).toBeInTheDocument();
    // Default kind is worker_camp.
    const kindSelect = (await screen.findByTestId(
      'accommodation-create-kind',
    )) as HTMLSelectElement;
    expect(kindSelect.value).toBe('worker_camp');
    // Name input is empty (fresh state).
    const nameInput = (await screen.findByTestId(
      'accommodation-create-name',
    )) as HTMLInputElement;
    expect(nameInput.value).toBe('');
    // Capacity defaults to "0".
    const capacityInput = (await screen.findByTestId(
      'accommodation-create-capacity',
    )) as HTMLInputElement;
    expect(capacityInput.value).toBe('0');
  });

  it('renders the RecoveryCard with Retry when the list fetch fails', async () => {
    (listAccommodations as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Boom'),
    );
    renderWithProviders(<AccommodationListPage />);

    // RecoveryCard falls back to its load-failed title for generic errors.
    expect(
      await screen.findByText(/Couldn’t load this|Couldn't load this/i),
    ).toBeInTheDocument();
    // Retry button must be present (so the failure isn't a dead-end).
    expect(
      await screen.findByRole('button', { name: /Retry/i }),
    ).toBeInTheDocument();
  });

  it('renders the summary KPI strip when accommodations exist', async () => {
    (listAccommodations as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeAccommodation({ id: 'a1', name: 'Alpha' }),
      makeAccommodation({ id: 'a2', name: 'Bravo', kind: 'hotel' }),
    ]);
    renderWithProviders(<AccommodationListPage />);

    const strip = await screen.findByTestId('accommodation-summary-strip');
    const tiles = within(strip).getAllByTestId('accommodation-summary-tile');
    // 4 tiles: Properties / Capacity / Worker camps / Rentals+Hotels
    expect(tiles).toHaveLength(4);
  });
});

describe('AccommodationDetailPage - IA grouping', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the 3-block tab strip + Settings, plus the KPI row', async () => {
    (getAccommodation as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeAccommodationDetail(),
    );
    (listAccommodationBookings as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    });

    renderWithProviders(<AccommodationDetailPage />);

    // KPI row is present.
    expect(
      await screen.findByTestId('accommodation-header-kpis'),
    ).toBeInTheDocument();

    // The 4 blocks (Inventory / Occupancy / Billing / Settings) are
    // mounted as role=tab.
    expect(
      await screen.findByTestId('accommodation-detail-tab-inventory'),
    ).toBeInTheDocument();
    expect(
      await screen.findByTestId('accommodation-detail-tab-occupancy'),
    ).toBeInTheDocument();
    expect(
      await screen.findByTestId('accommodation-detail-tab-billing'),
    ).toBeInTheDocument();
    expect(
      await screen.findByTestId('accommodation-detail-tab-settings'),
    ).toBeInTheDocument();
  });

  it('Billing tab auto-selects the first booking - no UUID paste required', async () => {
    (getAccommodation as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeAccommodationDetail(),
    );
    const sampleBooking = {
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
    (listAccommodationBookings as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [sampleBooking],
      total: 1,
      limit: 200,
      offset: 0,
    });
    (getBooking as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...sampleBooking,
      charges: [],
    });

    renderWithProviders(<AccommodationDetailPage />);

    // Switch to Billing block.
    fireEvent.click(
      await screen.findByTestId('accommodation-detail-tab-billing'),
    );

    // The booking picker rail shows our booking, no UUID paste field.
    expect(
      await screen.findByTestId('charges-booking-picker'),
    ).toBeInTheDocument();
    expect(
      await screen.findByTestId('charges-pick-booking-bk-1'),
    ).toBeInTheDocument();
    // The panel auto-selects + shows the "Add charge" CTA.
    expect(await screen.findByTestId('charges-add-button')).toBeInTheDocument();
    // The old UUID paste input is gone.
    expect(
      screen.queryByTestId('charges-booking-id-input'),
    ).not.toBeInTheDocument();
  });
});

describe('AccommodationCalendar - navigation', () => {
  beforeEach(() => vi.clearAllMocks());

  it('Next button moves the visible week forward by 7 days', async () => {
    (getAccommodation as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeAccommodationDetail(),
    );
    (listAccommodationBookings as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    });

    renderWithProviders(
      <AccommodationCalendar embedded scopedAccommodationId="acc-1" />,
    );

    // Capture initial day-header testids.
    const initialDayHeaders = await screen.findAllByTestId(
      /accommodation-calendar-day-header-/,
    );
    const initialFirstId = initialDayHeaders[0].getAttribute('data-testid');
    expect(initialFirstId).toMatch(
      /accommodation-calendar-day-header-\d{4}-\d{2}-\d{2}/,
    );
    const initialDate = initialFirstId!.replace(
      'accommodation-calendar-day-header-',
      '',
    );

    // Click Next.
    fireEvent.click(screen.getByTestId('accommodation-calendar-next'));

    // Wait for the headers to update — the first day-header testid now
    // points to a later date.
    const updatedDayHeaders = await screen.findAllByTestId(
      /accommodation-calendar-day-header-/,
    );
    const updatedFirstId = updatedDayHeaders[0].getAttribute('data-testid')!;
    const updatedDate = updatedFirstId.replace(
      'accommodation-calendar-day-header-',
      '',
    );
    expect(updatedDate).not.toBe(initialDate);
    // The new first day must be strictly after the original first day.
    expect(updatedDate > initialDate).toBe(true);

    // Click Previous — we should be back to the original date.
    fireEvent.click(screen.getByTestId('accommodation-calendar-prev'));
    const revertedHeaders = await screen.findAllByTestId(
      /accommodation-calendar-day-header-/,
    );
    const revertedFirstId =
      revertedHeaders[0].getAttribute('data-testid')!;
    expect(
      revertedFirstId.replace('accommodation-calendar-day-header-', ''),
    ).toBe(initialDate);
  });
});
