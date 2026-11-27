// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Who holds the ball and who receives the submittal, as two pickers of the
 * form. Both store user ids; the names come from the users list when the
 * viewer may read it, and from the names the server already resolved
 * otherwise.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown } from 'lucide-react';

import { apiGet } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { WideModalField, WideModalSection } from '@/shared/ui';
import type { Submittal, UpdateSubmittalPayload } from './api';

export interface PeopleFormData {
  /** User id, '' for nobody. */
  ball_in_court: string;
  distribution_list: string[];
}

export const EMPTY_PEOPLE_FORM: PeopleFormData = { ball_in_court: '', distribution_list: [] };

export function peopleFormData(existing: Submittal): PeopleFormData {
  return {
    ball_in_court: existing.ball_in_court ?? '',
    distribution_list: [...(existing.distribution_list ?? [])],
  };
}

/** Only what changed: `null` hands the ball to nobody, `[]` empties the list. */
export function buildPeoplePatch(form: PeopleFormData, base: PeopleFormData): UpdateSubmittalPayload {
  const out: UpdateSubmittalPayload = {};
  if (form.ball_in_court !== base.ball_in_court) out.ball_in_court = form.ball_in_court || null;
  if (form.distribution_list.join(',') !== base.distribution_list.join(',')) {
    out.distribution_list = form.distribution_list;
  }
  return out;
}

/** What a create sends: nothing for an empty choice, so the server's defaults apply. */
export function buildPeopleCreate(form: PeopleFormData): Pick<UpdateSubmittalPayload, 'ball_in_court' | 'distribution_list'> {
  return {
    ...(form.ball_in_court && { ball_in_court: form.ball_in_court }),
    ...(form.distribution_list.length > 0 && { distribution_list: form.distribution_list }),
  };
}

interface UserRow {
  id: string;
  email: string;
  full_name?: string | null;
}

const inputCls = 'oe-select oe-input-lg';

export function SubmittalPeopleFields({
  idPrefix,
  form,
  onChange,
  existing,
}: {
  idPrefix: string;
  form: PeopleFormData;
  onChange: (patch: Partial<PeopleFormData>) => void;
  existing?: Submittal;
}) {
  const { t } = useTranslation();
  const canListUsers = useHasPermission('users.list');
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () => apiGet<UserRow[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    retry: false,
    enabled: canListUsers,
  });

  // Selected people the list does not return still show under the name the server knew.
  const options = useMemo(() => {
    const known = new Map<string, string>();
    for (const u of users) known.set(u.id, (u.full_name || '').trim() || u.email);
    if (existing?.ball_in_court && !known.has(existing.ball_in_court)) {
      known.set(existing.ball_in_court, existing.ball_in_court_name || existing.ball_in_court);
    }
    (existing?.distribution_list ?? []).forEach((id, i) => {
      if (!known.has(id)) known.set(id, existing?.distribution_names?.[i] || id);
    });
    return [...known.entries()].map(([id, name]) => ({ id, name }));
  }, [users, existing]);

  const toggle = (id: string) =>
    onChange({
      distribution_list: form.distribution_list.includes(id)
        ? form.distribution_list.filter((x) => x !== id)
        : [...form.distribution_list, id],
    });

  return (
    <WideModalSection
      title={t('submittals.section_people', { defaultValue: 'Ball in court and distribution' })}
      columns={2}
    >
      <WideModalField
        label={t('submittals.field_ball_in_court', { defaultValue: 'Ball in court' })}
        htmlFor={`${idPrefix}-ball-in-court`}
        hint={t('submittals.ball_in_court_hint', {
          defaultValue: 'Who has to act next. Reassign it here when the item changes hands.',
        })}
        span={2}
      >
        <div className="relative">
          <select
            id={`${idPrefix}-ball-in-court`}
            value={form.ball_in_court}
            onChange={(e) => onChange({ ball_in_court: e.target.value })}
            className={inputCls}
          >
            <option value="">{t('submittals.ball_in_court_nobody', { defaultValue: 'Nobody' })}</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
            <ChevronDown size={14} />
          </div>
        </div>
      </WideModalField>

      <WideModalField
        label={t('submittals.field_distribution', { defaultValue: 'Distribution list' })}
        hint={t('submittals.distribution_hint', {
          defaultValue: 'People who receive this submittal for information.',
        })}
        span={2}
      >
        {options.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('submittals.distribution_no_users', { defaultValue: 'No users to choose from.' })}
          </p>
        ) : (
          <div className="max-h-36 overflow-y-auto rounded-lg border border-border-light p-2 space-y-1">
            {options.map((o) => (
              <label key={o.id} className="flex items-center gap-2 text-sm text-content-primary cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.distribution_list.includes(o.id)}
                  onChange={() => toggle(o.id)}
                />
                <span className="truncate">{o.name}</span>
              </label>
            ))}
          </div>
        )}
      </WideModalField>
    </WideModalSection>
  );
}
