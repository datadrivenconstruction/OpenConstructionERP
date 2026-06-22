// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Compliance documents page — renders inside the Project Detail "Compliance" tab.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, ShieldCheck } from 'lucide-react';

import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ModuleGuideButton,
  RecoveryCard,
  Skeleton,
} from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';

import { deleteComplianceDoc, listComplianceDocs } from './api';
import { complianceDocsGuide } from './complianceDocsGuide';
import { CreateComplianceDocModal } from './CreateComplianceDocModal';
import { ComplianceStatusBadge } from './ComplianceStatusBadge';
import {
  COMPLIANCE_DOC_TYPES,
  COMPLIANCE_STATUSES,
  type ComplianceDoc,
} from './types';

export interface CompliancePageProps {
  projectId: string | null;
}

export function CompliancePage({ projectId }: CompliancePageProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToastStore((s) => s.addToast);

  const [statusFilter, setStatusFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [showCreate, setShowCreate] = useState(false);
  const { confirm, ...confirmProps } = useConfirm();

  const query = useQuery({
    queryKey: [
      'compliance-docs',
      projectId,
      statusFilter || null,
      typeFilter || null,
    ],
    queryFn: () =>
      listComplianceDocs({
        project_id: projectId as string,
        status: statusFilter || null,
        doc_type: typeFilter || null,
      }),
    enabled: Boolean(projectId),
    staleTime: 10_000,
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteComplianceDoc(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['compliance-docs', projectId] });
      queryClient.invalidateQueries({
        queryKey: ['compliance-docs-expiring', projectId],
      });
      toast({
        title: t('compliance.toast.deleted', {
          defaultValue: 'Compliance document deleted.',
        }),
        type: 'success',
      });
    },
    onError: () => {
      toast({
        title: t('compliance.toast.delete_failed', {
          defaultValue: 'Failed to delete compliance document.',
        }),
        type: 'error',
      });
    },
  });

  const sortedRows = useMemo(() => {
    const rows = query.data ?? [];
    // Already sorted by expires_at asc server-side — reaffirm here for
    // robustness so a future cache/optimistic update can't undo it.
    return [...rows].sort((a, b) =>
      a.expires_at.localeCompare(b.expires_at),
    );
  }, [query.data]);

  if (!projectId) {
    return (
      <EmptyState
        icon={<ShieldCheck size={48} strokeWidth={1.5} />}
        title={t('compliance.empty.no_project_title', {
          defaultValue: 'Open a project',
        })}
        description={t('compliance.empty.no_project_description', {
          defaultValue:
            'Compliance documents are scoped to a project - open one first.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="compliance-page">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-content-primary">
            {t('compliance.page.title', {
              defaultValue: 'Compliance documents',
            })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('compliance.page.subtitle', {
              defaultValue:
                'Track insurance, permits, bonds and certifications with expiry reminders.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ModuleGuideButton content={complianceDocsGuide} />
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
            data-testid="compliance-filter-type"
            aria-label={t('compliance.filter.type', {
              defaultValue: 'Filter by type',
            })}
          >
            <option value="">
              {t('compliance.filter.all_types', { defaultValue: 'All types' })}
            </option>
            {COMPLIANCE_DOC_TYPES.map((dt) => (
              <option key={dt} value={dt}>
                {t(`compliance.doc_type.${dt}`, { defaultValue: dt })}
              </option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
            data-testid="compliance-filter-status"
            aria-label={t('compliance.filter.status', {
              defaultValue: 'Filter by status',
            })}
          >
            <option value="">
              {t('compliance.filter.all_statuses', {
                defaultValue: 'All statuses',
              })}
            </option>
            {COMPLIANCE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`compliance.status.${s}`, { defaultValue: s })}
              </option>
            ))}
          </select>
          <Button
            icon={<Plus size={14} />}
            onClick={() => setShowCreate(true)}
            data-testid="compliance-new"
          >
            {t('compliance.page.new', { defaultValue: 'New document' })}
          </Button>
        </div>
      </div>

      {query.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} height={48} className="w-full" rounded="md" />
          ))}
        </div>
      ) : query.isError ? (
        <RecoveryCard
          error={query.error}
          onRetry={() => query.refetch()}
        />
      ) : sortedRows.length === 0 ? (
        <EmptyState
          icon={<ShieldCheck size={48} strokeWidth={1.5} />}
          title={t('compliance.empty.title', {
            defaultValue: 'No compliance documents yet',
          })}
          description={t('compliance.empty.description', {
            defaultValue:
              'Track insurance policies, permits, bonds and certifications. Get a warning before each one expires.',
          })}
          action={
            <Button
              icon={<Plus size={14} />}
              onClick={() => setShowCreate(true)}
              data-testid="compliance-empty-cta"
            >
              {t('compliance.page.new', { defaultValue: 'New document' })}
            </Button>
          }
        />
      ) : (
        <Card padding="none">
          <table
            className="w-full text-sm"
            data-testid="compliance-table"
          >
            <thead className="bg-surface-secondary text-xs text-content-tertiary">
              <tr>
                <th className="px-3 py-2 text-left font-medium">
                  {t('compliance.col.name', { defaultValue: 'Name' })}
                </th>
                <th className="px-3 py-2 text-left font-medium">
                  {t('compliance.col.type', { defaultValue: 'Type' })}
                </th>
                <th className="px-3 py-2 text-left font-medium">
                  {t('compliance.col.expires_at', { defaultValue: 'Expires' })}
                </th>
                <th className="px-3 py-2 text-left font-medium">
                  {t('compliance.col.days_left', {
                    defaultValue: 'Days left',
                  })}
                </th>
                <th className="px-3 py-2 text-left font-medium">
                  {t('compliance.col.status', { defaultValue: 'Status' })}
                </th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row: ComplianceDoc) => (
                <tr
                  key={row.id}
                  className="border-t border-border-light"
                  data-testid={`compliance-row-${row.id}`}
                >
                  <td className="px-3 py-2 font-medium text-content-primary">
                    {row.name}
                    {row.issuer ? (
                      <span className="ml-2 text-xs text-content-tertiary">
                        ({row.issuer})
                      </span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {t(`compliance.doc_type.${row.doc_type}`, {
                      defaultValue: row.doc_type,
                    })}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-content-secondary">
                    {row.expires_at}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-content-secondary">
                    {row.days_until_expiry}
                  </td>
                  <td className="px-3 py-2">
                    <ComplianceStatusBadge status={row.status} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={async () => {
                        const ok = await confirm({
                          title: t('compliance.confirm.delete_title', {
                            defaultValue: 'Delete compliance document?',
                          }),
                          message: t('compliance.confirm.delete', {
                            defaultValue:
                              'Delete this compliance document?',
                          }),
                          confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                          variant: 'danger',
                        });
                        if (!ok) return;
                        removeMutation.mutate(row.id);
                      }}
                      className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                      aria-label={t('common.delete', {
                        defaultValue: 'Delete',
                      })}
                      data-testid={`compliance-delete-${row.id}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {showCreate && (
        <CreateComplianceDocModal
          projectId={projectId}
          onClose={() => setShowCreate(false)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
