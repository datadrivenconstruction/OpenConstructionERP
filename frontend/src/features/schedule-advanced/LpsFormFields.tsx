// Last Planner form fields​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Optional fields added to the constraint and commitment forms: the record
 * whose closing clears a constraint, and the subcontractor and target
 * progress of a commitment. Also the words for the 409 the commit call
 * answers with while a task still has open constraints.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { listSubcontractors } from '@/features/subcontractors/api';
import type { ConstraintLinkedType } from './api';
import { linkedTypeLabel } from './ConstraintsLog';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

export const LINKED_TYPES: ConstraintLinkedType[] = ['rfi', 'submittal', 'purchase_order', 'goods_receipt'];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A linked record is sent only as a complete pair with a well-formed id. */
export function isValidLink(type: string, id: string): boolean {
  return (type === '' && id.trim() === '') || (type !== '' && UUID_RE.test(id.trim()));
}

export function ConstraintLinkFields({
  type,
  id,
  onType,
  onId,
}: {
  type: ConstraintLinkedType | '';
  id: string;
  onType: (v: ConstraintLinkedType | '') => void;
  onId: (v: string) => void;
}) {
  const { t } = useTranslation();
  const invalid = !isValidLink(type, id);
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.link_type_label', { defaultValue: 'Linked record (optional)' })}
        </label>
        <select
          value={type}
          onChange={(e) => onType(e.target.value as ConstraintLinkedType | '')}
          className={inputCls}
          data-testid="constraint-link-type"
        >
          <option value="">{t('schedule_advanced.link_none', { defaultValue: 'None' })}</option>
          {LINKED_TYPES.map((lt) => (
            <option key={lt} value={lt}>
              {linkedTypeLabel(t, lt)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>{t('schedule_advanced.link_id_label', { defaultValue: 'Record ID' })}</label>
        <input
          value={id}
          onChange={(e) => onId(e.target.value)}
          disabled={type === ''}
          className={inputCls}
          aria-invalid={invalid}
          placeholder="00000000-0000-0000-0000-000000000000"
          data-testid="constraint-link-id"
        />
        {invalid && (
          <p className="mt-1 text-2xs text-semantic-error">
            {t('schedule_advanced.link_id_invalid', { defaultValue: 'Enter the record ID (UUID).' })}
          </p>
        )}
      </div>
    </div>
  );
}

export function CommitmentExtraFields({
  subcontractorId,
  targetPct,
  onSubcontractor,
  onTargetPct,
}: {
  subcontractorId: string;
  targetPct: string;
  onSubcontractor: (v: string) => void;
  onTargetPct: (v: string) => void;
}) {
  const { t } = useTranslation();
  const subsQ = useQuery({
    queryKey: ['schedule-advanced', 'commitment-subs'],
    queryFn: () => listSubcontractors({ limit: 200 }),
  });
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.commit_subcontractor', { defaultValue: 'Subcontractor (optional)' })}
        </label>
        <select
          value={subcontractorId}
          onChange={(e) => onSubcontractor(e.target.value)}
          className={inputCls}
          data-testid="commitment-subcontractor"
        >
          <option value="">{t('schedule_advanced.link_none', { defaultValue: 'None' })}</option>
          {(subsQ.data?.items ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.legal_name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.commit_target_pct', { defaultValue: 'Target progress % (optional)' })}
        </label>
        <input
          type="number"
          min={0}
          max={100}
          value={targetPct}
          onChange={(e) => onTargetPct(e.target.value)}
          className={inputCls}
          data-testid="commitment-target-pct"
        />
      </div>
    </div>
  );
}

/** A refused commit in the page's words; anything else is the ordinary message. */
export function commitErrorMessage(err: unknown, t: TFunction): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: { code?: string } } | null)?.detail;
    if (detail?.code === 'constraints_open') {
      return t('schedule_advanced.err_constraints_open', {
        defaultValue: 'This task is not ready: clear its open constraints before committing to it.',
      });
    }
  }
  return getErrorMessage(err);
}
