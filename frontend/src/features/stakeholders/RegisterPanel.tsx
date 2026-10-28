// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The stakeholder register: who is affected by the project, how they are
// classified, how engaged they are against how engaged the project needs them,
// and whether a fresh assessment is due. A row opens the stakeholder.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, CircleDashed, Plus, Users } from 'lucide-react';
import clsx from 'clsx';

import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtList } from '@/shared/lib/formatters';

import type { Readiness, ReadinessCode, Stakeholder, StakeholderSettings } from './api';
import { GatedButton, STAKEHOLDER_TONE, ToneBadge } from './StakeholderBits';
import { READINESS, STAKEHOLDER_STATUS, humanizeCode, nameOf, vocab, type LabelContext } from './labels';
import { stakeholderName, type Screen } from './screen';

type Filter = 'current' | 'review_due' | 'gap' | 'archived';

const READINESS_ORDER: ReadinessCode[] = [
  'register_present',
  'key_stakeholders_planned',
  'commitments_tracked',
  'roles_filled',
  'mandates_complete',
];

/** The name of a stakeholder's class under the project's analysis method. */
export function classificationName(labels: LabelContext, settings: StakeholderSettings, s: Pick<Stakeholder, 'classification' | 'method_code'>): string {
  if (!s.classification || s.classification === 'not_assessed') {
    return labels.t('stakeholders.ui.not_assessed', { defaultValue: 'Not assessed' });
  }
  const method = settings.framework.analysis_methods.find((m) => m.code === s.method_code);
  return method ? nameOf(labels, method.classes, s.classification) : humanizeCode(s.classification);
}

/** The five things a phase gate asks of this module, each met or not. */
export function ReadinessStrip({ readiness }: { readiness: Readiness | undefined }) {
  const { t } = useTranslation();
  if (!readiness) return null;
  return (
    <section
      aria-label={t('stakeholders.ui.readiness.title', { defaultValue: 'What the next gate checks here' })}
      className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3"
      data-testid="readiness-strip"
    >
      <h2 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        {t('stakeholders.ui.readiness.title', { defaultValue: 'What the next gate checks here' })}
      </h2>
      <ul className="mt-2 grid gap-1.5 sm:grid-cols-2">
        {READINESS_ORDER.map((code) => {
          const check = readiness[code];
          if (!check) return null;
          const met = check.status === 'met';
          return (
            <li key={code} data-testid="readiness-check" data-status={check.status} className="flex items-start gap-2 text-sm">
              {met ? (
                <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-semantic-success" aria-hidden />
              ) : (
                <CircleDashed size={15} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
              )}
              <span className={met ? 'text-content-secondary' : 'text-content-primary'}>
                {vocab(t, READINESS, code)}
                <span className="sr-only">
                  {' '}
                  {met
                    ? t('stakeholders.ui.readiness.met', { defaultValue: '(met)' })
                    : t('stakeholders.ui.readiness.not_met', { defaultValue: '(not met yet)' })}
                </span>
                {(check.overdue_refs?.length ?? 0) > 0 && (
                  <span className="block text-xs text-semantic-warning" data-testid="readiness-overdue">
                    {t('stakeholders.ui.readiness.overdue', {
                      defaultValue: 'Past their due date: {{codes}}',
                      codes: fmtList(check.overdue_refs ?? []),
                    })}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export interface RegisterPanelProps {
  screen: Screen;
  stakeholders: Stakeholder[];
  readiness: Readiness | undefined;
  onOpen: (id: string) => void;
  onAdd: () => void;
}

export function RegisterPanel({ screen, stakeholders, readiness, onOpen, onAdd }: RegisterPanelProps) {
  const { t } = useTranslation();
  const { settings, labels, personName } = screen;
  const fw = settings.framework;
  const [filter, setFilter] = useState<Filter>('current');

  const counts = useMemo(() => {
    const live = stakeholders.filter((s) => s.status !== 'archived');
    return {
      current: live.length,
      review_due: live.filter((s) => s.review_due).length,
      gap: live.filter((s) => (s.engagement_gap ?? 0) > 0).length,
      archived: stakeholders.length - live.length,
    };
  }, [stakeholders]);

  const shown = stakeholders.filter((s) => {
    if (filter === 'archived') return s.status === 'archived';
    if (s.status === 'archived') return false;
    if (filter === 'review_due') return s.review_due;
    if (filter === 'gap') return (s.engagement_gap ?? 0) > 0;
    return true;
  });

  const add = (
    <GatedButton allowed={settings.can.edit} capability="edit" icon={<Plus size={14} />} onClick={onAdd} data-testid="stakeholder-add">
      {t('stakeholders.ui.stakeholder.add', { defaultValue: 'Add stakeholder' })}
    </GatedButton>
  );

  if (stakeholders.length === 0) {
    return (
      <div className="space-y-4">
        <EmptyState
          icon={<Users size={28} />}
          title={t('stakeholders.ui.register.empty_title', { defaultValue: 'No stakeholders yet' })}
          description={t('stakeholders.ui.register.empty_body', {
            defaultValue: 'List everyone the project affects or depends on: the client, authorities, neighbours, utilities, users. Then assess each one, so you know whom to keep close.',
          })}
          action={add}
        />
      </div>
    );
  }

  const filters: Array<[Filter, string]> = [
    ['current', t('stakeholders.ui.register.filter_current', { defaultValue: 'All' })],
    ['review_due', t('stakeholders.ui.register.filter_review_due', { defaultValue: 'Assessment due' })],
    ['gap', t('stakeholders.ui.register.filter_gap', { defaultValue: 'Not engaged enough' })],
    ['archived', t('stakeholders.ui.register.filter_archived', { defaultValue: 'Archived' })],
  ];

  return (
    <div className="space-y-4">
      <ReadinessStrip readiness={readiness} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label={t('stakeholders.ui.register.filter', { defaultValue: 'Filter stakeholders' })}
        >
          {filters.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
              data-testid={`register-filter-${id}`}
              className={clsx(
                'rounded-full border px-3 py-1 text-xs',
                filter === id ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary',
              )}
            >
              {label} <span className="text-content-tertiary">{counts[id]}</span>
            </button>
          ))}
        </div>
        {add}
      </div>

      {shown.length === 0 ? (
        <p className="py-6 text-center text-sm text-content-tertiary">
          {t('stakeholders.ui.register.none_in_filter', { defaultValue: 'No stakeholder matches this filter.' })}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
          <table className="w-full min-w-[720px] text-sm" data-testid="register-table">
            <thead className="bg-surface-secondary text-left text-xs text-content-tertiary">
              <tr>
                <th className="px-3 py-2 font-medium">{t('stakeholders.ui.register.col_name', { defaultValue: 'Stakeholder' })}</th>
                <th className="px-3 py-2 font-medium">{t('stakeholders.ui.register.col_class', { defaultValue: 'Classification' })}</th>
                <th className="px-3 py-2 font-medium">{t('stakeholders.ui.register.col_engagement', { defaultValue: 'Engagement today / needed' })}</th>
                <th className="px-3 py-2 font-medium">{t('stakeholders.ui.register.col_owner', { defaultValue: 'Relationship kept by' })}</th>
                <th className="px-3 py-2 text-right font-medium">{t('stakeholders.ui.register.col_commitments', { defaultValue: 'Open commitments' })}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((s) => {
                const gap = (s.engagement_gap ?? 0) > 0;
                return (
                  <tr key={s.id} className="border-t border-border-light" data-testid="register-row">
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={() => onOpen(s.id)}
                        className="text-left font-medium text-oe-blue-text hover:underline"
                        data-testid="register-open"
                      >
                        {stakeholderName(t, s)}
                      </button>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
                        <span>{s.code}</span>
                        <span>{nameOf(labels, fw.stakeholder_categories, s.category)}</span>
                        {s.status !== 'active' && (
                          <ToneBadge tone={STAKEHOLDER_TONE[s.status]}>{vocab(t, STAKEHOLDER_STATUS, s.status)}</ToneBadge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={s.classification === 'not_assessed' ? 'text-content-tertiary' : 'text-content-primary'}>
                        {classificationName(labels, settings, s)}
                      </span>
                      {s.review_due && (
                        <div className="mt-0.5 flex items-center gap-1 text-xs text-semantic-warning" data-testid="review-due">
                          <AlertTriangle size={12} aria-hidden />
                          {t('stakeholders.ui.register.review_due', { defaultValue: 'Assessment due' })}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {s.engagement_current || s.engagement_desired ? (
                        <span className={gap ? 'font-medium text-semantic-warning' : 'text-content-secondary'} data-testid="engagement-cell" data-gap={gap}>
                          {t('stakeholders.ui.register.engagement_pair', {
                            defaultValue: '{{current}} / {{desired}}',
                            current: s.engagement_current
                              ? nameOf(labels, fw.engagement_levels, s.engagement_current)
                              : t('stakeholders.ui.not_set', { defaultValue: 'Not set' }),
                            desired: s.engagement_desired
                              ? nameOf(labels, fw.engagement_levels, s.engagement_desired)
                              : t('stakeholders.ui.not_set', { defaultValue: 'Not set' }),
                          })}
                        </span>
                      ) : (
                        <span className="text-content-tertiary">{t('stakeholders.ui.not_set', { defaultValue: 'Not set' })}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {personName(s.relationship_owner_user_id) ?? (
                        <span className="text-content-tertiary">{t('stakeholders.ui.nobody', { defaultValue: 'Nobody yet' })}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{s.open_commitments}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
