// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a client sees on the portal before and after signing in: the builder's
// brand, a way to get a fresh sign-in link without phoning anyone, and the
// milestones coming up on their project.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts) return key;
      let text: unknown = opts.defaultValue;
      if (typeof opts.count === 'number') {
        text = opts.count === 1 ? opts.defaultValue_one : opts.defaultValue_other;
      }
      return String(text ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts[name] ?? ''));
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
}));

const apiMocks = vi.hoisted(() => ({
  requestPortalMagicLink: vi.fn(),
  listMyProjects: vi.fn(),
  listProjectMilestones: vi.fn(),
}));
vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api')>()), ...apiMocks }));

const { PortalBrandHeader } = await import('../PortalBrandHeader');
const { RequestSignInLink } = await import('../RequestSignInLink');
const { UpcomingMilestones } = await import('../UpcomingMilestones');
const { useBrandingStore } = await import('@/stores/useBrandingStore');

function withQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function milestone(id: string, name: string, daysUntil: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    name,
    planned_date: '2026-10-12',
    expected_date: '2026-10-12',
    status: 'not_started',
    is_done: false,
    is_late: daysUntil < 0,
    days_until: daysUntil,
    ...extra,
  };
}

afterEach(() => {
  cleanup();
  useBrandingStore.setState({ mode: 'default', logoDataUrl: null, companyName: '' });
  vi.clearAllMocks();
});

describe('the portal carries the builder brand', () => {
  it('shows the uploaded logo, named after the company', () => {
    const hydrate = vi.fn().mockResolvedValue(undefined);
    useBrandingStore.setState({
      mode: 'logo',
      logoDataUrl: 'data:image/png;base64,AAAA',
      companyName: 'Northgate Builders',
      hydrateFromServer: hydrate,
    });
    render(<PortalBrandHeader />);
    const img = screen.getByRole('img');
    expect(img.getAttribute('src')).toBe('data:image/png;base64,AAAA');
    expect(img.getAttribute('alt')).toBe('Northgate Builders');
    expect(hydrate).toHaveBeenCalledTimes(1);
  });

  it('shows the company name when the brand is text', () => {
    useBrandingStore.setState({
      mode: 'text',
      companyName: 'Northgate Builders',
      hydrateFromServer: vi.fn().mockResolvedValue(undefined),
    });
    render(<PortalBrandHeader />);
    expect(screen.getByText('Northgate Builders')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('renders nothing when the workspace has no brand of its own', () => {
    useBrandingStore.setState({ mode: 'default', hydrateFromServer: vi.fn().mockResolvedValue(undefined) });
    render(<PortalBrandHeader />);
    expect(screen.queryByTestId('portal-brand-header')).toBeNull();
  });

  it('renders nothing for a logo mode whose image is missing', () => {
    useBrandingStore.setState({
      mode: 'logo',
      logoDataUrl: null,
      companyName: 'Northgate Builders',
      hydrateFromServer: vi.fn().mockResolvedValue(undefined),
    });
    render(<PortalBrandHeader />);
    expect(screen.queryByTestId('portal-brand-header')).toBeNull();
  });
});

describe('a client can ask for a fresh sign-in link', () => {
  it('sends the trimmed address and answers without saying whether it has access', async () => {
    apiMocks.requestPortalMagicLink.mockResolvedValue(undefined);
    render(<RequestSignInLink />);
    const button = screen.getByRole('button', { name: /send link/i }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: '  owner@example.com ' } });
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/if this address has portal access/i));
    expect(apiMocks.requestPortalMagicLink).toHaveBeenCalledWith('owner@example.com');
  });

  it('tells the client to try later when the request is refused', async () => {
    apiMocks.requestPortalMagicLink.mockRejectedValue(new Error('Request failed (429)'));
    render(<RequestSignInLink />);
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: 'owner@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: /send link/i }));
    await waitFor(() => expect(screen.getByText(/try again in a few minutes/i)).toBeTruthy());
  });
});

describe('the client sees what is coming up on the project', () => {
  it('lists late, due-today and upcoming milestones with a badge each', async () => {
    apiMocks.listMyProjects.mockResolvedValue([{ id: 'p1', name: 'Villa Rossi' }]);
    apiMocks.listProjectMilestones.mockResolvedValue({
      window_days: 14,
      items: [
        milestone('m1', 'Foundation poured', -3, { expected_date: '2026-10-02', planned_date: '2026-09-28' }),
        milestone('m2', 'Framing inspection', 0),
        milestone('m3', 'Roof on', 1),
        milestone('m4', 'Drywall done', 9),
      ],
    });
    withQuery(<UpcomingMilestones />);

    await waitFor(() => expect(screen.getByText('Foundation poured')).toBeTruthy());
    expect(screen.getByText('3 days late')).toBeTruthy();
    expect(screen.getByText('Today')).toBeTruthy();
    expect(screen.getByText('In 1 day')).toBeTruthy();
    expect(screen.getByText('In 9 days')).toBeTruthy();
    // Only the slipped milestone says when it was first planned.
    expect(screen.getAllByText('Originally planned')).toHaveLength(1);
    // One project: no project heading.
    expect(screen.queryByText('Villa Rossi')).toBeNull();
  });

  it('names each project when the client follows more than one', async () => {
    apiMocks.listMyProjects.mockResolvedValue([
      { id: 'p1', name: 'Villa Rossi' },
      { id: 'p2', name: 'Harbour Lofts' },
    ]);
    apiMocks.listProjectMilestones.mockImplementation(async (id: string) => ({
      window_days: 14,
      items: id === 'p1' ? [milestone('m1', 'Roof on', 4)] : [milestone('m2', 'Handover', 12)],
    }));
    withQuery(<UpcomingMilestones />);
    await waitFor(() => expect(screen.getByText('Handover')).toBeTruthy());
    expect(screen.getByText('Villa Rossi')).toBeTruthy();
    expect(screen.getByText('Harbour Lofts')).toBeTruthy();
  });

  it('shows no card at all when nothing is coming up', async () => {
    apiMocks.listMyProjects.mockResolvedValue([{ id: 'p1', name: 'Villa Rossi' }]);
    apiMocks.listProjectMilestones.mockResolvedValue({ window_days: 14, items: [] });
    const { container } = withQuery(<UpcomingMilestones />);
    await waitFor(() => expect(apiMocks.listProjectMilestones).toHaveBeenCalledWith('p1'));
    expect(container.textContent).toBe('');
  });
});
