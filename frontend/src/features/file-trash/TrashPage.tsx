// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Recycle Bin page — /files/trash.
 *
 * Lists every soft-deleted file in the active project with
 * restore + hard-purge buttons per row, plus a header strip
 * showing total count + bytes + retention countdown. The page
 * reads ``activeProjectId`` from the project context store so
 * it works both as a global view (no project selected → empty
 * state) and as a project-scoped view (active project set by
 * the file manager).
 */

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  Box,
  FileBarChart,
  FileText,
  Image as ImageIcon,
  Layout,
  Loader2,
  PenTool,
  Pencil,
  RotateCcw,
  Tag,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Card, EmptyState, ModuleGuideButton, Skeleton } from '@/shared/ui';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useFileTrash, useFileTrashStats, usePurgeTrash, useRestoreFromTrash } from './hooks';
import { fileTrashGuide } from './fileTrashGuide';
import type { TrashItem, TrashKind } from './types';
import { fmtFixed } from '@/shared/lib/formatters';

// English fallbacks for the computed `files.kind.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const FILES_KIND_LABELS: Record<string, string> = {
  document: 'Document', photo: 'Photo', sheet: 'Sheet', bim_model: 'BIM model', dwg_drawing: 'DWG drawing',
  takeoff: 'Takeoff', report: 'Report', markup: 'Markup'
};


const KIND_ICON: Record<TrashKind, typeof FileText> = {
  document: FileText,
  photo: ImageIcon,
  sheet: Layout,
  bim_model: Box,
  dwg_drawing: Pencil,
  takeoff: Tag,
  report: FileBarChart,
  markup: PenTool,
};

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
  return `${fmtFixed(bytes / (1024 * 1024 * 1024), 2)} GB`;
}

function daysUntilExpiry(trashedAt: string, retentionDays: number): number {
  const trashedMs = new Date(trashedAt).getTime();
  if (Number.isNaN(trashedMs)) return retentionDays;
  const elapsedDays = (Date.now() - trashedMs) / 86_400_000;
  return Math.max(0, Math.ceil(retentionDays - elapsedDays));
}

export function TrashPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const addToast = useToastStore((s) => s.addToast);
  const [confirmPurge, setConfirmPurge] = useState<TrashItem | null>(null);

  const list = useFileTrash(projectId);
  const stats = useFileTrashStats(projectId);
  const restore = useRestoreFromTrash(projectId);
  const purge = usePurgeTrash(projectId);

  const items = useMemo<TrashItem[]>(() => list.data?.items ?? [], [list.data]);

  if (!projectId) {
    return (
      <div className="animate-fade-in">
        <EmptyState
          icon={<Trash2 size={32} strokeWidth={1.5} />}
          title={t('files.trash.no_project_title', {
            defaultValue: 'Select a project first',
          })}
          description={t('files.trash.no_project_desc', {
            defaultValue:
              'The Recycle Bin is scoped to one project at a time. Open a project from /files to see its trashed files.',
          })}
          action={{
            label: t('files.trash.back_to_files', { defaultValue: 'Back to files' }),
            onClick: () => navigate('/files'),
          }}
        />
      </div>
    );
  }

  const handleRestore = (item: TrashItem) => {
    restore.mutate(item.id, {
      onSuccess: () => {
        addToast({
          type: 'success',
          title: t('files.trash.restored_title', {
            defaultValue: 'Restored: {{name}}',
            name: item.canonical_name,
          }),
        });
      },
      onError: (err: Error) => {
        addToast({
          type: 'error',
          title: t('files.trash.restore_failed_title', {
            defaultValue: 'Could not restore file',
          }),
          message: err.message,
        });
      },
    });
  };

  const handlePurge = (item: TrashItem) => {
    purge.mutate(
      { trashId: item.id, confirmToken: item.restore_token },
      {
        onSuccess: () => {
          addToast({
            type: 'success',
            title: t('files.trash.purged_title', {
              defaultValue: 'Permanently deleted: {{name}}',
              name: item.canonical_name,
            }),
          });
          setConfirmPurge(null);
        },
        onError: (err: Error) => {
          addToast({
            type: 'error',
            title: t('files.trash.purge_failed_title', {
              defaultValue: 'Could not purge file',
            }),
            message: err.message,
          });
        },
      },
    );
  };

  return (
    <div className="space-y-5 animate-fade-in" data-testid="trash-page">
      <Breadcrumb
        items={[
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('nav.documents'), to: '/files' },
          { label: t('files.trash.title', { defaultValue: 'Recycle Bin' }) },
        ]}
      />
      <PageHeader
        srTitle={t('files.trash.title', { defaultValue: 'Recycle Bin' })}
        subtitle={t('files.trash.subtitle', {
          defaultValue:
            'Deleted files stay here for 30 days before they are permanently removed. Restore or purge them per row.',
        })}
        actions={
          <>
            <span className="text-xs text-content-tertiary">
              {t('files.trash.summary', {
                defaultValue: '{{count}} item(s) · {{bytes}}',
                count: stats.data?.count ?? 0,
                bytes: formatBytes(stats.data?.total_bytes ?? 0),
              })}
            </span>
            <ModuleGuideButton content={fileTrashGuide} />
            <Button
              variant="secondary"
              size="sm"
              icon={<ArrowLeft size={14} />}
              onClick={() => navigate('/files')}
            >
              {t('files.trash.back_to_files', { defaultValue: 'Back to files' })}
            </Button>
          </>
        }
      />

      {list.isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      )}

      {!list.isLoading && items.length === 0 && (
        <EmptyState
          icon={<Trash2 size={32} strokeWidth={1.5} />}
          title={t('files.trash.empty_title', {
            defaultValue: 'Recycle Bin is empty',
          })}
          description={t('files.trash.empty_description', {
            defaultValue:
              'Deleted files appear here for 30 days before they are permanently removed.',
          })}
        />
      )}

      {items.length > 0 && (
        <ul className="space-y-2" data-testid="trash-list">
          {items.map((item) => {
            const Icon = KIND_ICON[item.original_kind] ?? FileText;
            const daysLeft = daysUntilExpiry(item.trashed_at, item.retention_days);
            const expiringSoon = daysLeft <= 3;
            const isConfirming = confirmPurge?.id === item.id;
            return (
              <Card key={item.id} padding="sm" data-testid={`trash-row-${item.id}`}>
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface-secondary text-content-tertiary">
                    <Icon size={16} strokeWidth={1.75} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p
                      className="text-sm font-medium text-content-primary truncate"
                      title={item.canonical_name}
                    >
                      {item.canonical_name || item.original_id}
                    </p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-content-tertiary">
                      <span className="capitalize">
                        {t(`files.kind.${item.original_kind}`, {
                          defaultValue: FILES_KIND_LABELS[item.original_kind] ?? item.original_kind.replace('_', ' '),
                        })}
                      </span>
                      <span>{formatBytes(item.file_size)}</span>
                      <span>
                        {t('files.trash.trashed_label', { defaultValue: 'Trashed' })}{' '}
                        <DateDisplay value={item.trashed_at} format="relative" />
                      </span>
                      <span
                        className={clsx(
                          'inline-flex items-center gap-1 px-1.5 h-4 rounded-full font-medium',
                          expiringSoon
                            ? 'bg-semantic-error/10 text-semantic-error'
                            : 'bg-surface-secondary text-content-secondary',
                        )}
                      >
                        {expiringSoon && <TriangleAlert size={9} strokeWidth={2.5} />}
                        {t('files.trash.days_left', {
                          defaultValue: '{{n}}d left',
                          n: daysLeft,
                        })}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => handleRestore(item)}
                      loading={restore.isPending && restore.variables === item.id}
                      icon={<RotateCcw size={12} />}
                      data-testid={`trash-restore-${item.id}`}
                    >
                      {t('files.trash.restore', { defaultValue: 'Restore' })}
                    </Button>
                    {isConfirming ? (
                      <div className="inline-flex items-center gap-1">
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => handlePurge(item)}
                          loading={purge.isPending}
                          icon={<Trash2 size={12} />}
                          data-testid={`trash-purge-confirm-${item.id}`}
                        >
                          {t('files.trash.confirm_purge', {
                            defaultValue: 'Confirm',
                          })}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setConfirmPurge(null)}
                        >
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setConfirmPurge(item)}
                        icon={<Trash2 size={12} />}
                        data-testid={`trash-purge-${item.id}`}
                      >
                        {t('files.trash.purge', { defaultValue: 'Delete forever' })}
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </ul>
      )}

      {/* The header strip counts the whole bin from the stats endpoint while
          the list below it is one server page (50 rows by default), so on a
          busy project the two numbers disagreed with nothing to explain it.
          Renders nothing once the page holds everything. */}
      {list.data && <TruncationNotice page={list.data} className="mt-2" />}

      {list.isError && (
        <div className="mt-4 flex items-center gap-2 px-3 py-2 text-xs text-semantic-error bg-semantic-error/5 rounded-md">
          <Loader2 size={12} className="animate-spin" />
          {t('files.trash.load_failed', {
            defaultValue: 'Could not load the Recycle Bin. Please try again.',
          })}
        </div>
      )}
    </div>
  );
}
