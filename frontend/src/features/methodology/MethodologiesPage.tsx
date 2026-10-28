// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Methodologies hub: a templates gallery (the built-in catalogue, grouped) plus the
// list of methodologies installed into the active project. Built-in templates
// install an editable project clone; installed clones open in the editor.
// Read-only built-ins (project_id === null) cannot be edited - the UI offers
// "Duplicate to edit" instead.

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Banknote,
  CheckCircle2,
  Copy,
  Download,
  FlaskConical,
  Globe2,
  Layers3,
  Pencil,
  Plus,
  Star,
  TrainFront,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  ErrorState,
  SkeletonCard,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { CountryFlag } from '@/shared/ui/CountryFlag';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { methodologyApi } from './api';
import type { MethodologyListItem, TemplateListItem } from './types';
import { CreateMethodologyModal } from './CreateMethodologyModal';

/** Group a template list into the sensible buckets the gallery renders. */
function groupTemplates(templates: TemplateListItem[]) {
  const international = templates.filter((t) => t.slug === 'international');
  const countries = templates.filter(
    (t) => t.country_code && t.slug !== 'uzbekistan',
  );
  const uzbekistan = templates.filter((t) => t.slug === 'uzbekistan');
  const industry = templates.filter((t) => t.industry);
  return { international, countries, uzbekistan, industry };
}

function TemplateCard({
  template,
  installedSlug,
  onInstall,
  installing,
}: {
  template: TemplateListItem;
  /** The project clone slug for this template, if already installed. */
  installedSlug: string | null;
  onInstall: (slug: string) => void;
  installing: boolean;
}) {
  const { t } = useTranslation();
  const installed = installedSlug !== null;
  return (
    <Card padding="md" className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          {template.industry ? (
            <TrainFront size={18} />
          ) : template.country_code ? (
            <CountryFlag code={template.country_code} size={20} />
          ) : (
            <Globe2 size={18} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h4 className="truncate text-sm font-semibold text-content-primary">
              {template.name}
            </h4>
            {installed && (
              <Badge variant="success" size="sm">
                {t('methodology.gallery.installed', { defaultValue: 'Installed' })}
              </Badge>
            )}
          </div>
          {template.description && (
            <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-content-secondary">
              {template.description}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {template.currency && (
          <Badge variant="neutral" size="sm">
            {template.currency}
          </Badge>
        )}
        <Badge variant="neutral" size="sm">
          {t('methodology.gallery.step_count', {
            defaultValue: '{{count}} markup steps',
            count: template.step_count,
          })}
        </Badge>
      </div>

      <div className="mt-auto flex items-center justify-end pt-1">
        <Button
          variant={installed ? 'secondary' : 'primary'}
          size="sm"
          icon={installed ? <Copy size={14} /> : <Download size={14} />}
          loading={installing}
          onClick={() => onInstall(template.slug)}
        >
          {installed
            ? t('methodology.gallery.install_copy', { defaultValue: 'Install another copy' })
            : t('methodology.gallery.install', { defaultValue: 'Install' })}
        </Button>
      </div>
    </Card>
  );
}

function GallerySection({
  title,
  icon,
  templates,
  installedByTemplate,
  onInstall,
  installingSlug,
}: {
  title: string;
  icon: React.ReactNode;
  templates: TemplateListItem[];
  installedByTemplate: Record<string, string>;
  onInstall: (slug: string) => void;
  installingSlug: string | null;
}) {
  if (templates.length === 0) return null;
  return (
    <div>
      <div className="mb-2.5 flex items-center gap-2">
        <span className="text-content-tertiary">{icon}</span>
        <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {templates.map((tpl) => (
          <TemplateCard
            key={tpl.slug}
            template={tpl}
            installedSlug={installedByTemplate[tpl.slug] ?? null}
            onInstall={onInstall}
            installing={installingSlug === tpl.slug}
          />
        ))}
      </div>
    </div>
  );
}

export function MethodologiesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  // Project selection happens once, globally, in the top bar (Module Style
  // Guide). This page reads the active project from the shared store.
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const [installingSlug, setInstallingSlug] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const templatesQ = useQuery({
    queryKey: ['methodology', 'templates'],
    queryFn: () => methodologyApi.listTemplates(),
    staleTime: 60 * 60 * 1000,
  });

  const methodologiesQ = useQuery({
    queryKey: ['methodology', 'list', activeProjectId],
    queryFn: () => methodologyApi.list(activeProjectId!),
    enabled: !!activeProjectId,
  });

  const activeQ = useQuery({
    queryKey: ['methodology', 'active', activeProjectId],
    queryFn: () => methodologyApi.getActive(activeProjectId!),
    enabled: !!activeProjectId,
  });

  const activeSlug = activeQ.data?.methodology_slug ?? 'international';

  // The project's editable clones (scope === 'project'). Built-ins / pack
  // templates (project_id === null) are read-only platform data.
  const installed = useMemo(
    () => (methodologiesQ.data ?? []).filter((m) => m.scope === 'project'),
    [methodologiesQ.data],
  );

  // Map a template slug to the slug of an already-installed clone of it (if
  // any), so the gallery can show an "Installed" badge. The backend tracks the
  // source template in metadata; here we approximate from the clone slug, which
  // the installer derives as `${template_slug}-${projectHash}`.
  const installedByTemplate = useMemo(() => {
    const out: Record<string, string> = {};
    for (const tpl of templatesQ.data ?? []) {
      const match = installed.find(
        (m) => m.slug === tpl.slug || m.slug.startsWith(`${tpl.slug}-`),
      );
      if (match) out[tpl.slug] = match.slug;
    }
    return out;
  }, [templatesQ.data, installed]);

  const grouped = useMemo(
    () => groupTemplates(templatesQ.data ?? []),
    [templatesQ.data],
  );

  const installMut = useMutation({
    mutationFn: (slug: string) =>
      methodologyApi.installTemplate({
        project_id: activeProjectId!,
        template_slug: slug,
        idempotent: false,
      }),
    onMutate: (slug) => setInstallingSlug(slug),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['methodology', 'list', activeProjectId] });
      addToast({
        type: 'success',
        title: t('methodology.gallery.installed_toast', {
          defaultValue: '{{name}} installed',
          name: created.name,
        }),
        message: t('methodology.gallery.installed_toast_msg', {
          defaultValue: 'Opening the editor so you can adjust it for this project.',
        }),
      });
      navigate(`/methodologies/${created.id}`);
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
    onSettled: () => setInstallingSlug(null),
  });

  // Installing requires a project; the templates gallery itself is global and
  // renders without one. Guard the install action so a no-project visitor gets
  // a clear "pick a project" prompt instead of a silent no-op.
  const handleInstall = (slug: string) => {
    if (!activeProjectId) {
      addToast({
        type: 'info',
        title: t('methodology.select_project_toast', { defaultValue: 'Select a project first' }),
        message: t('methodology.select_project_toast_msg', {
          defaultValue: 'Pick a project in the top bar, then install a methodology into it.',
        }),
      });
      return;
    }
    installMut.mutate(slug);
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: t('methodology.title', { defaultValue: 'Estimating methodologies' }) },
        ]}
      />

      <PageHeader
        srTitle={t('methodology.title', { defaultValue: 'Estimating methodologies' })}
        subtitle={
          activeProjectId
            ? t('methodology.subtitle', {
                defaultValue:
                  'How direct costs are marked up into a final estimate for {{project}}: the works vs equipment split, named base sets, the sequential percentage steps and VAT.',
                project:
                  activeProjectName || t('methodology.this_project', { defaultValue: 'this project' }),
              })
            : t('methodology.subtitle_no_project', {
                defaultValue:
                  'Browse the built-in estimating methodologies. Pick a project in the top bar to install one and tailor its markup cascade, dimensions and funding sources.',
              })
        }
        actions={
          activeProjectId ? (
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setCreateOpen(true)}
            >
              {t('methodology.create', { defaultValue: 'New methodology' })}
            </Button>
          ) : undefined
        }
      />

      <DismissibleInfo
        storageKey="methodology-hub"
        title={t('methodology.intro.title', {
          defaultValue: 'Data-driven estimating, your way',
        })}
        links={
          activeProjectId
            ? [
                {
                  label: t('project.settings.title', { defaultValue: 'Settings' }),
                  onClick: () => navigate(`/projects/${activeProjectId}/settings#methodology`),
                },
              ]
            : []
        }
      >
        {t('methodology.intro.body', {
          defaultValue:
            'Install a built-in methodology as a starting point, then edit every percentage, base set and step to match your jurisdiction. Set which one a project uses in project Settings. Built-in templates are read-only references - install or duplicate one to make changes.',
        })}
      </DismissibleInfo>

      {/* ── Installed methodologies (per project) ───────────────────────── */}
      {activeProjectId ? (
      <section>
        <h2 className="mb-3 text-base font-semibold text-content-primary">
          {t('methodology.installed.title', { defaultValue: 'Installed in this project' })}
        </h2>

        {methodologiesQ.isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : methodologiesQ.isError ? (
          <ErrorState
            title={t('methodology.installed.error', {
              defaultValue: 'Could not load this project’s methodologies.',
            })}
            onRetry={() => methodologiesQ.refetch()}
          />
        ) : installed.length === 0 ? (
          <Card padding="lg">
            <EmptyState
              icon={<Layers3 size={22} />}
              title={t('methodology.installed.empty', {
                defaultValue: 'No methodology installed yet',
              })}
              description={t('methodology.installed.empty_desc', {
                defaultValue:
                  'This project uses the neutral International method by default. Install one below to customise the markup cascade, dimensions and funding sources.',
              })}
            />
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {installed.map((m) => (
              <InstalledMethodologyCard
                key={m.id}
                methodology={m}
                isActive={m.slug === activeSlug}
                onOpen={() => navigate(`/methodologies/${m.id}`)}
              />
            ))}
          </div>
        )}
      </section>
      ) : (
        <Card padding="lg">
          <EmptyState
            icon={<Layers3 size={22} />}
            title={t('methodology.no_project.title', { defaultValue: 'Select a project first' })}
            description={t('methodology.no_project.desc', {
              defaultValue:
                'Methodologies are installed and edited per project. Pick a project in the top bar to install one of the templates below.',
            })}
            action={{
              label: t('methodology.no_project.action', { defaultValue: 'Go to projects' }),
              onClick: () => navigate('/projects'),
            }}
          />
        </Card>
      )}

      {/* ── Templates gallery ───────────────────────────────────────────── */}
      <section className="space-y-5">
        <h2 className="text-base font-semibold text-content-primary">
          {t('methodology.gallery.title', { defaultValue: 'Built-in templates' })}
        </h2>

        {templatesQ.isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : templatesQ.isError ? (
          <ErrorState
            title={t('methodology.gallery.error', {
              defaultValue: 'Could not load the template catalogue.',
            })}
            onRetry={() => templatesQ.refetch()}
          />
        ) : (
          <>
            <GallerySection
              title={t('methodology.gallery.group_default', { defaultValue: 'Neutral default' })}
              icon={<Globe2 size={15} />}
              templates={grouped.international}
              installedByTemplate={installedByTemplate}
              onInstall={handleInstall}
              installingSlug={installingSlug}
            />
            <GallerySection
              title={t('methodology.gallery.group_countries', { defaultValue: 'Countries' })}
              icon={<Banknote size={15} />}
              templates={grouped.countries}
              installedByTemplate={installedByTemplate}
              onInstall={handleInstall}
              installingSlug={installingSlug}
            />
            <GallerySection
              title={t('methodology.gallery.group_uzbekistan', {
                defaultValue: 'Cascading (Uzbekistan)',
              })}
              icon={<FlaskConical size={15} />}
              templates={grouped.uzbekistan}
              installedByTemplate={installedByTemplate}
              onInstall={handleInstall}
              installingSlug={installingSlug}
            />
            <GallerySection
              title={t('methodology.gallery.group_industry', { defaultValue: 'Industry packs' })}
              icon={<TrainFront size={15} />}
              templates={grouped.industry}
              installedByTemplate={installedByTemplate}
              onInstall={handleInstall}
              installingSlug={installingSlug}
            />
          </>
        )}
      </section>

      {activeProjectId && (
        <CreateMethodologyModal
          open={createOpen}
          projectId={activeProjectId}
          onClose={() => setCreateOpen(false)}
          onCreated={(m) => {
            setCreateOpen(false);
            queryClient.invalidateQueries({ queryKey: ['methodology', 'list', activeProjectId] });
            navigate(`/methodologies/${m.id}`);
          }}
        />
      )}
    </div>
  );
}

function InstalledMethodologyCard({
  methodology,
  isActive,
  onOpen,
}: {
  methodology: MethodologyListItem;
  isActive: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="md" hoverable className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-secondary text-content-secondary">
          {methodology.industry ? (
            <TrainFront size={18} />
          ) : methodology.country_code ? (
            <CountryFlag code={methodology.country_code} size={20} />
          ) : (
            <Layers3 size={18} />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h4 className="truncate text-sm font-semibold text-content-primary">
              {methodology.name}
            </h4>
            {isActive && (
              <Badge variant="blue" size="sm">
                <span className="inline-flex items-center gap-1">
                  <Star size={11} />
                  {t('methodology.installed.active', { defaultValue: 'Active' })}
                </span>
              </Badge>
            )}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {methodology.currency && (
              <Badge variant="neutral" size="sm">
                {methodology.currency}
              </Badge>
            )}
            {methodology.is_editable ? (
              <Badge variant="success" size="sm">
                {t('methodology.installed.editable', { defaultValue: 'Editable' })}
              </Badge>
            ) : (
              <Badge variant="neutral" size="sm">
                {t('methodology.installed.readonly', { defaultValue: 'Read-only' })}
              </Badge>
            )}
          </div>
        </div>
      </div>
      <div className="mt-auto flex items-center justify-end pt-1">
        <Button
          variant="secondary"
          size="sm"
          icon={methodology.is_editable ? <Pencil size={14} /> : <CheckCircle2 size={14} />}
          onClick={onOpen}
        >
          {methodology.is_editable
            ? t('methodology.installed.edit', { defaultValue: 'Edit' })
            : t('methodology.installed.view', { defaultValue: 'View' })}
        </Button>
      </div>
    </Card>
  );
}
