import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN } from './testStrings';

const data = vi.hoisted(() => ({ summary: null as unknown }));
vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('./procurementApi', () => ({ fetchProcurement: vi.fn(async () => data.summary) }));

import { AddendumDrafts } from './AddendumDrafts';

const draft = (state: string, id: string) => ({ revision_id: 'r2', revision_number: 2, addendum_id: id, revision_no: 1,
  lines: 1, sheets: 3, elements: 2, state });

async function mount() {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({ lng: 'en', resources: { en: { translation: EN } }, keySeparator: false,
    nsSeparator: false, interpolation: { escapeValue: false } });
  return render(
    <I18nextProvider i18n={inst}>
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><AddendumDrafts projectId="p1" /></MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
}

describe('tender addendum drafts', () => {
  it('lists only unsent drafts and opens the package in Tendering to review and send', async () => {
    data.summary = { procurement: true, packages: [
      { ifc_class: 'IfcSlab', package_id: 'pk1', name: 'Design take-off: IfcSlab', status: 'issued', missing: false, lines: 1,
        url: '/tendering', addenda: [draft('draft', 'a1'), draft('published', 'a0')] },
      { ifc_class: 'IfcWall', package_id: 'pk2', name: 'Walls', status: 'draft', missing: false, lines: 1, url: '/tendering', addenda: [] },
    ] };
    await mount();
    const link = await screen.findByTestId('addendum-a1');
    expect(link).toHaveAttribute('href', '/tendering?package=pk1');
    expect(link).toHaveTextContent('Design take-off: IfcSlab: addendum 1 for design revision 2');
    expect(link).toHaveTextContent('Positions: 1 · linked elements: 2 · sheets: 3');
    expect(screen.queryByTestId('addendum-a0')).toBeNull();
    expect(screen.getByRole('heading')).toHaveTextContent('Tender addendum drafts to review: 1');
  });

  it('shows nothing when no draft waits', async () => {
    data.summary = { procurement: false };
    const { container } = await mount();
    await new Promise((r) => setTimeout(r, 20));
    expect(container.innerHTML).toBe('');
  });
});
