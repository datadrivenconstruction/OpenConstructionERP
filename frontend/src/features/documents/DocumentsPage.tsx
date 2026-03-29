import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Upload, FileText, Image, FileSpreadsheet, File, Trash2, Download,
  Search, X, Loader2, FolderOpen,
} from 'lucide-react';
import { Card, Button, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

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

const CATEGORIES = ['all', 'drawing', 'contract', 'specification', 'photo', 'correspondence', 'other'] as const;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(mime: string) {
  if (mime.includes('pdf')) return <FileText size={20} className="text-red-500" />;
  if (mime.includes('image')) return <Image size={20} className="text-green-500" />;
  if (mime.includes('sheet') || mime.includes('excel') || mime.includes('csv')) return <FileSpreadsheet size={20} className="text-blue-500" />;
  return <File size={20} className="text-content-tertiary" />;
}

export function DocumentsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const projectId = activeProjectId;

  const { data: documents, isLoading } = useQuery({
    queryKey: ['documents', projectId, category],
    queryFn: () => {
      const params = new URLSearchParams();
      if (projectId) params.set('project_id', projectId);
      if (category !== 'all') params.set('category', category);
      return apiGet<DocItem[]>(`/v1/documents/?${params.toString()}`);
    },
    enabled: !!projectId,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/documents/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      addToast({ type: 'success', title: t('documents.deleted', { defaultValue: 'Document deleted' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('documents.delete_failed', { defaultValue: 'Delete failed' }), message: err.message });
    },
  });

  const handleUpload = useCallback(async (files: FileList | File[]) => {
    if (!projectId) return;
    setUploading(true);
    const token = useAuthStore.getState().accessToken;

    for (const file of Array.from(files)) {
      const formData = new FormData();
      formData.append('file', file);

      try {
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;

        await fetch(`/api/v1/documents/upload?project_id=${projectId}&category=${category === 'all' ? 'other' : category}`, {
          method: 'POST',
          headers,
          body: formData,
        });
        addToast({ type: 'success', title: t('documents.uploaded', { defaultValue: 'Uploaded' }), message: file.name });
      } catch {
        addToast({ type: 'error', title: t('documents.upload_failed', { defaultValue: 'Upload failed' }), message: file.name });
      }
    }

    setUploading(false);
    queryClient.invalidateQueries({ queryKey: ['documents'] });
  }, [projectId, category, addToast, t, queryClient]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) handleUpload(e.dataTransfer.files);
  }, [handleUpload]);

  const filtered = (documents ?? []).filter((d) =>
    !query || d.name.toLowerCase().includes(query.toLowerCase()),
  );

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
    <div className="max-w-content mx-auto animate-fade-in">
      <Breadcrumb items={[
        { label: t('nav.dashboard', 'Dashboard'), to: '/' },
        { label: t('nav.documents', 'Documents') },
        ...(activeProjectName ? [{ label: activeProjectName }] : []),
      ]} className="mb-4" />

      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('documents.title', { defaultValue: 'Documents' })}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('documents.subtitle', { defaultValue: 'Upload and manage project files — drawings, contracts, specifications' })}
          </p>
        </div>
        <label className="cursor-pointer">
          <input type="file" multiple className="hidden" onChange={(e) => e.target.files && handleUpload(e.target.files)} />
          <Button variant="primary" size="sm" icon={uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} as="span">
            {t('documents.upload', { defaultValue: 'Upload Files' })}
          </Button>
        </label>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`mb-5 rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver ? 'border-oe-blue bg-oe-blue-subtle/30' : 'border-border-light'
        }`}
      >
        <Upload size={24} className="mx-auto text-content-tertiary mb-2" />
        <p className="text-sm text-content-secondary">
          {t('documents.drop_hint', { defaultValue: 'Drag & drop files here, or click Upload' })}
        </p>
        <p className="text-xs text-content-tertiary mt-1">PDF, images, Excel, DWG, IFC — any file type</p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none" />
          <input
            type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={t('documents.search', { defaultValue: 'Search files...' })}
            className="h-10 w-full rounded-lg border border-border bg-surface-primary pl-10 pr-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          {query && (
            <button onClick={() => setQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary">
              <X size={14} />
            </button>
          )}
        </div>
        <div className="flex gap-1.5">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                category === c ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary border border-border-light'
              }`}
            >
              {t(`documents.cat_${c}`, { defaultValue: c === 'all' ? 'All' : c.charAt(0).toUpperCase() + c.slice(1) })}
            </button>
          ))}
        </div>
      </div>

      {/* Documents grid */}
      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} padding="md"><div className="h-16 animate-pulse bg-surface-secondary rounded" /></Card>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<FolderOpen size={24} />}
          title={t('documents.empty', { defaultValue: 'No documents yet' })}
          description={t('documents.empty_hint', { defaultValue: 'Upload your first file — drawings, contracts, photos, or any project document.' })}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((doc) => (
            <Card key={doc.id} padding="none" hoverable className="group">
              <div className="flex items-start gap-3 px-4 py-3">
                <div className="mt-0.5 shrink-0">{fileIcon(doc.mime_type)}</div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-semibold text-content-primary truncate">{doc.name}</h3>
                  <div className="flex items-center gap-2 mt-1 text-2xs text-content-tertiary">
                    <span>{formatSize(doc.file_size)}</span>
                    <span>&middot;</span>
                    <Badge variant="neutral" size="sm">{doc.category}</Badge>
                    {doc.version > 1 && <Badge variant="blue" size="sm">v{doc.version}</Badge>}
                  </div>
                  <p className="text-2xs text-content-quaternary mt-1">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <a
                    href={`/api/v1/documents/${doc.id}/download`}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue transition-colors"
                    title={t('documents.download', { defaultValue: 'Download' })}
                  >
                    <Download size={14} />
                  </a>
                  <button
                    onClick={() => {
                      if (window.confirm(t('documents.confirm_delete', { defaultValue: 'Delete this document?' }))) {
                        deleteMutation.mutate(doc.id);
                      }
                    }}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error transition-colors"
                    title={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
