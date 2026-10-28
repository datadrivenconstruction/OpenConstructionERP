// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ReviewSessionSummary - what a coordinator leaves a model review with.
 *
 * The session itself introduces no new stored object, on purpose: every
 * decision it lists is already persisted as BCF (a status change on a topic, a
 * comment with its author and timestamp), and the hand-over file is a `.bcfzip`
 * of exactly the walked issues, which the other side opens in their own tool.
 * What this dialog adds is the human close of the meeting - the list of what
 * was agreed, what is still open, and the two artefacts to take away: printable
 * minutes and the archive.
 *
 * The alternative we rejected was a persisted `review_session` table. It would
 * add a migration and a second source of truth for facts BCF already records,
 * and would not travel to the other side of the coordination; a session that
 * ends in an archive plus minutes does.
 */

import { useTranslation } from 'react-i18next';
import { ArrowRight, ClipboardCheck, Download, MessageSquare, Printer } from 'lucide-react';

import { Badge, Button, WideModal } from '@/shared/ui';
import { statusVariant } from '@/features/bcf/issueStatus';

import type { ReviewDecision } from './reviewMinutes';

export interface ReviewSessionSummaryProps {
  open: boolean;
  onClose: () => void;
  /** Model that was on screen during the session. */
  modelName: string | null;
  /** Localised date-time the session started. */
  heldOn: string;
  /** How many issues were on the agenda. */
  agendaSize: number;
  /** How many of them are still not closed. */
  stillOpen: number;
  /** Everything settled during the session, in the order it was settled. */
  decisions: ReviewDecision[];
  onPrintMinutes: () => void;
  onExportAgenda: () => void;
  exporting?: boolean;
}

function DecisionRow({ decision }: { decision: ReviewDecision }) {
  const changed = Boolean(decision.statusTo && decision.statusTo !== decision.statusFrom);
  return (
    <li className="flex flex-col gap-1 py-2">
      <span className="text-sm font-medium text-content-primary">{decision.title}</span>
      <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
        {changed && (
          <span className="inline-flex items-center gap-1.5">
            <Badge variant={statusVariant(decision.statusFrom ?? '')} size="sm">
              {decision.statusFrom}
            </Badge>
            <ArrowRight size={12} className="text-content-quaternary" />
            <Badge variant={statusVariant(decision.statusTo ?? '')} size="sm">
              {decision.statusTo}
            </Badge>
          </span>
        )}
        {decision.note && (
          <span className="inline-flex min-w-0 items-start gap-1.5">
            <MessageSquare size={12} className="mt-0.5 shrink-0 text-content-quaternary" />
            <span className="break-words">{decision.note}</span>
          </span>
        )}
      </div>
    </li>
  );
}

export function ReviewSessionSummary({
  open,
  onClose,
  modelName,
  heldOn,
  agendaSize,
  stillOpen,
  decisions,
  onPrintMinutes,
  onExportAgenda,
  exporting,
}: ReviewSessionSummaryProps) {
  const { t } = useTranslation();

  const tiles: { key: string; label: string; value: number; tone: 'default' | 'warning' }[] = [
    {
      key: 'agenda',
      label: t('bim.review_summary_agenda', { defaultValue: 'Issues reviewed' }),
      value: agendaSize,
      tone: 'default',
    },
    {
      key: 'decisions',
      label: t('bim.review_summary_decisions', { defaultValue: 'Decisions taken' }),
      value: decisions.length,
      tone: 'default',
    },
    {
      key: 'open',
      label: t('bim.review_summary_still_open', { defaultValue: 'Still open' }),
      value: stillOpen,
      tone: stillOpen > 0 ? 'warning' : 'default',
    },
  ];

  return (
    <WideModal
      open={open}
      onClose={onClose}
      size="lg"
      title={t('bim.review_summary_title', { defaultValue: 'Review finished' })}
      subtitle={[modelName, heldOn].filter(Boolean).join(' · ')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          <Button variant="secondary" onClick={onPrintMinutes} icon={<Printer size={16} />}>
            {t('bim.review_print_minutes', { defaultValue: 'Print minutes' })}
          </Button>
          <Button
            variant="primary"
            onClick={onExportAgenda}
            loading={exporting}
            disabled={agendaSize === 0}
            icon={<Download size={16} />}
          >
            {t('bim.review_export_agenda', { defaultValue: 'Export .bcfzip' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-2">
          {tiles.map((tile) => (
            <div
              key={tile.key}
              className="rounded-xl border border-border-light bg-surface-secondary/40 px-3 py-2.5 text-center"
            >
              <p
                className={
                  tile.tone === 'warning'
                    ? 'text-xl font-bold leading-none tabular-nums text-semantic-warning'
                    : 'text-xl font-bold leading-none tabular-nums text-content-primary'
                }
              >
                {tile.value}
              </p>
              <p className="mt-1 text-2xs uppercase tracking-wide text-content-quaternary">
                {tile.label}
              </p>
            </div>
          ))}
        </div>

        <div>
          <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            <ClipboardCheck size={13} />
            {t('bim.review_summary_decisions', { defaultValue: 'Decisions taken' })}
          </p>
          {decisions.length === 0 ? (
            <p className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-3 text-xs text-content-tertiary">
              {t('bim.review_summary_no_decisions', {
                defaultValue:
                  'Nothing was changed in this session. The archive still hands over the issues you walked.',
              })}
            </p>
          ) : (
            <ul className="divide-y divide-border-light">
              {decisions.map((decision, idx) => (
                <DecisionRow key={`${decision.guid}-${idx}`} decision={decision} />
              ))}
            </ul>
          )}
        </div>

        <p className="text-2xs leading-relaxed text-content-tertiary">
          {t('bim.review_summary_hint', {
            defaultValue:
              'Every change is already saved on the issues themselves. The minutes are a printable record of this meeting, and the .bcfzip hands the same issues to anyone using another BCF tool.',
          })}
        </p>
      </div>
    </WideModal>
  );
}

export default ReviewSessionSummary;
