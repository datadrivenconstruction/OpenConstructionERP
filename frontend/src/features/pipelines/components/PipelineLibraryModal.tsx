// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PipelineLibraryModal>` - one place to start a pipeline from: pick a
 * ready-made template, or reopen a workflow you saved earlier.
 *
 * It closes the two gaps in the builder: saved pipelines used to be reachable
 * only by pasting `?id=` into the URL, and there were no starter templates at
 * all. Both tabs hand back a {@link PipelineGraph} + a name; the page loads it
 * through the same hydration path it already uses for an opened pipeline, so a
 * template lands as an unsaved draft (id cleared) that Save turns into a real
 * pipeline, and an opened workflow lands with its id so Save updates it.
 */
import clsx from 'clsx';
import { FileStack, LayoutTemplate, Loader2, Trash2, Workflow } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import {
  useDeletePipeline,
  usePipelineList,
  type PipelineSummary,
} from '../api';
import {
  PIPELINE_TEMPLATES,
  TEMPLATE_TAG_LABELS,
  type PipelineTemplate,
} from '../templates';
import { getIntlLocale } from '@/shared/lib/formatters';

type Tab = 'templates' | 'saved';

export interface PipelineLibraryModalProps {
  open: boolean;
  onClose: () => void;
  /** Restrict the saved list to a project (optional). */
  projectId?: string | null;
  /** Which tab to show first. */
  initialTab?: Tab;
  /** Load a starter template onto the canvas as a fresh draft. */
  onPickTemplate: (template: PipelineTemplate) => void;
  /** Reopen a saved workflow by id (page navigates + hydrates). */
  onOpenSaved: (id: string) => void;
}

export function PipelineLibraryModal({
  open,
  onClose,
  projectId,
  initialTab = 'templates',
  onPickTemplate,
  onOpenSaved,
}: PipelineLibraryModalProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>(initialTab);

  // Each open() call can target a different tab (toolbar -> Saved, empty-state
  // -> Templates), so re-sync to the requested tab whenever the modal opens.
  useEffect(() => {
    if (open) setTab(initialTab);
  }, [open, initialTab]);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="2xl"
      title={t('pipeline.library.title', { defaultValue: 'Pipeline library' })}
      subtitle={t('pipeline.library.subtitle', {
        defaultValue:
          'Start from a ready-made automation, or reopen a workflow you saved before.',
      })}
    >
      <div
        role="tablist"
        aria-label={t('pipeline.library.tabs_aria', {
          defaultValue: 'Pipeline library tabs',
        })}
        className="mb-4 flex gap-1 border-b border-border"
      >
        <TabButton
          active={tab === 'templates'}
          onClick={() => setTab('templates')}
          icon={<LayoutTemplate size={14} aria-hidden="true" />}
          label={t('pipeline.library.tab_templates', {
            defaultValue: 'Templates',
          })}
        />
        <TabButton
          active={tab === 'saved'}
          onClick={() => setTab('saved')}
          icon={<FileStack size={14} aria-hidden="true" />}
          label={t('pipeline.library.tab_saved', {
            defaultValue: 'Saved workflows',
          })}
        />
      </div>

      {tab === 'templates' ? (
        <TemplatesTab
          onPick={(tpl) => {
            onPickTemplate(tpl);
            onClose();
          }}
        />
      ) : (
        <SavedTab
          projectId={projectId}
          onOpen={(id) => {
            onOpenSaved(id);
            onClose();
          }}
        />
      )}
    </WideModal>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors',
        active
          ? 'border-oe-blue text-oe-blue'
          : 'border-transparent text-content-tertiary hover:text-content-primary',
      )}
    >
      {icon}
      {label}
    </button>
  );
}

// ── Templates ────────────────────────────────────────────────────────────────

function TemplatesTab({ onPick }: { onPick: (tpl: PipelineTemplate) => void }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {PIPELINE_TEMPLATES.map((tpl) => (
        <button
          key={tpl.id}
          type="button"
          data-testid={`pipeline-template-${tpl.id}`}
          onClick={() => onPick(tpl)}
          className="group flex flex-col rounded-xl border border-border bg-surface-secondary/50 p-3.5 text-start transition-colors hover:border-oe-blue/50 hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30"
        >
          <div className="mb-1.5 flex items-center gap-2">
            <span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
              <Workflow size={15} aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-semibold text-content-primary">
              {tpl.name}
            </span>
            <span className="shrink-0 rounded-full bg-surface-tertiary px-2 py-0.5 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {TEMPLATE_TAG_LABELS[tpl.tag]}
            </span>
          </div>
          <p className="text-xs leading-relaxed text-content-secondary">
            {tpl.description}
          </p>
          <span className="mt-2 text-xs font-medium text-oe-blue opacity-0 transition-opacity group-hover:opacity-100">
            {t('pipeline.library.use_template', {
              defaultValue: 'Use this template →',
            })}
          </span>
        </button>
      ))}
    </div>
  );
}

// ── Saved workflows ──────────────────────────────────────────────────────────

function SavedTab({
  projectId,
  onOpen,
}: {
  projectId?: string | null;
  onOpen: (id: string) => void;
}) {
  const { t } = useTranslation();
  const listQuery = usePipelineList(projectId);
  const deleteMut = useDeletePipeline();
  const addToast = useToastStore((s) => s.addToast);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const handleDelete = async (id: string) => {
    try {
      await deleteMut.mutateAsync(id);
      addToast({
        type: 'success',
        title: t('pipeline.library.deleted', { defaultValue: 'Workflow deleted' }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('pipeline.library.delete_failed', {
          defaultValue: 'Could not delete the workflow',
        }),
        message: getErrorMessage(err),
      });
    } finally {
      setConfirmId(null);
    }
  };

  if (listQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-content-tertiary">
        <Loader2 size={18} className="animate-spin" aria-hidden="true" />
      </div>
    );
  }

  const rows = listQuery.data ?? [];
  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
        <FileStack size={28} className="text-content-quaternary" aria-hidden="true" />
        <p className="text-sm text-content-tertiary">
          {t('pipeline.library.empty_saved', {
            defaultValue:
              'No saved workflows yet. Build one and press Save, or start from a template.',
          })}
        </p>
      </div>
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-border">
      {rows.map((p: PipelineSummary) => (
        <li key={p.id} className="flex items-center gap-3 py-2.5">
          <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-tertiary text-content-tertiary">
            <Workflow size={15} aria-hidden="true" />
          </span>
          <button
            type="button"
            onClick={() => onOpen(p.id)}
            className="min-w-0 flex-1 text-start focus:outline-none"
          >
            <span className="block truncate text-sm font-medium text-content-primary hover:text-oe-blue">
              {p.name ||
                t('pipeline.untitled', { defaultValue: 'Untitled pipeline' })}
            </span>
            <span className="block truncate text-xs text-content-tertiary">
              {typeof p.node_count === 'number'
                ? t('pipeline.library.node_count', {
                    defaultValue: '{{count}} step(s)',
                    count: p.node_count,
                  })
                : ''}
              {p.updated_at
                ? ` · ${new Date(p.updated_at).toLocaleDateString(getIntlLocale())}`
                : ''}
            </span>
          </button>
          {confirmId === p.id ? (
            <span className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => handleDelete(p.id)}
                disabled={deleteMut.isPending}
                className="rounded-md bg-semantic-error px-2 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {t('common.delete', { defaultValue: 'Delete' })}
              </button>
              <button
                type="button"
                onClick={() => setConfirmId(null)}
                className="rounded-md border border-border px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmId(p.id)}
              title={t('common.delete', { defaultValue: 'Delete' })}
              aria-label={t('pipeline.library.delete_aria', {
                defaultValue: 'Delete {{name}}',
                name: p.name,
              })}
              className="rounded-md p-1.5 text-content-quaternary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-950/30"
            >
              <Trash2 size={15} aria-hidden="true" />
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

export default PipelineLibraryModal;
