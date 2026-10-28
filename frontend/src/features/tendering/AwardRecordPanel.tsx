// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The award record (Vergabevermerk) for one tender package.
 *
 * German public procurement asks the contracting authority to keep a written
 * record of the award procedure while the procedure runs, so a review body can
 * follow how the award was reached (VOB/A section 20 below the EU threshold,
 * VgV section 8 above it). Everything about the procedure is assembled by the
 * server from what the procedure already recorded, so nothing here asks the
 * reader to retype a fact the system holds. What the screen collects is only
 * what a person has to say: which procedure type was chosen and why, the award
 * criteria, the ground for excluding a bid, and why the winning bid won.
 *
 * Readable at any stage, and it says what it still owes rather than only
 * existing once an award has been made. Nothing is stored on the package until
 * somebody writes the first statement, so a package that has nothing to do with
 * public procurement is untouched by opening this.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  FileText,
  NotebookPen,
  PenLine,
} from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getAuthToken, triggerDownload } from '@/shared/lib/api';
import { fmtList, fmtCurrency, fmtDate } from '@/shared/lib/formatters';
import {
  getAwardRecord,
  recordAwardRecordNote,
  type AwardRecord,
  type AwardRecordFact,
  type AwardRecordSection,
} from './api';

interface Props {
  packageId: string;
}

/** The procedure types a German buyer picks between, by their own names. */
const PROCEDURE_CHOICES = [
  'open',
  'restricted_with_competition',
  'restricted',
  'negotiated',
  'direct',
] as const;

function useLabels() {
  const { t } = useTranslation();

  const section: Record<string, string> = {
    subject: t('tendering.award_record.section.subject', { defaultValue: 'Subject of the procurement' }),
    estimated_value: t('tendering.award_record.section.estimated_value', { defaultValue: 'Estimated value' }),
    procedure_type: t('tendering.award_record.section.procedure_type', { defaultValue: 'Type of procedure' }),
    procedure_reason: t('tendering.award_record.section.procedure_reason', {
      defaultValue: 'Reason for the type of procedure',
    }),
    evaluation_criteria: t('tendering.award_record.section.evaluation_criteria', { defaultValue: 'Award criteria' }),
    participants: t('tendering.award_record.section.participants', {
      defaultValue: 'Firms invited, and when the package went out',
    }),
    bids_received: t('tendering.award_record.section.bids_received', { defaultValue: 'Bids received' }),
    exclusions: t('tendering.award_record.section.exclusions', { defaultValue: 'Bids excluded, and on what ground' }),
    evaluation: t('tendering.award_record.section.evaluation', {
      defaultValue: 'Evaluation of the bids that remained',
    }),
    award_decision: t('tendering.award_record.section.award_decision', { defaultValue: 'Award' }),
    award_reason: t('tendering.award_record.section.award_reason', {
      defaultValue: 'Reason for the award decision',
    }),
  };

  const fact: Record<string, string> = {
    package_name: t('tendering.award_record.fact.package_name', { defaultValue: 'Tender package' }),
    project_name: t('tendering.award_record.fact.project_name', { defaultValue: 'Project' }),
    package_description: t('tendering.award_record.fact.package_description', { defaultValue: 'Description' }),
    bill_name: t('tendering.award_record.fact.bill_name', { defaultValue: 'Bill of quantities' }),
    scope_sections: t('tendering.award_record.fact.scope_sections', { defaultValue: 'Sections in scope' }),
    scope_positions: t('tendering.award_record.fact.scope_positions', { defaultValue: 'Positions in scope' }),
    bill_positions: t('tendering.award_record.fact.bill_positions', { defaultValue: 'Positions in the bill' }),
    covers_whole_bill: t('tendering.award_record.fact.covers_whole_bill', {
      defaultValue: 'Scope against the bill',
    }),
    deadline: t('tendering.award_record.fact.deadline', { defaultValue: 'Submission deadline' }),
    estimated_value: t('tendering.award_record.fact.estimated_value', { defaultValue: 'Estimated value' }),
    invited: t('tendering.award_record.fact.invited', { defaultValue: 'Invited' }),
    invited_count: t('tendering.award_record.fact.invited_count', { defaultValue: 'Firms invited' }),
    issued_at: t('tendering.award_record.fact.issued_at', { defaultValue: 'Issued' }),
    distributed_at: t('tendering.award_record.fact.distributed_at', { defaultValue: 'Sent to bidders' }),
    bid: t('tendering.award_record.fact.bid', { defaultValue: 'Bid' }),
    bid_count: t('tendering.award_record.fact.bid_count', { defaultValue: 'Bids received' }),
    bid_status: t('tendering.award_record.fact.bid_status', { defaultValue: 'Bid' }),
    excluded_count: t('tendering.award_record.fact.excluded_count', { defaultValue: 'Bids excluded' }),
    leveled_bid: t('tendering.award_record.fact.leveled_bid', { defaultValue: 'Levelled sum' }),
    leveled_lines_imputed: t('tendering.award_record.fact.leveled_lines_imputed', {
      defaultValue: 'Lines imputed during levelling',
    }),
    off_currency_excluded: t('tendering.award_record.fact.off_currency_excluded', {
      defaultValue: 'Bids left out on currency',
    }),
    awarded_to: t('tendering.award_record.fact.awarded_to', { defaultValue: 'Awarded to' }),
    awarded_sum: t('tendering.award_record.fact.awarded_sum', { defaultValue: 'Awarded sum' }),
    awarded_at: t('tendering.award_record.fact.awarded_at', { defaultValue: 'Award date' }),
    awarded_by: t('tendering.award_record.fact.awarded_by', { defaultValue: 'Awarded by' }),
  };

  // The German names are the procedures' own names, kept beside the English so
  // a buyer recognises what they are picking.
  const procedure: Record<string, string> = {
    open: t('tendering.award_record.procedure.open', {
      defaultValue: 'Open procedure (Öffentliche Ausschreibung)',
    }),
    restricted_with_competition: t('tendering.award_record.procedure.restricted_with_competition', {
      defaultValue: 'Restricted procedure with a call for competition (Beschränkte Ausschreibung mit Teilnahmewettbewerb)',
    }),
    restricted: t('tendering.award_record.procedure.restricted', {
      defaultValue: 'Restricted procedure (Beschränkte Ausschreibung)',
    }),
    negotiated: t('tendering.award_record.procedure.negotiated', {
      defaultValue: 'Negotiated procedure (Freihändige Vergabe)',
    }),
    direct: t('tendering.award_record.procedure.direct', {
      defaultValue: 'Direct award (Direktauftrag)',
    }),
  };

  // A fact carries a status as a code, so the wording lives here rather than in
  // the assembled record, which has no idea who is reading it.
  const state: Record<string, string> = {
    whole_bill: t('tendering.award_record.state.whole_bill', { defaultValue: 'The whole bill' }),
    part_of_bill: t('tendering.award_record.state.part_of_bill', { defaultValue: 'Part of the bill' }),
    pending: t('tendering.status_pending', { defaultValue: 'Pending' }),
    submitted: t('tendering.status_submitted', { defaultValue: 'Submitted' }),
    accepted: t('tendering.status_accepted', { defaultValue: 'Accepted' }),
    rejected: t('tendering.status_rejected', { defaultValue: 'Rejected' }),
    excluded: t('tendering.award_record.state.excluded', { defaultValue: 'Excluded' }),
    disqualified: t('tendering.award_record.state.disqualified', { defaultValue: 'Disqualified' }),
    withdrawn: t('tendering.award_record.state.withdrawn', { defaultValue: 'Withdrawn' }),
  };

  return { section, fact, procedure, state };
}

/** Render one assembled fact as the value the reader sees. */
function factValue(fact: AwardRecordFact, stateLabels: Record<string, string>): string {
  const parts: string[] = [];
  if (fact.text) parts.push(fact.text);
  if (fact.amount !== null && fact.amount !== '') {
    parts.push(fmtCurrency(fact.amount, fact.currency || undefined));
  }
  if (fact.count !== null) parts.push(String(fact.count));
  if (fact.at) parts.push(fmtDate(fact.at));
  if (fact.state) parts.push(stateLabels[fact.state] || fact.state);
  return fmtList(parts);
}

function StateBadge({ state }: { state: AwardRecordSection['state'] }) {
  const { t } = useTranslation();
  if (state === 'recorded') {
    return (
      <Badge variant="success" size="sm">
        {t('tendering.award_record.state_recorded', { defaultValue: 'Recorded' })}
      </Badge>
    );
  }
  if (state === 'missing') {
    return (
      <Badge variant="warning" size="sm">
        {t('tendering.award_record.state_missing', { defaultValue: 'Still open' })}
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" size="sm">
      {t('tendering.award_record.state_not_due', { defaultValue: 'Not due yet' })}
    </Badge>
  );
}

function SectionCard({
  section,
  title,
  factLabels,
  stateLabels,
  procedureLabels,
  onSave,
  saving,
}: {
  section: AwardRecordSection;
  title: string;
  factLabels: Record<string, string>;
  stateLabels: Record<string, string>;
  procedureLabels: Record<string, string>;
  onSave: (body: { section: string; text: string; value?: string }) => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [choice, setChoice] = useState(section.value || '');

  const isReasoning = section.source === 'reasoning';
  const isProcedureType = section.key === 'procedure_type';
  const fieldCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-sm font-semibold text-content-primary">{title}</h4>
        <div className="flex shrink-0 items-center gap-2">
          <StateBadge state={section.state} />
          {isReasoning && !editing && (
            <Button
              variant="ghost"
              size="sm"
              icon={<PenLine size={14} />}
              onClick={() => {
                setText('');
                setChoice(section.value || '');
                setEditing(true);
              }}
            >
              {section.statement
                ? t('tendering.award_record.update_button', { defaultValue: 'Add a newer statement' })
                : t('tendering.award_record.record_button', { defaultValue: 'Record' })}
            </Button>
          )}
        </div>
      </div>

      {section.facts.length > 0 && (
        <dl className="mt-3 divide-y divide-border-light rounded-lg border border-border-light">
          {section.facts.map((fact, index) => (
            <div key={`${fact.key}-${index}`} className="flex items-baseline gap-3 px-3 py-2">
              <dt className="w-56 shrink-0 text-xs text-content-secondary">
                {factLabels[fact.key] || fact.key}
              </dt>
              <dd className="min-w-0 flex-1 text-sm text-content-primary">{factValue(fact, stateLabels)}</dd>
            </div>
          ))}
        </dl>
      )}

      {/* A section assembled from the procedure that has nothing to show says
          why, rather than leaving the reader with an empty card. */}
      {!isReasoning && section.facts.length === 0 && (
        <p className="mt-3 text-sm text-content-tertiary">
          {section.state === 'missing'
            ? t('tendering.award_record.state_missing_procedure', {
                defaultValue: 'The procedure has reached this stage and nothing here is on record for it.',
              })
            : t('tendering.award_record.state_not_due_hint', {
                defaultValue: 'The procedure has not reached this stage.',
              })}
        </p>
      )}

      {isReasoning && (
        <div className="mt-3">
          {section.statement ? (
            <>
              {isProcedureType && section.value && (
                <p className="text-sm font-medium text-content-primary">
                  {procedureLabels[section.value] || section.value}
                </p>
              )}
              <p className="whitespace-pre-wrap text-sm text-content-primary">{section.statement}</p>
              {section.recorded_at && (
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('tendering.award_record.recorded_at', {
                    defaultValue: 'Recorded {{date}}',
                    date: fmtDate(section.recorded_at),
                  })}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-content-tertiary">
              {section.state === 'missing'
                ? t('tendering.award_record.state_missing_hint', {
                    defaultValue: 'The procedure has reached the point where this has to be stated, and it is not stated yet.',
                  })
                : t('tendering.award_record.state_not_due_hint', {
                    defaultValue: 'The procedure has not reached this stage.',
                  })}
            </p>
          )}

          {section.superseded.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-content-tertiary">
                {t('tendering.award_record.superseded_count', {
                  defaultValue: '{{count}} earlier statement(s)',
                  count: section.superseded.length,
                })}
              </summary>
              <div className="mt-2 space-y-2 border-l-2 border-border-light pl-3">
                {section.superseded.map((earlier, index) => (
                  <div key={index}>
                    <p className="whitespace-pre-wrap text-xs text-content-secondary">{earlier.text}</p>
                    {earlier.recorded_at && (
                      <p className="text-xs text-content-tertiary">
                        {t('tendering.award_record.superseded_at', {
                          defaultValue: 'Superseded, written {{date}}',
                          date: fmtDate(earlier.recorded_at),
                        })}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          {editing && (
            <div className="mt-3 space-y-2">
              {isProcedureType && (
                <select
                  value={choice}
                  onChange={(e) => setChoice(e.target.value)}
                  className={fieldCls}
                  aria-label={t('tendering.award_record.procedure_choice', { defaultValue: 'Type of procedure' })}
                >
                  <option value="">
                    {t('tendering.award_record.procedure_choose', { defaultValue: 'Choose the procedure type' })}
                  </option>
                  {PROCEDURE_CHOICES.map((code) => (
                    <option key={code} value={code}>
                      {procedureLabels[code]}
                    </option>
                  ))}
                </select>
              )}
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={4}
                maxLength={10000}
                placeholder={t('tendering.award_record.placeholder', {
                  defaultValue:
                    'Write the reasoning as it stands today. Recording a newer statement keeps the earlier ones rather than replacing them.',
                })}
                className="w-full resize-none rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary transition-all focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  loading={saving}
                  disabled={!text.trim() && !choice.trim()}
                  onClick={() => {
                    onSave({ section: section.key, text: text.trim(), value: choice.trim() || undefined });
                    setEditing(false);
                  }}
                >
                  {t('tendering.award_record.save', { defaultValue: 'Save statement' })}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                  {t('common.cancel', 'Cancel')}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export function AwardRecordPanel({ packageId }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const labels = useLabels();

  const recordQ = useQuery({
    queryKey: ['tendering-award-record', packageId],
    queryFn: () => getAwardRecord(packageId),
  });

  const saveMutation = useMutation({
    mutationFn: (body: { section: string; text: string; value?: string }) =>
      recordAwardRecordNote(packageId, body),
    onSuccess: (updated: AwardRecord) => {
      queryClient.setQueryData(['tendering-award-record', packageId], updated);
      queryClient.invalidateQueries({ queryKey: ['tendering-package', packageId] });
      addToast({
        type: 'success',
        title: t('tendering.award_record.saved', { defaultValue: 'Statement recorded' }),
      });
    },
    onError: (error: Error) => {
      addToast({ type: 'error', title: t('toasts.error', { defaultValue: 'Error' }), message: error.message });
    },
  });

  // Authenticated download, the same way the tender summary and the decision
  // letters are fetched: the token lives in localStorage, not in a cookie.
  const handleDownload = async () => {
    try {
      const token = getAuthToken();
      const response = await fetch(`/api/v1/tendering/packages/${packageId}/award-record/pdf/`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) {
        addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
        return;
      }
      const blob = await response.blob();
      const name = (recordQ.data?.package_name || 'tender').replace(/[^a-z0-9_-]+/gi, '_');
      triggerDownload(blob, `award_record_${name}.pdf`);
    } catch {
      addToast({ type: 'error', title: t('tendering.export_failed', { defaultValue: 'Export failed' }) });
    }
  };

  if (recordQ.isLoading) {
    return <SkeletonTable rows={5} columns={2} />;
  }

  if (recordQ.isError || !recordQ.data) {
    return (
      <Card className="py-12">
        <EmptyState
          icon={<AlertTriangle size={28} strokeWidth={1.5} />}
          title={t('common.error', { defaultValue: 'Error' })}
          description={t('tendering.award_record.load_error', {
            defaultValue: 'Failed to load the award record. Please try again.',
          })}
        />
      </Card>
    );
  }

  const record = recordQ.data;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
              <NotebookPen size={16} className="text-oe-blue" />
              {t('tendering.award_record.title', { defaultValue: 'Award record' })}
            </h4>
            <p className="mt-1 text-xs text-content-secondary">
              {t('tendering.award_record.intro', {
                defaultValue:
                  'German public procurement asks the buyer to keep a written record of the award procedure while it runs, so that a review body can follow how the award was reached (Vergabevermerk, VOB/A section 20 and VgV section 8). This one is assembled from the procedure itself: the scope, the firms invited, the bids, the levelling and the award. Only the reasoning is yours to write.',
              })}
            </p>
            {!record.started && (
              <p className="mt-1 text-xs text-content-tertiary">
                {t('tendering.award_record.opt_in', {
                  defaultValue:
                    'Nothing is stored on this package until you write the first statement, so a package this does not apply to is left exactly as it is.',
                })}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              icon={<FileText size={14} />}
              onClick={handleDownload}
              title={t('tendering.award_record.download_title', {
                defaultValue: 'Download the award record as a PDF for filing',
              })}
            >
              {t('tendering.award_record.download', { defaultValue: 'PDF' })}
            </Button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          {record.is_complete ? (
            <span className="flex items-center gap-1 text-semantic-success">
              <CheckCircle2 size={14} />
              {t('tendering.award_record.complete', { defaultValue: 'Complete for this stage' })}
            </span>
          ) : (
            <span className="flex items-center gap-1 text-content-secondary">
              <Circle size={14} />
              {t('tendering.award_record.open_points', {
                defaultValue: '{{count}} point(s) still open at this stage',
                count: record.gaps.length,
              })}
            </span>
          )}
          {record.gaps.map((gap) => (
            <Badge key={gap.section} variant="warning" size="sm">
              {labels.section[gap.section] || gap.section}
            </Badge>
          ))}
        </div>
      </Card>

      {record.sections.map((section) => (
        <SectionCard
          key={section.key}
          section={section}
          title={labels.section[section.key] || section.key}
          factLabels={labels.fact}
          stateLabels={labels.state}
          procedureLabels={labels.procedure}
          onSave={(body) => saveMutation.mutate(body)}
          saving={saveMutation.isPending}
        />
      ))}
    </div>
  );
}
