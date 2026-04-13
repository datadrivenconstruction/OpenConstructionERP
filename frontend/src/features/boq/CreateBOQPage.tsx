import { useState, useEffect, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronDown, X, FileSpreadsheet } from 'lucide-react';
import { Button, Input } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet } from '@/shared/lib/api';
import { boqApi } from './api';

interface Project {
  id: string;
  name: string;
}

interface CreateBOQModalProps {
  open: boolean;
  onClose: () => void;
  defaultProjectId?: string;
}

export function CreateBOQModal({ open, onClose, defaultProjectId }: CreateBOQModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [selectedProjectId, setSelectedProjectId] = useState(defaultProjectId ?? '');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  // Sync default project when modal opens or defaultProjectId changes
  useEffect(() => {
    if (open) {
      setSelectedProjectId(defaultProjectId ?? '');
      setName('');
      setDescription('');
    }
  }, [open, defaultProjectId]);

  const mutation = useMutation({
    mutationFn: () => boqApi.create({ project_id: selectedProjectId, name, description }),
    onSuccess: (boq) => {
      queryClient.invalidateQueries({ queryKey: ['boqs', selectedProjectId] });
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      addToast({ type: 'success', title: t('toasts.boq_created', { defaultValue: 'Bill of Quantities created successfully' }) });
      onClose();
      navigate(`/boq/${boq.id}`);
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.boq_create_failed', { defaultValue: 'Failed to create Bill of Quantities' }), message: error.message });
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !selectedProjectId) return;
    mutation.mutate();
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-lg mx-4 rounded-2xl bg-surface-elevated border border-border-light shadow-2xl animate-fade-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-primary/10">
              <FileSpreadsheet size={20} className="text-accent-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-content-primary">
                {t('projects.new_boq', { defaultValue: 'New BOQ' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('boq.create_subtitle', { defaultValue: 'Create a new bill of quantities' })}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-hover transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-6 pb-6 space-y-4">
          {/* Project selector */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('common.project', { defaultValue: 'Project' })}
            </label>
            <div className="relative">
              <select
                value={selectedProjectId}
                onChange={(e) => setSelectedProjectId(e.target.value)}
                className="w-full h-10 appearance-none rounded-lg border border-border px-3 pr-9 text-sm text-content-primary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary"
                required
              >
                <option value="" disabled>
                  {t('boq.select_project', { defaultValue: 'Select Project' })}
                </option>
                {projects?.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <ChevronDown size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
            </div>
          </div>

          {/* Name */}
          <Input
            label={t('boq.name_label', { defaultValue: 'BOQ Name' })}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Main Building — Structural Works"
            required
            autoFocus
          />

          {/* Description */}
          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              {t('common.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('boq.scope_placeholder', { defaultValue: 'Scope of this BOQ...' })}
              rows={3}
              className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
            />
          </div>

          {/* Error */}
          {mutation.error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {(mutation.error as Error).message || t('boq.create_failed', 'Failed to create BOQ')}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={mutation.isPending}>
              {t('boq.create_boq', { defaultValue: 'Create BOQ' })}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Route compat — redirects to /boq and opens modal
export function CreateBOQPage() {
  const navigate = useNavigate();
  const { projectId } = useParams<{ projectId: string }>();

  useEffect(() => {
    navigate('/boq', { state: { openCreateModal: true, projectId }, replace: true });
  }, [navigate, projectId]);

  return null;
}
