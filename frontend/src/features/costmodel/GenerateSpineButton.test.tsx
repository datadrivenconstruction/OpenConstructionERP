// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for <GenerateSpineButton>.
//
// Covers:
//   1. Clicking the button calls generateSpine and, on success, shows a toast
//      whose message names the created control-account / cost-line counts.
//   2. On success the ['spine', projectId] query is invalidated so the spine
//      panel refetches.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/* ── i18n shim with interpolation (so the toast message carries counts) ──
 * The component pulls in `@/shared/ui` -> ErrorBoundary -> app/i18n.ts, which
 * imports `initReactI18next`, so the mock must export the full surface the
 * global setup provides (Trans / initReactI18next / I18nextProvider) on top
 * of the interpolating `t`. */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string } & Record<string, unknown>) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in opts) {
        let dv = opts.defaultValue ?? '';
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return _key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

/* ── Toast mock ────────────────────────────────────────────────────────── */

const toastMocks = vi.hoisted(() => ({ addToastMock: vi.fn() }));
const addToastMock = toastMocks.addToastMock;
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: { addToast: typeof toastMocks.addToastMock }) => unknown) =>
      selector({ addToast: toastMocks.addToastMock }),
    { getState: () => ({ addToast: toastMocks.addToastMock }) },
  ),
}));

/* ── API mock ──────────────────────────────────────────────────────────── */

const apiMocks = vi.hoisted(() => ({ generateSpineMock: vi.fn() }));
const generateSpineMock = apiMocks.generateSpineMock;
vi.mock('./api', () => ({
  costModelApi: { generateSpine: apiMocks.generateSpineMock },
}));

import { ApiError } from '@/shared/lib/api';
import { GenerateSpineButton } from './GenerateSpineButton';

afterEach(() => {
  cleanup();
  generateSpineMock.mockReset();
  addToastMock.mockReset();
});

function renderButton(projectId = 'proj-1') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
  return {
    invalidateSpy,
    ...render(
      <QueryClientProvider client={client}>
        <GenerateSpineButton projectId={projectId} />
      </QueryClientProvider>,
    ),
  };
}

describe('<GenerateSpineButton>', () => {
  it('shows a toast with the created counts on success', async () => {
    generateSpineMock.mockResolvedValueOnce({ accounts_created: 5, cost_lines_created: 42 });
    renderButton();

    fireEvent.click(screen.getByRole('button', { name: /Generate from BOQ/i }));

    await waitFor(() => expect(generateSpineMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(addToastMock).toHaveBeenCalledTimes(1));

    const toast = (addToastMock.mock.calls[0]?.[0] ?? {}) as {
      type: string;
      title: string;
      message: string;
    };
    expect(toast.type).toBe('success');
    expect(toast.message).toContain('5');
    expect(toast.message).toContain('42');
  });

  it('invalidates the ["spine", projectId] query on success', async () => {
    generateSpineMock.mockResolvedValueOnce({ accounts_created: 1, cost_lines_created: 1 });
    const { invalidateSpy } = renderButton('proj-99');

    fireEvent.click(screen.getByRole('button', { name: /Generate from BOQ/i }));

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['spine', 'proj-99'] }),
    );
  });

  it('names the positions left in suspense with a warning toast', async () => {
    generateSpineMock.mockResolvedValueOnce({
      accounts_created: 2,
      cost_lines_created: 3,
      positions_in_suspense: 4,
      suspense_amount: '1250.50',
    });
    renderButton();

    fireEvent.click(screen.getByRole('button', { name: /Generate from BOQ/i }));

    await waitFor(() => expect(addToastMock).toHaveBeenCalledTimes(1));
    const toast = addToastMock.mock.calls[0]?.[0] as { type: string; message: string };
    expect(toast.type).toBe('warning');
    expect(toast.message).toContain('Positions without a code of this list: 4');
    expect(toast.message).toMatch(/1[,.\s\u00a0\u202f]?250/);
  });

  it('shows the structure mismatch as a sentence naming both lists', async () => {
    generateSpineMock.mockRejectedValueOnce(
      new ApiError(409, 'Conflict', {
        detail: {
          problem: 'structure_standard_mismatch',
          message: 'mismatch',
          params: { standard: 'din276', requested: 'nrm1' },
        },
      }),
    );
    renderButton();

    fireEvent.click(screen.getByRole('button', { name: /Generate from BOQ/i }));

    await waitFor(() => expect(addToastMock).toHaveBeenCalledTimes(1));
    const toast = addToastMock.mock.calls[0]?.[0] as { type: string; message: string };
    expect(toast.type).toBe('error');
    expect(toast.message).toBe(
      'The cost structure is built on din276, so it cannot take codes of nrm1.',
    );
  });

  it('passes the projectId through to generateSpine', async () => {
    generateSpineMock.mockResolvedValueOnce({ accounts_created: 0, cost_lines_created: 0 });
    renderButton('proj-7');

    fireEvent.click(screen.getByRole('button', { name: /Generate from BOQ/i }));

    await waitFor(() => expect(generateSpineMock).toHaveBeenCalledTimes(1));
    expect(generateSpineMock.mock.calls[0]?.[0]).toBe('proj-7');
  });
});
