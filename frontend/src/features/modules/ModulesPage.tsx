import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Package, Layers, ShieldCheck, Calendar, DollarSign, Database, Users, FolderOpen } from 'lucide-react';
import { Card, Badge } from '@/shared/ui';

interface ModuleInfo {
  name: string;
  version: string;
  display_name: string;
  category: string;
  depends: string[];
  has_router: boolean;
  loaded: boolean;
}

const moduleIcons: Record<string, React.ReactNode> = {
  oe_users: <Users size={18} />,
  oe_projects: <FolderOpen size={18} />,
  oe_boq: <Layers size={18} />,
  oe_costs: <Database size={18} />,
  oe_assemblies: <Package size={18} />,
  oe_schedule: <Calendar size={18} />,
  oe_costmodel: <DollarSign size={18} />,
  oe_validation: <ShieldCheck size={18} />,
};

export function ModulesPage() {
  const { t } = useTranslation();

  const { data: modules } = useQuery({
    queryKey: ['modules'],
    queryFn: () => fetch('/api/system/modules').then((r) => r.json()).then((d: { modules: ModuleInfo[] }) => d.modules),
  });

  const { data: rules } = useQuery({
    queryKey: ['validation-rules'],
    queryFn: () => fetch('/api/system/validation-rules').then((r) => r.json()),
  });

  return (
    <div className="max-w-content mx-auto">
      <div className="mb-6 animate-card-in" style={{ animationDelay: '0ms' }}>
        <h1 className="text-2xl font-bold text-content-primary">{t('modules.title', 'Modules')}</h1>
        <p className="mt-1 text-sm text-content-secondary">
          {modules?.length ?? 0} modules loaded, {rules?.rules?.length ?? 0} validation rules active
        </p>
      </div>

      {/* Loaded modules */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {modules?.map((mod, i) => (
          <Card
            key={mod.name}
            className="animate-card-in"
            style={{ animationDelay: `${100 + i * 60}ms` }}
          >
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                {moduleIcons[mod.name] ?? <Package size={18} />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-content-primary truncate">{mod.display_name}</span>
                  <Badge variant="success" size="sm" dot>Active</Badge>
                </div>
                <div className="mt-0.5 text-xs text-content-tertiary font-mono">{mod.name} v{mod.version}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  <Badge variant="neutral" size="sm">{mod.category}</Badge>
                  {mod.has_router && <Badge variant="blue" size="sm">API</Badge>}
                  {mod.depends.length > 0 && (
                    <Badge variant="neutral" size="sm">
                      {mod.depends.length} deps
                    </Badge>
                  )}
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Validation Rules */}
      {rules?.rule_sets && (
        <div className="mt-8 animate-card-in" style={{ animationDelay: '500ms' }}>
          <h2 className="text-lg font-semibold text-content-primary mb-4">Validation Rule Sets</h2>
          <Card padding="none">
            <div className="divide-y divide-border-light">
              {Object.entries(rules.rule_sets as Record<string, number>).map(([name, count]) => (
                <div key={name} className="flex items-center justify-between px-5 py-3">
                  <div className="flex items-center gap-3">
                    <ShieldCheck size={16} className="text-content-tertiary" />
                    <span className="text-sm font-medium text-content-primary">{name}</span>
                  </div>
                  <Badge variant="neutral" size="sm">{count} rules</Badge>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
