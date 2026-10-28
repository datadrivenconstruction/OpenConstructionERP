// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectFilePicker - open a file that is ALREADY in the project, instead of
 * re-uploading the same drawing from disk.
 *
 * Every viewer/takeoff module used to offer a local upload only. If the
 * drawing had already been filed in the project, the user had to find it on
 * their own machine again, and the project ended up with two copies of it.
 * This picker lists the stored files the calling module can actually open,
 * filtered by the module's own declared formats.
 *
 * The module declares what it opens; the pure matcher in
 * ``shared/lib/projectFileFormats`` decides what qualifies. Formats that only
 * become viewable after the DDC cad2data conversion (RVT, IFC) are shown with
 * a "needs conversion" note rather than being offered as an instant open, and
 * formats that another module handles (DWG in the BIM viewer) say so. Nothing
 * is offered that would silently fail to load.
 *
 * TWO SOURCES, ONE DIALOG. "Project files" is not one store. The documents
 * module has its filing cabinet, and a viewer module can have its own - PDF
 * takeoff keeps sheets in ``oe_takeoff_document``, where an uploaded or seeded
 * plan exists and nowhere else. A dialog that promised "project files" and
 * listed only the documents module told the user something false: a plan open
 * in that very module could not be found in it by name. Passing
 * ``moduleKinds`` federates the sources - one project-scoped,
 * permission-checked, paged request to the file manager, grouped by the module
 * each row came from and named on screen. Narrowing the label instead would
 * have made the sentence true and the feature useless.
 *
 * The federation is server-side on purpose. Merging two paginated listings in
 * the browser would search page one of each and call the result "the project".
 *
 * This ADDS a way to open a file. Every caller keeps its local-upload path.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { FileText, FolderOpen, Loader2, Search, Wand2 } from 'lucide-react';

import {
  downloadDocumentBlob,
  fetchDocuments,
  type DocumentItem,
} from '@/features/documents/api';
import { fetchFileList } from '@/features/file-manager/api';
import type { FileKind, FileRow } from '@/features/file-manager/types';
import { getAuthToken, type Page } from '@/shared/lib/api';
import { formatFileSize } from '@/shared/lib/formatters';
import {
  acceptedFormatLabel,
  filterProjectFiles,
  matchProjectFile,
  type AcceptedFormat,
  type ProjectFileMatch,
} from '@/shared/lib/projectFileFormats';

import { TruncationNotice } from './TruncationNotice';
import { WideModal } from './WideModal';

/** How many rows one federated request asks for. The endpoint caps at 2000;
 *  a picker that had to page would be a worse answer than one that says how
 *  much it is showing, which ``TruncationNotice`` does below. */
const FEDERATED_PAGE_SIZE = 500;

/** Debounce for the server-side search, in ms. */
const SEARCH_DEBOUNCE_MS = 250;

/**
 * Download a stored project document and wrap it in a ``File``, so a picked
 * file can be handed to the exact same handler a local upload uses.
 *
 * Every viewer module already has a working "here is a File, open it" path
 * (validated, instrumented, with its own error handling). Reusing it is what
 * keeps this feature additive: the picker becomes another way to produce a
 * File rather than a second, divergent loading pipeline. ``fetchDocuments``
 * is auth-aware and so is ``downloadDocumentBlob`` - a bare URL handed to a
 * loader would 401.
 */
export async function projectDocumentToFile(doc: DocumentItem): Promise<File> {
  const blob = await downloadDocumentBlob(doc.id);
  return new File([blob], doc.name, {
    // Prefer the blob's own type; the stored mime_type is nullable and is
    // frequently wrong for CAD payloads (see projectFileFormats).
    type: blob.type || doc.mime_type || 'application/octet-stream',
  });
}

/**
 * The same thing as ``projectDocumentToFile``, for a row that may have come
 * from any of the federated stores.
 *
 * The helper above only knows the documents module, so a caller that federates
 * would have had to learn each other module's download route to reuse its own
 * "here is a File, open it" path. Every collected row already carries the
 * authenticated URL its own module serves, which makes one fetch enough and
 * keeps the picker the only place that knows there is more than one store.
 */
export async function pickedProjectFileToFile(file: PickedProjectFile): Promise<File> {
  if (!file.download_url) {
    throw new Error(`Download failed (no route for ${file.name})`);
  }
  const token = getAuthToken();
  const res = await fetch(file.download_url, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  return new File([blob], file.name, {
    // Same order as above: the blob's own type first, because the stored
    // mime_type is nullable and frequently wrong for CAD payloads.
    type: blob.type || file.mime_type || 'application/octet-stream',
  });
}

/** A file picked from the federated listing. */
export interface PickedProjectFile {
  /** Id in the row's OWN store - a document id for ``document``, a takeoff
   *  document id for ``takeoff``. The two namespaces do not overlap, which is
   *  why ``kind`` travels with it. */
  id: string;
  /** Which module the row came from. */
  kind: FileKind;
  /** The name shown on screen and searched on. */
  name: string;
  mime_type: string | null;
  file_size: number;
  /** Authenticated download URL served by the row's own module. */
  download_url: string | null;
  /** On a document row, the takeoff document that already exists for it.
   *  Lets the caller reopen that work instead of asking for a second one. */
  takeoff_document_id: string | null;
}

interface BaseProps {
  open: boolean;
  onClose: () => void;
  /** Project whose files are listed. */
  projectId: string;
  /**
   * Formats the calling module can open. Use one of the exported per-module
   * sets in ``shared/lib/projectFileFormats`` rather than an inline literal,
   * so the list stays tied to what the module's loader really handles.
   */
  accepted: readonly AcceptedFormat[];
  /** Optional override for the modal title. */
  title?: string;
  /** Id of the file currently being opened, so its row can show a spinner. */
  busyId?: string | null;
}

/**
 * The two shapes of this picker, discriminated by ``moduleKinds``.
 *
 * Without it the picker lists the documents module and hands back the stored
 * ``DocumentItem`` - the behaviour every caller had before federation existed,
 * kept unchanged so modules adopt the wider listing one at a time rather than
 * all at once. With it, rows come from several stores and the callback
 * receives the store-tagged {@link PickedProjectFile}, because a takeoff
 * document is not a ``DocumentItem`` and pretending otherwise would mean
 * inventing the fields it does not have.
 */
export type ProjectFilePickerProps = BaseProps &
  (
    | {
        moduleKinds?: undefined;
        /**
         * Fired with the chosen stored document. The caller decides how to
         * open it - most callers download the bytes and feed their existing
         * upload/open path, which keeps one code path for local and stored
         * files alike.
         */
        onPick: (doc: DocumentItem) => void;
      }
    | {
        /** The calling module's own file stores, listed beside the documents
         *  area. ``document`` is always included and must not be repeated. */
        moduleKinds: readonly FileKind[];
        onPick: (file: PickedProjectFile) => void;
      }
  );

/** One row as the list renders it, whichever store it came from. */
interface PickerRow {
  id: string;
  kind: FileKind;
  name: string;
  sizeBytes: number;
  /** Secondary identifier shown after the size - a drawing number today. */
  detail: string | null;
  /** True when this file is already open in the calling module. */
  alreadyHere: boolean;
  match: ProjectFileMatch;
  select: () => void;
}

/**
 * Value that settles once typing pauses. Local to this file on purpose: the
 * only other implementation lives inside a feature, and shared/ui must not
 * import from features for a hook this small.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

export function ProjectFilePicker(props: ProjectFilePickerProps) {
  const { open, onClose, projectId, accepted, title, busyId = null } = props;
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, SEARCH_DEBOUNCE_MS);

  const federated = props.moduleKinds !== undefined;
  // Stable, order-independent key for the request and the cache entry.
  const kinds = useMemo<readonly FileKind[]>(
    () =>
      props.moduleKinds === undefined
        ? ['document']
        : ['document', ...props.moduleKinds.filter((k) => k !== 'document')],
    [props.moduleKinds],
  );
  /**
   * The server can filter by extension only when the module opens exactly one
   * format. That is the case that matters here (PDF takeoff), and it is what
   * makes ``total`` describe the same rows the list shows rather than every
   * file in the project.
   */
  const soleExtension = accepted.length === 1 ? accepted[0]?.ext.replace(/^\./, '') : undefined;

  const documentsQuery = useQuery({
    queryKey: ['documents', projectId],
    // The return type is spelled out because this query holds a page, not a
    // list. Three surfaces cache under ['documents', projectId] and React
    // Query will hand any of them what another put there.
    queryFn: (): Promise<Page<DocumentItem>> => fetchDocuments(projectId),
    enabled: open && !federated && Boolean(projectId),
    staleTime: 15_000,
  });
  const documentItems = useMemo<DocumentItem[]>(
    () => documentsQuery.data?.items ?? [],
    [documentsQuery.data],
  );

  // Its own cache key, never shared with the Files page: the same endpoint
  // under different filters is a different answer, and React Query hands a
  // cached value to anyone holding the key.
  const federatedQuery = useQuery({
    queryKey: ['project-file-picker', projectId, kinds.join(','), soleExtension ?? '', debouncedSearch],
    queryFn: () =>
      fetchFileList(projectId, {
        kinds,
        ...(soleExtension ? { extension: soleExtension } : {}),
        ...(debouncedSearch.trim() ? { q: debouncedSearch.trim() } : {}),
        limit: FEDERATED_PAGE_SIZE,
        sort: 'modified',
      }),
    enabled: open && federated && Boolean(projectId),
    staleTime: 15_000,
    // The search runs on the server, so every keystroke starts a new query.
    // Without this the list is replaced by a spinner between keystrokes and
    // the user watches their results blink out of existence while typing.
    placeholderData: (prev) => prev,
  });

  const federatedItems = useMemo<FileRow[]>(() => federatedQuery.data?.items ?? [], [federatedQuery.data]);

  const rows = useMemo<PickerRow[]>(() => {
    // Narrowed on ``props`` itself rather than on the ``federated`` boolean, so
    // each branch gets the callback signature its own rows really produce.
    if (props.moduleKinds === undefined) {
      // Newest first: the drawing a user wants to open is almost always the
      // one just filed. Sorting here (not in the matcher) keeps the filter
      // pure. The federated listing is already sorted by the server.
      const sorted = [...documentItems].sort((a, b) =>
        (b.created_at ?? '').localeCompare(a.created_at ?? ''),
      );
      const onPickDocument = props.onPick;
      return filterProjectFiles(sorted, accepted, search).map(({ doc, match }) => ({
        id: doc.id,
        kind: 'document' as FileKind,
        name: doc.name,
        sizeBytes: doc.file_size ?? 0,
        detail: doc.drawing_number ?? null,
        alreadyHere: false,
        match,
        select: () => onPickDocument(doc),
      }));
    }
    const onPickFile = props.onPick;
    const out: PickerRow[] = [];
    for (const row of federatedItems) {
      const match = matchProjectFile(row, accepted);
      if (!match) continue;
      // The server already searched, over every collected row rather than one
      // page of them. Re-filtering here would only hide rows while the
      // debounce settles.
      const takeoffId =
        typeof row.extra?.['takeoff_document_id'] === 'string'
          ? (row.extra['takeoff_document_id'] as string)
          : null;
      const drawingNumber =
        typeof row.extra?.['drawing_number'] === 'string' ? (row.extra['drawing_number'] as string) : null;
      out.push({
        id: row.id,
        kind: row.kind,
        name: row.name,
        sizeBytes: row.size_bytes,
        detail: drawingNumber,
        // Marks a PROJECT FILE this module has already been given, where
        // picking the row reopens that work instead of starting a second copy
        // of it. A row from the module's own store needs no badge - the group
        // it sits under already says where it lives.
        alreadyHere: row.kind === 'document' && takeoffId !== null,
        match,
        select: () =>
          onPickFile({
            id: row.id,
            kind: row.kind,
            name: row.name,
            mime_type: row.mime_type,
            file_size: row.size_bytes,
            download_url: row.download_url,
            takeoff_document_id: takeoffId,
          }),
      });
    }
    return out;
  }, [props.moduleKinds, props.onPick, federatedItems, documentItems, accepted, search]);

  // Rows grouped by the store they came from, in the order the caller listed
  // the stores, so the group a user is looking for does not move around.
  const groups = useMemo(() => {
    if (!federated) return [{ kind: 'document' as FileKind, rows }];
    return kinds
      .map((kind) => ({ kind, rows: rows.filter((r) => r.kind === kind) }))
      .filter((group) => group.rows.length > 0);
  }, [federated, kinds, rows]);

  /**
   * Distinguishes "the project has nothing this module opens" from "your
   * search matched nothing", which need different wording and different fixes.
   * With a server-side search the unsearched total is not on hand, so an
   * active search is itself the signal.
   */
  const totalOpenable = useMemo(() => {
    if (federated) return search.trim() ? 1 : rows.length;
    return filterProjectFiles(documentItems, accepted).length;
  }, [federated, search, rows.length, documentItems, accepted]);

  const formatList = useMemo(() => acceptedFormatLabel(accepted), [accepted]);
  const loading = federated ? federatedQuery.isLoading : documentsQuery.isLoading;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="lg"
      title={title ?? t('project_files.picker_title', { defaultValue: 'Open from project files' })}
      subtitle={
        federated
          ? t('project_files.picker_subtitle_federated', {
              defaultValue:
                'Files stored in this project and the files this module already holds. Formats: {{formats}}',
              formats: formatList,
            })
          : t('project_files.picker_subtitle', {
              defaultValue:
                'Files already stored in this project that this module can open. Formats: {{formats}}',
              formats: formatList,
            })
      }
    >
      <div className="flex flex-col gap-3">
        {/* Search */}
        <div className="relative">
          <Search
            size={14}
            className="pointer-events-none absolute start-3 top-1/2 -translate-y-1/2 text-content-quaternary"
          />
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t('project_files.picker_search_aria', {
              defaultValue: 'Search project files by name',
            })}
            placeholder={t('project_files.picker_search_placeholder', {
              defaultValue: 'Search by file name...',
            })}
            className="w-full rounded-lg border border-border-medium bg-surface-primary py-2 ps-9 pe-3 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
          />
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
            {t('project_files.picker_loading', { defaultValue: 'Loading project files...' })}
          </div>
        )}

        {!loading && rows.length === 0 && (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border-medium px-6 py-10 text-center">
            <FolderOpen size={24} className="text-content-quaternary" />
            {totalOpenable === 0 ? (
              <>
                <p className="text-sm font-semibold text-content-primary">
                  {t('project_files.picker_empty_title', {
                    defaultValue: 'No compatible file in this project yet',
                  })}
                </p>
                <p className="max-w-md text-xs leading-relaxed text-content-tertiary">
                  {t('project_files.picker_empty_body', {
                    defaultValue:
                      'This project has no {{formats}} file stored yet. Add one in Files, or upload it here from your computer.',
                    formats: formatList,
                  })}
                </p>
                <Link
                  to="/files"
                  onClick={onClose}
                  className="mt-1 text-xs font-semibold text-oe-blue hover:underline"
                >
                  {t('project_files.picker_go_to_files', { defaultValue: 'Go to Files' })}
                </Link>
              </>
            ) : (
              <p className="text-sm text-content-tertiary">
                {t('project_files.picker_no_search_match', {
                  defaultValue: 'No file matches your search.',
                })}
              </p>
            )}
          </div>
        )}

        {!loading && rows.length > 0 && (
          <div className="max-h-[22rem] space-y-3 overflow-y-auto pr-1">
            {groups.map((group) => (
              <div key={group.kind} className="space-y-1.5">
                {/* The group is named so a row's origin is never a guess. The
                    label is the one the Files page already uses for the same
                    store, translated everywhere, rather than a second name for
                    the same thing. */}
                {federated && (
                  <p className="px-1 text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
                    {t(`files.category.${group.kind}`, { defaultValue: group.kind })}
                  </p>
                )}
                <ul className="space-y-1.5">
                  {group.rows.map((row) => (
                    <li key={`${row.kind}:${row.id}`}>
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={row.select}
                        data-testid="project-file-picker-row"
                        className="group flex w-full items-center gap-3 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 text-left transition-all hover:border-oe-blue/40 hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border-light bg-surface-secondary text-content-tertiary group-hover:text-oe-blue">
                          {busyId === row.id ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <FileText size={14} />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-content-primary">
                            {row.name}
                          </p>
                          <p className="flex flex-wrap items-center gap-x-1.5 text-[11px] text-content-tertiary">
                            <span className="font-mono uppercase">
                              {row.match.ext.replace(/^\./, '')}
                            </span>
                            <span>·</span>
                            <span>{formatFileSize(row.sizeBytes)}</span>
                            {row.detail ? (
                              <>
                                <span>·</span>
                                <span className="truncate">{row.detail}</span>
                              </>
                            ) : null}
                          </p>
                        </div>
                        {/* Honest labelling: say what will really happen rather
                            than implying every format opens instantly in this
                            module. */}
                        {row.match.handoff ? (
                          <span className="shrink-0 rounded-md border border-amber-500/20 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
                            {t('project_files.picker_opens_elsewhere', {
                              defaultValue: 'Opens in another module',
                            })}
                          </span>
                        ) : row.match.needsConversion ? (
                          <span className="flex shrink-0 items-center gap-1 rounded-md border border-violet-500/20 bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-violet-600 dark:text-violet-400">
                            <Wand2 size={10} />
                            {t('project_files.picker_needs_conversion', {
                              defaultValue: 'Converts first',
                            })}
                          </span>
                        ) : row.alreadyHere ? (
                          <span className="shrink-0 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                            {t('project_files.picker_already_open_here', {
                              defaultValue: 'Already in this module',
                            })}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {/* A picker cannot page, so it says how much of the project it is
            showing. Measured against what the server returned, which is what
            the total counts. */}
        {federated && federatedQuery.data ? (
          <TruncationNotice
            page={{ items: federatedItems, total: federatedQuery.data.total }}
            className="px-1"
          />
        ) : null}
        {!federated && documentsQuery.data ? (
          <TruncationNotice
            page={{ items: documentItems, total: documentsQuery.data.total }}
            className="px-1"
          />
        ) : null}
      </div>
    </WideModal>
  );
}
