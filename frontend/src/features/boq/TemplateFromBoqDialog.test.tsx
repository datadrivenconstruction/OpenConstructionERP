// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Save as template" from an estimate, and "From an existing estimate" from the
// templates page: the options reach the server as chosen.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: (url: string) => api.get(url),
    apiPost: (url: string, body: unknown) => api.post(url, body),
  };
});

import { TemplateFromBoqDialog } from './TemplateFromBoqDialog';

function mount(props: Parameters<typeof TemplateFromBoqDialog>[0]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TemplateFromBoqDialog {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('TemplateFromBoqDialog', () => {
  it('sends the chosen options for a fixed estimate', async () => {
    api.post.mockResolvedValue({ id: 't1', name: 'Shell kit' });
    const onClose = vi.fn();
    const onCreated = vi.fn();
    mount({ boqId: 'boq-1', boqName: 'Shell kit', onClose, onCreated });

    fireEvent.click(screen.getByLabelText(/Keep quantities as defaults/));
    fireEvent.click(screen.getByLabelText('Keep unit rates'));
    fireEvent.click(screen.getByLabelText('Include markups'));
    fireEvent.click(screen.getByText('Create template'));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith('/v1/boq/boqs/templates/from-boq/', {
      boq_id: 'boq-1',
      name: 'Shell kit',
      classification_standard: '',
      keep_quantities: true,
      keep_rates: false,
      include_markups: true,
      renumber: true,
    });
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it('asks for a project and an estimate when none is fixed, and waits for both', async () => {
    api.get.mockImplementation((url: string) => {
      if (url.startsWith('/v1/projects/')) return Promise.resolve([{ id: 'p1', name: 'Alpha', currency: 'EUR' }]);
      if (url.startsWith('/v1/boq/boqs/')) return Promise.resolve([{ id: 'b1', name: 'Alpha shell', project_id: 'p1' }]);
      return Promise.resolve([]);
    });
    api.post.mockResolvedValue({ id: 't2', name: 'Alpha shell' });
    mount({ onClose: vi.fn() });

    const submit = screen.getByText('Create template').closest('button') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    const project = screen.getByTestId('tpl-from-boq-project');
    await screen.findByText('Alpha');
    fireEvent.change(project, { target: { value: 'p1' } });
    await screen.findByText('Alpha shell');
    fireEvent.change(screen.getByTestId('tpl-from-boq-estimate'), { target: { value: 'b1' } });
    expect(submit.disabled).toBe(false);
    expect((screen.getByTestId('tpl-from-boq-name') as HTMLInputElement).value).toBe('Alpha shell');

    fireEvent.click(submit);
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post.mock.calls[0]?.[1]).toMatchObject({ boq_id: 'b1', keep_quantities: false, keep_rates: true });
  });
});
