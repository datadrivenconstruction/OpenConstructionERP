// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a commitment is tied to in the other registers of the project, as a
// row of named chips: the task that delivers it, the risk if it is not kept,
// the requirement it puts on the works and the budget release that pays for
// it. A chip opens the record where its module has a page for one; the names
// are read only when some commitment in the list carries such a link.

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import type { Commitment } from './api';
import type { TickOption } from './StakeholderBits';
import type { KeyText, TFn } from './labels';
import { useReleaseItemOptions, useRequirementOptions, useRiskOptions, useTaskOptions } from './links';

export type CommitmentLinkKind = 'task' | 'risk' | 'requirement' | 'release';

export const COMMITMENT_LINK: Record<CommitmentLinkKind, KeyText> = {
  task: ['stakeholders.ui.chip.task', 'Task: {{name}}'],
  risk: ['stakeholders.ui.chip.risk', 'Risk: {{name}}'],
  requirement: ['stakeholders.ui.chip.requirement', 'Requirement: {{name}}'],
  release: ['stakeholders.ui.chip.release', 'Budget release: {{name}}'],
};

const FIELD: Record<CommitmentLinkKind, 'task_id' | 'risk_id' | 'requirement_id' | 'release_item_id'> = {
  task: 'task_id',
  risk: 'risk_id',
  requirement: 'requirement_id',
  release: 'release_item_id',
};

const KINDS: CommitmentLinkKind[] = ['task', 'risk', 'requirement', 'release'];

/** Where a linked record opens, or null when its module has no page for a single record. */
export function linkTarget(kind: CommitmentLinkKind, projectId: string, id: string): string | null {
  if (kind === 'task') return `/projects/${projectId}/tasks?id=${id}`;
  if (kind === 'risk') return `/risks?id=${id}`;
  return null;
}

export type LinkNames = Record<CommitmentLinkKind, TickOption[]>;

/** The names of the linked records, each list asked for only when a commitment points into it. */
export function useCommitmentLinkNames(projectId: string, commitments: readonly Commitment[]): LinkNames {
  const { t } = useTranslation();
  const has = (kind: CommitmentLinkKind) => commitments.some((c) => !!c[FIELD[kind]]);
  return {
    task: useTaskOptions(projectId, t as TFn, has('task')).options,
    risk: useRiskOptions(projectId, t as TFn, has('risk')).options,
    requirement: useRequirementOptions(projectId, t as TFn, has('requirement')).options,
    release: useReleaseItemOptions(projectId, t as TFn, has('release')).options,
  };
}

const CHIP_CLASS = 'inline-flex max-w-full items-center rounded-full border border-border-light px-2 py-0.5 text-2xs text-content-secondary';

export function CommitmentLinks({ projectId, commitment, names }: { projectId: string; commitment: Commitment; names: LinkNames }) {
  const { t } = useTranslation();
  const linked = KINDS.filter((kind) => !!commitment[FIELD[kind]]);
  if (linked.length === 0) return null;
  return (
    <ul className="mt-1.5 flex flex-wrap gap-1.5" data-testid="commitment-links">
      {linked.map((kind) => {
        const id = commitment[FIELD[kind]] as string;
        // A record the list does not hold (a longer register, a module that is off) is still named as linked.
        const name =
          names[kind].find((o) => o.id === id)?.label ?? t('stakeholders.ui.chip.unnamed', { defaultValue: 'linked record' });
        const text = t(COMMITMENT_LINK[kind][0], { defaultValue: COMMITMENT_LINK[kind][1], name });
        const to = linkTarget(kind, projectId, id);
        return (
          <li key={kind} className="min-w-0" data-testid={`commitment-link-${kind}`}>
            {to ? (
              <Link to={to} className={`${CHIP_CLASS} hover:border-oe-blue hover:text-oe-blue-text`}>
                <span className="truncate">{text}</span>
              </Link>
            ) : (
              <span className={CHIP_CLASS}>
                <span className="truncate">{text}</span>
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
