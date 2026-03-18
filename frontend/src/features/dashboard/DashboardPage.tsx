import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '@/shared/lib/api';
import {
  FolderPlus,
  ArrowRight,
  Layers,
  Globe,
  Zap,
  ShieldCheck,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, Skeleton } from '@/shared/ui';

export function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectSummary[]>('/v1/projects/').catch(() => []),
    retry: false,
  });

  return (
    <div className="max-w-content mx-auto">
      {/* Hero — gradient animated heading */}
      <div
        className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between animate-card-in"
        style={{ animationDelay: '0ms' }}
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight gradient-text">
            {t('dashboard.welcome')}
          </h1>
          <p className="mt-2 text-base text-content-secondary animate-stagger-in" style={{ animationDelay: '100ms' }}>
            {t('dashboard.subtitle')}
          </p>
        </div>
        <div className="animate-stagger-in" style={{ animationDelay: '200ms' }}>
          <Button
            variant="primary"
            size="lg"
            icon={<FolderPlus size={18} />}
            onClick={() => navigate('/projects/new')}
            className="btn-shimmer"
          >
            {t('projects.new_project')}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent Projects — staggered card entrance */}
        <div
          className="lg:col-span-2 animate-card-in"
          style={{ animationDelay: '150ms' }}
        >
          <Card padding="none">
            <div className="p-6 pb-0">
              <CardHeader
                title={t('dashboard.recent_projects')}
                action={
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<ArrowRight size={14} />}
                    iconPosition="right"
                    onClick={() => navigate('/projects')}
                  >
                    {t('projects.title')}
                  </Button>
                }
              />
            </div>
            <CardContent className="!mt-0">
              <ProjectsList projects={projects} />
            </CardContent>
          </Card>
        </div>

        {/* System Status — staggered card entrance */}
        <div
          className="animate-card-in"
          style={{ animationDelay: '300ms' }}
        >
          <Card>
            <CardHeader title={t('dashboard.system_status')} />
            <CardContent>
              <SystemStatus />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

/* ── Projects List ────────────────────────────────────────────────────── */

interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  region: string;
  classification_standard: string;
  currency: string;
  created_at: string;
}

function ProjectsList({ projects }: { projects?: ProjectSummary[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (!projects || projects.length === 0) {
    return (
      <div className="px-6 py-10 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary">
          <FolderPlus size={22} className="text-content-tertiary" strokeWidth={1.5} />
        </div>
        <p className="text-sm font-medium text-content-primary">{t('projects.no_projects')}</p>
        <p className="mt-1 text-xs text-content-tertiary">
          Create your first project to get started
        </p>
        <div className="mt-4">
          <Button variant="primary" size="sm" onClick={() => navigate('/projects/new')}>
            {t('projects.new_project')}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border-light">
      {projects.map((p, index) => (
        <button
          key={p.id}
          onClick={() => navigate(`/projects/${p.id}`)}
          className="flex w-full items-center gap-4 px-6 py-3.5 text-left transition-all duration-normal ease-oe hover:bg-surface-secondary animate-stagger-in"
          style={{ animationDelay: `${300 + index * 60}ms` }}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue text-xs font-bold">
            {p.name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-content-primary truncate">{p.name}</div>
            <div className="text-xs text-content-tertiary truncate">
              {p.description || `${p.classification_standard.toUpperCase()} · ${p.currency}`}
            </div>
          </div>
          <div className="text-xs text-content-tertiary">
            {new Date(p.created_at).toLocaleDateString()}
          </div>
          <ArrowRight size={14} className="text-content-tertiary" />
        </button>
      ))}
    </div>
  );
}

/* ── System Status ────────────────────────────────────────────────────── */

function SystemStatus() {
  const { t } = useTranslation();

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['health'],
    queryFn: () => fetch('/api/health').then((r) => r.json()),
    retry: false,
    refetchInterval: 30000,
  });

  const { data: modules } = useQuery({
    queryKey: ['modules'],
    queryFn: () => fetch('/api/system/modules').then((r) => r.json()),
    retry: false,
  });

  const { data: rules } = useQuery({
    queryKey: ['validation-rules'],
    queryFn: () => fetch('/api/system/validation-rules').then((r) => r.json()),
    retry: false,
  });

  const isHealthy = health?.status === 'healthy';

  return (
    <div className="space-y-4">
      {/* API status with live dot */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '400ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          API
          {isHealthy && <span className="live-dot" aria-label="Live" />}
        </span>
        {healthLoading ? (
          <Skeleton width={80} height={20} rounded="full" />
        ) : (
          <Badge variant={isHealthy ? 'success' : 'error'} dot size="sm">
            {isHealthy ? 'Healthy' : 'Offline'}
          </Badge>
        )}
      </div>

      {/* Version */}
      {health?.version && (
        <div
          className="flex items-center justify-between animate-stagger-in"
          style={{ animationDelay: '460ms' }}
        >
          <span className="text-sm text-content-secondary">Version</span>
          <span className="text-sm font-mono text-content-primary inline-block animate-count-up" style={{ animationDelay: '500ms' }}>
            {health.version}
          </span>
        </div>
      )}

      {/* Modules loaded */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '520ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <Layers size={14} strokeWidth={1.75} />
          {t('dashboard.modules_loaded')}
        </span>
        <span className="text-sm font-semibold text-content-primary inline-block animate-count-up" style={{ animationDelay: '600ms' }}>
          {modules?.modules?.length ?? '\u2014'}
        </span>
      </div>

      {/* Validation rules */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '580ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <ShieldCheck size={14} strokeWidth={1.75} />
          {t('dashboard.validation_rules')}
        </span>
        <span className="text-sm font-semibold text-content-primary inline-block animate-count-up" style={{ animationDelay: '680ms' }}>
          {rules?.rules?.length ?? '\u2014'}
        </span>
      </div>

      {/* Languages */}
      <div
        className="flex items-center justify-between animate-stagger-in"
        style={{ animationDelay: '640ms' }}
      >
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <Globe size={14} strokeWidth={1.75} />
          {t('dashboard.languages')}
        </span>
        <span className="text-sm font-semibold text-content-primary inline-block animate-count-up" style={{ animationDelay: '760ms' }}>
          20
        </span>
      </div>

      {/* Phase indicator */}
      <div
        className="border-t border-border-light pt-3 animate-stagger-in"
        style={{ animationDelay: '700ms' }}
      >
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <Zap size={12} />
          <span>Phase 1 — Core Estimation</span>
        </div>
      </div>
    </div>
  );
}
