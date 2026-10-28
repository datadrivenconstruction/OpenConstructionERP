// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Areas down, phases across. Each cell says which frame documents the area
// owes at the gate that closes the phase, in what state they are, and how
// ready the area is. Above it, the next gate and how many blockers stand in
// its way.

import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowRight, CheckCircle2, Flag } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { fmtDate } from '@/shared/lib/formatters';

import type { GovernanceGate } from './api';
import {
  CHECK_STATUS,
  DOCUMENT_STATUS,
  GATE_STATUS,
  OUTCOME,
  catalogueName,
  vocab,
  type LabelContext,
} from './labels';
import type { GovernanceMatrixData, MatrixCell } from './matrix';
import { CHECK_TONE, GATE_STATUS_TONE, OUTCOME_TONE, PersonChip, ToneBadge } from './GovernanceBits';

export interface GovernanceMatrixProps {
  data: GovernanceMatrixData;
  catalogueId: string;
  next: GovernanceGate | null;
  /** Blockers on the next gate, counted by the server. */
  blockerCount: number;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onOpenGate: (gateId: string) => void;
  onOpenArea: (areaId: string) => void;
}

export function NextGateBanner({
  next,
  blockerCount,
  catalogueId,
  labels,
  onOpen,
}: {
  next: GovernanceGate | null;
  blockerCount: number;
  catalogueId: string;
  labels: LabelContext;
  onOpen: (gateId: string) => void;
}) {
  const { t } = useTranslation();
  if (!next) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary px-4 py-3 text-sm text-content-secondary">
        <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />
        {t('governance.project.matrix.all_gates_decided', {
          defaultValue: 'Every gate of this phase model is decided.',
        })}
      </div>
    );
  }
  const blockers = blockerCount;
  const gateName = catalogueName(labels, {
    kind: 'gate',
    code: next.code,
    catalogueId,
    label: next.name,
  });
  return (
    <div
      data-testid="next-gate-banner"
      className={clsx(
        'flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3',
        blockers > 0
          ? 'border-semantic-warning/40 bg-semantic-warning-bg'
          : 'border-oe-blue/30 bg-oe-blue-subtle',
      )}
    >
      <Flag size={16} className="shrink-0 text-content-secondary" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-content-tertiary">
          {t('governance.project.matrix.next_gate', { defaultValue: 'Next gate' })}
        </p>
        <p className="truncate text-sm font-semibold text-content-primary">{gateName}</p>
      </div>
      <ToneBadge tone={GATE_STATUS_TONE[next.status]}>{vocab(t, GATE_STATUS, next.status)}</ToneBadge>
      {next.target_date && (
        <span className="text-xs text-content-secondary">
          {t('governance.project.matrix.planned_on', {
            defaultValue: 'Planned {{date}}',
            date: fmtDate(next.target_date),
          })}
        </span>
      )}
      <span
        data-testid="next-gate-blockers"
        className={clsx(
          'inline-flex items-center gap-1 text-xs font-medium',
          blockers > 0 ? 'text-[#b45309]' : 'text-semantic-success',
        )}
      >
        {blockers > 0 ? <AlertTriangle size={13} aria-hidden /> : <CheckCircle2 size={13} aria-hidden />}
        {blockers > 0
          ? t('governance.project.matrix.blockers', { defaultValue: '{{count}} blockers', count: blockers })
          : t('governance.project.matrix.no_blockers', { defaultValue: 'No blockers' })}
      </span>
      <Button size="sm" variant="secondary" icon={<ArrowRight size={14} />} iconPosition="right" onClick={() => onOpen(next.id)}>
        {t('governance.project.matrix.open_gate', { defaultValue: 'Open gate' })}
      </Button>
    </div>
  );
}

function Cell({
  cell,
  labels,
  catalogueId,
  gated,
}: {
  cell: MatrixCell;
  labels: LabelContext;
  catalogueId: string;
  gated: boolean;
}) {
  const { t } = useTranslation();
  const r = cell.readiness;
  return (
    <div className="flex min-h-[3.25rem] flex-col gap-1">
      {r.kind === 'decided' && r.outcome && (
        <ToneBadge tone={OUTCOME_TONE[r.outcome]} testId="cell-outcome">
          {vocab(t, OUTCOME, r.outcome)}
        </ToneBadge>
      )}
      {r.kind === 'check' && (
        <ToneBadge tone={r.stale ? 'warning' : CHECK_TONE[r.status]} testId="cell-check">
          {r.stale
            ? t('governance.project.check_stale', { defaultValue: 'Confirm again' })
            : vocab(t, CHECK_STATUS, r.status)}
        </ToneBadge>
      )}
      {cell.documents.map((d) => (
        <span key={d.id} className="flex items-center gap-1 text-2xs text-content-secondary" data-testid="cell-document">
          <span
            className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', {
              'bg-semantic-success': d.status === 'binding' || d.status === 'approved_at_gate',
              'bg-oe-blue': d.status === 'in_review',
              'bg-content-tertiary': d.status === 'draft' || d.status === 'superseded',
            })}
            aria-hidden
          />
          <span className="truncate" title={vocab(t, DOCUMENT_STATUS, d.status)}>
            {catalogueName(labels, { kind: 'doc', code: d.docType, catalogueId, label: d.name })}
          </span>
          <span className="sr-only">{vocab(t, DOCUMENT_STATUS, d.status)}</span>
        </span>
      ))}
      {/* A column without a gate says so once in its header; its cells stay empty. Every other cell that
          carries neither a badge nor a document shows the same dash. */}
      {gated && r.kind !== 'check' && !(r.kind === 'decided' && r.outcome) && cell.documents.length === 0 && (
        <span className="text-2xs text-content-quaternary">-</span>
      )}
    </div>
  );
}

export function GovernanceMatrix({
  data,
  catalogueId,
  next,
  blockerCount,
  labels,
  personName,
  onOpenGate,
  onOpenArea,
}: GovernanceMatrixProps) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <NextGateBanner
        next={next}
        blockerCount={blockerCount}
        catalogueId={catalogueId}
        labels={labels}
        onOpen={onOpenGate}
      />
      <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
        <table className="w-full min-w-[720px] border-collapse text-left" data-testid="governance-matrix">
          <thead>
            <tr className="bg-surface-secondary">
              <th scope="col" className="sticky left-0 z-10 w-56 bg-surface-secondary px-3 py-2 text-xs font-semibold text-content-secondary">
                {t('governance.project.matrix.area_column', { defaultValue: 'Management area' })}
              </th>
              {data.columns.map((col) => (
                <th
                  key={col.phase.code}
                  scope="col"
                  className={clsx(
                    'min-w-[9rem] px-3 py-2 align-bottom text-xs font-semibold',
                    col.isCurrent ? 'bg-oe-blue-subtle text-oe-blue-text' : 'text-content-secondary',
                  )}
                >
                  <span className="block">
                    {catalogueName(labels, { kind: 'phase', code: col.phase.code, catalogueId, label: col.phase.name })}
                  </span>
                  {col.isCurrent && (
                    <span className="text-2xs font-normal">
                      {t('governance.project.matrix.current_phase', { defaultValue: 'Current phase' })}
                    </span>
                  )}
                  {!col.gate && (
                    <span className="mt-1 block text-2xs font-normal text-content-tertiary" data-testid="column-no-gate">
                      {t('governance.project.matrix.no_gate', { defaultValue: 'No gate in this phase' })}
                    </span>
                  )}
                  {col.gate && (
                    <button
                      type="button"
                      onClick={() => onOpenGate(col.gate!.id)}
                      className="mt-1 block text-2xs font-normal text-oe-blue hover:underline"
                    >
                      {vocab(t, GATE_STATUS, col.gate.status)}
                    </button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => {
              const owner = personName(row.area.owner_user_id);
              const name = catalogueName(labels, {
                kind: 'area',
                code: row.area.code,
                catalogueId,
                label: row.area.name,
                override: row.area.name_override,
              });
              return (
                <tr key={row.area.area_id} className="border-t border-border-light align-top" data-testid="matrix-row">
                  <th scope="row" className="sticky left-0 z-10 bg-surface-primary px-3 py-2 text-left font-normal">
                    <button
                      type="button"
                      onClick={() => onOpenArea(row.area.area_id)}
                      className="block text-sm font-medium text-content-primary hover:text-oe-blue"
                    >
                      {name}
                    </button>
                    <div className="mt-1">
                      {row.area.applicable ? (
                        <PersonChip name={row.area.owner_user_id ? owner ?? t('governance.project.unknown_person', { defaultValue: 'Project member' }) : null} />
                      ) : (
                        <span className="text-xs text-content-tertiary">
                          {t('governance.project.not_applicable', { defaultValue: 'Not applicable' })}
                        </span>
                      )}
                    </div>
                  </th>
                  {row.cells.map((cell, i) => (
                    <td
                      key={data.columns[i]!.phase.code}
                      className={clsx('px-3 py-2', data.columns[i]!.isCurrent && 'bg-oe-blue-subtle/40')}
                    >
                      <Cell cell={cell} labels={labels} catalogueId={catalogueId} gated={!!data.columns[i]!.gate} />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
