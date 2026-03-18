import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Table2, ArrowRight, FolderOpen } from 'lucide-react';
import { Card, Badge, EmptyState, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';

interface Project {
  id: string;
  name: string;
  currency: string;
  classification_standard: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
}

interface BOQWithProject extends BOQ {
  projectName: string;
  currency: string;
}

export function BOQListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data: projects, isLoading: projLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const { data: allBoqs, isLoading: boqLoading } = useQuery({
    queryKey: ['all-boqs', projects],
    queryFn: async () => {
      if (!projects || projects.length === 0) return [];
      const results: BOQWithProject[] = [];
      for (const p of projects) {
        try {
          const boqs = await apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${p.id}`);
          for (const b of boqs) {
            results.push({ ...b, projectName: p.name, currency: p.currency });
          }
        } catch {
          // skip failed fetches
        }
      }
      return results;
    },
    enabled: !!projects && projects.length > 0,
  });

  const isLoading = projLoading || boqLoading;

  return (
    <div className="max-w-content mx-auto">
      <div className="mb-6 animate-card-in" style={{ animationDelay: '0ms' }}>
        <h1 className="text-2xl font-bold text-content-primary">{t('boq.title')}</h1>
        <p className="mt-1 text-sm text-content-secondary">
          {allBoqs ? `${allBoqs.length} BOQs across ${projects?.length ?? 0} projects` : 'Loading...'}
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={80} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !allBoqs || allBoqs.length === 0 ? (
        <EmptyState
          icon={<Table2 size={24} strokeWidth={1.5} />}
          title="No Bills of Quantities yet"
          description="Create a project first, then add BOQs to it"
          action={
            <button
              onClick={() => navigate('/projects/new')}
              className="inline-flex items-center gap-2 text-sm font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
            >
              <FolderOpen size={14} />
              Create Project
            </button>
          }
        />
      ) : (
        <div className="space-y-3">
          {allBoqs.map((boq, i) => (
            <Card
              key={boq.id}
              hoverable
              padding="none"
              className="cursor-pointer animate-card-in"
              style={{ animationDelay: `${100 + i * 60}ms` }}
              onClick={() => navigate(`/boq/${boq.id}`)}
            >
              <div className="flex items-center gap-4 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                  <Table2 size={18} strokeWidth={1.75} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-content-primary truncate">
                    {boq.name}
                  </div>
                  <div className="mt-0.5 text-xs text-content-tertiary truncate">
                    {boq.projectName}
                    {boq.description ? ` — ${boq.description}` : ''}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge variant={boq.status === 'final' ? 'success' : boq.status === 'draft' ? 'blue' : 'neutral'} size="sm">
                    {boq.status}
                  </Badge>
                  <Badge variant="neutral" size="sm">
                    {boq.currency || '—'}
                  </Badge>
                  <span className="text-xs text-content-tertiary">
                    {new Date(boq.created_at).toLocaleDateString()}
                  </span>
                  <ArrowRight size={14} className="text-content-tertiary" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
