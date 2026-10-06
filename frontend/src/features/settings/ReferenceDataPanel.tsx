// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bring the shipped countries, work calendars and tax rates up to this release.
 *
 * The seeder fills those tables only while they are empty, so an install set up
 * on an older release keeps the copy it started with. The server command
 * `update-reference-data` shows and applies the difference; a desktop install
 * has no console, so the same pass is offered here. First a preview grouped by
 * what will happen, then an Apply button behind a confirmation. The apply names
 * exactly the entries the preview showed as ready, and the server writes only
 * those that are still ready when it looks again.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Database, RefreshCw } from 'lucide-react';

import { Button, ConfirmDialog } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

export type ReferenceChangeStatus = 'ready' | 'kept' | 'review';

export interface ReferenceFieldChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface ReferenceChange {
  key: string;
  kind: 'country' | 'calendar' | 'tax';
  action: 'add' | 'update' | 'none';
  status: ReferenceChangeStatus;
  reason: string;
  label: string;
  detail: string;
  rows_added: number;
  fields: ReferenceFieldChange[];
}

export interface ReferenceDataPreview {
  ready: number;
  kept: number;
  review: number;
  changes: ReferenceChange[];
}

export interface ReferenceDataApplyResult {
  applied: string[];
  skipped: string[];
  rows_added: number;
  rows_updated: number;
  preview: ReferenceDataPreview;
}

export const REFERENCE_DATA_PREVIEW_URL = '/v1/i18n-foundation/reference-data/updates/';
export const REFERENCE_DATA_APPLY_URL = '/v1/i18n-foundation/reference-data/updates/apply/';

const STATUS_ORDER: ReferenceChangeStatus[] = ['ready', 'review', 'kept'];

/** The preview split by status, in the order the panel shows the groups. */
export function groupByStatus(changes: ReferenceChange[]): [ReferenceChangeStatus, ReferenceChange[]][] {
  return STATUS_ORDER.map((status) => [status, changes.filter((c) => c.status === status)] as [
    ReferenceChangeStatus,
    ReferenceChange[],
  ]).filter(([, list]) => list.length > 0);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') {
    const text = JSON.stringify(value);
    return text.length > 60 ? `${text.slice(0, 57)}...` : text;
  }
  return String(value);
}

export function ReferenceDataPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [preview, setPreview] = useState<ReferenceDataPreview | null>(null);
  const [confirming, setConfirming] = useState(false);

  const kindLabel = (kind: ReferenceChange['kind']): string => {
    if (kind === 'country') return t('settings.refdata_kind_country', { defaultValue: 'Country' });
    if (kind === 'calendar') return t('settings.refdata_kind_calendar', { defaultValue: 'Work calendar' });
    return t('settings.refdata_kind_tax', { defaultValue: 'Tax rate' });
  };

  const reasonLabel = (reason: string): string => {
    switch (reason) {
      case 'new':
        return t('settings.refdata_reason_new', { defaultValue: 'New in this release' });
      case 'new_period':
        return t('settings.refdata_reason_new_period', { defaultValue: 'New rate period in this release' });
      case 'fields_changed':
        return t('settings.refdata_reason_fields_changed', { defaultValue: 'Updated in this release' });
      case 'edited_locally':
        return t('settings.refdata_reason_edited_locally', { defaultValue: 'Edited here, your version stays' });
      case 'removed_here':
        return t('settings.refdata_reason_removed_here', { defaultValue: 'Removed here, not added back' });
      case 'rate_differs':
        return t('settings.refdata_reason_rate_differs', {
          defaultValue: 'The shipped rate differs for the same period. Check it and change it by hand if needed.',
        });
      case 'overlap':
        return t('settings.refdata_reason_overlap', {
          defaultValue: 'It would overlap a rate period already on file.',
        });
      case 'jurisdiction':
        return t('settings.refdata_reason_jurisdiction', {
          defaultValue: 'A rate of your own already covers this.',
        });
      default:
        return t('settings.refdata_reason_field_conflict', {
          defaultValue: 'A shipped setting differs from the one here. Check it and change it by hand if needed.',
        });
    }
  };

  const headingFor = (status: ReferenceChangeStatus, n: number): string => {
    if (status === 'ready') return t('settings.refdata_ready_heading', { defaultValue: 'Ready to apply ({{n}})', n });
    if (status === 'review') {
      return t('settings.refdata_review_heading', { defaultValue: 'Needs your decision, not applied ({{n}})', n });
    }
    return t('settings.refdata_kept_heading', { defaultValue: 'Kept as they are ({{n}})', n });
  };

  const checkMutation = useMutation({
    mutationFn: () => apiGet<ReferenceDataPreview>(REFERENCE_DATA_PREVIEW_URL),
    onSuccess: (data) => setPreview(data),
    onError: (error: Error) =>
      addToast({
        type: 'error',
        title: t('settings.refdata_check_failed', { defaultValue: 'Could not check the reference data' }),
        message: error.message,
      }),
  });

  const readyKeys = useMemo(
    () => (preview?.changes ?? []).filter((c) => c.status === 'ready').map((c) => c.key),
    [preview],
  );
  const grouped = useMemo(() => groupByStatus(preview?.changes ?? []), [preview]);

  const applyMutation = useMutation({
    mutationFn: (keys: string[]) => apiPost<ReferenceDataApplyResult>(REFERENCE_DATA_APPLY_URL, { keys }),
    onSuccess: (data) => {
      setConfirming(false);
      setPreview(data.preview);
      queryClient.invalidateQueries({ queryKey: ['tax-rates'] });
      addToast({
        type: 'success',
        title: t('settings.refdata_applied_title', { defaultValue: 'Reference data updated' }),
        message: t('settings.refdata_applied_message', {
          defaultValue: 'Rows added: {{added}}. Rows updated: {{updated}}.',
          added: data.rows_added,
          updated: data.rows_updated,
        }),
      });
    },
    onError: (error: Error) => {
      setConfirming(false);
      addToast({
        type: 'error',
        title: t('settings.refdata_apply_failed', { defaultValue: 'Could not apply the reference data updates' }),
        message: error.message,
      });
    },
  });

  return (
    <div
      data-testid="reference-data-panel"
      className="rounded-lg border border-border-light bg-surface-elevated px-4 py-3"
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-content-primary">
            {t('settings.refdata_title', { defaultValue: 'Update reference data' })}
          </p>
          <p className="text-xs text-content-secondary mt-0.5">
            {t('settings.refdata_desc', {
              defaultValue:
                'Countries, work calendars and tax rates come with each release, but an install set up on an older release keeps the copy it started with. Check what this release would add or change. Nothing is written until you apply it, and rows you created or edited yourself are never changed.',
            })}
          </p>
        </div>
        <Button
          variant="secondary"
          icon={<RefreshCw size={14} />}
          loading={checkMutation.isPending}
          onClick={() => checkMutation.mutate()}
        >
          {t('settings.refdata_check', { defaultValue: 'Check for updates' })}
        </Button>
      </div>

      {preview && (
        <div className="mt-3 border-t border-border-light pt-3" data-testid="reference-data-preview">
          {preview.changes.length === 0 ? (
            <p className="text-sm text-content-secondary">
              {t('settings.refdata_up_to_date', { defaultValue: 'Your reference data already matches this release.' })}
            </p>
          ) : (
            <div className="max-h-96 overflow-y-auto space-y-3">
              {grouped.map(([status, list]) => (
                <div key={status} data-testid={`reference-data-${status}`}>
                  <p className="text-xs font-semibold text-content-primary">{headingFor(status, list.length)}</p>
                  <ul className="mt-1 space-y-1">
                    {list.map((change) => (
                      <li key={change.key} className="text-xs">
                        <div className="flex flex-wrap items-baseline gap-x-2">
                          <span className="text-content-tertiary">{kindLabel(change.kind)}</span>
                          <span className="font-medium text-content-primary break-all">{change.label}</span>
                          <span className="text-content-secondary">{reasonLabel(change.reason)}</span>
                          {status === 'ready' && change.rows_added > 0 && (
                            <span className="text-content-tertiary">
                              {t('settings.refdata_rows_added', { defaultValue: 'Rows to add: {{n}}', n: change.rows_added })}
                            </span>
                          )}
                        </div>
                        {change.fields.length > 0 && (
                          <ul className="ml-4 mt-0.5 space-y-0.5">
                            {change.fields.map((f, i) => (
                              <li key={`${f.field}-${i}`} className="text-content-tertiary break-all">
                                {`${f.field}: ${formatValue(f.before)} -> ${formatValue(f.after)}`}
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}

          {readyKeys.length > 0 && (
            <div className="mt-3 flex justify-end">
              <Button variant="primary" icon={<Database size={14} />} onClick={() => setConfirming(true)}>
                {t('settings.refdata_apply', { defaultValue: 'Apply updates' })}
              </Button>
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        loading={applyMutation.isPending}
        variant="warning"
        title={t('settings.refdata_confirm_title', { defaultValue: 'Apply the reference data updates?' })}
        message={t('settings.refdata_confirm_message', {
          defaultValue:
            'Updates to apply: {{n}}. New rows are added and unchanged shipped rows are brought up to date. Rows you created or edited are not changed, and rates already on file keep their values.',
          n: readyKeys.length,
        })}
        confirmLabel={t('settings.refdata_apply', { defaultValue: 'Apply updates' })}
        onCancel={() => {
          if (!applyMutation.isPending) setConfirming(false);
        }}
        onConfirm={() => applyMutation.mutate(readyKeys)}
      />
    </div>
  );
}
