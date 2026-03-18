import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Table2 } from 'lucide-react';
import { Button, Card, CardHeader, Badge, Skeleton } from '@/shared/ui';
import { projectsApi } from './api';

interface BOQSummary {
  id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
}

export function ProjectDetailPage() {
  const { t } = useTranslation();
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  });

  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () =>
      fetch(`/api/v1/boq/boqs/?project_id=${projectId}`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem('oe_access_token')}`,
        },
      }).then((r) => (r.ok ? r.json() : [])),
    enabled: !!projectId,
  });

  if (isLoading) {
    return (
      <div className="max-w-content mx-auto space-y-4 animate-fade-in">
        <Skeleton height={24} width={200} />
        <Skeleton height={120} className="w-full" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="max-w-content mx-auto text-center py-16">
        <p className="text-content-secondary">Project not found</p>
      </div>
    );
  }

  const standardLabels: Record<string, string> = {
    din276: 'DIN 276',
    nrm: 'NRM',
    masterformat: 'MasterFormat',
  };

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <button
        onClick={() => navigate('/projects')}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        {t('projects.title')}
      </button>

      {/* Project Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{project.name}</h1>
          {project.description && (
            <p className="mt-1 text-sm text-content-secondary">{project.description}</p>
          )}
          <div className="mt-3 flex items-center gap-2">
            <Badge variant="blue" size="sm">
              {standardLabels[project.classification_standard] ?? project.classification_standard}
            </Badge>
            <Badge variant="neutral" size="sm">{project.currency}</Badge>
            <Badge variant="neutral" size="sm">{project.region}</Badge>
          </div>
        </div>
        <Button
          variant="primary"
          icon={<Table2 size={16} />}
          onClick={() => navigate(`/projects/${projectId}/boq/new`)}
        >
          New BOQ
        </Button>
      </div>

      {/* BOQ List */}
      <Card padding="none">
        <div className="p-6 pb-0">
          <CardHeader title={t('boq.title')} subtitle="Bills of Quantities for this project" />
        </div>
        <div className="mt-4">
          {!boqs || boqs.length === 0 ? (
            <div className="px-6 py-10 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary">
                <Table2 size={22} className="text-content-tertiary" strokeWidth={1.5} />
              </div>
              <p className="text-sm font-medium text-content-primary">No BOQs yet</p>
              <p className="mt-1 text-xs text-content-tertiary">
                Create a Bill of Quantities to start estimating
              </p>
              <div className="mt-4">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => navigate(`/projects/${projectId}/boq/new`)}
                >
                  Create BOQ
                </Button>
              </div>
            </div>
          ) : (
            <div className="divide-y divide-border-light">
              {(boqs as BOQSummary[]).map((boq) => (
                <button
                  key={boq.id}
                  onClick={() => navigate(`/boq/${boq.id}`)}
                  className="flex w-full items-center gap-4 px-6 py-3.5 text-left transition-colors hover:bg-surface-secondary"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
                    <Table2 size={16} strokeWidth={1.75} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-content-primary truncate">
                      {boq.name}
                    </div>
                    <div className="text-xs text-content-tertiary">
                      {boq.description || boq.status}
                    </div>
                  </div>
                  <Badge variant={boq.status === 'final' ? 'success' : 'neutral'} size="sm">
                    {boq.status}
                  </Badge>
                </button>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
