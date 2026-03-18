import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  FolderPlus,
  FileUp,
  Database,
  ShieldCheck,
  ArrowRight,
  Activity,
  Layers,
  Globe,
  Zap,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, StatusDot, Skeleton } from '@/shared/ui';

export function DashboardPage() {
  const { t } = useTranslation();

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Hero */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-content-primary">
          {t('dashboard.welcome')}
        </h1>
        <p className="mt-2 text-base text-content-secondary">
          {t('dashboard.subtitle')}
        </p>
      </div>

      {/* Quick Actions */}
      <section className="mb-8">
        <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
          {t('dashboard.quick_actions')}
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <QuickAction
            icon={<FolderPlus size={20} strokeWidth={1.5} />}
            label={t('projects.new_project')}
            description="Start a new cost estimation"
            color="blue"
          />
          <QuickAction
            icon={<FileUp size={20} strokeWidth={1.5} />}
            label={t('common.import')}
            description="GAEB, Excel, CAD files"
            color="green"
          />
          <QuickAction
            icon={<Database size={20} strokeWidth={1.5} />}
            label={t('costs.title')}
            description="55,000+ cost items (CWICR)"
            color="purple"
          />
          <QuickAction
            icon={<ShieldCheck size={20} strokeWidth={1.5} />}
            label={t('validation.title')}
            description="DIN 276, GAEB, NRM, quality"
            color="amber"
          />
        </div>
      </section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent Projects */}
        <div className="lg:col-span-2">
          <Card padding="none">
            <div className="p-6 pb-0">
              <CardHeader
                title={t('dashboard.recent_projects')}
                action={
                  <Button variant="ghost" size="sm" icon={<ArrowRight size={14} />} iconPosition="right">
                    {t('projects.title')}
                  </Button>
                }
              />
            </div>
            <CardContent className="!mt-0">
              <ProjectsList />
            </CardContent>
          </Card>
        </div>

        {/* System Status */}
        <div>
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

/* ── Quick Action Card ────────────────────────────────────────────────── */

const colorMap = {
  blue: { bg: 'bg-oe-blue-subtle', text: 'text-oe-blue' },
  green: { bg: 'bg-semantic-success-bg', text: 'text-[#15803d]' },
  purple: { bg: 'bg-[#f3f0ff]', text: 'text-[#6d28d9]' },
  amber: { bg: 'bg-semantic-warning-bg', text: 'text-[#b45309]' },
};

function QuickAction({
  icon,
  label,
  description,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  description: string;
  color: keyof typeof colorMap;
}) {
  const colors = colorMap[color];
  return (
    <button
      className={
        'group flex items-center gap-4 rounded-xl border border-border-light bg-surface-elevated p-4 ' +
        'text-left transition-all duration-normal ease-oe ' +
        'hover:shadow-md hover:border-border active:scale-[0.98]'
      }
    >
      <div
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${colors.bg} ${colors.text}`}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-content-primary">{label}</div>
        <div className="text-xs text-content-tertiary truncate">{description}</div>
      </div>
    </button>
  );
}

/* ── Projects List ────────────────────────────────────────────────────── */

function ProjectsList() {
  const { t } = useTranslation();

  // Placeholder — no projects yet in Phase 0
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
        <Button variant="primary" size="sm">
          {t('projects.new_project')}
        </Button>
      </div>
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
      {/* API Status */}
      <div className="flex items-center justify-between">
        <span className="text-sm text-content-secondary">API</span>
        {healthLoading ? (
          <Skeleton width={80} height={20} rounded="full" />
        ) : (
          <Badge variant={isHealthy ? 'success' : 'error'} dot size="sm">
            {isHealthy ? 'Healthy' : 'Offline'}
          </Badge>
        )}
      </div>

      {health?.version && (
        <div className="flex items-center justify-between">
          <span className="text-sm text-content-secondary">Version</span>
          <span className="text-sm font-mono text-content-primary">{health.version}</span>
        </div>
      )}

      {/* Modules */}
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <Layers size={14} strokeWidth={1.75} />
          {t('dashboard.modules_loaded')}
        </span>
        <span className="text-sm font-semibold text-content-primary">
          {modules?.modules?.length ?? '—'}
        </span>
      </div>

      {/* Validation Rules */}
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <ShieldCheck size={14} strokeWidth={1.75} />
          {t('dashboard.validation_rules')}
        </span>
        <span className="text-sm font-semibold text-content-primary">
          {rules?.rules?.length ?? '—'}
        </span>
      </div>

      {/* Languages */}
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm text-content-secondary">
          <Globe size={14} strokeWidth={1.75} />
          {t('dashboard.languages')}
        </span>
        <span className="text-sm font-semibold text-content-primary">20</span>
      </div>

      {/* Separator */}
      <div className="border-t border-border-light pt-3">
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <Zap size={12} />
          <span>Phase 0 — Foundation</span>
        </div>
      </div>
    </div>
  );
}
