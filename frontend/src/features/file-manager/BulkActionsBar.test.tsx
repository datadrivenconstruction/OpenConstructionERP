// @ts-nocheck
/**
 * Unit tests for the bulk-delete dispatcher in ``BulkActionsBar``.
 *
 * Covers:
 *   1. ``groupByKind`` partitions rows by ``file.kind``.
 *   2. ``dispatchBulkDelete`` soft-deletes every selected row through the
 *      recycle bin (``softDelete`` from ``file-trash/api``), one call per
 *      row, regardless of kind, with ``Promise.allSettled`` so a 404 on
 *      one row doesn't abort siblings.
 *   3. Partial failure (some rows 200, others 404/403) flows through to a
 *      "warning" summary toast — full success → trash toasts only, full
 *      failure → "error".
 *
 * Since the W2 recycle-bin landed, the dispatcher's only external
 * dependency is ``softDelete`` from ``@/features/file-trash/api`` (the
 * legacy hard-delete path lives on under ``dispatchHardBulkDelete``). We
 * mock ``softDelete`` directly — testing the live ``fetch`` pipeline is
 * covered by the integration tests for the file-trash endpoint.
 */

import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
/* ── Recycle-bin layer mock — what the dispatcher actually calls ───── */

vi.mock('@/features/file-trash/api', () => {
  return {
    softDelete: vi.fn(),
    restoreFromTrash: vi.fn(async () => ({ id: 'restored' })),
    fileTrashKeys: { list: 'file-trash-list', stats: 'file-trash-stats' },
  };
});

import * as trashApi from '@/features/file-trash/api';
const softDeleteMock = trashApi.softDelete as unknown as ReturnType<typeof vi.fn>;

/* ── References check + hard batch delete ──────────────────────────── */

vi.mock('@/features/documents/api', async (importOriginal) => ({
  ...(await importOriginal()),
  fetchBatchDocumentReferences: vi.fn(),
}));

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal()),
  bulkDeleteDocuments: vi.fn(),
}));

import * as documentsApi from '@/features/documents/api';
import * as fileManagerApi from './api';
const fetchBatchMock = documentsApi.fetchBatchDocumentReferences as unknown as ReturnType<typeof vi.fn>;
const bulkDeleteDocumentsMock = fileManagerApi.bulkDeleteDocuments as unknown as ReturnType<typeof vi.fn>;

import {
  BulkActionsBar,
  dispatchBulkDelete,
  dispatchHardBulkDelete,
  groupByKind,
} from './components/BulkActionsBar';
import type { FileKind, FileRow } from './types';

/* ── Toast spy ─────────────────────────────────────────────────────── */

vi.mock('@/stores/useToastStore', () => {
  const addToast = vi.fn();
  return {
    useToastStore: Object.assign(
      (selector: (s: { addToast: typeof addToast }) => unknown) => selector({ addToast }),
      { getState: () => ({ addToast }) },
    ),
    __addToast: addToast,
  };
});

import * as toastMod from '@/stores/useToastStore';
const addToastSpy = (toastMod as unknown as { __addToast: ReturnType<typeof vi.fn> }).__addToast;

/* ── i18n stub ─────────────────────────────────────────────────────── */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const fallback = (opts?.defaultValue as string) ?? key;
      // tiny {{var}} substitution so we can assert on toast text
      return fallback.replace(/\{\{(\w+)\}\}/g, (_, name) =>
        opts && opts[name] !== undefined ? String(opts[name]) : `{{${name}}}`,
      );
    },
  }),
  // ``src/app/i18n.ts`` is pulled in transitively and calls
  // ``.use(initReactI18next)`` at module load — expose the noop plugin.
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

/* ── Fixtures ──────────────────────────────────────────────────────── */

function row(id: string, kind: FileKind): FileRow {
  return {
    id,
    kind,
    name: `${kind}-${id}.bin`,
    project_id: 'proj-001',
    size_bytes: 1024,
    mime_type: null,
    extension: null,
    modified_at: null,
    physical_path: '/tmp/x',
    relative_path: 'x',
    storage_backend: 'local',
    download_url: null,
    preview_url: null,
    thumbnail_url: null,
    discipline: null,
    category: null,
    extra: {},
  };
}

/* ── Call recorders driven by the mocked recycle-bin module ────────── */

// Every selected row, regardless of kind, is soft-deleted via one
// ``softDelete`` call. We record the ids that were soft-deleted per
// kind and let ``failIds`` make a given ``original_id`` reject (404).
let docDeleteIds: string[] = [];
let photoDeleteIds: string[] = [];
let bimDeleteIds: string[] = [];
let reportDeleteIds: string[] = [];
let failIds = new Set<string>();

const RECORDERS: Partial<Record<FileKind, string[]>> = {
  document: docDeleteIds,
  photo: photoDeleteIds,
  bim_model: bimDeleteIds,
  report: reportDeleteIds,
};

function resetApiMocks() {
  softDeleteMock.mockReset();

  softDeleteMock.mockImplementation(
    async (payload: { kind: FileKind; original_id: string; canonical_name?: string }) => {
      if (failIds.has(payload.original_id)) {
        throw new Error('Not found');
      }
      RECORDERS[payload.kind]?.push(payload.original_id);
      // ``dispatchBulkDelete`` reads ``res.value.id`` to build the trash
      // ids list, so return a minimal TrashItem-shaped object.
      return { id: `trash-${payload.original_id}`, original_id: payload.original_id };
    },
  );
}

resetApiMocks();

afterEach(() => {
  // Re-point the module-level recorder bindings at fresh arrays.
  docDeleteIds = [];
  photoDeleteIds = [];
  bimDeleteIds = [];
  reportDeleteIds = [];
  RECORDERS.document = docDeleteIds;
  RECORDERS.photo = photoDeleteIds;
  RECORDERS.bim_model = bimDeleteIds;
  RECORDERS.report = reportDeleteIds;
  failIds = new Set();
  addToastSpy.mockClear();
  resetApiMocks();
  cleanup();
});

/* ── groupByKind ───────────────────────────────────────────────────── */

describe('groupByKind', () => {
  it('partitions rows by their kind', () => {
    const groups = groupByKind([
      row('a', 'document'),
      row('b', 'photo'),
      row('c', 'document'),
      row('d', 'bim_model'),
    ]);
    expect(groups.get('document')?.map((r) => r.id)).toEqual(['a', 'c']);
    expect(groups.get('photo')?.map((r) => r.id)).toEqual(['b']);
    expect(groups.get('bim_model')?.map((r) => r.id)).toEqual(['d']);
  });
});

/* ── dispatchBulkDelete ────────────────────────────────────────────── */

describe('dispatchBulkDelete', () => {
  it('soft-deletes every selected row through the recycle bin, grouped by kind', async () => {
    const rows = [row('d1', 'document'), row('d2', 'document'), row('p1', 'photo')];
    const summary = await dispatchBulkDelete(rows, 'proj-001');

    // Every row — documents included — goes through one softDelete call.
    expect(softDeleteMock).toHaveBeenCalledTimes(3);
    expect(docDeleteIds).toEqual(['d1', 'd2']);
    expect(photoDeleteIds).toEqual(['p1']);
    // The payload carries the project id and the row's kind/id/name.
    expect(softDeleteMock).toHaveBeenCalledWith(
      expect.objectContaining({
        project_id: 'proj-001',
        kind: 'document',
        original_id: 'd1',
      }),
    );
    expect(summary.total).toBe(3);
    expect(summary.deleted).toBe(3);
    expect(summary.failed).toBe(0);
    // Successful rows produce trash ids for the Undo / Recycle-Bin toast.
    expect(summary.trashIds.map((t) => t.id)).toEqual(['d1', 'd2', 'p1']);
  });

  it('records per-row failures from a partial 404 without aborting siblings', async () => {
    failIds = new Set(['p2']);
    const rows = [row('p1', 'photo'), row('p2', 'photo'), row('m1', 'bim_model')];
    const summary = await dispatchBulkDelete(rows, 'proj-001');

    expect(photoDeleteIds).toEqual(['p1']); // p2 rejected
    expect(bimDeleteIds).toEqual(['m1']);
    expect(summary.total).toBe(3);
    expect(summary.deleted).toBe(2);
    expect(summary.failed).toBe(1);
    const photoResult = summary.perKind.find((r) => r.kind === 'photo');
    expect(photoResult?.failed).toHaveLength(1);
    expect(photoResult?.failed[0]!.id).toBe('p2');
  });
});

/* ── BulkActionsBar component-level partial-failure toast ──────────── */

function renderBar(rows: FileRow[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BulkActionsBar selectedRows={rows} projectId="proj-001" onClear={() => {}} />
    </QueryClientProvider>,
  );
}

describe('BulkActionsBar - partial failure summary toast', () => {
  it('emits a warning toast with succeeded/failed counts when one row 404s', async () => {
    failIds = new Set(['p2']);
    renderBar([row('p1', 'photo'), row('p2', 'photo'), row('r1', 'report')]);

    // Two-step confirm: open the inline confirm, then click Delete.
    fireEvent.click(screen.getAllByRole('button', { name: /^Delete$/ })[0]!);
    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }));

    await waitFor(() => {
      expect(addToastSpy).toHaveBeenCalled();
    });

    // The summary "warning" toast is pushed last (after the Recycle-Bin
    // info toast for the surviving rows), so .at(-1) is the warning.
    const lastCall = addToastSpy.mock.calls.at(-1)![0];
    expect(lastCall.type).toBe('warning');
    expect(lastCall.title).toMatch(/2 of 3 deleted/);
    expect(lastCall.message).toMatch(/1 file\(s\) could not be deleted/);
  });
});

/* ── What the bulk delete severs ───────────────────────────────────── */

describe('BulkActionsBar - references warning on the delete confirm', () => {
  it('asks about the selected documents only, and shows the answer before Delete', async () => {
    fetchBatchMock.mockReset();
    fetchBatchMock.mockResolvedValue({
      checked: 2,
      referenced_documents: 1,
      total: 2,
      strands: 2,
      unlinks: 0,
      retains: 0,
      references: [
        { key: 'Sheet.document_id', module: 'documents', model: 'Sheet', impact: 'strands', count: 2 },
      ],
      documents: [
        { document_id: 'd1', total: 2, strands: 2, unlinks: 0, retains: 0, references: [] },
      ],
    });
    renderBar([row('d1', 'document'), row('d2', 'document'), row('p1', 'photo')]);

    // Nothing is asked before the person opens the confirm.
    expect(fetchBatchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: /^Delete$/ })[0]!);

    expect(await screen.findByText('What still links to the selected files')).toBeInTheDocument();
    expect(fetchBatchMock).toHaveBeenCalledTimes(1);
    expect(fetchBatchMock.mock.calls[0]![0]).toEqual(['d1', 'd2']);
    expect(screen.getByText('document-d1.bin')).toBeInTheDocument();
    expect(screen.getByText('2 records will be left pointing at nothing')).toBeInTheDocument();
    // Advisory: the Delete button is still there to press.
    expect(screen.getByRole('button', { name: /^Delete$/ })).toBeEnabled();
  });

  it('does not ask when the selection holds no document', async () => {
    fetchBatchMock.mockReset();
    renderBar([row('p1', 'photo'), row('r1', 'report')]);
    fireEvent.click(screen.getAllByRole('button', { name: /^Delete$/ })[0]!);
    await screen.findByText(/Delete 2 file\(s\)\?/);
    expect(fetchBatchMock).not.toHaveBeenCalled();
  });
});

describe('dispatchHardBulkDelete - references acknowledgement', () => {
  it('does not acknowledge on behalf of the caller', async () => {
    bulkDeleteDocumentsMock.mockReset();
    bulkDeleteDocumentsMock.mockResolvedValue({ requested: 1, deleted: 1 });
    await dispatchHardBulkDelete([row('d1', 'document')]);
    expect(bulkDeleteDocumentsMock).toHaveBeenCalledWith(['d1'], false);

    await dispatchHardBulkDelete([row('d1', 'document')], { acknowledgeReferences: true });
    expect(bulkDeleteDocumentsMock).toHaveBeenLastCalledWith(['d1'], true);
  });

  it('reports a refused batch as failed rows carrying the server message', async () => {
    bulkDeleteDocumentsMock.mockReset();
    bulkDeleteDocumentsMock.mockRejectedValue(new Error('Records elsewhere still point at documents in this batch.'));
    const summary = await dispatchHardBulkDelete([row('d1', 'document'), row('d2', 'document')]);
    expect(summary.deleted).toBe(0);
    expect(summary.failed).toBe(2);
    expect(summary.perKind[0]!.failed[0]!.message).toMatch(/still point at documents/);
  });
});
