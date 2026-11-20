// UI QA: source dialog state between openings, and a keyboard path for the plot outline.
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CiteDialog } from '../CiteDialog';
import { PlotEditor } from '../PlotEditor';
import { newBrief } from '../data/briefModel';

vi.mock('@/features/documents/api', () => ({
  fetchDocuments: vi.fn(async () => ({ items: [{ id: 'd1', name: 'Bauantrag.pdf' }], total: 1, offset: 0, limit: 100 })),
}));
vi.mock('../PlotMap', () => ({ default: () => <div data-testid="map-stub" />, PlotMap: () => <div data-testid="map-stub" /> }));

const wrap = (ui: React.ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
);

describe('source dialog', () => {
  it('starts empty when reopened for another value after Cancel', async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const props = { projectId: 'p1', onClose: vi.fn(), onCite: vi.fn() };
    const { rerender } = render(<QueryClientProvider client={qc}><CiteDialog {...props} pointer="/massing/floors_above" /></QueryClientProvider>);
    await screen.findByRole('option', { name: 'Bauantrag.pdf' });
    await user.selectOptions(screen.getAllByRole('combobox')[0]!, 'd1');
    await user.type(screen.getAllByRole('textbox')[1]!, 'secret quote');
    await user.click(screen.getByRole('button', { name: /cancel/i }));
    rerender(<QueryClientProvider client={qc}><CiteDialog {...props} pointer={null} /></QueryClientProvider>);
    rerender(<QueryClientProvider client={qc}><CiteDialog {...props} pointer="/massing/floors_below" /></QueryClientProvider>);
    await waitFor(() => expect(screen.getAllByRole('textbox').length).toBeGreaterThan(1));
    expect((screen.getAllByRole('textbox')[1] as HTMLTextAreaElement).value).toBe('');
    expect((screen.getAllByRole('combobox')[0] as HTMLSelectElement).value).toBe('');
  });
});

describe('plot editor without a pointer device', () => {
  it('offers a text way to enter or edit the corners (keyboard, screen reader)', () => {
    const doc = newBrief({ id: 'p1', country_code: 'DE' }, 'b1');
    render(wrap(<PlotEditor doc={doc} errors={[]} focus={null} onChange={vi.fn()}
      provenance={{ onConfirm: null }} />));
    const inputs = [...screen.queryAllByRole('textbox'), ...screen.queryAllByRole('spinbutton')];
    expect(inputs.length).toBeGreaterThan(0);
  });

  it('labels the map region for assistive technology', () => {
    const doc = newBrief({ id: 'p1', country_code: 'DE' }, 'b1');
    render(wrap(<PlotEditor doc={doc} errors={[]} focus={null} onChange={vi.fn()}
      provenance={{ onConfirm: null }} />));
    expect(document.querySelector('[role="application"][aria-label], [role="region"][aria-label], figure[aria-label]')).toBeTruthy();
  });
});
