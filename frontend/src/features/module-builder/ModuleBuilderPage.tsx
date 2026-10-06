// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The modules built on this instance: what is installed, and how to remove one.
 *
 * Separate from the header button on purpose. The button is the action - build
 * something - and this is the register: anyone signed in can read it, because
 * knowing which modules an instance carries is part of knowing the instance.
 * Only an administrator sees the build and remove controls, and the server
 * enforces that on the call rather than trusting this page.
 *
 * Removal offers to drop the data as a second, explicit choice. Uninstalling a
 * module someone regrets installing should not also lose what was recorded with
 * it, so the records stay unless the box is ticked, and the table can still be
 * dropped later by uninstalling again.
 *
 * Whether an AI provider is connected is answered by this module's own
 * `assistant_available`, not by a shared readiness probe. The server computes it
 * from the provider the draft call would actually use, so a second opinion
 * assembled here could say "connected" about a provider this module cannot
 * reach, or the reverse.
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, Boxes, ExternalLink, Sparkles, Trash2, Wand2 } from 'lucide-react';

import {
  Badge,
  Button,
  CollapsibleSection,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonTable,
  WideModal,
} from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  fetchInstalledModules,
  fetchVocabulary,
  isQuarantined,
  uninstallModule,
  type InstalledModule,
} from './api';
import { QuarantineBadge, QuarantineMessage } from './QuarantineNotice';
import { ModuleBuilderWizard } from './ModuleBuilderWizard';
import { ExtendModuleButton } from './ExtendModuleButton';
import { RUNTIME_MODULE_QUERY_KEY } from './GeneratedModulePage';

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

export function ModuleBuilderPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';

  const [wizardOpen, setWizardOpen] = useState(false);
  const [pending, setPending] = useState<InstalledModule | null>(null);
  const [dropData, setDropData] = useState(false);

  const installedQuery = useQuery({
    queryKey: ['module-builder', 'installed'],
    queryFn: fetchInstalledModules,
    staleTime: 5 * 60_000,
  });

  // Same query key as the wizard's, so the two share one answer instead of
  // asking twice. Only fetched for an administrator: the strip it feeds is the
  // one thing on this page a reader is expected to act on, and connecting a
  // provider is an administrator's screen.
  const vocabularyQuery = useQuery({
    queryKey: ['module-builder', 'vocabulary'],
    queryFn: fetchVocabulary,
    enabled: isAdmin,
    staleTime: 30 * 60_000,
  });
  // Deliberately not defaulted to `false`. Undefined means "not answered yet",
  // which covers both the request in flight and a request that failed, and
  // neither of those is evidence that no provider is connected. Announcing one
  // for the length of every page load would be a false alarm that then
  // corrects itself, which reads as a bug.
  const assistantAvailable = vocabularyQuery.data?.assistant_available;

  const removal = useMutation({
    mutationFn: (module: InstalledModule) => uninstallModule(module.key, dropData),
    onSuccess: (result) => {
      addToast({
        type: 'success',
        title: result.data_dropped
          ? t('module_builder.removed_with_data', {
              defaultValue: 'Removed, and its records were dropped',
            })
          : t('module_builder.removed', { defaultValue: 'Removed. Its records are still there.' }),
      });
      void qc.invalidateQueries({ queryKey: ['module-builder', 'installed'] });
      void qc.invalidateQueries({ queryKey: [RUNTIME_MODULE_QUERY_KEY] });
      setPending(null);
      setDropData(false);
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
      setPending(null);
    },
  });

  const modules = installedQuery.data?.items ?? [];

  const closeRemoval = () => {
    setPending(null);
    setDropData(false);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        srTitle={t('module_builder.title', { defaultValue: 'Module builder' })}
        subtitle={t('module_builder.page_subtitle', {
          defaultValue: 'Modules built on this instance, and where they live.',
        })}
        actions={
          isAdmin ? (
            <Button
              variant="primary"
              size="sm"
              icon={<Wand2 size={14} />}
              onClick={() => setWizardOpen(true)}
              data-testid="module-builder-page-build"
            >
              {t('module_builder.header_button', { defaultValue: 'Build a module' })}
            </Button>
          ) : undefined
        }
      />

      {assistantAvailable === true && (
        <p
          className="flex items-center gap-1.5 text-xs text-content-tertiary"
          data-testid="module-builder-ai-ready"
        >
          <Sparkles size={13} strokeWidth={1.9} className="shrink-0 text-oe-blue-text" />
          {t('module_builder.ai_connected', {
            defaultValue:
              'An AI provider is connected, so a module can be drafted from a sentence.',
          })}
        </p>
      )}

      {assistantAvailable === false && (
        <div
          className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200"
          data-testid="module-builder-ai-missing"
        >
          <AlertTriangle size={13} strokeWidth={1.9} className="shrink-0" />
          <span>
            {t('module_builder.ai_missing_v2', {
              defaultValue:
                'No AI is connected. The builder still works: start from a template or build the register by hand.',
            })}
          </span>
          <Link
            to="/settings?tab=ai"
            className="inline-flex items-center gap-1 font-semibold underline-offset-2 hover:underline"
            data-testid="module-builder-connect-ai"
          >
            {t('module_builder.connect_ai', { defaultValue: 'Connect an AI provider' })}
            <ArrowRight size={12} className="shrink-0" />
          </Link>
        </div>
      )}

      <CollapsibleSection
        storageKey="module_builder.how"
        title={t('module_builder.title', { defaultValue: 'Module builder' })}
        icon={<Boxes size={15} strokeWidth={1.9} />}
        subtitle={t('module_builder.page_subtitle', {
          defaultValue: 'Modules built on this instance, and where they live.',
        })}
      >
        <p className="text-sm text-content-secondary">
          {t('module_builder.how_intro_v2', {
            defaultValue:
              'Build your own register for anything the site keeps track of, such as pours, permits, deliveries or briefings. It works like every other part of the platform, with its own list, form and checks, and it is ready the moment you create it.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-4 text-sm text-content-secondary">
          <li>
            {t('module_builder.how_1_v2', {
              defaultValue: 'Say what you want to keep track of, in a sentence or by picking a template.',
            })}
          </li>
          <li>
            {t('module_builder.how_2_v2', {
              defaultValue:
                'Look over what each entry holds and switch on the extras you want, such as stages, reminders or export.',
            })}
          </li>
          <li>
            {t('module_builder.how_3_v2', {
              defaultValue: 'Create it. It appears in the menu straight away, with no restart.',
            })}
          </li>
          <li>
            {t('module_builder.how_4_v2', {
              defaultValue: 'It belongs to this instance, so a platform upgrade leaves it and its entries alone.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-sm text-content-secondary">
          {t('module_builder.how_ai_v2', {
            defaultValue:
              'Where an AI is connected, it only suggests the fields, the checks and the extras. Nothing is added until you switch it on, and nothing is created until you press Create module.',
          })}
        </p>
        <p className="mt-2 text-sm text-content-secondary">
          {/* Worded to avoid repeating the removal dialog's own sentence about
              records: the two would then read as one duplicated warning, and a
              page holding both is what the reader actually sees. */}
          {t('module_builder.how_remove', {
            defaultValue:
              'A module is removed from the list below. It stops serving straight away, and what was recorded with it is kept unless you ask for that to go too - reinstalling then brings it back.',
          })}
        </p>
        {/* The server path is for the administrator taking backups, not for
            the reader learning what the page is, so it stays folded away. */}
        {installedQuery.data?.runtime_root && (
          <details className="mt-2 text-xs text-content-tertiary" data-testid="module-builder-files-location">
            <summary className="cursor-pointer select-none hover:text-content-secondary">
              {t('module_builder.files_location', { defaultValue: 'Where these modules are stored on the server' })}
            </summary>
            <p className="mt-1 break-all font-mono">{installedQuery.data.runtime_root}</p>
          </details>
        )}
        <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
          <span>
            <span className="font-medium text-content-secondary">
              {t('module_builder.flow_feeds', { defaultValue: 'Feeds:' })}
            </span>{' '}
            <ModLink to="/modules">{t('nav.modules', { defaultValue: 'Modules' })}</ModLink>
          </span>
        </div>
      </CollapsibleSection>

      {installedQuery.isLoading ? (
        <SkeletonTable rows={4} columns={4} />
      ) : installedQuery.isError ? (
        <ErrorState
          title={t('module_builder.list_failed', { defaultValue: 'The list could not be read' })}
          hint={getErrorMessage(installedQuery.error)}
          onRetry={() => void installedQuery.refetch()}
        />
      ) : modules.length === 0 ? (
        <EmptyState
          icon={<Boxes size={28} strokeWidth={1.5} />}
          title={t('module_builder.empty_title', { defaultValue: 'Nothing has been built here yet' })}
          description={t('module_builder.empty_hint', {
            defaultValue:
              'A module built here is a register the platform did not ship: whatever this project actually records.',
          })}
          action={
            isAdmin
              ? {
                  label: t('module_builder.header_button', { defaultValue: 'Build a module' }),
                  onClick: () => setWizardOpen(true),
                }
              : undefined
          }
        />
      ) : (
        // Cards rather than rows. A module built here is a thing someone made,
        // and the flat list read as configuration; the path each one lives at
        // matters enough to keep, so the card gives it a line of its own
        // instead of crowding it into a subtitle.
        <ul className="grid gap-3 sm:grid-cols-2" data-testid="module-builder-list">
          {modules.map((module) => (
            <li
              key={module.key}
              className="flex flex-col gap-3 rounded-xl border border-border-light bg-surface-primary p-4 transition-colors hover:border-oe-blue/40"
            >
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
                  <Boxes size={17} strokeWidth={1.8} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-content-primary">
                    <span className="min-w-0 truncate">{module.display_name}</span>
                    <Badge variant="neutral" size="sm">
                      v{module.version}
                    </Badge>
                    {isQuarantined(module) && <QuarantineBadge />}
                  </p>
                  <p className="mt-0.5 text-xs text-content-tertiary">
                    {t('module_builder.module_summary', {
                      entity: module.entity,
                      fields: module.field_count,
                      rules: module.rule_count,
                      defaultValue: '{{entity}} · {{fields}} fields · {{rules}} rules',
                    })}
                  </p>
                </div>
              </div>

              {/* Kept on its own line and allowed to wrap. It is the answer to
                  "where did this actually go", and truncating a path hides the
                  part that differs between one instance and another. */}
              {/* A module switched off for safety answers nothing at its
                  address, so the card says why instead of offering to open
                  it or add to it. Removing it still works. */}
              {isQuarantined(module) ? (
                <QuarantineMessage problem={module.problem} testId={`module-builder-quarantined-${module.key}`} />
              ) : (
                <p className="break-all font-mono text-[11px] leading-relaxed text-content-quaternary">
                  {module.base_path}
                </p>
              )}

              <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border-light pt-3">
                {!isQuarantined(module) && (
                  <>
                    <Link
                      to={`/modules/${module.key}`}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary hover:text-content-primary"
                      data-testid={`module-builder-open-${module.key}`}
                    >
                      <ExternalLink size={12} />
                      {t('module_builder.open_module', { defaultValue: 'Open the module' })}
                    </Link>
                    <ExtendModuleButton moduleKey={module.key} basePath={module.base_path} className="me-auto" />
                  </>
                )}
                {isAdmin && (
                  <button
                    type="button"
                    onClick={() => {
                      setDropData(false);
                      setPending(module);
                    }}
                    aria-label={t('module_builder.uninstall', { defaultValue: 'Remove this module' })}
                    className="rounded-lg p-1.5 text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error"
                    data-testid={`module-builder-remove-${module.key}`}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Its own dialog rather than the shared ConfirmDialog: whether the data
          goes too is a choice that has to be made before confirming, and the
          shared one takes a message rather than a body to put it in. */}
      <WideModal
        open={pending !== null}
        onClose={closeRemoval}
        size="sm"
        title={t('module_builder.confirm_uninstall_title', {
          name: pending?.display_name ?? '',
          defaultValue: 'Remove {{name}}?',
        })}
        busy={removal.isPending}
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={closeRemoval} disabled={removal.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="danger"
              loading={removal.isPending}
              onClick={() => {
                if (pending) removal.mutate(pending);
              }}
              data-testid="module-builder-confirm-remove"
            >
              {t('module_builder.uninstall', { defaultValue: 'Remove this module' })}
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm text-content-secondary">
          <p>
            {t('module_builder.confirm_uninstall', {
              defaultValue:
                'The module stops serving straight away. Its records stay, and reinstalling it brings them back.',
            })}
          </p>
          <label className="flex items-start gap-2.5" data-testid="module-builder-drop-data">
            <input
              type="checkbox"
              checked={dropData}
              onChange={(e) => setDropData(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-border-light text-oe-blue focus:ring-oe-blue/40"
            />
            <span>
              <span className="block text-content-primary">
                {t('module_builder.drop_data', {
                  defaultValue: 'Also delete everything recorded with it',
                })}
              </span>
              {dropData && (
                <span className="block text-xs text-semantic-error">
                  {t('module_builder.confirm_uninstall_with_data', {
                    defaultValue:
                      'The module and everything recorded with it are removed. This cannot be undone.',
                  })}
                </span>
              )}
            </span>
          </label>
        </div>
      </WideModal>

      <ModuleBuilderWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
    </div>
  );
}

export default ModuleBuilderPage;
