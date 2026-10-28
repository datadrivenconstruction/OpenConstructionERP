// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The dialogs of a personnel file: open a file for a person, change its
// header, record a document, add a trip, add leave, and end the assignment.
//
// A personnel file holds no document content. A document here is the dates it
// is valid between plus, where the catalogue allows it, the last four
// characters of its number. The full number is never typed. The dialog reads
// nothing from the credentials register: what a reader may see of a person's
// documents is only what the file itself returned.

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/shared/ui/Button';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';

import {
  createFile,
  createLeave,
  createTravel,
  endFile,
  recordDocument,
  updateFile,
  updateLeave,
  updateTravel,
  type EmploymentBasis,
  type FileDocument,
  type Finding,
  type FitForRole,
  type LawfulBasis,
  type LeaveRecord,
  type PersonnelFile,
  type FileCandidate,
  type StaffingCatalogue,
  type TravelKind,
  type TravelRecord,
} from './api';
import { useRoster } from './hooks';
import {
  EMPLOYMENT_BASIS,
  FIT,
  LAWFUL_BASIS,
  TRAVEL_KIND,
  catalogueName,
  errorText,
  vocab,
  whyNot,
  type LabelContext,
} from './labels';
import { costProblem, datesProblem, decimalString, last4Problem } from './rules';
import { FIELD_CLASS, FormError, personLabel } from './StaffingBits';
import { useSubmit } from './useSubmit';

const BASES = Object.keys(EMPLOYMENT_BASIS) as EmploymentBasis[];
const LAWFUL = Object.keys(LAWFUL_BASIS) as LawfulBasis[];
const FITS = Object.keys(FIT) as FitForRole[];
const TRAVEL_KINDS = Object.keys(TRAVEL_KIND) as TravelKind[];

interface DialogBase {
  open: boolean;
  projectId: string;
  labels: LabelContext;
  onClose: () => void;
  onDone: () => void;
}

function Footer({
  busy,
  error,
  onClose,
  onSave,
  saveLabel,
  testId,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: () => void;
  saveLabel: string;
  testId: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex w-full items-center justify-end gap-2">
      <FormError message={error} />
      <Button variant="ghost" onClick={onClose} disabled={busy}>
        {t('common.cancel', { defaultValue: 'Cancel' })}
      </Button>
      <Button loading={busy} onClick={onSave} data-testid={testId}>
        {saveLabel}
      </Button>
    </div>
  );
}

function HeaderFields({
  employer,
  setEmployer,
  basis,
  setBasis,
  lawful,
  setLawful,
  permit,
  setPermit,
}: {
  employer: string;
  setEmployer: (v: string) => void;
  basis: EmploymentBasis;
  setBasis: (v: EmploymentBasis) => void;
  lawful: LawfulBasis;
  setLawful: (v: LawfulBasis) => void;
  permit: boolean;
  setPermit: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <WideModalField label={t('staffing.file.employer', { defaultValue: 'Employer' })} htmlFor="file-employer">
        <input id="file-employer" className={FIELD_CLASS} value={employer} onChange={(e) => setEmployer(e.target.value)} />
      </WideModalField>
      <WideModalField label={t('staffing.file.employment_basis', { defaultValue: 'Employment basis' })} htmlFor="file-basis">
        <select id="file-basis" className={FIELD_CLASS} value={basis} onChange={(e) => setBasis(e.target.value as EmploymentBasis)}>
          {BASES.map((b) => (
            <option key={b} value={b}>
              {vocab(t, EMPLOYMENT_BASIS, b)}
            </option>
          ))}
        </select>
      </WideModalField>
      <WideModalField
        label={t('staffing.file.lawful_basis', { defaultValue: 'Lawful basis' })}
        hint={t('staffing.file.lawful_basis_hint', { defaultValue: 'Why the project may keep this personal data.' })}
        htmlFor="file-lawful"
      >
        <select id="file-lawful" className={FIELD_CLASS} value={lawful} onChange={(e) => setLawful(e.target.value as LawfulBasis)}>
          {LAWFUL.map((b) => (
            <option key={b} value={b}>
              {vocab(t, LAWFUL_BASIS, b)}
            </option>
          ))}
        </select>
      </WideModalField>
      <WideModalField>
        <label className="flex items-start gap-2 text-sm text-content-primary">
          <input type="checkbox" className="mt-0.5" checked={permit} onChange={(e) => setPermit(e.target.checked)} />
          <span>
            {t('staffing.file.nationality_required', { defaultValue: 'Work permit check applies' })}
            <span className="block text-xs text-content-tertiary">
              {t('staffing.file.nationality_required_hint', { defaultValue: 'A work permit then becomes a required document for this person.' })}
            </span>
          </span>
        </label>
      </WideModalField>
    </>
  );
}

/**
 * Open a personnel file for somebody on the plan who has none yet.
 *
 * The people offered are the server's candidates; one it would refuse stays
 * in the list, disabled, with its reason. The roster is read only to suggest
 * the employer.
 */
export function CreateFileDialog({ open, projectId, labels, candidates, onClose, onDone }: DialogBase & { candidates: FileCandidate[] }) {
  const { t } = useTranslation();
  const rosterQ = useRoster(projectId, open);
  const [member, setMember] = useState('');
  const [employer, setEmployer] = useState('');
  const [basis, setBasis] = useState<EmploymentBasis>('employee');
  const [lawful, setLawful] = useState<LawfulBasis>('contract');
  const [permit, setPermit] = useState(false);
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setMember('');
      setEmployer('');
      setBasis('employee');
      setLawful('contract');
      setPermit(false);
      setTried(false);
      reset();
    }
  }, [open, reset]);


  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="create-file-dialog"
      title={t('staffing.file.create', { defaultValue: 'Open personnel file' })}
      subtitle={t('staffing.file.create_hint', {
        defaultValue: 'The file tracks the documents this person needs before starting work, plus travel and leave. Only the people entitled to it can open it.',
      })}
      footer={
        <Footer
          busy={busy}
          error={error ?? (tried && !member ? t('staffing.file.person_required', { defaultValue: 'Choose a person.' }) : null)}
          onClose={onClose}
          onSave={() => {
            if (!member) {
              setTried(true);
              return;
            }
            void run(() =>
              createFile(projectId, {
                roster_member_id: member,
                employer_organisation: employer.trim(),
                employment_basis: basis,
                nationality_required: permit,
                lawful_basis: lawful,
              }),
            );
          }}
          saveLabel={t('staffing.file.create', { defaultValue: 'Open personnel file' })}
          testId="create-file-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('staffing.fill.person', { defaultValue: 'Person' })} required span={2} htmlFor="file-person">
          <select
            id="file-person"
            className={FIELD_CLASS}
            value={member}
            onChange={(e) => {
              setMember(e.target.value);
              const picked = (rosterQ.data ?? []).find((m) => m.id === e.target.value);
              if (picked && !employer) setEmployer(picked.company_name ?? '');
            }}
            data-testid="file-person"
          >
            <option value="">{t('staffing.choose', { defaultValue: 'Choose' })}</option>
            {candidates.map((c) => {
              const name = personLabel(labels.t, c.name);
              const refusal = c.can.create_file.allowed ? '' : whyNot(labels.t, c.can.create_file);
              return (
                <option key={c.roster_member_id} value={c.roster_member_id} disabled={!c.can.create_file.allowed}>
                  {refusal ? `${name}: ${refusal}` : name}
                </option>
              );
            })}
          </select>
        </WideModalField>
        <HeaderFields
          employer={employer}
          setEmployer={setEmployer}
          basis={basis}
          setBasis={setBasis}
          lawful={lawful}
          setLawful={setLawful}
          permit={permit}
          setPermit={setPermit}
        />
      </WideModalSection>
    </WideModal>
  );
}

export function FileHeaderDialog({ open, projectId, file, onClose, onDone }: Omit<DialogBase, 'labels'> & { file: PersonnelFile }) {
  const { t } = useTranslation();
  const [employer, setEmployer] = useState(file.employer_organisation);
  const [basis, setBasis] = useState<EmploymentBasis>(file.employment_basis);
  const [lawful, setLawful] = useState<LawfulBasis>(file.lawful_basis);
  const [permit, setPermit] = useState(file.nationality_required);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setEmployer(file.employer_organisation);
      setBasis(file.employment_basis);
      setLawful(file.lawful_basis);
      setPermit(file.nationality_required);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="file-header-dialog"
      title={t('staffing.file.edit', { defaultValue: 'Edit personnel file' })}
      footer={
        <Footer
          busy={busy}
          error={error}
          onClose={onClose}
          onSave={() =>
            void run(() =>
              updateFile(projectId, file.id, {
                employer_organisation: employer.trim(),
                employment_basis: basis,
                nationality_required: permit,
                lawful_basis: lawful,
              }),
            )
          }
          saveLabel={t('common.save', { defaultValue: 'Save' })}
          testId="file-header-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <HeaderFields
          employer={employer}
          setEmployer={setEmployer}
          basis={basis}
          setBasis={setBasis}
          lawful={lawful}
          setLawful={setLawful}
          permit={permit}
          setPermit={setPermit}
        />
      </WideModalSection>
    </WideModal>
  );
}

/** Record a document of the file: when it was issued and how long it is valid. */
export function DocumentDialog({
  open,
  projectId,
  labels,
  fileId,
  catalogue,
  document,
  onClose,
  onDone,
}: DialogBase & { fileId: string; catalogue: StaffingCatalogue | null; document: FileDocument | null }) {
  const { t } = useTranslation();
  const kind = catalogue?.document_kinds.find((k) => k.code === document?.document_kind);
  const [issued, setIssued] = useState('');
  const [until, setUntil] = useState('');
  const [last4, setLast4] = useState('');
  const [fit, setFit] = useState<FitForRole | ''>('');
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setIssued(document?.issued_at ?? '');
      setUntil(document?.valid_until ?? '');
      setLast4(document?.number_last4 ?? '');
      setFit(document?.fit_for_role ?? '');
      setTried(false);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, document?.document_kind]);

  const problem = last4Problem(last4) ?? (issued && until && until < issued ? 'validity_dates_invalid' : null);
  // The server says which kind carries the fit answer; the client knows no kind by name.
  const takesFit = !!kind?.takes_fit_flag;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="document-dialog"
      title={
        document?.status
          ? t('staffing.document.update', { defaultValue: 'Update document' })
          : t('staffing.document.record', { defaultValue: 'Record document' })
      }
      subtitle={document ? catalogueName(labels, catalogue, 'document_kind', document.document_kind) : undefined}
      footer={
        <Footer
          busy={busy}
          error={error ?? (tried && problem ? errorText(labels.t, problem) : null)}
          onClose={onClose}
          onSave={() => {
            if (problem || !document) {
              setTried(true);
              return;
            }
            void run(() =>
              recordDocument(projectId, fileId, {
                document_kind: document.document_kind,
                issued_at: issued || null,
                valid_until: until || null,
                number_last4: kind?.store_number && last4.trim() ? last4.trim() : null,
                fit_for_role: takesFit && fit ? fit : null,
              }),
            );
          }}
          saveLabel={t('common.save', { defaultValue: 'Save' })}
          testId="document-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField span={2}>
          <p className="text-sm text-content-secondary" data-testid="document-record-hint">
            {t('staffing.document.record_hint', {
              defaultValue: 'Only the dates are kept here. The document itself is not stored, and nobody outside this file sees them.',
            })}
          </p>
        </WideModalField>
        <WideModalField label={t('staffing.document.issued_at', { defaultValue: 'Issued on' })} htmlFor="document-issued">
          <input
            id="document-issued"
            type="date"
            className={FIELD_CLASS}
            value={issued}
            onChange={(e) => setIssued(e.target.value)}
            data-testid="document-issued"
          />
        </WideModalField>
        <WideModalField
          label={t('staffing.document.valid_until', { defaultValue: 'Valid until' })}
          hint={t('staffing.document.valid_until_hint', { defaultValue: 'Leave empty when the document has no end date.' })}
          htmlFor="document-until"
        >
          <input
            id="document-until"
            type="date"
            className={FIELD_CLASS}
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            data-testid="document-until"
          />
        </WideModalField>
        {kind?.store_number && (
          <WideModalField
            label={t('staffing.document.number_last4', { defaultValue: 'Last 4 characters of the number' })}
            hint={t('staffing.document.number_hint', { defaultValue: 'Never enter the full number.' })}
            htmlFor="document-last4"
          >
            <input
              id="document-last4"
              className={FIELD_CLASS}
              value={last4}
              autoComplete="off"
              onChange={(e) => setLast4(e.target.value)}
              data-testid="document-last4"
            />
          </WideModalField>
        )}
        {takesFit && (
          <WideModalField
            label={t('staffing.document.fit_for_role', { defaultValue: 'Fit for role' })}
            hint={t('staffing.document.fit_hint', { defaultValue: 'Only the result is recorded. Medical findings stay with the physician.' })}
            htmlFor="document-fit"
          >
            <select
              id="document-fit"
              className={FIELD_CLASS}
              value={fit}
              onChange={(e) => setFit(e.target.value as FitForRole | '')}
              data-testid="document-fit"
            >
              <option value="">{t('staffing.not_set', { defaultValue: 'Not set' })}</option>
              {FITS.map((f) => (
                <option key={f} value={f}>
                  {vocab(t, FIT, f)}
                </option>
              ))}
            </select>
          </WideModalField>
        )}
      </WideModalSection>
    </WideModal>
  );
}

export function TravelDialog({
  open,
  projectId,
  labels,
  fileId,
  currency,
  travel,
  onClose,
  onDone,
}: DialogBase & { fileId: string; currency: string; travel: TravelRecord | null }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<TravelKind>('mobilisation');
  const [fromPlace, setFromPlace] = useState('');
  const [toPlace, setToPlace] = useState('');
  const [depart, setDepart] = useState('');
  const [back, setBack] = useState('');
  const [ref, setRef] = useState('');
  const [cost, setCost] = useState('');
  const [cur, setCur] = useState(currency);
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setKind(travel?.kind ?? 'mobilisation');
      setFromPlace(travel?.from_place ?? '');
      setToPlace(travel?.to_place ?? '');
      setDepart(travel?.depart_date ?? '');
      setBack(travel?.return_date ?? '');
      setRef(travel?.booking_ref ?? '');
      setCost(travel?.cost ?? '');
      setCur(travel?.currency || currency);
      setTried(false);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, travel?.id]);

  const problem = !depart ? 'required' : datesProblem(depart, back) ?? costProblem(cost, cur);
  const problemText =
    problem === 'required'
      ? t('staffing.travel.depart_required', { defaultValue: 'Set the departure date.' })
      : problem
        ? errorText(labels.t, problem)
        : null;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="md"
      testId="travel-dialog"
      title={travel ? t('staffing.travel.edit', { defaultValue: 'Edit trip' }) : t('staffing.travel.add', { defaultValue: 'Add trip' })}
      footer={
        <Footer
          busy={busy}
          error={error ?? (tried ? problemText : null)}
          onClose={onClose}
          onSave={() => {
            if (problem) {
              setTried(true);
              return;
            }
            const amount = cost.trim() ? decimalString(cost) : null;
            const body = {
              kind,
              from_place: fromPlace.trim(),
              to_place: toPlace.trim(),
              depart_date: depart,
              return_date: back || null,
              booking_ref: ref.trim(),
              cost: amount,
              currency: amount ? cur.trim().toUpperCase() : '',
            };
            void run(() => (travel ? updateTravel(projectId, fileId, travel.id, body) : createTravel(projectId, fileId, body)));
          }}
          saveLabel={travel ? t('common.save', { defaultValue: 'Save' }) : t('staffing.travel.add', { defaultValue: 'Add trip' })}
          testId="travel-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('staffing.travel.kind_label', { defaultValue: 'Kind of trip' })} span={2} htmlFor="travel-kind">
          <select id="travel-kind" className={FIELD_CLASS} value={kind} onChange={(e) => setKind(e.target.value as TravelKind)}>
            {TRAVEL_KINDS.map((k) => (
              <option key={k} value={k}>
                {vocab(t, TRAVEL_KIND, k)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('staffing.travel.from_place', { defaultValue: 'From' })} htmlFor="travel-from">
          <input id="travel-from" className={FIELD_CLASS} value={fromPlace} onChange={(e) => setFromPlace(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('staffing.travel.to_place', { defaultValue: 'To' })} htmlFor="travel-to">
          <input id="travel-to" className={FIELD_CLASS} value={toPlace} onChange={(e) => setToPlace(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('staffing.travel.depart_date', { defaultValue: 'Departure' })} required htmlFor="travel-depart">
          <input id="travel-depart" type="date" className={FIELD_CLASS} value={depart} onChange={(e) => setDepart(e.target.value)} data-testid="travel-depart" />
        </WideModalField>
        <WideModalField label={t('staffing.travel.return_date', { defaultValue: 'Return' })} htmlFor="travel-return">
          <input id="travel-return" type="date" className={FIELD_CLASS} value={back} onChange={(e) => setBack(e.target.value)} />
        </WideModalField>
        <WideModalField label={t('staffing.travel.cost', { defaultValue: 'Cost' })} htmlFor="travel-cost">
          <div className="flex gap-2">
            <input id="travel-cost" inputMode="decimal" className={FIELD_CLASS} value={cost} onChange={(e) => setCost(e.target.value)} data-testid="travel-cost" />
            <input
              aria-label={t('staffing.travel.currency', { defaultValue: 'Currency' })}
              placeholder={t('staffing.travel.currency', { defaultValue: 'Currency' })}
              maxLength={3}
              className={`${FIELD_CLASS} !w-24 uppercase`}
              value={cur}
              onChange={(e) => setCur(e.target.value)}
              data-testid="travel-currency"
            />
          </div>
        </WideModalField>
        <WideModalField label={t('staffing.travel.booking_ref', { defaultValue: 'Booking reference' })} htmlFor="travel-ref">
          <input id="travel-ref" className={FIELD_CLASS} value={ref} onChange={(e) => setRef(e.target.value)} />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

export function LeaveDialog({
  open,
  projectId,
  labels,
  fileId,
  catalogue,
  leave,
  onClose,
  onDone,
  onWarnings,
}: DialogBase & {
  fileId: string;
  catalogue: StaffingCatalogue | null;
  leave: LeaveRecord | null;
  onWarnings: (warnings: Finding[]) => void;
}) {
  const { t } = useTranslation();
  const types = catalogue?.leave_types ?? [];
  const [type, setType] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [tried, setTried] = useState(false);
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) {
      setType(leave?.leave_type ?? types[0]?.code ?? '');
      setFrom(leave?.from_date ?? '');
      setTo(leave?.to_date ?? '');
      setTried(false);
      reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, leave?.id]);

  const problem = !type || !from || !to ? 'required' : datesProblem(from, to);
  const problemText =
    problem === 'required'
      ? t('staffing.leave.required', { defaultValue: 'Choose the type and both dates.' })
      : problem
        ? errorText(labels.t, problem)
        : null;

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="sm"
      testId="leave-dialog"
      title={leave ? t('staffing.leave.edit', { defaultValue: 'Edit leave' }) : t('staffing.leave.add', { defaultValue: 'Add leave' })}
      subtitle={t('staffing.leave.add_hint', { defaultValue: 'Type and dates only. No reason or medical detail is recorded.' })}
      footer={
        <Footer
          busy={busy}
          error={error ?? (tried ? problemText : null)}
          onClose={onClose}
          onSave={() => {
            if (problem) {
              setTried(true);
              return;
            }
            const body = { leave_type: type, from_date: from, to_date: to };
            void run(async () => {
              if (leave) {
                await updateLeave(projectId, fileId, leave.id, body);
                return;
              }
              const created = await createLeave(projectId, fileId, body);
              onWarnings(created?.warnings ?? []);
            });
          }}
          saveLabel={leave ? t('common.save', { defaultValue: 'Save' }) : t('staffing.leave.add', { defaultValue: 'Add leave' })}
          testId="leave-save"
        />
      }
    >
      <WideModalSection columns={2}>
        <WideModalField label={t('staffing.leave.type', { defaultValue: 'Type' })} span={2} htmlFor="leave-type">
          <select id="leave-type" className={FIELD_CLASS} value={type} onChange={(e) => setType(e.target.value)}>
            {types.map((lt) => (
              <option key={lt.code} value={lt.code}>
                {catalogueName(labels, catalogue, 'leave_type', lt.code)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('staffing.leave.from', { defaultValue: 'From' })} required htmlFor="leave-from">
          <input id="leave-from" type="date" className={FIELD_CLASS} value={from} onChange={(e) => setFrom(e.target.value)} data-testid="leave-from" />
        </WideModalField>
        <WideModalField label={t('staffing.leave.to', { defaultValue: 'To' })} required htmlFor="leave-to">
          <input id="leave-to" type="date" className={FIELD_CLASS} value={to} onChange={(e) => setTo(e.target.value)} data-testid="leave-to" />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/** End the assignment today. From that day the retention period of the file runs. The day is the server's. */
export function EndFileDialog({ open, projectId, fileId, onClose, onDone }: Omit<DialogBase, 'labels'> & { fileId: string }) {
  const { t } = useTranslation();
  const { busy, error, run, reset } = useSubmit(() => {
    onDone();
    onClose();
  });
  useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="sm"
      testId="end-file-dialog"
      title={t('staffing.file.end', { defaultValue: 'End assignment' })}
      footer={
        <Footer
          busy={busy}
          error={error}
          onClose={onClose}
          onSave={() => void run(() => endFile(projectId, fileId))}
          saveLabel={t('staffing.file.end', { defaultValue: 'End assignment' })}
          testId="end-file-save"
        />
      }
    >
      <WideModalSection columns={1}>
        <WideModalField>
          <p className="text-sm text-content-primary" data-testid="end-file-today">
            {t('staffing.file.end_today', { defaultValue: 'The assignment ends today.' })}
          </p>
          <p className="mt-1 text-sm text-content-secondary">
            {t('staffing.file.end_hint', {
              defaultValue: 'The file is closed and its personal data is deleted when the retention period of the catalogue has passed.',
            })}
          </p>
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
