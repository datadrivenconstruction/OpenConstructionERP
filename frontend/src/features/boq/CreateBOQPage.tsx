import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button, Input, Card } from '@/shared/ui';
import { boqApi } from './api';

export function CreateBOQPage() {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const mutation = useMutation({
    mutationFn: () => boqApi.create({ project_id: projectId!, name, description }),
    onSuccess: (boq) => {
      queryClient.invalidateQueries({ queryKey: ['boqs', projectId] });
      navigate(`/boq/${boq.id}`);
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !projectId) return;
    mutation.mutate();
  };

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      <button
        onClick={() => navigate(`/projects/${projectId}`)}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        Back to project
      </button>

      <h1 className="text-2xl font-bold text-content-primary mb-6">
        New Bill of Quantities
      </h1>

      <Card>
        <form onSubmit={handleSubmit} className="space-y-5">
          <Input
            label="BOQ Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Main Building — Structural Works"
            required
            autoFocus
          />

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Scope of this BOQ..."
              rows={3}
              className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
            />
          </div>

          {mutation.error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {(mutation.error as Error).message || 'Failed to create BOQ'}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={() => navigate(-1)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={mutation.isPending}>
              Create BOQ
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
