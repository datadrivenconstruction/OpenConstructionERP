// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Transmittal log page — full route at /files/transmittals.
//
// Shows every transmittal for the active project, newest first, with
// filters on status + reason. Row click opens TransmittalDetailDrawer.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Send, FileText, CheckCircle2, AlertCircle, Eye } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { EmptyState } from '@/shared/ui/EmptyState';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { PageHeader } from '@/shared/ui/PageHeader';
import { ModuleGuideButton } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import { NewTransmittalWizard } from './NewTransmittalWizard';
import { TransmittalDetailDrawer } from './TransmittalDetailDrawer';
import { fileTransmittalsGuide } from './fileTransmittalsGuide';
import { useTransmittals } from './hooks';
import type { TransmittalListRow, TransmittalReason, TransmittalStatus } from './types';

// English fallbacks for the computed `files.transmittals.reason.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const TRANSMITTALS_REASON_LABELS: Record<string, string> = {
  for_review: 'For review', for_construction: 'For construction', for_approval: 'For approval',
  for_information: 'For information', for_record: 'For record'
};

// English fallbacks for the computed `files.transmittals.status.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const TRANSMITTALS_STATUS_LABELS: Record<string, string> = {
  draft: 'Draft', sent: 'Sent', acknowledged: 'Acknowledged', rejected: 'Rejected'
};


type StatusFilter = TransmittalStatus | 'all';
type ReasonFilter = TransmittalReason | 'all';

const STATUS_VARIANT: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  sent: 'blue',
  acknowledged: 'success',
  rejected: 'error',
};

const STATUS_ICON: Record<string, typeof Send> = {
  draft: FileText,
  sent: Send,
  acknowledged: CheckCircle2,
  rejected: AlertCircle,
};

const REASON_OPTIONS: ReasonFilter[] = [
  'all',
  'for_review',
  'for_construction',
  'for_approval',
  'for_information',
  'for_record',
];

const STATUS_OPTIONS: StatusFilter[] = [
  'all',
  'draft',
  'sent',
  'acknowledged',
  'rejected',
];

export function TransmittalLogPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const { data, isLoading } = useTransmittals(projectId);

  const [wizardOpen, setWizardOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [reasonFilter, setReasonFilter] = useState<ReasonFilter>('all');

  const rows = useMemo(() => {
    if (!data) return [] as TransmittalListRow[];
    return data.filter((r) => {
      if (statusFilter !== 'all' && r.status !== statusFilter) return false;
      if (reasonFilter !== 'all' && r.reason_code !== reasonFilter) return false;
      return true;
    });
  }, [data, statusFilter, reasonFilter]);

  if (!projectId) {
    return (
      <div className="animate-fade-in">
        <EmptyState
          icon={<Send size={32} strokeWidth={1.5} />}
          title={t('files.transmittals.title', { defaultValue: 'Transmittals' })}
          description={t('files.transmittals.no_project', {
            defaultValue: 'Select a project to view its transmittal log.',
          })}
        />
      </div>
    );
  }

  const reasonLabel = (code: string): string =>
    code === 'all'
      ? t('common.all', { defaultValue: 'All' })
      : t(`files.transmittals.reason.${code}`, {
          defaultValue: TRANSMITTALS_REASON_LABELS[code] ?? code
            .split('_')
            .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
            .join(' '),
        });

  const statusLabel = (code: string): string =>
    code === 'all'
      ? t('common.all', { defaultValue: 'All' })
      : t(`files.transmittals.status.${code}`, {
          defaultValue: TRANSMITTALS_STATUS_LABELS[code] ?? code.charAt(0).toUpperCase() + code.slice(1),
        });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.documents', { defaultValue: 'Documents' }), to: '/files' },
          {
            label: t('files.transmittals.title', { defaultValue: 'Transmittals' }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('files.transmittals.title', { defaultValue: 'Transmittals' })}
        subtitle={t('files.transmittals.description', {
          defaultValue:
            'Formal send-records of files to external parties, with auto-generated cover sheets and acknowledgement tracking.',
        })}
        actions={
          <>
            <ModuleGuideButton content={fileTransmittalsGuide} />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setWizardOpen(true)}
              icon={<Send size={14} />}
            >
              {t('files.transmittals.new', { defaultValue: 'New Transmittal' })}
            </Button>
          </>
        }
      />

      <Card padding="none" className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-border-light bg-surface-secondary/30">
          <div className="flex items-center gap-2">
            <label className="text-xs text-content-secondary">
              {t('files.transmittals.filter_status', { defaultValue: 'Status' })}
            </label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              className="h-9 text-sm px-2 rounded-lg border border-border bg-surface-primary text-content-primary"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-content-secondary">
              {t('files.transmittals.filter_reason', { defaultValue: 'Reason' })}
            </label>
            <select
              value={reasonFilter}
              onChange={(e) => setReasonFilter(e.target.value as ReasonFilter)}
              className="h-9 text-sm px-2 rounded-lg border border-border bg-surface-primary text-content-primary"
            >
              {REASON_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {reasonLabel(r)}
                </option>
              ))}
            </select>
          </div>
          <div className="ml-auto text-xs text-content-tertiary">
            {t('files.transmittals.count', {
              defaultValue: '{{count}} transmittals',
              count: rows.length,
            })}
          </div>
        </div>

        <div className="overflow-x-auto">
        {isLoading ? (
          <p className="p-8 text-center text-sm text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading…' })}
          </p>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center">
            <FileText
              size={32}
              className="mx-auto mb-3 text-content-tertiary"
              aria-hidden
            />
            <p className="text-sm text-content-secondary">
              {t('files.transmittals.empty', {
                defaultValue:
                  'No transmittals yet. Click "New Transmittal" to formally send files to external parties.',
              })}
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-content-secondary border-b border-border-light bg-surface-secondary/20 sticky top-0">
              <tr>
                <th className="text-left px-6 py-2 font-medium">
                  {t('files.transmittals.col_number', { defaultValue: 'Number' })}
                </th>
                <th className="text-left px-3 py-2 font-medium">
                  {t('files.transmittals.col_subject', { defaultValue: 'Subject' })}
                </th>
                <th className="text-left px-3 py-2 font-medium">
                  {t('files.transmittals.col_reason', { defaultValue: 'Reason' })}
                </th>
                <th className="text-right px-3 py-2 font-medium">
                  {t('files.transmittals.col_items', { defaultValue: 'Items' })}
                </th>
                <th className="text-right px-3 py-2 font-medium">
                  {t('files.transmittals.col_recipients', {
                    defaultValue: 'Recipients',
                  })}
                </th>
                <th className="text-left px-3 py-2 font-medium">
                  {t('files.transmittals.col_sent_at', { defaultValue: 'Sent' })}
                </th>
                <th className="text-left px-3 py-2 font-medium">
                  {t('files.transmittals.col_status', { defaultValue: 'Status' })}
                </th>
                <th className="px-3 py-2" aria-hidden />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {rows.map((row) => {
                const StatusIcon = STATUS_ICON[row.status] ?? FileText;
                const variant = STATUS_VARIANT[row.status] ?? 'neutral';
                return (
                  <tr
                    key={row.id}
                    className={clsx(
                      'hover:bg-surface-secondary/40 cursor-pointer transition-colors',
                      selectedId === row.id && 'bg-oe-blue-subtle/40',
                    )}
                    onClick={() => setSelectedId(row.id)}
                  >
                    <td className="px-6 py-2 font-mono text-xs">{row.number}</td>
                    <td className="px-3 py-2">
                      <span className="line-clamp-1">{row.subject}</span>
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {reasonLabel(row.reason_code)}
                    </td>
                    <td className="px-3 py-2 text-right">{row.item_count}</td>
                    <td className="px-3 py-2 text-right">
                      {row.acknowledged_count}/{row.recipient_count}
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      <DateDisplay value={row.sent_at} />
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={variant} dot>
                        <StatusIcon size={10} className="mr-1" />
                        {statusLabel(row.status)}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        className="text-content-tertiary hover:text-oe-blue"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedId(row.id);
                        }}
                        aria-label={t('common.view', { defaultValue: 'View' })}
                      >
                        <Eye size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        </div>
      </Card>

      <NewTransmittalWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        projectId={projectId}
      />
      <TransmittalDetailDrawer
        open={selectedId !== null}
        transmittalId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}
