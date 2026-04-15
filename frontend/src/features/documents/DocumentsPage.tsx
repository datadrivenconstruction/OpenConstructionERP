import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Upload, FileText, Image, FileSpreadsheet, File, Trash2, Download,
  Search, X, Loader2, FolderOpen, ChevronDown, HardDrive, Eye,
  MoreHorizontal, Pencil, Tag, Ruler, Send,
} from 'lucide-react';
import { Card, Button, Badge, EmptyState, Breadcrumb, ViewInBIMButton } from '@/shared/ui';
import SimilarItemsPanel from '@/shared/ui/SimilarItemsPanel';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet, apiDelete, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { listSessions } from '../cad-explorer/api';

/* ── Types ───────────────────────────────────────────────────────────── */

interface DocItem {
  id: string;
  name: string;
  description: string;
  category: string;
  file_size: number;
  mime_type: string;
  version: number;
  uploaded_by: string;
  tags: string[];
  created_at: string;
  cde_state?: 'wip' | 'shared' | 'published' | 'archived' | null;
}

type SortField = 'date' | 'name' | 'size';

const CATEGORIES = ['all', 'drawing', 'contract', 'specification', 'photo', 'correspondence', 'other'] as const;

const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024; // 100 MB

const CDE_STATE_COLORS: Record<string, 'warning' | 'blue' | 'success' | 'neutral'> = {
  wip: 'warning',
  shared: 'blue',
  published: 'success',
  archived: 'neutral',
};

/* ── Helpers ─────────────────────────────────────────────────────────── */

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fileIcon(mime: string) {
  if (mime.includes('pdf')) return <FileText size={20} className="text-red-500" />;
  if (mime.includes('image')) return <Image size={20} className="text-green-500" />;
  if (mime.includes('sheet') || mime.includes('excel') || mime.includes('csv')) return <FileSpreadsheet size={20} className="text-blue-500" />;
  return <File size={20} className="text-content-tertiary" />;
}

function isPreviewable(mime: string): 'pdf' | 'image' | null {
  if (mime.includes('pdf')) return 'pdf';
  if (mime.startsWith('image/')) return 'image';
  return null;
}

function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/* ── Inline BIM link icon for document cards ────────────────────────── */

/**
 * Lazily fetches BIM links for a single document and renders a compact
 * ViewInBIMButton when at least one link exists.  React Query caching
 * prevents redundant requests when the list re-renders.
 */
function DocBIMIcon({ docId }: { docId: string }) {
  const { data } = useQuery({
    queryKey: ['document-bim-links', docId],
    queryFn: () =>
      apiGet<{ items: Array<{ id: string; bim_element_id: string; document_id: string }> }>(
        `/v1/documents/bim-links/?document_id=${encodeURIComponent(docId)}`,
      ).catch(() => ({ items: [] })),
    enabled: !!docId,
    staleTime: 60_000,
  });

  const elementIds = useMemo(
    () => (data?.items ?? []).map((l) => l.bim_element_id),
    [data],
  );

  if (!elementIds.length) return null;

  return (
    <ViewInBIMButton
      elementIds={elementIds}
      iconSize={10}
      label=""
      className="inline-flex items-center gap-0.5 text-2xs text-oe-blue hover:text-oe-blue-dark transition-colors"
    />
  );
}

/* ── Preview Modal ───────────────────────────────────────────────────── */

function PreviewModal({
  doc,
  onClose,
}: {
  doc: DocItem;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const kind = isPreviewable(doc.mime_type);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Reverse-direction lookup: every BIM element this document is linked to.
  // The endpoint may not exist on older deployments — we tolerate a 404 by
  // showing nothing instead of throwing.  Lazy-loaded only when the modal
  // is open so we don't hammer the API on every documents-list render.
  const { data: linkedElements } = useQuery({
    queryKey: ['document-bim-links', doc.id],
    queryFn: () =>
      apiGet<{ items: Array<{ id: string; bim_element_id: string; document_id: string }> }>(
        `/v1/documents/bim-links/?document_id=${encodeURIComponent(doc.id)}`,
      ).catch(() => ({ items: [] })),
    enabled: !!doc.id,
    staleTime: 30_000,
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('documents.preview_title', { defaultValue: 'Document preview' })}
    >
      <div
        className="relative w-full max-w-4xl max-h-[90vh] mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border-light bg-surface-primary">
          <div className="flex items-center gap-3 min-w-0">
            {fileIcon(doc.mime_type)}
            <h3 className="text-sm font-semibold text-content-primary truncate">{doc.name}</h3>
            <span className="text-xs text-content-tertiary shrink-0">{formatSize(doc.file_size)}</span>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <a
              href={`/api/v1/documents/${doc.id}/download`}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
              aria-label={t('documents.download', { defaultValue: 'Download' })}
            >
              <Download size={16} />
            </a>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto flex items-center justify-center bg-black/5 min-h-[400px]">
          {kind === 'pdf' ? (
            <iframe
              src={`/api/v1/documents/${doc.id}/download`}
              title={doc.name}
              className="w-full h-[80vh]"
            />
          ) : kind === 'image' ? (
            <img
              src={`/api/v1/documents/${doc.id}/download`}
              alt={doc.name}
              className="max-w-full max-h-[80vh] object-contain"
            />
          ) : null}
        </div>

        {/* Semantic similarity — finds documents with related content
            across all projects (drawings about the same scope, RFIs on
            the same trade, etc.).  Cross-project default is on so the
            estimator gets cross-pollination from past work. */}
        <div className="border-t border-border-light px-5 py-3 bg-surface-primary shrink-0">
          <SimilarItemsPanel module="documents" id={doc.id} crossProject limit={5} />
        </div>

        {/* Linked BIM elements — appears at the bottom of the preview when
            this document has any DocumentBIMLink rows.  Click → opens the
            BIM viewer with the element preselected. */}
        {linkedElements && linkedElements.items.length > 0 && (
          <div className="border-t border-border-light px-5 py-3 bg-surface-primary shrink-0">
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-2">
              {t('documents.linked_bim_elements', {
                defaultValue: 'Linked BIM elements',
              })}
              <span className="ms-2 text-content-quaternary normal-case font-normal">
                ({linkedElements.items.length})
              </span>
            </h4>
            <div className="flex flex-wrap gap-1">
              {linkedElements.items.slice(0, 12).map((link) => (
                <button
                  key={link.id}
                  type="button"
                  onClick={() => {
                    navigate(`/bim?element=${encodeURIComponent(link.bim_element_id)}`);
                    onClose();
                  }}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-border-light text-[11px] text-content-secondary hover:text-oe-blue hover:bg-oe-blue/5"
                  title={link.bim_element_id}
                >
                  <span className="font-mono text-[10px]">
                    {link.bim_element_id.slice(0, 8)}
                  </span>
                </button>
              ))}
              {linkedElements.items.length > 12 && (
                <span className="text-[10px] text-content-tertiary">
                  + {linkedElements.items.length - 12} more
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Sort Dropdown ───────────────────────────────────────────────────── */

function SortDropdown({
  value,
  onChange,
}: {
  value: SortField;
  onChange: (v: SortField) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const labels: Record<SortField, string> = {
    date: t('documents.sort_date', { defaultValue: 'Date' }),
    name: t('documents.sort_name', { defaultValue: 'Name' }),
    size: t('documents.sort_size', { defaultValue: 'Size' }),
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1.5 h-10 px-3 text-xs font-medium rounded-lg border border-border-light text-content-secondary hover:bg-surface-secondary transition-colors"
        aria-label={t('documents.sort_by', { defaultValue: 'Sort by' })}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        {t('documents.sort_by', { defaultValue: 'Sort by' })}: {labels[value]}
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 w-36 rounded-lg border border-border-light bg-surface-elevated shadow-lg z-10 overflow-hidden"
          role="listbox"
          aria-label={t('documents.sort_options', { defaultValue: 'Sort options' })}
        >
          {(['date', 'name', 'size'] as SortField[]).map((field) => (
            <button
              key={field}
              role="option"
              aria-selected={value === field}
              onClick={() => { onChange(field); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-xs transition-colors ${
                value === field
                  ? 'bg-oe-blue-subtle/30 text-oe-blue font-medium'
                  : 'text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {labels[field]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main Component ──────────────────────────────────────────────────── */

const INITIAL_EDIT_DOC_FORM = { category: '', description: '', tagInput: '', tags: [] as string[] };

export function DocumentsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const [query, setQuery] = useState('');
  const debouncedQuery = useDebounce(query, 300);
  const [category, setCategory] = useState('all');
  const [sortBy, setSortBy] = useState<SortField>('date');
  const [dragOver, setDragOver] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<DocItem | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renameDoc, setRenameDoc] = useState<{ id: string; name: string } | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [editDoc, setEditDoc] = useState<DocItem | null>(null);
  const [editForm, setEditForm] = useState(INITIAL_EDIT_DOC_FORM);
  const menuRef = useRef<HTMLDivElement>(null);

  // Upload state (progress shown in FloatingQueuePanel)

  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const projectId = activeProjectId;

  /* ── Deep-link auto-preview ─────────────────────────────────────────────
   * Cmd+Shift+K global semantic search and other deep links land here
   * with `?id=<document_id>` — open the matching document in the preview
   * modal as soon as it loads.  Cleans up the param afterwards so a
   * page refresh doesn't keep re-opening the modal. */
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkDocId = searchParams.get('id');

  /* ── Data fetching ──────────────────────────────────────────────────── */

  const { data: documents, isLoading } = useQuery({
    queryKey: ['documents', projectId, category, debouncedQuery],
    queryFn: () => {
      const params = new URLSearchParams();
      if (projectId) params.set('project_id', projectId);
      if (category !== 'all') params.set('category', category);
      if (debouncedQuery.trim()) params.set('search', debouncedQuery.trim());
      return apiGet<DocItem[]>(`/v1/documents/?${params.toString()}`);
    },
    enabled: !!projectId,
  });

  // Open the deep-linked document in the preview modal as soon as it
  // appears in the list.  We clear the `?id=` query param immediately
  // afterwards so a refresh doesn't keep re-opening the modal.
  useEffect(() => {
    if (!deepLinkDocId || !documents) return;
    const target = documents.find((d) => d.id === deepLinkDocId);
    if (target) {
      setPreviewDoc(target);
      const next = new URLSearchParams(searchParams);
      next.delete('id');
      setSearchParams(next, { replace: true });
    }
  }, [deepLinkDocId, documents, searchParams, setSearchParams]);

  /* ── CAD/BIM models (saved sessions) ─────────────────────────────────── */

  // Show ALL CAD sessions (including ones without project_id)
  const { data: cadSessions = [] } = useQuery({
    queryKey: ['cad-saved-sessions'],
    queryFn: () => listSessions(),
  });

  /* ── Sorted documents ───────────────────────────────────────────────── */

  const sortedDocuments = useMemo(() => {
    const docs = documents ?? [];
    return [...docs].sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return a.name.localeCompare(b.name);
        case 'size':
          return b.file_size - a.file_size;
        case 'date':
        default:
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      }
    });
  }, [documents, sortBy]);

  /* ── Stats ──────────────────────────────────────────────────────────── */

  const stats = useMemo(() => {
    const docs = documents ?? [];
    const totalSize = docs.reduce((sum, d) => sum + d.file_size, 0);
    return { count: docs.length, totalSize };
  }, [documents]);

  /* ── Delete mutation ────────────────────────────────────────────────── */

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/documents/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      addToast({ type: 'success', title: t('documents.deleted', { defaultValue: 'Document deleted successfully' }) });
      setConfirmDeleteId(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.delete_failed', { defaultValue: 'Failed to delete document' }), message: err.message });
      setConfirmDeleteId(null);
    },
  });

  /* ── Upload handler (background queue) ───────────────────────────────── */

  const addQueueTask = useUploadQueueStore((s) => s.addTask);
  const updateQueueTask = useUploadQueueStore((s) => s.updateTask);

  const handleUpload = useCallback(async (files: FileList | File[]) => {
    if (!projectId) {
      addToast({
        type: 'error',
        title: t('documents.no_project_error', { defaultValue: 'No project selected' }),
        message: t('documents.select_project_first', { defaultValue: 'Please select a project first before uploading.' }),
      });
      return;
    }

    const fileArray = Array.from(files);
    if (fileArray.length === 0) return;

    // Frontend file-size validation
    const oversized = fileArray.filter((f) => f.size > MAX_FILE_SIZE_BYTES);
    if (oversized.length > 0) {
      addToast({
        type: 'warning',
        title: t('documents.files_too_large', { defaultValue: 'Files too large' }),
        message: t('documents.max_size_warning', {
          defaultValue: '{{count}} file(s) exceed the 100 MB limit and were skipped: {{names}}',
          count: oversized.length,
          names: oversized.map((f) => f.name).join(', '),
        }),
      });
    }

    const validFiles = fileArray.filter((f) => f.size <= MAX_FILE_SIZE_BYTES);
    if (validFiles.length === 0) return;

    const token = useAuthStore.getState().accessToken;
    const cat = category === 'all' ? 'other' : category;

    // Add each file to the global queue and upload in background
    for (const file of validFiles) {
      const taskId = crypto.randomUUID();

      addQueueTask({
        id: taskId,
        type: 'file_upload',
        filename: file.name,
        status: 'processing',
        progress: 0,
        message: t('documents.uploading', { defaultValue: 'Uploading...' }),
      });

      // Fire-and-forget: upload runs in background
      (async () => {
        try {
          const formData = new FormData();
          formData.append('file', file);

          const headers: Record<string, string> = { 'X-DDC-Client': 'OE/1.0' };
          if (token) headers['Authorization'] = `Bearer ${token}`;

          // Simulate progress based on file size
          const estimatedMs = Math.max(2000, (file.size / (1024 * 1024)) * 500);
          const progressTimer = setInterval(() => {
            const task = useUploadQueueStore.getState().tasks.find((t) => t.id === taskId);
            if (task && task.status === 'processing' && task.progress < 90) {
              updateQueueTask(taskId, { progress: task.progress + 5 });
            }
          }, estimatedMs / 18);

          const response = await fetch(
            `/api/v1/documents/upload?project_id=${projectId}&category=${cat}`,
            { method: 'POST', headers, body: formData },
          );

          clearInterval(progressTimer);

          if (!response.ok) {
            let detail = file.name;
            try { const body = await response.json(); if (body?.detail) detail = body.detail; } catch { /* */ }
            updateQueueTask(taskId, { status: 'error', error: detail, completedAt: Date.now() });
          } else {
            updateQueueTask(taskId, {
              status: 'completed',
              progress: 100,
              message: t('documents.uploaded', { defaultValue: 'Uploaded' }),
              completedAt: Date.now(),
            });
            queryClient.invalidateQueries({ queryKey: ['documents'] });
          }
        } catch (err) {
          updateQueueTask(taskId, {
            status: 'error',
            error: err instanceof Error ? err.message : 'Upload failed',
            completedAt: Date.now(),
          });
        }
      })();
    }

    addToast({
      type: 'info',
      title: t('documents.upload_queued', { defaultValue: '{{count}} file(s) queued for upload', count: validFiles.length }),
    });

    // Reset input so re-selecting the same file works
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [projectId, category, addToast, t, queryClient, addQueueTask, updateQueueTask]);

  /* ── Drag & Drop ────────────────────────────────────────────────────── */

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) handleUpload(e.dataTransfer.files);
  }, [handleUpload]);

  /* ── Card click handler ─────────────────────────────────────────────── */

  const handleCardClick = useCallback((doc: DocItem) => {
    const kind = isPreviewable(doc.mime_type);
    if (kind) {
      setPreviewDoc(doc);
    } else {
      // Non-previewable — trigger download
      window.open(`/api/v1/documents/${doc.id}/download`, '_blank');
    }
  }, []);

  /* ── Close preview ──────────────────────────────────────────────────── */

  const handleClosePreview = useCallback(() => {
    setPreviewDoc(null);
  }, []);

  // Close dropdown menu on outside click
  useEffect(() => {
    if (!openMenuId) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpenMenuId(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [openMenuId]);

  // Rename mutation
  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiPatch<unknown, { name: string }>(`/v1/documents/${id}`, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      addToast({ type: 'success', title: t('documents.renamed', { defaultValue: 'Document renamed successfully' }) });
      setRenameDoc(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.rename_failed', { defaultValue: 'Failed to rename document' }), message: err.message });
    },
  });

  // Edit properties mutation
  const editMutation = useMutation({
    mutationFn: ({ id, ...fields }: { id: string; category?: string; description?: string; tags?: string[] }) =>
      apiPatch<unknown, Record<string, unknown>>(`/v1/documents/${id}`, fields),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      addToast({ type: 'success', title: t('documents.properties_saved', { defaultValue: 'Document properties saved successfully' }) });
      setEditDoc(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.save_failed', { defaultValue: 'Failed to save document properties' }), message: err.message });
    },
  });

  const openEditDialog = useCallback((doc: DocItem) => {
    setEditDoc(doc);
    setEditForm({
      category: doc.category,
      description: doc.description || '',
      tagInput: '',
      tags: doc.tags || [],
    });
  }, []);

  const handleAddTag = useCallback(() => {
    const tag = editForm.tagInput.trim();
    if (tag && !editForm.tags.includes(tag)) {
      setEditForm((prev) => ({ ...prev, tags: [...prev.tags, tag], tagInput: '' }));
    }
  }, [editForm.tagInput, editForm.tags]);

  const handleRemoveTag = useCallback((tag: string) => {
    setEditForm((prev) => ({ ...prev, tags: prev.tags.filter((t) => t !== tag) }));
  }, []);

  /* ── No project selected ────────────────────────────────────────────── */

  if (!projectId) {
    return (
      <div className="w-full animate-fade-in">
        <Breadcrumb items={[{ label: t('nav.dashboard', 'Dashboard'), to: '/' }, { label: t('nav.documents', 'Documents') }]} className="mb-4" />
        <EmptyState
          icon={<FolderOpen size={28} strokeWidth={1.5} />}
          title={t('documents.select_project', { defaultValue: 'Select a project' })}
          description={t('documents.select_project_hint', { defaultValue: 'Use the project switcher in the header to select a project first.' })}
        />
      </div>
    );
  }

  return (
    <div
      className="w-full animate-fade-in"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('nav.documents', 'Documents') },
        ...(activeProjectName ? [{ label: activeProjectName }] : []),
      ]} className="mb-4" />

      {/* ── No project warning ────────────────────────────────────────── */}
      {!projectId && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 px-4 py-3">
          <Upload size={18} className="text-amber-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
              {t('documents.no_project_selected', { defaultValue: 'No project selected' })}
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-400">
              {t('documents.select_project_hint', { defaultValue: 'Select a project from the header to upload and view documents.' })}
            </p>
          </div>
        </div>
      )}

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('documents.title', { defaultValue: 'Documents' })}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('documents.subtitle', { defaultValue: 'Upload and manage project files — drawings, contracts, specifications' })}
          </p>
        </div>
        <div className="shrink-0">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) handleUpload(e.target.files);
            }}
            aria-label={t('documents.upload_input', { defaultValue: 'Choose files to upload' })}
          />
          <Button
            variant="primary"
            size="sm"
            icon={<Upload size={14} />}
            disabled={!projectId}
            onClick={() => fileInputRef.current?.click()}
            title={!projectId ? t('documents.select_project_first', { defaultValue: 'Select a project first' }) : ''}
          >
            {t('documents.upload', { defaultValue: 'Upload Files' })}
          </Button>
        </div>
      </div>

      {/* ── Document flow ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-2xs text-content-quaternary mb-4">
        <span className="text-content-tertiary">
          {t('documents.flow_label', { defaultValue: 'Document flow:' })}
        </span>
        <span className="text-oe-blue font-medium">
          {t('documents.flow_upload', { defaultValue: 'Upload' })}
        </span>
        <span>&#8594;</span>
        <button onClick={() => navigate('/cde')} className="hover:text-oe-blue transition-colors">
          {t('documents.flow_organize', { defaultValue: 'Organize (CDE)' })}
        </button>
        <span>&#8594;</span>
        <button onClick={() => navigate('/transmittals')} className="hover:text-oe-blue transition-colors">
          {t('documents.flow_distribute', { defaultValue: 'Distribute' })}
        </button>
      </div>

      {/* ── Stats bar ───────────────────────────────────────────────────── */}
      {!isLoading && documents && documents.length > 0 && (
        <div className="flex items-center gap-4 mb-4 text-xs text-content-tertiary">
          <span className="flex items-center gap-1.5">
            <FileText size={13} />
            {t('documents.total_count', { defaultValue: '{{count}} documents', count: stats.count })}
          </span>
          <span className="flex items-center gap-1.5">
            <HardDrive size={13} />
            {t('documents.total_size', { defaultValue: '{{size}} total', size: formatSize(stats.totalSize) })}
          </span>
        </div>
      )}

      {/* ── Drop zone ───────────────────────────────────────────────────── */}
      <div
        className={`mb-5 rounded-xl border-2 border-dashed p-6 text-center transition-all duration-200 ${
          dragOver
            ? 'border-oe-blue bg-oe-blue-subtle/30 scale-[1.01] shadow-lg'
            : 'border-border-light hover:border-border'
        }`}
        role="region"
        aria-label={t('documents.drop_zone', { defaultValue: 'File drop zone' })}
      >
        <Upload size={28} className={`mx-auto mb-3 transition-colors ${dragOver ? 'text-oe-blue' : 'text-content-tertiary'}`} />
        <p className="text-sm text-content-secondary mb-1">
          {dragOver
            ? t('documents.drop_now', { defaultValue: 'Drop files to upload' })
            : t('documents.drop_hint', { defaultValue: 'Drag & drop files here' })}
        </p>
        <p className="text-xs text-content-tertiary mb-3">
          {t('documents.supported_types', { defaultValue: 'PDF, images, Excel, DWG, IFC — any file type (max 100 MB)' })}
        </p>
        <button
          type="button"
          disabled={!projectId}
          onClick={() => fileInputRef.current?.click()}
          className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
            projectId
              ? 'border-oe-blue text-oe-blue hover:bg-oe-blue hover:text-white'
              : 'border-border text-content-quaternary cursor-not-allowed'
          }`}
        >
          <Upload size={14} />
          {projectId
            ? t('documents.browse_files', { defaultValue: 'Browse Files' })
            : t('documents.select_project_first', { defaultValue: 'Select a project first' })}
        </button>
      </div>

      {/* ── Filters + Sort ──────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('documents.search', { defaultValue: 'Search files...' })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            aria-label={t('documents.search_label', { defaultValue: 'Search documents' })}
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary"
              aria-label={t('common.clear_search', { defaultValue: 'Clear search' })}
            >
              <X size={14} />
            </button>
          )}
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                category === c ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary border border-border-light'
              }`}
              aria-label={t('documents.filter_category', {
                defaultValue: 'Filter by {{category}}',
                category: c === 'all' ? 'All' : c,
              })}
              aria-pressed={category === c}
            >
              {t(`documents.cat_${c}`, { defaultValue: c === 'all' ? 'All' : c.charAt(0).toUpperCase() + c.slice(1) })}
            </button>
          ))}
        </div>
        <SortDropdown value={sortBy} onChange={setSortBy} />
      </div>

      {/* ── CAD/BIM Models ──────────────────────────────────────────────── */}
      {cadSessions.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-content-primary flex items-center gap-1.5">
              <HardDrive size={13} className="text-oe-blue" />
              {t('documents.cad_models', { defaultValue: 'CAD/BIM Models' })}
              <Badge variant="blue" size="sm">{cadSessions.length}</Badge>
            </h3>
            <button onClick={() => navigate('/data-explorer')} className="text-2xs text-oe-blue hover:underline">
              {t('documents.open_explorer', { defaultValue: 'Open Explorer' })}
            </button>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {cadSessions.map((s) => {
              const fmt = (s.file_format || '').toUpperCase();
              const fmtColor: Record<string, string> = {
                RVT: 'bg-blue-100 text-blue-700', IFC: 'bg-green-100 text-green-700',
                DWG: 'bg-orange-100 text-orange-700', DGN: 'bg-purple-100 text-purple-700',
              };
              return (
                <Card
                  key={s.session_id}
                  padding="none"
                  hoverable
                  className="cursor-pointer"
                  onClick={() => navigate(`/data-explorer?session=${s.session_id}`)}
                >
                  <div className="flex items-center gap-3 p-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue-subtle shrink-0">
                      <HardDrive size={18} className="text-oe-blue" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-content-primary truncate">{s.display_name}</p>
                      <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                        <span className={`px-1.5 py-0.5 rounded text-2xs font-bold ${fmtColor[fmt] || 'bg-gray-100 text-gray-600'}`}>{fmt}</span>
                        <span className="text-2xs text-content-tertiary">{s.element_count.toLocaleString()} elements</span>
                        <span className="text-2xs text-content-quaternary">{s.extraction_time.toFixed(1)}s</span>
                        {s.created_at && <span className="text-2xs text-content-quaternary"><DateDisplay value={s.created_at} /></span>}
                        {s.is_permanent ? (
                          <Badge variant="success" size="sm">{t('documents.saved', { defaultValue: 'Saved' })}</Badge>
                        ) : (
                          <Badge variant="neutral" size="sm">{t('documents.temporary', { defaultValue: '24h' })}</Badge>
                        )}
                      </div>
                    </div>
                    <ChevronDown size={14} className="text-content-tertiary -rotate-90 shrink-0" />
                  </div>
                </Card>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Documents grid ──────────────────────────────────────────────── */}
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} padding="md"><div className="h-16 animate-pulse bg-surface-secondary rounded" /></Card>
          ))}
        </div>
      ) : sortedDocuments.length === 0 ? (
        debouncedQuery.trim() ? (
          <EmptyState
            icon={<Search size={28} strokeWidth={1.5} />}
            title={t('documents.no_results', { defaultValue: 'No results found' })}
            description={t('documents.no_results_hint', {
              defaultValue: 'No documents match "{{query}}". Try a different search term or clear filters.',
              query: debouncedQuery,
            })}
            action={{
              label: t('documents.clear_search', { defaultValue: 'Clear search' }),
              onClick: () => setQuery(''),
            }}
          />
        ) : (
          <EmptyState
            icon={<FolderOpen size={28} strokeWidth={1.5} />}
            title={t('documents.empty', { defaultValue: 'No documents yet' })}
            description={t('documents.empty_hint', { defaultValue: 'Upload your first file — drawings, contracts, photos, or any project document.' })}
          />
        )
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sortedDocuments.map((doc) => {
            const isDeleting = deleteMutation.isPending && deleteMutation.variables === doc.id;
            const isConfirming = confirmDeleteId === doc.id;
            const previewKind = isPreviewable(doc.mime_type);

            return (
              <Card
                key={doc.id}
                padding="none"
                hoverable
                className={`group ${isDeleting ? 'opacity-50 pointer-events-none' : ''}`}
              >
                <div
                  className={`flex items-start gap-3 px-4 py-3 ${previewKind ? 'cursor-pointer' : 'cursor-default'}`}
                  onClick={() => handleCardClick(doc)}
                  role={previewKind ? 'button' : undefined}
                  tabIndex={previewKind ? 0 : undefined}
                  onKeyDown={(e) => {
                    if (previewKind && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault();
                      handleCardClick(doc);
                    }
                  }}
                  aria-label={
                    previewKind
                      ? t('documents.click_to_preview', { defaultValue: 'Click to preview {{name}}', name: doc.name })
                      : undefined
                  }
                >
                  <div className="mt-0.5 shrink-0">{fileIcon(doc.mime_type)}</div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-content-primary truncate">{doc.name}</h3>
                    <div className="flex items-center gap-2 mt-1 text-2xs text-content-tertiary">
                      <span>{formatSize(doc.file_size)}</span>
                      <span>&middot;</span>
                      <Badge variant="neutral" size="sm">{doc.category}</Badge>
                      {doc.version > 1 && <Badge variant="blue" size="sm">v{doc.version}</Badge>}
                      {doc.cde_state && (
                        <Badge variant={CDE_STATE_COLORS[doc.cde_state] ?? 'neutral'} size="sm">
                          {doc.cde_state.toUpperCase()}
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-2xs text-content-quaternary">
                        <DateDisplay value={doc.created_at} />
                      </p>
                      {previewKind && (
                        <span className="flex items-center gap-0.5 text-2xs text-oe-blue opacity-0 group-hover:opacity-100 transition-opacity">
                          <Eye size={10} />
                          {t('documents.preview', { defaultValue: 'Preview' })}
                        </span>
                      )}
                      <DocBIMIcon docId={doc.id} />
                    </div>
                    {doc.tags && doc.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {doc.tags.slice(0, 3).map((tag) => (
                          <span key={tag} className="rounded-full bg-content-primary/[0.04] px-2 py-[1px] text-[9px] font-medium text-content-tertiary">
                            {tag}
                          </span>
                        ))}
                        {doc.tags.length > 3 && (
                          <span className="text-[9px] text-content-quaternary">+{doc.tags.length - 3}</span>
                        )}
                      </div>
                    )}
                  </div>
                  <div
                    className="flex items-center gap-1 shrink-0 relative"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {isDeleting ? (
                      <div className="flex h-7 w-7 items-center justify-center">
                        <Loader2 size={14} className="animate-spin text-content-tertiary" />
                      </div>
                    ) : isConfirming ? (
                      <div className="flex items-center gap-0.5 animate-fade-in">
                        <span className="text-2xs text-semantic-error font-medium mr-0.5">
                          {t('common.confirm_question', { defaultValue: 'Delete?' })}
                        </span>
                        <button
                          onClick={() => deleteMutation.mutate(doc.id)}
                          className="flex h-6 px-1.5 items-center justify-center rounded text-2xs font-medium bg-semantic-error text-content-inverse hover:opacity-90 transition-colors"
                        >
                          {t('common.yes', { defaultValue: 'Yes' })}
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="flex h-6 px-1.5 items-center justify-center rounded text-2xs font-medium text-content-secondary hover:bg-surface-secondary transition-colors"
                        >
                          {t('common.no', { defaultValue: 'No' })}
                        </button>
                      </div>
                    ) : (
                      <>
                        {/* Action menu button — always visible */}
                        <button
                          onClick={() => setOpenMenuId(openMenuId === doc.id ? null : doc.id)}
                          className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
                          aria-label={t('documents.actions', { defaultValue: 'Actions' })}
                          aria-haspopup="menu"
                          aria-expanded={openMenuId === doc.id}
                        >
                          <MoreHorizontal size={16} />
                        </button>

                        {/* Dropdown menu */}
                        {openMenuId === doc.id && (
                          <div
                            ref={menuRef}
                            className="absolute right-0 top-full mt-1 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-xl z-20 py-1 animate-fade-in"
                            role="menu"
                          >
                            {previewKind && (
                              <button
                                role="menuitem"
                                onClick={() => { setOpenMenuId(null); setPreviewDoc(doc); }}
                                className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                              >
                                <Eye size={14} className="text-content-tertiary" />
                                {t('documents.preview', { defaultValue: 'Preview' })}
                              </button>
                            )}
                            {previewKind === 'pdf' && (
                              <button
                                role="menuitem"
                                onClick={() => { setOpenMenuId(null); navigate(`/takeoff?doc=${doc.id}&name=${encodeURIComponent(doc.name)}`); }}
                                className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                              >
                                <Ruler size={14} className="text-oe-blue" />
                                {t('documents.open_in_takeoff', { defaultValue: 'Measure & Takeoff' })}
                              </button>
                            )}
                            <a
                              role="menuitem"
                              href={`/api/v1/documents/${doc.id}/download`}
                              className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                              onClick={() => setOpenMenuId(null)}
                            >
                              <Download size={14} className="text-content-tertiary" />
                              {t('documents.download', { defaultValue: 'Download' })}
                            </a>
                            <button
                              role="menuitem"
                              onClick={() => {
                                setOpenMenuId(null);
                                setRenameDoc({ id: doc.id, name: doc.name });
                                setRenameValue(doc.name);
                              }}
                              className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                            >
                              <Pencil size={14} className="text-content-tertiary" />
                              {t('documents.rename', { defaultValue: 'Rename' })}
                            </button>
                            <button
                              role="menuitem"
                              onClick={() => {
                                setOpenMenuId(null);
                                openEditDialog(doc);
                              }}
                              className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                            >
                              <Tag size={14} className="text-content-tertiary" />
                              {t('documents.properties', { defaultValue: 'Properties' })}
                            </button>
                            <button
                              role="menuitem"
                              onClick={() => {
                                setOpenMenuId(null);
                                navigate('/transmittals?create=true&doc_ids=' + doc.id);
                              }}
                              className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-content-primary hover:bg-surface-secondary transition-colors"
                            >
                              <Send size={14} className="text-content-tertiary" />
                              {t('documents.send_transmittal', { defaultValue: 'Send via Transmittal' })}
                            </button>
                            <div className="my-1 h-px bg-border-light" />
                            <button
                              role="menuitem"
                              onClick={() => { setOpenMenuId(null); setConfirmDeleteId(doc.id); }}
                              className="flex w-full items-center gap-2.5 px-3 py-2 text-xs text-semantic-error hover:bg-semantic-error-bg transition-colors"
                            >
                              <Trash2 size={14} />
                              {t('common.delete', { defaultValue: 'Delete' })}
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* ── Properties dialog ────────────────────────────────────────── */}
      {editDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in" onClick={() => setEditDoc(null)}>
          <div className="relative w-full max-w-md mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light overflow-hidden" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-border-light">
              <div className="flex items-center gap-2 min-w-0">
                {fileIcon(editDoc.mime_type)}
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-content-primary truncate">{editDoc.name}</h3>
                  <p className="text-2xs text-content-tertiary">{formatSize(editDoc.file_size)} · <DateDisplay value={editDoc.created_at} /></p>
                </div>
              </div>
              <button onClick={() => setEditDoc(null)} className="p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors">
                <X size={16} />
              </button>
            </div>

            <div className="px-5 py-4 space-y-4">
              {/* Category */}
              <div>
                <label className="text-xs font-medium text-content-primary block mb-1.5">
                  {t('documents.category_label', { defaultValue: 'Category' })}
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {CATEGORIES.filter((c) => c !== 'all').map((c) => (
                    <button
                      key={c}
                      onClick={() => setEditForm((prev) => ({ ...prev, category: c }))}
                      className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                        editForm.category === c
                          ? 'bg-oe-blue text-white'
                          : 'text-content-secondary hover:bg-surface-secondary border border-border-light'
                      }`}
                    >
                      {t(`documents.cat_${c}`, { defaultValue: c.charAt(0).toUpperCase() + c.slice(1) })}
                    </button>
                  ))}
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="text-xs font-medium text-content-primary block mb-1.5">
                  {t('documents.description_label', { defaultValue: 'Description' })}
                </label>
                <textarea
                  value={editForm.description}
                  onChange={(e) => setEditForm((prev) => ({ ...prev, description: e.target.value }))}
                  placeholder={t('documents.description_placeholder', { defaultValue: 'Add notes about this document...' })}
                  rows={3}
                  className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                />
              </div>

              {/* Tags */}
              <div>
                <label className="text-xs font-medium text-content-primary block mb-1.5">
                  {t('documents.tags_label', { defaultValue: 'Tags' })}
                </label>
                <div className="flex items-center gap-2 mb-2">
                  <input
                    type="text"
                    value={editForm.tagInput}
                    onChange={(e) => setEditForm((prev) => ({ ...prev, tagInput: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { e.preventDefault(); handleAddTag(); }
                    }}
                    placeholder={t('documents.tag_placeholder', { defaultValue: 'Type a tag and press Enter' })}
                    className="h-8 flex-1 rounded-lg border border-border bg-surface-primary px-3 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                  />
                  <Button variant="secondary" size="sm" onClick={handleAddTag} disabled={!editForm.tagInput.trim()}>
                    {t('common.add', { defaultValue: 'Add' })}
                  </Button>
                </div>
                {editForm.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {editForm.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 rounded-full bg-oe-blue/[0.08] px-2.5 py-1 text-2xs font-medium text-oe-blue"
                      >
                        {tag}
                        <button
                          onClick={() => handleRemoveTag(tag)}
                          className="hover:text-semantic-error transition-colors"
                          aria-label={`Remove tag ${tag}`}
                        >
                          <X size={10} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                {editForm.tags.length === 0 && (
                  <p className="text-2xs text-content-quaternary">
                    {t('documents.no_tags', { defaultValue: 'No tags yet. Tags help organize and find documents faster.' })}
                  </p>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex justify-end gap-2 px-5 py-3 border-t border-border-light bg-surface-primary/50">
              <Button variant="secondary" size="sm" onClick={() => setEditDoc(null)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                loading={editMutation.isPending}
                onClick={() => {
                  editMutation.mutate({
                    id: editDoc.id,
                    category: editForm.category,
                    description: editForm.description,
                    tags: editForm.tags,
                  });
                }}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Rename dialog ──────────────────────────────────────────────── */}
      {renameDoc && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in" onClick={() => setRenameDoc(null)}>
          <div className="relative w-full max-w-sm mx-4 rounded-xl bg-surface-elevated shadow-xl border border-border-light p-5" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('documents.rename', { defaultValue: 'Rename' })}
            </h3>
            <input
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && renameValue.trim()) {
                  renameMutation.mutate({ id: renameDoc.id, name: renameValue.trim() });
                }
                if (e.key === 'Escape') setRenameDoc(null);
              }}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-4">
              <Button variant="secondary" size="sm" onClick={() => setRenameDoc(null)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!renameValue.trim() || renameValue.trim() === renameDoc.name || renameMutation.isPending}
                loading={renameMutation.isPending}
                onClick={() => renameMutation.mutate({ id: renameDoc.id, name: renameValue.trim() })}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Drag overlay (full-page visual feedback) ────────────────────── */}
      {dragOver && (
        <div className="fixed inset-0 z-40 bg-oe-blue/5 border-4 border-dashed border-oe-blue/40 rounded-xl pointer-events-none flex items-center justify-center">
          <div className="bg-surface-elevated px-6 py-4 rounded-xl shadow-xl border border-border-light text-center">
            <Upload size={32} className="mx-auto text-oe-blue mb-2" />
            <p className="text-sm font-medium text-content-primary">
              {t('documents.drop_to_upload', { defaultValue: 'Drop files to upload' })}
            </p>
          </div>
        </div>
      )}

      {/* ── Preview modal ───────────────────────────────────────────────── */}
      {previewDoc && (
        <PreviewModal doc={previewDoc} onClose={handleClosePreview} />
      )}
    </div>
  );
}
