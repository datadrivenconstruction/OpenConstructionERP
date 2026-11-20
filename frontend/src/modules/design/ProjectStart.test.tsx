import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU } from './testStrings';

const api = vi.hoisted(() => ({
  brief: null as unknown,
  extraction: null as unknown,
  templates: null as unknown,
  templatesFail: false,
  aiSettings: { anthropic_api_key_set: true } as unknown,
  save: vi.fn(),
  confirm: vi.fn(),
  extract: vi.fn(),
  post: vi.fn(),
  upload: vi.fn(),
}));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path === '/v1/design/templates') {
      if (api.templatesFail) throw new Error('templates down');
      return api.templates;
    }
    throw new Error(`unexpected ${path}`);
  }),
  apiPost: vi.fn(async (path: string, body: unknown) => api.post(path, body)),
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock('@/features/documents/api', () => ({ uploadDocument: (...a: unknown[]) => api.upload(...a) }));
vi.mock('@/features/projects/api', () => ({
  projectsApi: { get: vi.fn(async () => ({ id: 'p1', name: 'Haus', country_code: 'DE', locale: 'de', currency: 'EUR', address: null })) },
}));
vi.mock('./api', () => ({
  LINK_VERSION: '1',
  fetchBrief: vi.fn(async () => api.brief),
  fetchAiSettings: vi.fn(async () => api.aiSettings),
  extractBrief: (...a: unknown[]) => api.extract(...a),
  saveBrief: (...a: unknown[]) => api.save(...a),
  confirmBrief: (...a: unknown[]) => api.confirm(...a),
}));
vi.mock('./PlotEditor', () => ({
  PlotEditor: ({ onChange }: { onChange: (p: string, v: unknown) => void }) => (
    <button type="button" onClick={() => onChange('/site/plot', {
      type: 'Polygon', coordinates: [[[12.37, 51.34], [12.3707, 51.34], [12.3707, 51.3402], [12.37, 51.3402], [12.37, 51.34]]],
    })}>draw-plot</button>
  ),
}));
vi.mock('@/shared/ui', () => ({
  Button: ({ children, onClick, loading: _l, variant: _v, size: _s, icon, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & Record<string, unknown>) => (
    <button type="button" onClick={onClick} {...(rest as object)}>{icon as ReactNode}{children}</button>),
  ErrorState: ({ title, onRetry }: { title: string; onRetry?: () => void }) => (
    <div role="alert">{title}<button type="button" onClick={onRetry}>retry</button></div>),
  Skeleton: () => <div aria-busy="true" />,
}));

import { ProjectStart } from './ProjectStart';

const TEMPLATES = {
  source: 'editor', templates: [
    { id: 'residential_block', typology: 'apartment_section', max_floors: 40, source: 'editor', values: [
      { pointer: '/use/category', value: 'residential_multi', doubtful: false },
      { pointer: '/generator/template', value: 'apartment_section', doubtful: false },
      { pointer: '/massing/floor_height_m', value: 3, doubtful: true }] },
    { id: 'school', typology: 'school', max_floors: 5, source: 'editor', values: [
      { pointer: '/use/category', value: 'school', doubtful: false },
      { pointer: '/generator/template', value: 'school', doubtful: false },
      { pointer: '/massing/floor_height_m', value: 3.6, doubtful: true }] },
  ],
};

const EXTRACTION = {
  brief: {
    schema: 'ddc-brief/1', brief_id: 'b', project_id: 'p1', version: 1,
    massing: { floors_above: 5, floor_height_m: 3.1 }, use: {}, programme: {},
    provenance: {
      '/massing/floors_above': { status: 'proposed', sources: [{ kind: 'text', quote: 'five storeys' }] },
      '/massing/floor_height_m': { status: 'proposed', sources: [{ kind: 'text' }] },
    },
  },
  rejected: [], notes: [], used_model: 'm', tokens: 1,
  summary: { proposed: ['/massing/floors_above', '/massing/floor_height_m'], defaults: [], questions: [], rejected: 0 },
};

async function mount(lang = 'en', steps: { id: string; done: boolean; count: number | null; url: string }[] = []) {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(
    <I18nextProvider i18n={inst}>
      <QueryClientProvider client={qc}>
        <MemoryRouter><ProjectStart projectId="p1" steps={steps as never} /></MemoryRouter>
      </QueryClientProvider>
    </I18nextProvider>,
  );
  await screen.findByTestId('project-start');
  return user;
}

beforeEach(() => {
  cleanup();
  api.brief = null;
  api.templates = TEMPLATES;
  api.templatesFail = false;
  api.aiSettings = { anthropic_api_key_set: true };
  for (const f of [api.save, api.confirm, api.extract, api.post, api.upload]) f.mockReset();
  api.save.mockImplementation(async (_p: string, doc: object) => ({ ...doc, version: 1 }));
  api.confirm.mockImplementation(async () => ({ ...(EXTRACTION.brief as object), version: 2 }));
  api.extract.mockResolvedValue(EXTRACTION);
});

describe('project start', () => {
  it('offers four equal ways as tabs, moved with the arrow keys, Home and End', async () => {
    const user = await mount();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual([
      EN['design.start.way.describe'] + EN['design.start.way.describe_hint'],
      EN['design.start.way.upload'] + EN['design.start.way.upload_hint'],
      EN['design.start.way.template'] + EN['design.start.way.template_hint'],
      EN['design.start.way.map'] + EN['design.start.way.map_hint'],
    ]);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    tabs[0]!.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('way-upload')).toHaveAttribute('aria-selected', 'true');
    expect(document.activeElement).toBe(screen.getByTestId('way-upload'));
    await user.keyboard('{End}');
    expect(screen.getByTestId('way-map')).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('way-describe')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('start-path')).toBeTruthy();
  });

  it('describe: AI reads the text, one summary shows all values with sources, doubtful first; one button confirms', async () => {
    const user = await mount();
    await user.type(await screen.findByLabelText(EN['design.start.describe.label']), 'five storeys');
    await user.click(screen.getByRole('button', { name: EN['design.start.describe.read'] }));
    const summary = await screen.findByTestId('proposal-summary');
    expect(api.extract).toHaveBeenCalledWith('p1', 'five storeys', null);
    const rows = within(summary).getAllByRole('listitem');
    expect(rows[0]).toHaveAttribute('data-doubt', 'no_quote'); // floor height: no quote -> first, highlighted
    expect(rows[0]).toHaveTextContent(EN['design.start.doubt.no_quote']);
    expect(rows[1]).toHaveTextContent('five storeys');
    expect(screen.getByTestId('summary-counts')).toHaveTextContent('to check: 1');
    // correct the doubtful value
    await user.click(within(rows[0]!).getByRole('button', { name: /Correct/ }));
    const input = within(rows[0]!).getByRole('textbox');
    await user.clear(input);
    await user.type(input, '3,0{Enter}');
    expect(rows[0]).toHaveTextContent(EN['design.start.corrected']);
    expect(screen.getByTestId('summary-counts')).not.toHaveTextContent('to check');
    await user.click(screen.getByTestId('confirm-all'));
    await waitFor(() => expect(api.confirm).toHaveBeenCalled());
    const [, pointers, version] = api.confirm.mock.calls[0]!;
    expect((pointers as string[]).sort()).toEqual(['/massing/floor_height_m', '/massing/floors_above']);
    expect(version).toBe(1);
    expect((api.save.mock.calls[0]![1] as { massing: object }).massing).toEqual({ floors_above: 5, floor_height_m: 3 });
    expect(await screen.findByTestId('start-done')).toHaveTextContent('2 values confirmed; brief version 2 saved.');
    expect(screen.getByTestId('start-next-model')).toHaveAttribute('href', '/design/revisions');
  });

  it('describe again: what is already confirmed is said, not "nothing found"', async () => {
    api.extract.mockResolvedValue({ ...EXTRACTION, brief: { ...EXTRACTION.brief, provenance: {} },
      summary: { proposed: [], defaults: [], questions: [], rejected: 0, confirmed: ['/massing/floors_above'] } });
    const user = await mount();
    await user.type(await screen.findByLabelText(EN['design.start.describe.label']), 'five storeys');
    await user.click(screen.getByRole('button', { name: EN['design.start.describe.read'] }));
    expect(await screen.findByTestId('summary-empty')).toHaveTextContent(EN['design.start.summary.known'].replace('{{count}}', '1'));
  });

  it('a value can be left out, and Ctrl+Enter confirms the rest', async () => {
    const user = await mount();
    await user.type(await screen.findByLabelText(EN['design.start.describe.label']), 'x');
    await user.click(screen.getByRole('button', { name: EN['design.start.describe.read'] }));
    await screen.findByTestId('proposal-summary');
    await user.click(screen.getByRole('button', { name: 'Leave out Floor height' }));
    expect(screen.getByTestId('confirm-all')).toHaveTextContent('Confirm all (1)');
    await user.keyboard('{Control>}{Enter}{/Control}');
    await waitFor(() => expect(api.confirm).toHaveBeenCalledWith('p1', ['/massing/floors_above'], 1));
  });

  it('template: picked from a radio group by keyboard, typical values marked, nothing stored before confirming', async () => {
    const user = await mount();
    await user.click(screen.getByTestId('way-template'));
    const first = await screen.findByTestId('template-residential_block');
    expect(screen.getByTestId('start-use-template')).toBeDisabled();
    first.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('template-school')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByTestId('template-school')).toHaveTextContent('up to 5 storeys');
    await user.click(screen.getByTestId('start-use-template'));
    const summary = await screen.findByTestId('proposal-summary');
    expect(summary).toHaveAttribute('data-origin', 'template');
    expect(within(summary).getAllByRole('listitem')[0]).toHaveTextContent(EN['design.start.doubt.typical']);
    // every row reads as words: field names and template values translated, lengths with their unit
    expect(summary.textContent).not.toMatch(/design\.|apartment_section/);
    expect(summary).toHaveTextContent(EN['design.field.generator.template']);
    expect(summary).toHaveTextContent('3.6 m');
    expect(api.save).not.toHaveBeenCalled();
    await user.click(screen.getByTestId('confirm-all'));
    await waitFor(() => expect(api.confirm).toHaveBeenCalled());
    const saved = api.save.mock.calls[0]![1] as { use: object; generator: object; name: string };
    expect(saved.use).toEqual({ category: 'school' });
    expect(saved.generator).toEqual({ template: 'school' });
    expect(saved.name).toBe('Haus'); // new brief prefilled from the project
    expect(api.save.mock.calls[0]![3]).toBe(true); // still a draft: required values are missing
  });

  it('template list failing to load says so and retries', async () => {
    api.templatesFail = true;
    const user = await mount();
    await user.click(screen.getByTestId('way-template'));
    expect(await screen.findByRole('alert')).toHaveTextContent(EN['design.start.template.failed']);
    api.templatesFail = false;
    await user.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByTestId('template-school')).toBeTruthy();
  });

  it('upload: refuses other file types, uploads to Documents, AI reads them and cites the file and page', async () => {
    api.upload.mockImplementation(async (_p: string, f: File, cat: string) => ({ id: `doc-${f.name}`, cat }));
    api.post.mockResolvedValue({
      ...EXTRACTION,
      brief: { ...EXTRACTION.brief, provenance: { ...EXTRACTION.brief.provenance,
        '/massing/floors_above': { status: 'proposed', sources: [{ kind: 'document', document_id: 'doc-plan.pdf', page: 3, quote: '5 OG' }] } } },
    });
    const user = await mount();
    await user.click(screen.getByTestId('way-upload'));
    const input = screen.getByLabelText(EN['design.start.upload.pick'], { selector: 'input' });
    fireEvent.change(input, { target: { files: [new File(['%PDF'], 'plan.pdf', { type: 'application/pdf' }), new File(['x'], 'notes.docx')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('Not added: notes.docx');
    await waitFor(() => expect(screen.getByTestId('start-files')).toHaveTextContent(EN['design.start.upload.ready']));
    expect(api.upload).toHaveBeenCalledWith('p1', expect.any(File), 'drawing');
    await user.click(screen.getByTestId('start-read-files'));
    const summary = await screen.findByTestId('proposal-summary');
    expect(api.post).toHaveBeenCalledWith('/v1/design/projects/p1/brief/extract',
      { document_ids: ['doc-plan.pdf'], text: null, use_ai: true, base: null });
    expect(summary).toHaveTextContent('plan.pdf, page 3');
  });

  it('map: the outline is proposed only once drawn, shown with its area', async () => {
    const user = await mount();
    await user.click(screen.getByTestId('way-map'));
    expect(screen.getByTestId('start-use-plot')).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'draw-plot' }));
    await user.click(screen.getByTestId('start-use-plot'));
    const summary = await screen.findByTestId('proposal-summary');
    expect(summary).toHaveTextContent(/Plot outline, [\d,.]+ m²/);
    expect(summary).toHaveTextContent(EN['design.start.source.map']);
  });

  it('without AI settings it says so and links to them', async () => {
    api.aiSettings = {};
    await mount();
    expect(await screen.findByTestId('start-no-ai')).toHaveTextContent(EN['design.start.ai_settings']);
  });

  it('speaks Russian', async () => {
    await mount('ru');
    expect(screen.getByText(RU['design.start.title'])).toBeTruthy();
    expect(screen.getByTestId('way-map')).toHaveTextContent(RU['design.start.way.map']);
  });
});
