// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The permit roadmap: every permit the project needs, who applies, where it
// stands, and whether its decision will be there by the date it is needed.

import { useTranslation } from 'react-i18next';
import { AlertTriangle, ClipboardList, Plus, Route, Settings2 } from 'lucide-react';
import clsx from 'clsx';

import { EmptyState } from '@/shared/ui/EmptyState';

import type { RoadmapCan } from './api';
import { APPLICANT_ROLE, APPLICATION_STATE, REQUIREMENT_STATE, typeName, vocab, type LabelContext } from './labels';
import { GatedButton, REQUIREMENT_TONE, RefusedActions, ToneBadge, dateText } from './PermitBits';
import { gate, summariseRoadmap, type RoadmapRow } from './rules';

export interface RoadmapTableProps {
  rows: RoadmapRow[];
  /** True once the roadmap frame document is binding: the list changes through a change request. */
  binding: boolean;
  /** What the reader may do with the roadmap, as the server says; absent on an older answer. */
  can?: RoadmapCan;
  /** False when the project runs without gates; the roadmap then stays a working list. */
  gatesInUse?: boolean;
  labels: LabelContext;
  onOpen: (requirementId: string) => void;
  onAdd: () => void;
  onPropose: () => void;
  onSettings: () => void;
}

export function RoadmapTable({ rows, binding, can, gatesInUse, labels, onOpen, onAdd, onPropose, onSettings }: RoadmapTableProps) {
  const { t } = useTranslation();
  const summary = summariseRoadmap(rows);

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <GatedButton gate={gate(can?.add_requirement, true)} size="sm" icon={<Plus size={14} />} onClick={onAdd} data-testid="roadmap-add">
        {t('permits.ui.roadmap.add', { defaultValue: 'Add permit' })}
      </GatedButton>
      <GatedButton gate={gate(can?.accept_proposals, true)} size="sm" variant="secondary" icon={<Route size={14} />} onClick={onPropose} data-testid="roadmap-propose">
        {t('permits.ui.roadmap.propose', { defaultValue: 'Take from the permit route' })}
      </GatedButton>
      <GatedButton gate={gate(can?.edit, true)} size="sm" variant="ghost" icon={<Settings2 size={14} />} onClick={onSettings} data-testid="roadmap-settings">
        {t('permits.ui.roadmap.settings', { defaultValue: 'Settings' })}
      </GatedButton>
    </div>
  );

  const reasons = (
    <RefusedActions
      testId="roadmap-refused"
      items={[
        [t('permits.ui.roadmap.add', { defaultValue: 'Add permit' }), gate(can?.add_requirement, true)],
        [t('permits.ui.roadmap.propose', { defaultValue: 'Take from the permit route' }), gate(can?.accept_proposals, true)],
        [t('permits.ui.roadmap.settings', { defaultValue: 'Settings' }), gate(can?.edit, true)],
      ]}
    />
  );

  if (rows.length === 0) {
    return (
      <div className="space-y-3">
        <EmptyState
          icon={<ClipboardList size={28} />}
          title={t('permits.ui.roadmap.empty_title', { defaultValue: 'No permit on the roadmap yet' })}
          description={t('permits.ui.roadmap.empty_body', {
            defaultValue:
              'List every permit this project needs before work can start and before it can be used. Take them from the confirmed permit route, or add them one by one.',
          })}
          action={{ label: t('permits.ui.roadmap.add', { defaultValue: 'Add permit' }), onClick: onAdd }}
        />
        <div className="flex justify-center gap-2">
          <GatedButton gate={gate(can?.accept_proposals, true)} size="sm" variant="secondary" icon={<Route size={14} />} onClick={onPropose} data-testid="roadmap-propose">
            {t('permits.ui.roadmap.propose', { defaultValue: 'Take from the permit route' })}
          </GatedButton>
          <GatedButton gate={gate(can?.edit, true)} size="sm" variant="ghost" icon={<Settings2 size={14} />} onClick={onSettings} data-testid="roadmap-settings">
            {t('permits.ui.roadmap.settings', { defaultValue: 'Settings' })}
          </GatedButton>
        </div>
        {reasons}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-content-secondary" data-testid="roadmap-summary">
          {t('permits.ui.roadmap.summary', {
            defaultValue: 'Permits needed: {{total}}. Granted: {{granted}}. With the authority or in preparation: {{inProgress}}.',
            total: summary.total,
            granted: summary.granted,
            inProgress: summary.inProgress,
          })}
        </p>
        {toolbar}
      </div>
      {reasons}
      {gatesInUse === false && (
        <p role="status" className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="roadmap-no-gates">
          {t('permits.ui.roadmap.no_gates', {
            defaultValue:
              'This project does not use gates. The roadmap is a working list: it is not agreed at a gate, and permits can be added or removed without a change request.',
          })}
        </p>
      )}
      {binding && (
        <p role="status" className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-sm text-content-secondary" data-testid="roadmap-binding">
          {t('permits.ui.roadmap.binding', {
            defaultValue:
              'The roadmap is binding. Adding or removing a permit now needs an approved change request in project governance.',
          })}
        </p>
      )}
      {summary.conflicts > 0 && (
        <p
          role="status"
          data-testid="roadmap-conflicts"
          className="flex items-start gap-2 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-3 py-2 text-sm text-content-primary"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          {t('permits.ui.roadmap.conflicts', {
            defaultValue: 'Permits whose decision is forecast after the date they are needed: {{n}}. Submit earlier or move the works.',
            n: summary.conflicts,
          })}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[760px] text-sm">
          <thead className="bg-surface-secondary text-left text-2xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className="px-3 py-2 font-medium">{t('permits.ui.roadmap.col_permit', { defaultValue: 'Permit' })}</th>
              <th className="px-3 py-2 font-medium">{t('permits.ui.roadmap.col_applicant', { defaultValue: 'Applicant' })}</th>
              <th className="px-3 py-2 font-medium">{t('permits.ui.roadmap.col_state', { defaultValue: 'Status' })}</th>
              <th className="px-3 py-2 font-medium">{t('permits.ui.roadmap.col_submit', { defaultValue: 'Submit by' })}</th>
              <th className="px-3 py-2 font-medium">{t('permits.ui.roadmap.col_forecast', { defaultValue: 'Decision expected' })}</th>
              <th className="px-3 py-2 font-medium">{t('permits.ui.roadmap.col_needed', { defaultValue: 'Needed by' })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ requirement: r, timeline: tl, application }) => {
              const type = typeName(labels, r.permit_type_code, r.name_key);
              const conflict = !!tl?.schedule_conflict && !tl.conflict_accepted;
              return (
                <tr
                  key={r.id}
                  data-testid="roadmap-row"
                  className={clsx('border-t border-border-light', !r.applicable && 'text-content-tertiary')}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="text-left font-medium text-oe-blue-text hover:underline"
                      onClick={() => onOpen(r.id)}
                    >
                      {r.title || type}
                    </button>
                    {r.title && <span className="block text-xs text-content-tertiary">{type}</span>}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {vocab(t, APPLICANT_ROLE, r.applicant_role)}
                    {r.applicant_party && <span className="block text-xs text-content-tertiary">{r.applicant_party}</span>}
                  </td>
                  <td className="px-3 py-2">
                    {r.state && <ToneBadge tone={REQUIREMENT_TONE[r.state]}>{vocab(t, REQUIREMENT_STATE, r.state)}</ToneBadge>}
                    {application && r.state === 'in_progress' && (
                      <span className="mt-0.5 block text-xs text-content-tertiary">{vocab(t, APPLICATION_STATE, application.state)}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">{dateText(tl?.latest_submit)}</td>
                  <td className="px-3 py-2 text-content-secondary">
                    {dateText(tl?.forecast_decision)}
                    {tl?.estimate && tl.forecast_decision && (
                      <span className="block text-xs text-content-tertiary">
                        {t('permits.ui.roadmap.estimate', { defaultValue: 'estimate' })}
                      </span>
                    )}
                  </td>
                  <td className={clsx('px-3 py-2', conflict ? 'font-medium text-semantic-error' : 'text-content-secondary')}>
                    {dateText(tl?.needed_by)}
                    {conflict && (
                      <span className="block text-xs" data-testid="row-conflict">
                        {t('permits.ui.roadmap.late_by', {
                          count: tl?.conflict_days ?? 0,
                          defaultValue_one: 'decision {{count}} day late',
                          defaultValue_other: 'decision {{count}} days late',
                        })}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
