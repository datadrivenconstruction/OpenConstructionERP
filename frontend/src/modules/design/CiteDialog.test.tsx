import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CiteDialog } from './CiteDialog';

vi.mock('@/features/documents/api', () => ({
  fetchDocuments: vi.fn(async () => ({
    items: [
      { id: 'd1', name: 'Bauantrag.pdf' },
      { id: 'd2', name: 'Lageplan.pdf' },
    ],
    total: 2,
    offset: 0,
    limit: 100,
  })),
}));

function setup(pointer: string | null = '/massing/floors_above') {
  const onCite = vi.fn();
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CiteDialog projectId="p1" pointer={pointer} onClose={onClose} onCite={onCite} />
    </QueryClientProvider>,
  );
  return { onCite, onClose };
}

describe('CiteDialog', () => {
  it('renders nothing while no value is being cited', () => {
    setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('hands the chosen document, page and quote back', async () => {
    const { onCite, onClose } = setup();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Lageplan.pdf' })).toBeTruthy());
    const add = screen.getByRole('button', { name: 'Add source' }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'd2');
    await userEvent.type(screen.getByLabelText('Page'), '4');
    await userEvent.type(screen.getByLabelText('Quote from the document'), 'fünf Vollgeschosse');
    await userEvent.click(add);
    expect(onCite).toHaveBeenCalledWith('/massing/floors_above', { document_id: 'd2', page: 4, quote: 'fünf Vollgeschosse' });
    expect(onClose).toHaveBeenCalled();
  });

  it('refuses a page that is not a whole number', async () => {
    const { onCite } = setup();
    await waitFor(() => expect(screen.getByRole('option', { name: 'Bauantrag.pdf' })).toBeTruthy());
    await userEvent.selectOptions(screen.getByRole('combobox'), 'd1');
    await userEvent.type(screen.getByLabelText('Page'), '2.5');
    expect((screen.getByRole('button', { name: 'Add source' }) as HTMLButtonElement).disabled).toBe(true);
    expect(onCite).not.toHaveBeenCalled();
  });
});
