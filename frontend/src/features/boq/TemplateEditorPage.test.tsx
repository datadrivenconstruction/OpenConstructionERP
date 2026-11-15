// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The template editor: own templates are edited and saved after the server's
// rules have been shown; built-in ones are read only and only offer a copy.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const nav = vi.hoisted(() => ({ navigate: vi.fn(), params: { templateId: 'tpl-1' } }));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => nav.navigate, useParams: () => nav.params };
});

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: (url: string) => api.get(url),
    apiPost: (url: string, body: unknown) => api.post(url, body),
    apiPut: (url: string, body: unknown) => api.put(url, body),
  };
});

import { TemplateEditorPage } from './TemplateEditorPage';
import { moveItem, renumberSections } from './templatesApi';

function detail(over: Record<string, unknown> = {}) {
  return {
    id: 'tpl-1',
    builtin: false,
    name: 'Shell kit',
    description: '',
    icon: 'FileText',
    classification_standard: '',
    origin: 'manual',
    copied_from: null,
    markups: [],
    warnings: [],
    sections: [
      {
        ordinal: '01',
        description: 'Earthwork',
        classification: {},
        positions: [
          { ordinal: '01.0010', description: 'Excavation', unit: 'm3', quantity: null, qty_factor: '0.8', rate: '12.5', classification: {} },
        ],
      },
    ],
    ...over,
  };
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TemplateEditorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.get.mockResolvedValue(detail());
  api.post.mockResolvedValue([]);
  api.put.mockResolvedValue(detail({ name: 'Renamed' }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('TemplateEditorPage', () => {
  it('saves an edited own template straight away when the rules find nothing', async () => {
    mount();
    const name = await screen.findByTestId('tpl-name');
    fireEvent.change(name, { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByTestId('tpl-add-position-0'));
    fireEvent.click(screen.getByTestId('tpl-save'));

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    const [url, body] = api.put.mock.calls[0] as [string, { name: string; sections: { positions: unknown[] }[] }];
    expect(url).toBe('/v1/boq/boqs/templates/tpl-1/');
    expect(body.name).toBe('Renamed');
    expect(body.sections[0]?.positions).toHaveLength(2);
    expect(api.post).toHaveBeenCalledWith('/v1/boq/boqs/templates/validate/', expect.anything());
  });

  it('lists the warnings first and saves only after Save anyway', async () => {
    api.post.mockResolvedValue([
      { rule_id: 'boq.template.position_has_unit', severity: 'warning', path: { section: 0, position: 0 }, params: { ordinal: '01.0010' } },
    ]);
    mount();
    await screen.findByTestId('tpl-name');
    fireEvent.click(screen.getByTestId('tpl-save'));

    expect(await screen.findByTestId('tpl-warnings')).toBeTruthy();
    expect(api.put).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('tpl-save-anyway'));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
  });

  it('shows a built-in template read only and offers a copy instead', async () => {
    api.get.mockResolvedValue(detail({ id: 'residential', builtin: true, origin: 'builtin' }));
    api.post.mockResolvedValue(detail({ id: 'copy-1' }));
    nav.params = { templateId: 'residential' };
    mount();

    expect(await screen.findByTestId('tpl-readonly-notice')).toBeTruthy();
    expect((screen.getByTestId('tpl-name') as HTMLInputElement).disabled).toBe(true);
    expect(screen.queryByTestId('tpl-save')).toBeNull();

    fireEvent.click(screen.getByText('Duplicate to edit'));
    await waitFor(() => expect(nav.navigate).toHaveBeenCalledWith('/templates/copy-1'));
    expect(api.put).not.toHaveBeenCalled();
    nav.params = { templateId: 'tpl-1' };
  });
});

describe('template list helpers', () => {
  it('renumbers sections and positions in list order', () => {
    const out = renumberSections(detail().sections);
    expect(out[0]?.ordinal).toBe('01');
    expect(out[0]?.positions[0]?.ordinal).toBe('01.0010');
  });

  it('moves an item and ignores out-of-range moves', () => {
    expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a']);
    const same = ['a', 'b'];
    expect(moveItem(same, 0, -1)).toBe(same);
    expect(moveItem(same, 1, 2)).toBe(same);
  });
});
