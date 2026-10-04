// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Recurring schedules tab — RRULE-driven ticket templates (T10).
 *
 * Backend: /api/v1/service/recurring-schedules/
 */

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Repeat,
  PlayCircle,
  Plus,
  Power,
  Loader2,
  Trash2,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  SkeletonTable,
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listRecurringSchedules,
  createRecurringSchedule,
  updateRecurringSchedule,
  deleteRecurringSchedule,
  materializeRecurringSchedule,
  type RecurringSchedule,
  type ServiceContract,
} from './api';

interface Props {
  contracts: ServiceContract[];
  /** Set on the /projects/:projectId/service mount, absent on the flat one. */
  projectId?: string;
}

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function RecurringSchedulesTab({ contracts, projectId }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);

  const [createOpen, setCreateOpen] = useState(false);

  const schedulesQ = useQuery({
    queryKey: ['service', 'recurring-schedules', projectId ?? ''],
    queryFn: () => listRecurringSchedules({ project_id: projectId, limit: 200 }),
  });

  const toggleEnabled = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateRecurringSchedule(id, { enabled }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['service', 'recurring-schedules'] });
    },
    onError: (e) => {
      toast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  const runNow = useMutation({
    mutationFn: (id: string) => materializeRecurringSchedule(id, { force: true }),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: ['service', 'recurring-schedules'] });
      void qc.invalidateQueries({ queryKey: ['service', 'tickets'] });
      if (result.materialized) {
        toast({
          type: 'success',
          title: t('common.success', { defaultValue: 'Success' }),
          message: t('service.recurring.run_ok', {
            defaultValue: 'Ticket {{n}} created',
            n: result.ticket_number ?? '',
          }),
        });
      } else {
        toast({
          type: 'info',
          title: t('service.recurring.skipped', {
            defaultValue: 'Run skipped',
          }),
          message: result.reason ?? 'Not materialised',
        });
      }
    },
    onError: (e) => {
      toast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteRecurringSchedule(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['service', 'recurring-schedules'] });
    },
    onError: (e) => {
      toast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  const rows = useMemo(() => schedulesQ.data ?? [], [schedulesQ.data]);

  return (
    <>
      <div className="flex items-center justify-end pb-3">
        <Button
          variant="primary"
          icon={<Plus size={14} />}
          onClick={() => setCreateOpen(true)}
        >
          {t('service.recurring.new', { defaultValue: 'New Recurring Schedule' })}
        </Button>
      </div>

      <Card padding="none">
        {schedulesQ.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={5} columns={5} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Repeat size={22} />}
            title={t('service.recurring.empty_title', {
              defaultValue: 'No recurring schedules yet',
            })}
            description={t('service.recurring.empty_desc', {
              defaultValue:
                'Recurring schedules use RRULE syntax (RFC 5545) to materialise tickets automatically - e.g. monthly elevator inspections.',
            })}
            action={{
              label: t('service.recurring.new', {
                defaultValue: 'New Recurring Schedule',
              }),
              onClick: () => setCreateOpen(true),
            }}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">
                    {t('service.recurring.col_name', { defaultValue: 'Name' })}
                  </th>
                  <th className="px-4 py-2.5 text-left">
                    {t('service.recurring.col_rrule', { defaultValue: 'RRULE' })}
                  </th>
                  <th className="px-4 py-2.5 text-left">
                    {t('service.recurring.col_next', { defaultValue: 'Next run' })}
                  </th>
                  <th className="px-4 py-2.5 text-left">
                    {t('service.recurring.col_last', { defaultValue: 'Last run' })}
                  </th>
                  <th className="px-4 py-2.5 text-left">
                    {t('service.recurring.col_status', { defaultValue: 'Status' })}
                  </th>
                  <th className="px-4 py-2.5 text-right">
                    {t('common.actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <ScheduleRow
                    key={row.id}
                    row={row}
                    onToggle={() =>
                      toggleEnabled.mutate({ id: row.id, enabled: !row.enabled })
                    }
                    onRun={() => runNow.mutate(row.id)}
                    onDelete={() => remove.mutate(row.id)}
                    busy={
                      (toggleEnabled.isPending &&
                        toggleEnabled.variables?.id === row.id) ||
                      (runNow.isPending && runNow.variables === row.id) ||
                      (remove.isPending && remove.variables === row.id)
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {createOpen && (
        <CreateRecurringModal
          contracts={contracts}
          projectId={projectId}
          onClose={() => setCreateOpen(false)}
        />
      )}
    </>
  );
}

function ScheduleRow({
  row,
  onToggle,
  onRun,
  onDelete,
  busy,
}: {
  row: RecurringSchedule;
  onToggle: () => void;
  onRun: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  return (
    <tr className="border-t border-border-light">
      <td className="px-4 py-2 font-medium text-content-primary truncate max-w-[260px]">
        {row.name}
      </td>
      <td className="px-4 py-2 font-mono text-xs text-content-secondary truncate max-w-[200px]">
        {row.rrule}
      </td>
      <td className="px-4 py-2 text-content-secondary text-xs">
        {row.next_run_at ? <DateDisplay value={row.next_run_at} /> : '—'}
      </td>
      <td className="px-4 py-2 text-content-secondary text-xs">
        {row.last_run_at ? <DateDisplay value={row.last_run_at} /> : '—'}
      </td>
      <td className="px-4 py-2">
        <Badge variant={row.enabled ? 'success' : 'neutral'} dot>
          {row.enabled
            ? t('service.recurring.enabled', { defaultValue: 'Enabled' })
            : t('service.recurring.disabled', { defaultValue: 'Disabled' })}
        </Badge>
      </td>
      <td className="px-4 py-2 text-right">
        <div className="inline-flex items-center gap-1">
          <button
            type="button"
            disabled={busy}
            onClick={onRun}
            title={t('service.recurring.run_now', { defaultValue: 'Run now' })}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-light text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:opacity-50"
          >
            {busy ? <Loader2 size={12} className="animate-spin" /> : <PlayCircle size={14} />}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onToggle}
            title={
              row.enabled
                ? t('service.recurring.disable', { defaultValue: 'Disable' })
                : t('service.recurring.enable', { defaultValue: 'Enable' })
            }
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-light text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:opacity-50"
          >
            <Power size={14} />
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onDelete}
            title={t('common.delete', { defaultValue: 'Delete' })}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-light text-semantic-error transition-colors hover:border-semantic-error disabled:opacity-50"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </td>
    </tr>
  );
}

function CreateRecurringModal({
  contracts,
  projectId,
  onClose,
}: {
  contracts: ServiceContract[];
  projectId?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const toast = useToastStore((s) => s.addToast);

  const [name, setName] = useState('');
  const [rrule, setRrule] = useState('FREQ=MONTHLY;BYMONTHDAY=1');
  const [contractId, setContractId] = useState(contracts[0]?.id ?? '');
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<'low' | 'med' | 'high' | 'critical'>('med');

  const create = useMutation({
    mutationFn: () =>
      createRecurringSchedule({
        name,
        rrule,
        // On the project mount the schedule is that project's, so it stays
        // in the list it was created from.
        project_id: projectId || null,
        contract_id: contractId || null,
        template_ticket_data: {
          contract_id: contractId || undefined,
          title,
          priority,
        },
        enabled: true,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['service', 'recurring-schedules'] });
      onClose();
    },
    onError: (e) => {
      toast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  const canSubmit = name.trim().length > 0 && rrule.trim().length > 0 && !!contractId;

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('service.recurring.new', { defaultValue: 'New Recurring Schedule' })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!canSubmit || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? (
              <Loader2 size={14} className="mr-2 animate-spin" />
            ) : null}
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('service.recurring.section_schedule', {
          defaultValue: 'Schedule',
        })}
      >
        <WideModalField
          label={t('service.recurring.field_name', { defaultValue: 'Name' })}
          required
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Monthly boiler inspection"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('service.recurring.field_rrule', {
            defaultValue: 'RRULE (RFC 5545)',
          })}
          required
          hint={t('service.recurring.field_rrule_hint', {
            defaultValue:
              'e.g. FREQ=MONTHLY;BYMONTHDAY=1 or FREQ=WEEKLY;BYDAY=MO',
          })}
        >
          <input
            type="text"
            value={rrule}
            onChange={(e) => setRrule(e.target.value)}
            className={`${inputCls} font-mono`}
          />
        </WideModalField>
      </WideModalSection>
      <WideModalSection
        title={t('service.recurring.section_template', {
          defaultValue: 'Ticket template',
        })}
      >
        <WideModalField
          label={t('service.recurring.field_contract', {
            defaultValue: 'Contract',
          })}
          required
        >
          <select
            value={contractId}
            onChange={(e) => setContractId(e.target.value)}
            className={inputCls}
          >
            <option value="">—</option>
            {contracts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.contract_number} — {c.title || 'Untitled'}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('service.recurring.field_title', {
            defaultValue: 'Ticket title',
          })}
        >
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Routine inspection"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('service.recurring.field_priority', {
            defaultValue: 'Priority',
          })}
        >
          <select
            value={priority}
            onChange={(e) =>
              setPriority(e.target.value as 'low' | 'med' | 'high' | 'critical')
            }
            className={inputCls}
          >
            <option value="low">low</option>
            <option value="med">med</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
