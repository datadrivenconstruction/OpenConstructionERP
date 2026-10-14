// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One personnel file: who the person is on the project, the documents the
// roles require and where each stands, travel, leave, the booked
// accommodation, and the retention controls (end, hold, erase).
//
// The server decides who may open the file and who may change it (the `can` flags of the file).
// Opening is logged, so the file is fetched once and the access log is loaded
// only when the reader asks for it.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft, Pencil, Plus, ShieldAlert, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { fmtDate, fmtList, formatDateValue } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';

import {
  deleteLeave,
  deleteTravel,
  downloadOwnFile,
  eraseFile,
  holdFile,
  releaseFile,
  setLeaveStatus,
  setTravelStatus,
  staffingErrorCode,
  staffingForbidden,
  verifyDocument,
  waiveDocument,
  type FileDocument,
  type LeaveRecord,
  type LeaveStatus,
  type StaffingCatalogue,
  type TravelRecord,
  type TravelStatus,
} from './api';
import { DocumentDialog, EndFileDialog, FileHeaderDialog, LeaveDialog, TravelDialog } from './FileDialogs';
import { useAccessLog, useInvalidateFile, usePersonnelFile } from './hooks';
import {
  ACCESS_ACTION,
  DOCUMENT_STATUS,
  EMPLOYMENT_BASIS,
  FILE_STATUS,
  FIT,
  LAWFUL_BASIS,
  LEAVE_STATUS,
  TRAVEL_KIND,
  TRAVEL_STATUS,
  catalogueName,
  findingText,
  humanizeCode,
  refusalText,
  vocab,
  offered,
  whyNot,
  type LabelContext,
} from './labels';
import { FindingList } from './PlanPanel';
import { nextLeaveStatuses, nextTravelStatuses } from './rules';
import {
  ClearedBadge,
  ExportButtons,
  FILE_TONE,
  LEAVE_TONE,
  ReasonDialog,
  Refusal,
  TRAVEL_TONE,
  ToneBadge,
  personLabel,
  useStaffingAction,
} from './StaffingBits';

export interface PersonnelFilePanelProps {
  projectId: string;
  fileId: string;
  catalogue: StaffingCatalogue | null;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onBack: () => void;
}

type Dialog =
  | { kind: 'header' }
  | { kind: 'end' }
  | { kind: 'hold' }
  | { kind: 'erase' }
  | { kind: 'document'; document: FileDocument }
  | { kind: 'waive'; document: FileDocument }
  | { kind: 'travel'; travel: TravelRecord | null }
  | { kind: 'leave'; leave: LeaveRecord | null }
  | null;

/** A document's state in one word: waived, missing, or the validity the server reports for it. */
function documentState(doc: FileDocument): { tone: 'success' | 'warning' | 'error' | 'purple' | 'neutral'; key: 'waived' | 'missing' | 'not_required' | 'status' } {
  if (doc.waived) return { tone: 'purple', key: 'waived' };
  if (!doc.status) return doc.required ? { tone: 'error', key: 'missing' } : { tone: 'neutral', key: 'not_required' };
  if (doc.status === 'active') return { tone: 'success', key: 'status' };
  if (doc.status === 'expiring_soon') return { tone: 'warning', key: 'status' };
  return { tone: 'error', key: 'status' };
}

function Section({ title, action, children, testId }: { title: string; action?: ReactNode; children: ReactNode; testId: string }) {
  return (
    <section className="space-y-2" data-testid={testId}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-base font-semibold text-content-primary">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Quiet({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="rounded-lg border border-dashed border-border-light px-4 py-4 text-sm text-content-secondary" data-testid={testId}>
      {children}
    </p>
  );
}

export function PersonnelFilePanel({ projectId, fileId, catalogue, labels, personName, onBack }: PersonnelFilePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const fileQ = usePersonnelFile(projectId, fileId);
  const reload = useInvalidateFile(projectId, fileId);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [showLog, setShowLog] = useState(false);
  const logQ = useAccessLog(projectId, fileId, showLog);

  const verify = useStaffingAction((documentId: string) => verifyDocument(projectId, fileId, documentId), () => void reload());
  const release = useStaffingAction(() => releaseFile(projectId, fileId), () => void reload());
  const travelStatus = useStaffingAction(
    (a: { id: string; status: TravelStatus }) => setTravelStatus(projectId, fileId, a.id, a.status),
    () => void reload(),
  );
  const travelRemove = useStaffingAction((id: string) => deleteTravel(projectId, fileId, id), () => void reload());
  const leaveStatus = useStaffingAction(
    (a: { id: string; status: Exclude<LeaveStatus, 'requested'> }) => setLeaveStatus(projectId, fileId, a.id, a.status),
    () => void reload(),
  );
  const leaveRemove = useStaffingAction((id: string) => deleteLeave(projectId, fileId, id), () => void reload());

  const back = (
    <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} className="rtl:rotate-180" />} onClick={onBack} data-testid="file-back">
      {t('staffing.people.back', { defaultValue: 'All people' })}
    </Button>
  );

  if (fileQ.isLoading) {
    return (
      <div className="space-y-4">
        {back}
        <SkeletonTable rows={5} columns={4} />
      </div>
    );
  }
  if (fileQ.isError || !fileQ.data) {
    const denied = staffingForbidden(fileQ.error);
    return (
      <div className="space-y-4" data-testid={denied ? 'file-denied' : 'file-error'}>
        {back}
        <ErrorState
          title={
            denied
              ? t('staffing.file.no_access', { defaultValue: 'You cannot open this file.' })
              : t('staffing.file.load_failed', { defaultValue: 'The personnel file could not be loaded' })
          }
          hint={
            denied
              ? staffingErrorCode(fileQ.error)
                ? refusalText(labels.t, fileQ.error)
                : t('staffing.file.no_access_hint', {
                    defaultValue: 'A personnel file opens for the owner of the personnel area, the line manager of the position and the person concerned.',
                  })
              : refusalText(labels.t, fileQ.error)
          }
          onRetry={denied ? undefined : () => fileQ.refetch()}
        />
      </div>
    );
  }

  const file = fileQ.data;
  const anonymised = file.status === 'anonymised';
  // Every button below follows a flag the server computed with the function that enforces it.
  const editable = file.can.edit.allowed;
  const fieldRow = (label: string, value: ReactNode) => (
    <div className="flex gap-1.5">
      <dt className="text-content-tertiary">{label}</dt>
      <dd className="text-content-primary">{value}</dd>
    </div>
  );

  return (
    <div className="space-y-5" data-testid="personnel-file">
      {back}

      <section className="rounded-lg border border-border-light p-4" data-testid="file-header">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">{personLabel(labels.t, file.name)}</h2>
              <ToneBadge tone={FILE_TONE[file.status]} testId="file-status">
                {vocab(t, FILE_STATUS, file.status)}
              </ToneBadge>
              {!anonymised && <ClearedBadge cleared={file.cleared_to_work} />}
            </div>
            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              {file.roles.length > 0 &&
                fieldRow(
                  t('staffing.people.roles', { defaultValue: 'Roles' }),
                  fmtList(file.roles.map((r) => catalogueName(labels, catalogue, 'role', r))),
                )}
              {file.start &&
                fieldRow(
                  t('staffing.position.period', { defaultValue: 'Period' }),
                  file.end
                    ? t('staffing.period_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(file.start), to: fmtDate(file.end) })
                    : t('staffing.period_from', { defaultValue: 'From {{from}}', from: fmtDate(file.start) }),
                )}
              {file.employer_organisation && fieldRow(t('staffing.file.employer', { defaultValue: 'Employer' }), file.employer_organisation)}
              {fieldRow(t('staffing.file.employment_basis', { defaultValue: 'Employment basis' }), vocab(t, EMPLOYMENT_BASIS, file.employment_basis))}
              {fieldRow(t('staffing.file.lawful_basis', { defaultValue: 'Lawful basis' }), vocab(t, LAWFUL_BASIS, file.lawful_basis))}
              {file.retention_due_at &&
                fieldRow(t('staffing.file.retention_due', { defaultValue: 'Data deleted on' }), fmtDate(file.retention_due_at))}
            </dl>
            {file.status === 'retention_hold' && file.hold_rationale && (
              <p className="text-sm text-content-secondary" data-testid="file-hold-reason">
                {t('staffing.file.hold_reason', { defaultValue: 'On hold because: {{reason}}', reason: file.hold_rationale })}
              </p>
            )}
            {anonymised && (
              <p className="text-sm text-content-secondary" role="status" data-testid="file-anonymised">
                {t('staffing.file.anonymised_hint', {
                  defaultValue: 'The personal data of this file was erased. Only the record that the assignment existed remains.',
                })}
              </p>
            )}
            {!editable && !anonymised && (
              <p className="text-xs text-content-tertiary" role="status" data-testid="file-read-only">
                {whyNot(labels.t, file.can.edit) ||
                  t('staffing.file.read_only', { defaultValue: 'You can read this file but not change it.' })}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            {editable && (
              <Button variant="ghost" size="sm" icon={<Pencil size={14} />} onClick={() => setDialog({ kind: 'header' })} data-testid="file-edit">
                {t('common.edit', { defaultValue: 'Edit' })}
              </Button>
            )}
            <Refusal text={offered(file.can.end) ? whyNot(labels.t, file.can.end) : ''} testId="file-end-refused" />
            {offered(file.can.end) && (
              <Button variant="secondary" size="sm" disabled={!file.can.end.allowed} onClick={() => setDialog({ kind: 'end' })} data-testid="file-end">
                {t('staffing.file.end', { defaultValue: 'End assignment' })}
              </Button>
            )}
            <Refusal text={offered(file.can.hold) ? whyNot(labels.t, file.can.hold) : ''} testId="file-hold-refused" />
            {offered(file.can.hold) && (
              <Button variant="ghost" size="sm" disabled={!file.can.hold.allowed} onClick={() => setDialog({ kind: 'hold' })} data-testid="file-hold">
                {t('staffing.file.hold', { defaultValue: 'Place hold' })}
              </Button>
            )}
            <Refusal text={offered(file.can.release) ? whyNot(labels.t, file.can.release) : ''} testId="file-release-refused" />
            {offered(file.can.release) && (
              <Button
                variant="secondary"
                size="sm"
                loading={release.isPending}
                disabled={!file.can.release.allowed}
                onClick={() => release.mutate()}
                data-testid="file-release"
              >
                {t('staffing.file.release', { defaultValue: 'Release hold' })}
              </Button>
            )}
          </div>
        </div>
      </section>

      {file.warnings.length > 0 && (
        <section className="rounded-lg bg-surface-secondary p-3" data-testid="file-warnings">
          <h2 className="mb-1.5 text-sm font-medium text-content-primary">{t('staffing.file.warnings', { defaultValue: 'To check' })}</h2>
          <FindingList findings={file.warnings} catalogue={catalogue} labels={labels} />
        </section>
      )}

      {!anonymised && (
        <>
          <Section title={t('staffing.document.heading', { defaultValue: 'Documents' })} testId="file-documents">
            {file.documents.length === 0 ? (
              <Quiet testId="documents-empty">
                {t('staffing.document.empty', {
                  defaultValue: 'No document is required yet. The documents appear as soon as the person is put on a position, because the role decides what is needed.',
                })}
              </Quiet>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border-light">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                      <th scope="col" className="px-3 py-2 font-medium">{t('staffing.document.kind', { defaultValue: 'Document' })}</th>
                      <th scope="col" className="px-3 py-2 font-medium">{t('staffing.position.status', { defaultValue: 'Status' })}</th>
                      <th scope="col" className="px-3 py-2 font-medium">{t('staffing.document.valid_until', { defaultValue: 'Valid until' })}</th>
                      <th scope="col" className="px-3 py-2 font-medium">{t('staffing.document.checked', { defaultValue: 'Checked' })}</th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        <span className="sr-only">{t('staffing.actions', { defaultValue: 'Actions' })}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {file.documents.map((d) => {
                      const state = documentState(d);
                      const checker = personName(d.verified_by);
                      return (
                        <tr key={d.document_kind} className="border-b border-border-light align-top last:border-b-0" data-testid="document-row">
                          <td className="px-3 py-2">
                            <div className="font-medium text-content-primary">{catalogueName(labels, catalogue, 'document_kind', d.document_kind)}</div>
                            <div className="text-xs text-content-tertiary">
                              {d.required
                                ? t('staffing.document.required', { defaultValue: 'Required for the role' })
                                : t('staffing.document.optional', { defaultValue: 'Not required' })}
                              {d.number_last4 && (
                                <span className="ml-2" data-testid="document-last4-shown">
                                  {t('staffing.document.number_ending', { defaultValue: 'Number ending {{last4}}', last4: d.number_last4 })}
                                </span>
                              )}
                            </div>
                            {d.waived && d.waiver_rationale && (
                              <div className="text-xs text-content-secondary">
                                {t('staffing.document.waived_because', { defaultValue: 'Waived because: {{reason}}', reason: d.waiver_rationale })}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <ToneBadge tone={state.tone} testId="document-state">
                              {state.key === 'status'
                                ? vocab(t, DOCUMENT_STATUS, d.status ?? '')
                                : state.key === 'waived'
                                  ? t('staffing.cell.waived', { defaultValue: 'Waived' })
                                  : state.key === 'missing'
                                    ? t('staffing.cell.missing', { defaultValue: 'Missing' })
                                    : t('staffing.cell.not_required', { defaultValue: 'Not required' })}
                            </ToneBadge>
                            {d.fit_for_role && <div className="mt-1 text-xs text-content-secondary">{vocab(t, FIT, d.fit_for_role)}</div>}
                          </td>
                          <td className="px-3 py-2 text-content-secondary">
                            {d.valid_until
                              ? fmtDate(d.valid_until)
                              : d.status
                                ? t('staffing.document.no_end', { defaultValue: 'No end date' })
                                : ''}
                          </td>
                          <td className="px-3 py-2 text-content-secondary">
                            {d.verified_at
                              ? checker
                                ? t('staffing.document.checked_by', { defaultValue: '{{date}} by {{name}}', date: fmtDate(d.verified_at), name: checker })
                                : fmtDate(d.verified_at)
                              : t('staffing.document.not_checked', { defaultValue: 'Not checked' })}
                          </td>
                          <td className="px-3 py-2">
                            {editable && d.status && !d.verified_at && !d.can.verify.allowed && (
                              <p className="mb-1 text-right text-xs text-content-tertiary" data-testid="document-verify-refused">
                                {whyNot(labels.t, d.can.verify)}
                              </p>
                            )}
                            {editable && (
                              <div className="flex flex-wrap justify-end gap-1">
                                <Button variant="ghost" size="sm" onClick={() => setDialog({ kind: 'document', document: d })} data-testid="document-link">
                                  {d.status
                                    ? t('staffing.document.update', { defaultValue: 'Update document' })
                                    : t('staffing.document.record', { defaultValue: 'Record document' })}
                                </Button>
                                {d.id && offered(d.can.verify) && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    disabled={!d.can.verify.allowed}
                                    onClick={() => verify.mutate(d.id as string)}
                                    data-testid="document-verify"
                                  >
                                    {t('staffing.document.verify', { defaultValue: 'Mark as checked' })}
                                  </Button>
                                )}
                                {d.required && !d.waived && !d.status && (
                                  <Button variant="ghost" size="sm" onClick={() => setDialog({ kind: 'waive', document: d })} data-testid="document-waive">
                                    {t('staffing.document.waive', { defaultValue: 'Waive' })}
                                  </Button>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          <Section
            title={t('staffing.travel.heading', { defaultValue: 'Travel' })}
            testId="file-travel"
            action={
              editable && (
                <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'travel', travel: null })} data-testid="add-travel">
                  {t('staffing.travel.add', { defaultValue: 'Add trip' })}
                </Button>
              )
            }
          >
            {file.travel.length === 0 ? (
              <Quiet testId="travel-empty">
                {t('staffing.travel.empty', { defaultValue: 'No trip is planned. Add the mobilisation to site, rotations and the trip home.' })}
              </Quiet>
            ) : (
              <ul className="space-y-2">
                {file.travel.map((tr) => (
                  <li key={tr.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light p-3 text-sm" data-testid="travel-row">
                    <span className="font-medium text-content-primary">{vocab(t, TRAVEL_KIND, tr.kind)}</span>
                    <ToneBadge tone={TRAVEL_TONE[tr.status]}>{vocab(t, TRAVEL_STATUS, tr.status)}</ToneBadge>
                    <span className="text-content-secondary">
                      {tr.depart_date &&
                        (tr.return_date
                          ? t('staffing.period_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(tr.depart_date), to: fmtDate(tr.return_date) })
                          : fmtDate(tr.depart_date))}
                    </span>
                    {(tr.from_place || tr.to_place) && (
                      <span className="text-content-secondary">
                        {tr.from_place && tr.to_place
                          ? t('staffing.travel.route', { defaultValue: '{{from}} to {{to}}', from: tr.from_place, to: tr.to_place })
                          : tr.from_place || tr.to_place}
                      </span>
                    )}
                    {tr.cost && <span className="tabular-nums text-content-secondary" data-testid="travel-cost-shown">{formatCurrency(tr.cost, tr.currency)}</span>}
                    {editable && (
                      <span className="ml-auto flex flex-wrap gap-1">
                        {nextTravelStatuses(tr.status).map((s) => (
                          <Button key={s} variant="ghost" size="sm" onClick={() => travelStatus.mutate({ id: tr.id, status: s })}>
                            {t('staffing.set_status', { defaultValue: 'Set {{status}}', status: vocab(t, TRAVEL_STATUS, s) })}
                          </Button>
                        ))}
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Pencil size={14} />}
                          aria-label={t('staffing.travel.edit', { defaultValue: 'Edit trip' })}
                          title={t('staffing.travel.edit', { defaultValue: 'Edit trip' })}
                          onClick={() => setDialog({ kind: 'travel', travel: tr })}
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={14} />}
                          aria-label={t('staffing.travel.delete', { defaultValue: 'Delete trip' })}
                          title={t('staffing.travel.delete', { defaultValue: 'Delete trip' })}
                          onClick={() => travelRemove.mutate(tr.id)}
                        />
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title={t('staffing.upcoming.leave', { defaultValue: 'Leave' })}
            testId="file-leave"
            action={
              editable && (
                <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'leave', leave: null })} data-testid="add-leave">
                  {t('staffing.leave.add', { defaultValue: 'Add leave' })}
                </Button>
              )
            }
          >
            {file.leave.length === 0 ? (
              <Quiet testId="leave-empty">{t('staffing.leave.empty', { defaultValue: 'No leave is recorded.' })}</Quiet>
            ) : (
              <ul className="space-y-2">
                {file.leave.map((lv) => (
                  <li key={lv.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light p-3 text-sm" data-testid="leave-row">
                    <span className="font-medium text-content-primary">{catalogueName(labels, catalogue, 'leave_type', lv.leave_type)}</span>
                    <ToneBadge tone={LEAVE_TONE[lv.status]}>{vocab(t, LEAVE_STATUS, lv.status)}</ToneBadge>
                    <span className="text-content-secondary">
                      {lv.from_date && lv.to_date
                        ? t('staffing.period_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(lv.from_date), to: fmtDate(lv.to_date) })
                        : ''}
                    </span>
                    {editable && (
                      <span className="ml-auto flex flex-wrap gap-1">
                        {nextLeaveStatuses(lv.status).map((s) => (
                          <Button key={s} variant="ghost" size="sm" onClick={() => leaveStatus.mutate({ id: lv.id, status: s })}>
                            {s === 'approved'
                              ? t('staffing.leave.approve', { defaultValue: 'Approve' })
                              : t('staffing.set_status', { defaultValue: 'Set {{status}}', status: vocab(t, LEAVE_STATUS, s) })}
                          </Button>
                        ))}
                        {lv.status === 'requested' && (
                          <Button
                            variant="ghost"
                            size="sm"
                            icon={<Pencil size={14} />}
                            aria-label={t('staffing.leave.edit', { defaultValue: 'Edit leave' })}
                            title={t('staffing.leave.edit', { defaultValue: 'Edit leave' })}
                            onClick={() => setDialog({ kind: 'leave', leave: lv })}
                          />
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={14} />}
                          aria-label={t('staffing.leave.delete', { defaultValue: 'Delete leave' })}
                          title={t('staffing.leave.delete', { defaultValue: 'Delete leave' })}
                          onClick={() => leaveRemove.mutate(lv.id)}
                        />
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title={t('staffing.accommodation.heading', { defaultValue: 'Accommodation' })}
            testId="file-accommodation"
            action={
              <Link to="/accommodation" className="text-sm text-oe-blue-text hover:underline">
                {t('staffing.accommodation.open', { defaultValue: 'Open accommodation' })}
              </Link>
            }
          >
            {file.accommodation.length === 0 ? (
              <Quiet testId="accommodation-empty">
                {t('staffing.accommodation.empty', {
                  defaultValue: 'No room is booked for this person. Rooms are booked in Accommodation; a booking made for this person appears here.',
                })}
              </Quiet>
            ) : (
              <ul className="space-y-2">
                {file.accommodation.map((b, i) => (
                  <li key={b.id ?? i} className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light p-3 text-sm" data-testid="booking-row">
                    <span className="font-medium text-content-primary">
                      {fmtList([b.accommodation ?? '', b.room ?? ''])}
                    </span>
                    <span className="text-content-secondary">
                      {b.check_in && b.check_out
                        ? t('staffing.period_range', { defaultValue: '{{from}} to {{to}}', from: fmtDate(b.check_in), to: fmtDate(b.check_out) })
                        : b.check_in
                          ? fmtDate(b.check_in)
                          : ''}
                    </span>
                    {b.status && <ToneBadge tone="neutral">{humanizeCode(b.status)}</ToneBadge>}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </>
      )}

      <Section title={t('staffing.file.data_heading', { defaultValue: 'Personal data' })} testId="file-data">
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light p-3">
          <p className="mr-auto max-w-xl text-sm text-content-secondary">
            {t('staffing.file.data_body', {
              defaultValue: 'The person concerned can download their own file. An administrator can erase the personal data on request, unless a legal retention duty or a hold still applies.',
            })}
          </p>
          {file.can.export.allowed && (
            <span className="inline-flex items-center gap-1" data-testid="file-export-own">
              <span className="text-xs text-content-tertiary">{t('staffing.file.export_own', { defaultValue: 'Download my file' })}</span>
              <ExportButtons download={(format) => downloadOwnFile(projectId, fileId, format)} />
            </span>
          )}
          <Button variant="ghost" size="sm" onClick={() => setShowLog((v) => !v)} aria-expanded={showLog} data-testid="file-log-toggle">
            {t('staffing.file.access_log', { defaultValue: 'Who opened this file' })}
          </Button>
          {offered(file.can.erase) && (
            <Button
              variant="danger"
              size="sm"
              icon={<ShieldAlert size={14} />}
              disabled={!file.can.erase.allowed}
              onClick={() => setDialog({ kind: 'erase' })}
              data-testid="file-erase"
            >
              {t('staffing.file.erase', { defaultValue: 'Erase personal data' })}
            </Button>
          )}
        </div>
        {editable && !file.can.erase.allowed && (
          <p className="text-xs text-content-tertiary" role="status" data-testid="file-erase-refused">
            {whyNot(labels.t, file.can.erase)}
          </p>
        )}
        {showLog &&
          (logQ.isLoading ? (
            <SkeletonTable rows={3} columns={3} />
          ) : logQ.isError ? (
            <ErrorState compact title={refusalText(labels.t, logQ.error)} onRetry={() => logQ.refetch()} />
          ) : (
            <ul className="divide-y divide-border-light rounded-lg border border-border-light text-sm" data-testid="access-log">
              {(logQ.data ?? []).map((entry, i) => (
                <li key={`${entry.at}:${i}`} className="flex flex-wrap gap-x-4 px-3 py-1.5">
                  <span className="w-40 text-content-tertiary">{entry.at ? formatDateValue(entry.at, { dateStyle: 'medium', timeStyle: 'short' }) : ''}</span>
                  <span className="text-content-primary">
                    {personName(entry.actor_id) ?? t('staffing.file.log_someone', { defaultValue: 'Somebody outside the project team' })}
                  </span>
                  <span className="text-content-secondary">{vocab(t, ACCESS_ACTION, entry.action)}</span>
                </li>
              ))}
            </ul>
          ))}
      </Section>

      <FileHeaderDialog open={dialog?.kind === 'header'} projectId={projectId} file={file} onClose={() => setDialog(null)} onDone={() => void reload()} />
      <EndFileDialog open={dialog?.kind === 'end'} projectId={projectId} fileId={fileId} onClose={() => setDialog(null)} onDone={() => void reload()} />
      <DocumentDialog
        open={dialog?.kind === 'document'}
        projectId={projectId}
        labels={labels}
        fileId={fileId}
        catalogue={catalogue}
        document={dialog?.kind === 'document' ? dialog.document : null}
        onClose={() => setDialog(null)}
        onDone={() => void reload()}
      />
      <TravelDialog
        open={dialog?.kind === 'travel'}
        projectId={projectId}
        labels={labels}
        fileId={fileId}
        currency=""
        travel={dialog?.kind === 'travel' ? dialog.travel : null}
        onClose={() => setDialog(null)}
        onDone={() => void reload()}
      />
      <LeaveDialog
        open={dialog?.kind === 'leave'}
        projectId={projectId}
        labels={labels}
        fileId={fileId}
        catalogue={catalogue}
        leave={dialog?.kind === 'leave' ? dialog.leave : null}
        onClose={() => setDialog(null)}
        onDone={() => void reload()}
        onWarnings={(warnings) => {
          for (const w of warnings) addToast({ type: 'warning', title: findingText(labels, catalogue, w) });
        }}
      />
      <ReasonDialog
        open={dialog?.kind === 'hold'}
        title={t('staffing.file.hold', { defaultValue: 'Place hold' })}
        subtitle={t('staffing.file.hold_hint', {
          defaultValue: 'A hold stops the scheduled deletion of this file, for example during a dispute. It stays until somebody releases it.',
        })}
        label={t('staffing.file.rationale', { defaultValue: 'Reason' })}
        confirmLabel={t('staffing.file.hold', { defaultValue: 'Place hold' })}
        onClose={() => setDialog(null)}
        onSubmit={async (reason) => {
          await holdFile(projectId, fileId, reason);
          void reload();
        }}
      />
      <ReasonDialog
        open={dialog?.kind === 'erase'}
        danger
        title={t('staffing.file.erase', { defaultValue: 'Erase personal data' })}
        subtitle={t('staffing.file.erase_hint', {
          defaultValue: 'This removes the personal data of the file for good and cannot be undone. The server refuses while a legal retention duty or a hold applies.',
        })}
        label={t('staffing.file.rationale', { defaultValue: 'Reason' })}
        confirmLabel={t('staffing.file.erase', { defaultValue: 'Erase personal data' })}
        onClose={() => setDialog(null)}
        onSubmit={async (reason) => {
          await eraseFile(projectId, fileId, reason);
          void reload();
        }}
      />
      <ReasonDialog
        open={dialog?.kind === 'waive'}
        title={t('staffing.document.waive_title', { defaultValue: 'Waive this document' })}
        subtitle={dialog?.kind === 'waive' ? catalogueName(labels, catalogue, 'document_kind', dialog.document.document_kind) : undefined}
        label={t('staffing.file.rationale', { defaultValue: 'Reason' })}
        confirmLabel={t('staffing.document.waive', { defaultValue: 'Waive' })}
        onClose={() => setDialog(null)}
        onSubmit={async (reason) => {
          if (dialog?.kind !== 'waive') return;
          await waiveDocument(projectId, fileId, dialog.document.document_kind, reason);
          void reload();
        }}
      />
    </div>
  );
}
