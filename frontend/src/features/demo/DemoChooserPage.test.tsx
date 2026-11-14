// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const apiGet = vi.fn();
const fetchProjectList = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));
vi.mock('@/shared/lib/projectList', () => ({ fetchProjectList: () => fetchProjectList() }));
const changeLanguage = vi.fn();
vi.mock('@/app/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/app/i18n')>()),
  changeLanguage: (code: string) => {
    changeLanguage(code);
    return Promise.resolve();
  },
}));

import { DemoChooserPage } from './DemoChooserPage';
import { applyDemoMenuStyle } from '@/shared/lib/demoProfiles';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { FEATURED_ARTICLE_COVER, FEATURED_ARTICLE_URL } from './FeaturedArticle';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DemoChooserPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const PROJECTS = [
  { id: 'p1', name: 'London', metadata: { demo_id: 'office-london' } },
  { id: 'p2', name: 'Berlin', metadata: { demo_id: 'residential-berlin' } },
  { id: 'p3', name: 'Showcase', metadata: { demo_id: 'full-showcase-riyadh' } },
];
const SIX = [
  ...PROJECTS,
  { id: 'p4', name: 'Medical', metadata: { demo_id: 'medical-us' } },
  { id: 'p5', name: 'Toronto', metadata: { demo_id: 'condo-toronto' } },
  { id: 'p6', name: 'Belleville', metadata: { demo_id: 'school-paris' } },
  { id: 'p7', name: 'Lujiazui', metadata: { demo_id: 'office-shanghai' } },
];

describe('DemoChooserPage', () => {
  beforeEach(() => {
    apiGet.mockReset();
    fetchProjectList.mockReset();
    sessionStorage.clear();
    applyDemoMenuStyle(null);
    changeLanguage.mockReset();
    useDemoSessionStore.getState().setDemo(null);
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
  });

  it('puts the full platform first and highlights it', async () => {
    renderPage();
    const cards = await screen.findAllByTestId(/^demo-card-/);
    expect(cards.map((c) => c.getAttribute('data-testid'))).toEqual([
      'demo-card-full-showcase-riyadh',
      'demo-card-residential-berlin',
      'demo-card-office-london',
    ]);
    expect(cards[0]!.getAttribute('data-featured')).toBe('true');
    expect(cards[1]!.getAttribute('data-featured')).toBeNull();
    expect(screen.getByText('Full platform: every module')).toBeTruthy();
    expect(screen.getByText('Or start from a variant cut to one kind of company')).toBeTruthy();
  });

  it('shows the Berlin card only when that demo is installed', async () => {
    fetchProjectList.mockResolvedValue([PROJECTS[0]]);
    renderPage();
    await screen.findByTestId('demo-card-office-london');
    expect(screen.queryByTestId('demo-card-residential-berlin')).toBeNull();
  });

  it('applies the card menu style when a demo opens', async () => {
    renderPage();
    await userEvent.click(await screen.findByTestId('demo-card-residential-berlin'));
    await waitFor(() => expect(document.documentElement.dataset.oeMenu).toBe('outline'));
    await userEvent.click(screen.getByTestId('demo-card-full-showcase-riyadh'));
    await waitFor(() => expect(document.documentElement.dataset.oeMenu).toBeUndefined());
  });

  it('links the footer to the packs and settings pages', async () => {
    renderPage();
    await screen.findByTestId('demo-card-full-showcase-riyadh');
    expect(screen.getByTestId('demo-footer-packs').getAttribute('href')).toBe('/packs');
    expect(screen.getByTestId('demo-footer-settings').getAttribute('href')).toBe('/settings');
  });

  it('offers six company demos after the full platform', async () => {
    fetchProjectList.mockResolvedValue(SIX);
    renderPage();
    const cards = await screen.findAllByTestId(/^demo-card-/);
    expect(cards).toHaveLength(7);
    expect(screen.getByTestId('demo-standards-school-paris').textContent).toContain('DPGF');
    expect(screen.getByTestId('demo-standards-office-shanghai').textContent).toContain('GB 50500');
  });

  it('spans the full platform over two columns with the featured article in the third', async () => {
    renderPage();
    const card = await screen.findByTestId('demo-card-full-showcase-riyadh');
    const lead = screen.getByTestId('demo-chooser-lead');
    expect(lead.className).toContain('lg:grid-cols-3');
    expect(card.parentElement!.className).toContain('lg:col-span-2');
    const article = screen.getByTestId('demo-featured-article');
    expect(lead.contains(article)).toBe(true);
    expect(article.getAttribute('href')).toBe(FEATURED_ARTICLE_URL);
    expect(article.getAttribute('target')).toBe('_blank');
    expect(article.textContent).toContain('Uberization of Construction');
    expect(article.querySelector('img')!.getAttribute('src')).toBe(FEATURED_ARTICLE_COVER);
  });

  it('draws its own panel when the article cover cannot load', async () => {
    renderPage();
    const article = await screen.findByTestId('demo-featured-article');
    fireEvent.error(article.querySelector('img')!);
    expect(article.querySelector('img')).toBeNull();
  });

  it('names the sections a demo covers on its card', async () => {
    renderPage();
    const chips = await screen.findByTestId('demo-sections-residential-berlin');
    expect(chips.querySelectorAll('li').length).toBe(6);
    expect(chips.textContent).toContain('+5 more');
    expect(screen.queryByTestId('demo-sections-full-showcase-riyadh')).toBeNull();
  });

  it('switches the language first, then opens that market demo', async () => {
    fetchProjectList.mockResolvedValue(SIX);
    renderPage();
    const select = (await screen.findByTestId('demo-market-switch')) as HTMLSelectElement;
    expect(Array.from(select.options).filter((o) => !o.disabled)).toHaveLength(7);
    await userEvent.selectOptions(select, 'residential-berlin');
    await waitFor(() => expect(useDemoSessionStore.getState().slug).toBe('residential-berlin'));
    expect(changeLanguage).toHaveBeenCalledWith('de');
    expect(useProjectContextStore.getState().activeProjectId).toBe('p2');
    expect(useDemoSessionStore.getState().modules).toContain('/boq');
  });

  it('opening a card keeps the language and publishes the demo modules', async () => {
    fetchProjectList.mockResolvedValue(SIX);
    renderPage();
    await userEvent.click(await screen.findByTestId('demo-card-office-shanghai'));
    await waitFor(() => expect(useDemoSessionStore.getState().slug).toBe('office-shanghai'));
    expect(changeLanguage).not.toHaveBeenCalled();
    expect(useDemoSessionStore.getState().groups).toContain('grp_commercial');
  });
});
