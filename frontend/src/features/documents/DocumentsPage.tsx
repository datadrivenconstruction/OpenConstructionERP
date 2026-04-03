import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Upload, FileText, Image, FileSpreadsheet, File, Trash2, Download,
  Search, X, Loader2, FolderOpen, ChevronDown, HardDrive, Eye,
  CheckCircle2, XCircle, MoreHorizontal, Pencil, Tag,
} from 'lucide-react';
import { Card, Button, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet, apiDelete, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

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
}

type SortField = 'date' | 'name' | 'size';

const CATEGORIES = ['all', 'drawing', 'contract', 'specification', 'photo', 'correspondence', 'other'] as const;

const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024; // 100 MB

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

/* ── Preview Modal ───────────────────────────────────────────────────── */

function PreviewModal({
  doc,
  onClose,
}: {
  doc: DocItem;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const kind = isPreviewable(doc.mime_type);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

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
  const [editForm, setEditForm] = useState({ category: '', description: '', tagInput: '', tags: [] as string[] });
  const menuRef = useRef<HTMLDivElement>(null);

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{
    current: number;
    total: number;
    fileName: string;
    successCount: number;
    failCount: number;
  } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const projectId = activeProjectId;

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
      addToast({ type: 'success', title: t('documents.deleted', { defaultValue: 'Document deleted' }) });
      setConfirmDeleteId(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.delete_failed', { defaultValue: 'Delete failed' }), message: err.message });
      setConfirmDeleteId(null);
    },
  });

  /* ── Upload handler ─────────────────────────────────────────────────── */

  const handleUpload = useCallback(async (files: FileList | File[]) => {
    if (!projectId) return;

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

    setUploading(true);
    const token = useAuthStore.getState().accessToken;
    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < validFiles.length; i++) {
      const file = validFiles[i]!;
      setUploadProgress({
        current: i + 1,
        total: validFiles.length,
        fileName: file.name,
        successCount,
        failCount,
      });

      const formData = new FormData();
      formData.append('file', file);

      try {
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const response = await fetch(
          `/api/v1/documents/upload?project_id=${projectId}&category=${category === 'all' ? 'other' : category}`,
          { method: 'POST', headers, body: formData },
        );

        if (!response.ok) {
          let detail = file.name;
          try {
            const body = await response.json();
            if (body?.detail) detail = `${file.name}: ${body.detail}`;
          } catch {
            // ignore parse error
          }
          addToast({ type: 'error', title: t('documents.upload_failed', { defaultValue: 'Upload failed' }), message: detail });
          failCount++;
        } else {
          successCount++;
        }
      } catch {
        addToast({ type: 'error', title: t('documents.upload_failed', { defaultValue: 'Upload failed' }), message: file.name });
        failCount++;
      }
    }

    // Summary toast for multi-file uploads
    if (validFiles.length > 1) {
      addToast({
        type: failCount > 0 ? 'warning' : 'success',
        title: t('documents.upload_summary', { defaultValue: 'Upload complete' }),
        message: t('documents.upload_summary_detail', {
          defaultValue: '{{success}} succeeded, {{fail}} failed out of {{total}} files',
          success: successCount,
          fail: failCount,
          total: validFiles.length,
        }),
      });
    } else if (validFiles.length === 1 && successCount === 1) {
      addToast({ type: 'success', title: t('documents.uploaded', { defaultValue: 'Uploaded' }), message: validFiles[0]!.name });
    }

    setUploading(false);
    setUploadProgress(null);
    queryClient.invalidateQueries({ queryKey: ['documents'] });

    // Reset input so re-selecting the same file works
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [projectId, category, addToast, t, queryClient]);

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
      addToast({ type: 'success', title: t('documents.renamed', { defaultValue: 'Document renamed' }) });
      setRenameDoc(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.rename_failed', { defaultValue: 'Rename failed' }), message: err.message });
    },
  });

  // Edit properties mutation
  const editMutation = useMutation({
    mutationFn: ({ id, ...fields }: { id: string; category?: string; description?: string; tags?: string[] }) =>
      apiPatch<unknown, Record<string, unknown>>(`/v1/documents/${id}`, fields),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      addToast({ type: 'success', title: t('documents.properties_saved', { defaultValue: 'Properties saved' }) });
      setEditDoc(null);
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.save_failed', { defaultValue: 'Save failed' }), message: err.message });
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
      <div className="max-w-content mx-auto animate-fade-in">
        <Breadcrumb items={[{ label: t('nav.dashboard', 'Dashboard'), to: '/' }, { label: t('nav.documents', 'Documents') }]} className="mb-4" />
        <EmptyState
          icon={<FolderOpen size={24} />}
          title={t('documents.select_project', { defaultValue: 'Select a project' })}
          description={t('documents.select_project_hint', { defaultValue: 'Use the project switcher in the header to select a project first.' })}
        />
      </div>
    );
  }

  return (
    <div
      className="max-w-content mx-auto animate-fade-in"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('nav.documents', 'Documents') },
        ...(activeProjectName ? [{ label: activeProjectName }] : []),
      ]} className="mb-4" />

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
            icon={uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {t('documents.upload', { defaultValue: 'Upload Files' })}
          </Button>
        </div>
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

      {/* ── Upload progress bar ─────────────────────────────────────────── */}
      {uploadProgress && (
        <div className="mb-4 rounded-lg border border-border-light bg-surface-primary px-4 py-3">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-content-secondary flex items-center gap-1.5">
              <Loader2 size={13} className="animate-spin text-oe-blue" />
              {t('documents.uploading_file', {
                defaultValue: 'Uploading {{current}} of {{total}}: {{name}}',
                current: uploadProgress.current,
                total: uploadProgress.total,
                name: uploadProgress.fileName,
              })}
            </span>
            <span className="text-content-tertiary flex items-center gap-2">
              {uploadProgress.successCount > 0 && (
                <span className="flex items-center gap-0.5 text-semantic-success">
                  <CheckCircle2 size={12} /> {uploadProgress.successCount}
                </span>
              )}
              {uploadProgress.failCount > 0 && (
                <span className="flex items-center gap-0.5 text-semantic-error">
                  <XCircle size={12} /> {uploadProgress.failCount}
                </span>
              )}
            </span>
          </div>
          <div className="h-1.5 bg-surface-secondary rounded-full overflow-hidden">
            <div
              className="h-full bg-oe-blue rounded-full transition-all duration-300"
              style={{ width: `${(uploadProgress.current / uploadProgress.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Drop zone ───────────────────────────────────────────────────── */}
      <div
        className={`mb-5 rounded-xl border-2 border-dashed p-8 text-center transition-all duration-200 ${
          dragOver
            ? 'border-oe-blue bg-oe-blue-subtle/30 scale-[1.01] shadow-lg'
            : 'border-border-light hover:border-border'
        }`}
        role="region"
        aria-label={t('documents.drop_zone', { defaultValue: 'File drop zone' })}
      >
        <Upload size={24} className={`mx-auto mb-2 transition-colors ${dragOver ? 'text-oe-blue' : 'text-content-tertiary'}`} />
        <p className="text-sm text-content-secondary">
          {dragOver
            ? t('documents.drop_now', { defaultValue: 'Drop files to upload' })
            : t('documents.drop_hint', { defaultValue: 'Drag & drop files here, or click Upload' })}
        </p>
        <p className="text-xs text-content-tertiary mt-1">
          {t('documents.supported_types', { defaultValue: 'PDF, images, Excel, DWG, IFC — any file type (max 100 MB)' })}
        </p>
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
            icon={<Search size={24} />}
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
            icon={<FolderOpen size={24} />}
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
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-2xs text-content-quaternary">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </p>
                      {previewKind && (
                        <span className="flex items-center gap-0.5 text-2xs text-oe-blue opacity-0 group-hover:opacity-100 transition-opacity">
                          <Eye size={10} />
                          {t('documents.preview', { defaultValue: 'Preview' })}
                        </span>
                      )}
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
                  <p className="text-2xs text-content-tertiary">{formatSize(editDoc.file_size)} · {new Date(editDoc.created_at).toLocaleDateString()}</p>
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
