import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n from 'i18next';
import { I18nextProvider, initReactI18next } from 'react-i18next';
import { EN, RU, DE } from './testStrings';
import type { LinkStatusView } from './linksApi';

const h = vi.hoisted(() => ({ status: null as LinkStatusView | null, revoke: vi.fn() }));

vi.mock('react-i18next', async () => await vi.importActual('react-i18next'));
vi.mock('./linksApi', () => ({
  fetchLinkStatus: async () => h.status,
  revokeEditor: (...a: unknown[]) => h.revoke(...a),
}));
vi.mock('@/shared/ui', () => ({
  Button: ({ children, loading, icon: _i, variant: _v, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; icon?: unknown; variant?: string }) =>
    <button type="button" {...rest} disabled={rest.disabled || loading}>{children}</button>,
  Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  CardHeader: ({ title }: { title: string }) => <header>{title}</header>,
}));

import { LinkStatus } from './LinkStatus';

async function mount(lang: 'en' | 'ru' | 'de' = 'en') {
  const inst = i18n.createInstance();
  await inst.use(initReactI18next).init({
    lng: lang, fallbackLng: 'en', resources: { en: { translation: EN }, ru: { translation: RU }, de: { translation: DE } },
    keySeparator: false, nsSeparator: false, interpolation: { escapeValue: false },
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <I18nextProvider i18n={inst}>
      <QueryClientProvider client={qc}><MemoryRouter><LinkStatus projectId="p1" /></MemoryRouter></QueryClientProvider>
    </I18nextProvider>,
  );
}

const editor = { id: 'e1', client_name: 'OpenConstructionDesign', client_version: '0.9.1', client_os: 'windows', mine: true,
  linked_at: '2026-11-20T10:00:00Z', last_used_at: '2026-11-25T09:30:00Z', expires_at: '2026-12-20T10:00:00Z' };

afterEach(() => { cleanup(); h.revoke.mockReset(); });

describe('LinkStatus', () => {
  it('says plainly that no editor is linked', async () => {
    h.status = { editors: [], pending_revisions: 0, last_revision_at: null, last_revision: null };
    await mount();
    expect(await screen.findByTestId('link-state')).toHaveTextContent('No editor is linked to this project.');
    expect(screen.queryByTestId('link-pending')).toBeNull();
  });

  it('shows the editor, its last sync and the pending revisions, in Russian too', async () => {
    h.status = { editors: [editor], pending_revisions: 2, last_revision_at: '2026-11-25T09:31:00Z', last_revision: { revision_id: 'r7', number: 7, status: 'shared', source_kind: 'editor', package_sha256: 'ab12', author: 'Anna Petrova', received_at: '2026-11-25T09:31:00Z' } };
    await mount('ru');
    expect(await screen.findByTestId('link-state')).toHaveTextContent('Подключённых редакторов: 1');
    expect(screen.getByTestId('link-editor')).toHaveTextContent('OpenConstructionDesign 0.9.1');
    expect(screen.getByTestId('link-editor')).toHaveTextContent('Последняя синхронизация');
    expect(screen.getByTestId('link-pending')).toHaveTextContent('Ревизий ждут решения: 2');
    expect(screen.getByTestId('link-last-revision')).toHaveTextContent('Ревизия 7');
    expect(screen.getByTestId('link-last-revision')).toHaveTextContent('Anna Petrova');
  });

  it('unlinks an editor on request', async () => {
    h.status = { editors: [editor], pending_revisions: 0, last_revision_at: null, last_revision: null };
    h.revoke.mockResolvedValue(undefined);
    await mount('de');
    await userEvent.click(await screen.findByRole('button', { name: 'Trennen' }));
    await waitFor(() => expect(h.revoke).toHaveBeenCalledWith('p1', 'e1'));
  });
});
