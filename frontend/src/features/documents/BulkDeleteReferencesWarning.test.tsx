/**
 * The bulk delete warning: what a multi-file delete severs, before Delete.
 *
 * The panel reads one batch request and has to keep the single panel's rules:
 * silent while nothing links to the selection, explicit when the check failed
 * (an absent panel would read as "nothing links"), and never a stale answer.
 * On top it names the linked files, which only a selection needs.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  fetchDocumentReferences: vi.fn(),
  fetchBatchDocumentReferences: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const fallback = (opts?.defaultValue as string | undefined) ?? key;
      return fallback.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
        opts && opts[name] !== undefined ? String(opts[name]) : `{{${name}}}`,
      );
    },
  }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import * as api from './api';
import type { DocumentBatchReferences } from './api';
import { BulkDeleteReferencesWarning } from './DocumentDeleteWarning';

const fetchBatch = vi.mocked(api.fetchBatchDocumentReferences);

function renderPanel(documentIds: string[], namesById?: Record<string, string>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BulkDeleteReferencesWarning documentIds={documentIds} namesById={namesById} />
    </QueryClientProvider>,
  );
}

function answer(over: Partial<DocumentBatchReferences> = {}): DocumentBatchReferences {
  return {
    checked: 0,
    referenced_documents: 0,
    total: 0,
    strands: 0,
    unlinks: 0,
    retains: 0,
    references: [],
    documents: [],
    ...over,
  };
}

function perDoc(id: string, strands: number, unlinks: number) {
  return {
    document_id: id,
    total: strands + unlinks,
    strands,
    unlinks,
    retains: 0,
    references: [],
  };
}

afterEach(() => {
  cleanup();
  fetchBatch.mockReset();
});

describe('BulkDeleteReferencesWarning', () => {
  it('asks once, about the selection in a stable order', async () => {
    fetchBatch.mockResolvedValue(answer({ checked: 2 }));
    renderPanel(['b', 'a']);
    await waitFor(() => expect(fetchBatch).toHaveBeenCalledTimes(1));
    expect(fetchBatch.mock.calls[0]![0]).toEqual(['a', 'b']);
  });

  it('renders nothing when nothing links to the selection', async () => {
    fetchBatch.mockResolvedValue(answer({ checked: 2 }));
    const { container } = renderPanel(['a', 'b']);
    await waitFor(() => expect(fetchBatch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('does not ask at all for an empty selection', () => {
    const { container } = renderPanel([]);
    expect(fetchBatch).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it('says the check failed instead of going quiet', async () => {
    fetchBatch.mockRejectedValue(new Error('boom'));
    renderPanel(['a']);
    expect(
      await screen.findByText('Could not check what links to the selected files'),
    ).toBeInTheDocument();
  });

  it('names the linked files, heaviest first, and folds the rest into a count', async () => {
    fetchBatch.mockResolvedValue(
      answer({
        checked: 5,
        referenced_documents: 4,
        total: 9,
        strands: 3,
        unlinks: 6,
        references: [
          { key: 'Sheet.document_id', module: 'documents', model: 'Sheet', impact: 'strands', count: 3 },
          { key: 'PunchItem.document_id', module: 'punchlist', model: 'PunchItem', impact: 'unlinks', count: 6 },
        ],
        documents: [perDoc('d1', 3, 0), perDoc('d2', 0, 3), perDoc('d3', 0, 2), perDoc('d4', 0, 1)],
      }),
    );
    renderPanel(['d1', 'd2', 'd3', 'd4', 'd5'], {
      d1: 'A-101.pdf',
      d2: 'A-102.pdf',
      d3: 'A-103.pdf',
      d4: 'A-104.pdf',
      d5: 'A-105.pdf',
    });

    expect(await screen.findByText('What still links to the selected files')).toBeInTheDocument();
    expect(screen.getByText(/4 selected documents are still linked/)).toBeInTheDocument();
    expect(screen.getByText('A-101.pdf, A-102.pdf, A-103.pdf +1 more')).toBeInTheDocument();
    // The breakdown is the single panel's: counted headline per consequence.
    expect(screen.getByText('3 records will be left pointing at nothing')).toBeInTheDocument();
    expect(screen.getByText('6 records lose the attachment')).toBeInTheDocument();
    // A file that links nothing is not named.
    expect(screen.queryByText(/A-105\.pdf/)).toBeNull();
  });
});
