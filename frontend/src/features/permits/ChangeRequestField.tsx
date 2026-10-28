// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Once the roadmap is binding, adding, removing or re-ordering a permit needs
// an approved change request of the roadmap's frame document, and each
// request pays for one change. This field lets the reader pick it.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { listFrameChangeRequests, permitKeys, type Roadmap } from './api';
import { refusalText } from './hooks';
import type { TFn } from './labels';
import { Field, Refusal, dateText, fieldClass } from './PermitBits';

/** True once the roadmap frame document is binding. */
export function isBinding(roadmap: Pick<Roadmap, 'state'> | null | undefined): boolean {
  return roadmap?.state === 'agreed';
}

export interface ChangeRequestFieldProps {
  projectId: string;
  roadmap: Roadmap | null | undefined;
  value: string;
  onChange: (changeRequestId: string) => void;
  /** Load the list only while the dialog is open. */
  enabled: boolean;
}

/** Renders nothing while the roadmap is still a draft. */
export function ChangeRequestField({ projectId, roadmap, value, onChange, enabled }: ChangeRequestFieldProps) {
  const { t } = useTranslation();
  const binding = isBinding(roadmap);
  const requestsQ = useQuery({
    queryKey: [...permitKeys.project(projectId), 'change-requests'],
    queryFn: () => listFrameChangeRequests(projectId).then((page) => page.items),
    enabled: enabled && binding && !!projectId,
  });
  if (!binding) return null;
  // One approved request covers one change, so a request already used up is not offered again.
  const consumed = roadmap?.consumed_change_request_ids ?? [];
  const approved = (requestsQ.data ?? []).filter(
    (r) => r.status === 'approved' && r.document_id === roadmap?.governance_document_id && !consumed.includes(r.id),
  );
  return (
    <div className="space-y-1 rounded-md border border-border-light bg-surface-secondary p-3" data-testid="change-request-field">
      <Field
        label={t('permits.ui.change_request.label', { defaultValue: 'Approved change request' })}
        hint={t('permits.ui.change_request.hint', {
          defaultValue: 'The roadmap is binding. Each change to its list of permits uses up one approved change request.',
        })}
        required
      >
        {(id) => (
          <select id={id} className={fieldClass} value={value} disabled={requestsQ.isLoading} onChange={(e) => onChange(e.target.value)}>
            <option value="">
              {requestsQ.isLoading
                ? t('permits.ui.loading', { defaultValue: 'Loading...' })
                : t('permits.ui.change_request.choose', { defaultValue: 'Choose a change request' })}
            </option>
            {approved.map((r) => (
              <option key={r.id} value={r.id}>
                {t('permits.ui.change_request.option', {
                  defaultValue: '{{reason}} (approved {{date}})',
                  reason: r.reason,
                  date: dateText(r.decided_at),
                })}
              </option>
            ))}
          </select>
        )}
      </Field>
      {requestsQ.isError && <Refusal>{refusalText(t as TFn, requestsQ.error)}</Refusal>}
      {requestsQ.isSuccess && approved.length === 0 && (
        <p className="text-xs text-content-secondary" data-testid="change-request-none">
          {t('permits.ui.change_request.none', {
            defaultValue: 'No approved change request for the roadmap yet. Raise one in project governance and have it approved.',
          })}
        </p>
      )}
    </div>
  );
}

/** The problem line a dialog shows while a binding roadmap has no change request picked. */
export function changeRequestProblem(t: TFn, roadmap: Roadmap | null | undefined, value: string): string[] {
  if (!isBinding(roadmap) || value) return [];
  return [t('permits.ui.change_request.problem', { defaultValue: 'Choose the approved change request that covers this change.' })];
}
