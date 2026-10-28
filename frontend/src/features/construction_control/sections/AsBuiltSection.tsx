// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pillar 3: As-built records (verified survey / scan records with metrology
// tolerance, an e-signed legal-record attestation, and import-from-scan).
//
// Fully implements the third pillar's workflow:
//   * list as-built records for the active project,
//   * create a record (capture method + accuracy class + optional criterion +
//     model element link), or import one from a point-cloud scan registration,
//   * record a survey (captured value -> server-computed tolerance result),
//   * verify a surveyed record (an out-of-tolerance record auto-raises a
//     workmanship NCR, surfaced as a chip),
//   * e-sign the legal-record attestation (only a verified record can be
//     attested valid, which moves it to recorded).
//
// FSM: draft -> surveyed -> verified -> recorded (+ superseded / void). The
// action buttons are shown only when valid for the record's current status.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  X,
  Ruler,
  ShieldCheck,
  ScanLine,
  AlertOctagon,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import { Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listAsBuilt,
  listCriteria,
  createAsBuilt,
  importAsBuiltFromScan,
  recordAsBuiltSurvey,
  verifyAsBuilt,
  signAsBuiltValidity,
  type AsBuiltRecord,
  type AcceptanceCriterion,
  type CaptureMethod,
  type AccuracyClass,
  type SourceKind,
  type NcrSeverity,
} from '../api';
import { ElementLinks, SectionToolbar, StatusBadge, inputCls, labelCls, textareaCls } from './shared';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

// English fallbacks for the computed `construction_control.accuracy_class.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const ACCURACY_CLASS_LABELS: Record<string, string> = {
  survey: 'Survey grade', standard: 'Standard', coarse: 'Coarse'
};

// English fallbacks for the computed `construction_control.capture_method.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const CAPTURE_METHOD_LABELS: Record<string, string> = {
  laser_scan: 'Laser scan', photogrammetry: 'Photogrammetry', total_station: 'Total station', gnss: 'GNSS',
  tape: 'Tape measure', drone_lidar: 'Drone LiDAR', model_extract: 'Model extract', manual: 'Manual'
};

// English fallbacks for the computed `construction_control.ncr_severity.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const NCR_SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critical', major: 'Major', minor: 'Minor', observation: 'Observation'
};

// English fallbacks for the computed `construction_control.source_kind.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const SOURCE_KIND_LABELS: Record<string, string> = {
  pointcloud_scan: 'Point cloud scan', pointcloud_registration: 'Point cloud registration',
  takeoff_measurement: 'Takeoff measurement', cde_document: 'CDE document', manual: 'Manual entry'
};


const ASBUILT_STATUS_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  surveyed: 'blue',
  verified: 'blue',
  recorded: 'success',
  superseded: 'neutral',
  void: 'neutral',
};

const TOLERANCE_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  within: 'success',
  out_of_tolerance: 'error',
  not_assessed: 'neutral',
};

const CAPTURE_METHODS: CaptureMethod[] = [
  'laser_scan',
  'photogrammetry',
  'total_station',
  'gnss',
  'tape',
  'drone_lidar',
  'model_extract',
  'manual',
];

const ACCURACY_CLASSES: AccuracyClass[] = ['survey', 'standard', 'coarse'];

const SOURCE_KINDS: SourceKind[] = [
  'pointcloud_scan',
  'pointcloud_registration',
  'takeoff_measurement',
  'cde_document',
  'manual',
];

const NCR_SEVERITIES: NcrSeverity[] = ['critical', 'major', 'minor', 'observation'];

/** Statuses on which a survey may be (re)recorded - mirrors the service. */
const SURVEYABLE = new Set<string>(['draft', 'surveyed']);

interface SectionProps {
  projectId: string;
}

type ActionKind = 'survey' | 'verify' | 'sign';

export function AsBuiltSection({ projectId }: SectionProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [action, setAction] = useState<{ kind: ActionKind; record: AsBuiltRecord } | null>(null);

  const recordsQuery = useQuery({
    queryKey: ['cc', 'asbuilt', projectId],
    queryFn: () => listAsBuilt(projectId),
    enabled: !!projectId,
  });

  const criteriaQuery = useQuery({
    queryKey: ['cc', 'criteria', projectId],
    queryFn: () => listCriteria(projectId),
    enabled: !!projectId,
  });

  const records = recordsQuery.data ?? [];
  const criteria = useMemo(() => criteriaQuery.data ?? [], [criteriaQuery.data]);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['cc', 'asbuilt', projectId] });
  };

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Something went wrong' }),
      message: (e as Error).message,
    });

  const createMutationOnce = useSingleFlight();
  const createMutation = useMutation({
    mutationFn: createAsBuilt,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.asbuilt.created_title', {
          defaultValue: 'As-built record created',
        }),
        message: t('construction_control.asbuilt.created_msg', {
          defaultValue: 'The as-built record has been added to this project.',
        }),
      });
      setShowCreate(false);
      invalidate();
    },
    onError: toastError,
  });

  const importMutation = useMutation({
    mutationFn: importAsBuiltFromScan,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.asbuilt.imported_title', {
          defaultValue: 'Imported from scan',
        }),
        message: t('construction_control.asbuilt.imported_msg', {
          defaultValue: 'A draft as-built record was created from the scan registration.',
        }),
      });
      setShowImport(false);
      invalidate();
    },
    onError: toastError,
  });

  const surveyMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: {
        measured_value?: string | null;
        deviation_value?: string | null;
        accuracy_value?: string | null;
        accuracy_unit?: string | null;
        survey_date?: string | null;
        notes?: string | null;
      };
    }) => recordAsBuiltSurvey(id, payload),
    onSuccess: (updated) => {
      const tol = updated.tolerance_result;
      addToast({
        type: tol === 'out_of_tolerance' ? 'warning' : 'success',
        title: t('construction_control.asbuilt.survey_title', {
          defaultValue: 'Survey recorded',
        }),
        message:
          tol === 'out_of_tolerance'
            ? t('construction_control.asbuilt.survey_out_msg', {
                defaultValue:
                  'The captured value is out of tolerance. Verify the record to raise an NCR.',
              })
            : tol === 'within'
              ? t('construction_control.asbuilt.survey_within_msg', {
                  defaultValue: 'The captured value is within tolerance.',
                })
              : t('construction_control.asbuilt.survey_na_msg', {
                  defaultValue: 'The captured value was recorded; tolerance was not assessed.',
                }),
      });
      setAction(null);
      invalidate();
    },
    onError: toastError,
  });

  const verifyMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: { notes?: string | null; ncr_severity?: NcrSeverity | null };
    }) => verifyAsBuilt(id, payload),
    onSuccess: (updated) => {
      const raisedNcr = !!updated.raised_ncr_id;
      addToast({
        type: raisedNcr ? 'warning' : 'success',
        title: raisedNcr
          ? t('construction_control.asbuilt.verified_ncr_title', {
              defaultValue: 'Verified - NCR raised',
            })
          : t('construction_control.asbuilt.verified_title', { defaultValue: 'Record verified' }),
        message: raisedNcr
          ? t('construction_control.asbuilt.verified_ncr_msg', {
              defaultValue:
                'The record was out of tolerance; a workmanship NCR was raised and linked.',
            })
          : t('construction_control.asbuilt.verified_msg', {
              defaultValue: 'The as-built record has been verified.',
            }),
      });
      setAction(null);
      invalidate();
    },
    onError: toastError,
  });

  const signMutation = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: { valid: boolean; notes?: string | null };
    }) => signAsBuiltValidity(id, payload),
    onSuccess: (updated) => {
      const valid = updated.valid_for_legal_record;
      addToast({
        type: 'success',
        title: valid
          ? t('construction_control.asbuilt.signed_title', {
              defaultValue: 'Attestation signed',
            })
          : t('construction_control.asbuilt.declined_title', {
              defaultValue: 'Attestation declined',
            }),
        message: valid
          ? t('construction_control.asbuilt.signed_msg', {
              defaultValue:
                'The record is now signed valid for the legal record and marked recorded.',
            })
          : t('construction_control.asbuilt.declined_msg', {
              defaultValue: 'The signer declined to attest the record; it stays verified.',
            }),
      });
      setAction(null);
      invalidate();
    },
    onError: toastError,
  });

  return (
    <div className="space-y-3">
      <SectionToolbar
        title={t('construction_control.asbuilt_heading', { defaultValue: 'As-built records' })}
        count={records.length}
      >
        <Button
          variant="secondary"
          size="sm"
          icon={<ScanLine className="h-4 w-4" />}
          onClick={() => setShowImport(true)}
        >
          {t('construction_control.asbuilt.import', { defaultValue: 'Import from scan' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => setShowCreate(true)}
        >
          {t('construction_control.asbuilt.new', { defaultValue: 'New record' })}
        </Button>
      </SectionToolbar>

      {recordsQuery.isLoading ? (
        <SkeletonTable rows={4} columns={6} />
      ) : recordsQuery.isError ? (
        <Card>
          <div className="p-6 text-sm text-semantic-error">
            {t('construction_control.asbuilt.load_error', {
              defaultValue: 'Could not load as-built records. Please try again.',
            })}
          </div>
        </Card>
      ) : records.length === 0 ? (
        <EmptyState
          icon={<Ruler size={26} strokeWidth={1.5} />}
          title={t('construction_control.asbuilt.empty_title', {
            defaultValue: 'No as-built records yet',
          })}
          description={t('construction_control.asbuilt.empty_desc', {
            defaultValue:
              'As-built records capture a surveyed or scanned value, judge it against tolerance, and hold a signed legal-record attestation.',
          })}
          action={{
            label: t('construction_control.asbuilt.new', { defaultValue: 'New record' }),
            onClick: () => setShowCreate(true),
          }}
        />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.number', { defaultValue: 'Number' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.title', { defaultValue: 'Title' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.capture', { defaultValue: 'Capture' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.tolerance_result', { defaultValue: 'Tolerance' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.status', { defaultValue: 'Status' })}
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    {t('construction_control.col.actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => {
                  const canSurvey = SURVEYABLE.has(r.status);
                  const canVerify = r.status === 'surveyed';
                  const canSign = r.status === 'verified';
                  return (
                    <tr
                      key={r.id}
                      className="border-b border-border-light/60 last:border-b-0 align-top"
                      data-testid={`cc-asbuilt-row-${r.id}`}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                        {r.record_number}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-content-primary">{r.title}</div>
                        {r.discipline && (
                          <div className="text-xs text-content-tertiary">{r.discipline}</div>
                        )}
                        {r.location_description && (
                          <div className="text-xs text-content-tertiary">
                            {r.location_description}
                          </div>
                        )}
                        <div className="mt-1">
                          <ElementLinks elements={r.elements} />
                        </div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-content-secondary">
                        {r.capture_method.replace(/_/g, ' ')}
                        {r.measured_value && (
                          <div className="text-2xs text-content-tertiary">
                            {t('construction_control.asbuilt.measured', {
                              defaultValue: 'measured {{value}}',
                              value: r.measured_value,
                            })}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {r.tolerance_result ? (
                          <StatusBadge status={r.tolerance_result} variants={TOLERANCE_VARIANTS} />
                        ) : (
                          <span className="text-content-tertiary">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <StatusBadge status={r.status} variants={ASBUILT_STATUS_VARIANTS} />
                          {r.valid_for_legal_record && (
                            <span
                              className="inline-flex items-center gap-1 text-2xs text-semantic-success"
                              title={t('construction_control.asbuilt.signed', {
                                defaultValue: 'Signed valid for the legal record',
                              })}
                            >
                              <ShieldCheck className="h-3.5 w-3.5" />
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          {r.raised_ncr_id && (
                            <span className="inline-flex items-center gap-1 rounded-md bg-semantic-error-bg px-2 py-0.5 text-2xs font-medium text-semantic-error">
                              <AlertOctagon className="h-3 w-3" />
                              {t('construction_control.ncr_linked', { defaultValue: 'NCR' })}
                            </span>
                          )}
                          {canSurvey && (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => setAction({ kind: 'survey', record: r })}
                            >
                              {t('construction_control.asbuilt.record_survey', {
                                defaultValue: 'Record survey',
                              })}
                            </Button>
                          )}
                          {canVerify && (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => setAction({ kind: 'verify', record: r })}
                            >
                              {t('construction_control.asbuilt.verify', { defaultValue: 'Verify' })}
                            </Button>
                          )}
                          {canSign && (
                            <Button
                              variant="primary"
                              size="sm"
                              icon={<ShieldCheck className="h-4 w-4" />}
                              onClick={() => setAction({ kind: 'sign', record: r })}
                            >
                              {t('construction_control.asbuilt.sign', {
                                defaultValue: 'Sign validity',
                              })}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showCreate && (
        <CreateRecordModal
          projectId={projectId}
          criteria={criteria}
          isPending={createMutation.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => createMutationOnce(() => createMutation.mutateAsync(payload))}
        />
      )}

      {showImport && (
        <ImportFromScanModal
          projectId={projectId}
          criteria={criteria}
          isPending={importMutation.isPending}
          onClose={() => setShowImport(false)}
          onSubmit={(payload) => importMutation.mutate(payload)}
        />
      )}

      {action?.kind === 'survey' && (
        <RecordSurveyModal
          record={action.record}
          isPending={surveyMutation.isPending}
          onClose={() => setAction(null)}
          onSubmit={(payload) => surveyMutation.mutate({ id: action.record.id, payload })}
        />
      )}

      {action?.kind === 'verify' && (
        <VerifyModal
          record={action.record}
          isPending={verifyMutation.isPending}
          onClose={() => setAction(null)}
          onSubmit={(payload) => verifyMutation.mutate({ id: action.record.id, payload })}
        />
      )}

      {action?.kind === 'sign' && (
        <SignValidityModal
          record={action.record}
          isPending={signMutation.isPending}
          onClose={() => setAction(null)}
          onSubmit={(payload) => signMutation.mutate({ id: action.record.id, payload })}
        />
      )}
    </div>
  );
}

// -- Create-record modal --------------------------------------------------------

interface CreateForm {
  title: string;
  discipline: string;
  location_description: string;
  capture_method: CaptureMethod;
  accuracy_class: AccuracyClass;
  instrument: string;
  instrument_calibration_ref: string;
  accuracy_value: string;
  accuracy_unit: string;
  coordinate_system: string;
  source_kind: SourceKind;
  criterion_id: string;
  measured_value: string;
}

const EMPTY_CREATE: CreateForm = {
  title: '',
  discipline: '',
  location_description: '',
  capture_method: 'total_station',
  accuracy_class: 'standard',
  instrument: '',
  instrument_calibration_ref: '',
  accuracy_value: '',
  accuracy_unit: '',
  coordinate_system: '',
  source_kind: 'manual',
  criterion_id: '',
  measured_value: '',
};

function CreateRecordModal({
  projectId,
  criteria,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  criteria: AcceptanceCriterion[];
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    project_id: string;
    title: string;
    discipline?: string | null;
    location_description?: string | null;
    capture_method: CaptureMethod;
    accuracy_class: AccuracyClass;
    instrument?: string | null;
    instrument_calibration_ref?: string | null;
    accuracy_value?: string | null;
    accuracy_unit?: string | null;
    coordinate_system?: string | null;
    source_kind: SourceKind;
    criterion_id?: string | null;
    measured_value?: string | null;
  }) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CreateForm>(EMPTY_CREATE);
  const [touched, setTouched] = useState(false);
  const canSubmit = form.title.trim().length > 0;

  const set = <K extends keyof CreateForm>(key: K, value: CreateForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      project_id: projectId,
      title: form.title.trim(),
      discipline: form.discipline.trim() || null,
      location_description: form.location_description.trim() || null,
      capture_method: form.capture_method,
      accuracy_class: form.accuracy_class,
      instrument: form.instrument.trim() || null,
      instrument_calibration_ref: form.instrument_calibration_ref.trim() || null,
      accuracy_value: form.accuracy_value.trim() || null,
      accuracy_unit: form.accuracy_unit.trim() || null,
      coordinate_system: form.coordinate_system.trim() || null,
      source_kind: form.source_kind,
      criterion_id: form.criterion_id || null,
      measured_value: form.measured_value.trim() || null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.asbuilt.new', { defaultValue: 'New record' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div>
          <label htmlFor="cc-ab-title" className={labelCls}>
            {t('construction_control.col.title', { defaultValue: 'Title' })}
          </label>
          <input
            id="cc-ab-title"
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.asbuilt.title_ph', {
              defaultValue: 'e.g. Slab level survey - Level 2',
            })}
          />
          {touched && !canSubmit && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.field.title_required', {
                defaultValue: 'A title is required.',
              })}
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ab-capture" className={labelCls}>
              {t('construction_control.col.capture', { defaultValue: 'Capture' })}
            </label>
            <select
              id="cc-ab-capture"
              value={form.capture_method}
              onChange={(e) => set('capture_method', e.target.value as CaptureMethod)}
              className={inputCls}
            >
              {CAPTURE_METHODS.map((m) => (
                <option key={m} value={m}>
                  {t(`construction_control.capture_method.${m}`, {
                    defaultValue: CAPTURE_METHOD_LABELS[m] ?? m.replace(/_/g, ' '),
                  })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-ab-accuracy-class" className={labelCls}>
              {t('construction_control.field.accuracy_class', { defaultValue: 'Accuracy class' })}
            </label>
            <select
              id="cc-ab-accuracy-class"
              value={form.accuracy_class}
              onChange={(e) => set('accuracy_class', e.target.value as AccuracyClass)}
              className={inputCls}
            >
              {ACCURACY_CLASSES.map((a) => (
                <option key={a} value={a}>
                  {t(`construction_control.accuracy_class.${a}`, { defaultValue: ACCURACY_CLASS_LABELS[a] ?? a })}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ab-discipline" className={labelCls}>
              {t('construction_control.field.discipline', { defaultValue: 'Discipline' })}
            </label>
            <input
              id="cc-ab-discipline"
              value={form.discipline}
              onChange={(e) => set('discipline', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.discipline_ph', {
                defaultValue: 'e.g. Structural',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-location" className={labelCls}>
              {t('construction_control.field.location', { defaultValue: 'Location' })}
            </label>
            <input
              id="cc-ab-location"
              value={form.location_description}
              onChange={(e) => set('location_description', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.location_ph', {
                defaultValue: 'e.g. Building A, Level 2, Grid C4',
              })}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ab-instrument" className={labelCls}>
              {t('construction_control.field.instrument', { defaultValue: 'Instrument' })}
            </label>
            <input
              id="cc-ab-instrument"
              value={form.instrument}
              onChange={(e) => set('instrument', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.instrument_ph', {
                defaultValue: 'e.g. Total station model',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-calibration" className={labelCls}>
              {t('construction_control.field.calibration_ref', {
                defaultValue: 'Calibration reference',
              })}
            </label>
            <input
              id="cc-ab-calibration"
              value={form.instrument_calibration_ref}
              onChange={(e) => set('instrument_calibration_ref', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.calibration_ref_ph', {
                defaultValue: 'e.g. CAL-2026-018',
              })}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="cc-ab-accuracy-value" className={labelCls}>
              {t('construction_control.field.accuracy_value', { defaultValue: 'Accuracy value' })}
            </label>
            <input
              id="cc-ab-accuracy-value"
              value={form.accuracy_value}
              onChange={(e) => set('accuracy_value', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.accuracy_value_ph', {
                defaultValue: 'e.g. 2',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-accuracy-unit" className={labelCls}>
              {t('construction_control.field.accuracy_unit', { defaultValue: 'Accuracy unit' })}
            </label>
            <input
              id="cc-ab-accuracy-unit"
              value={form.accuracy_unit}
              onChange={(e) => set('accuracy_unit', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.accuracy_unit_ph', {
                defaultValue: 'e.g. mm',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-coordinate" className={labelCls}>
              {t('construction_control.field.coordinate_system', {
                defaultValue: 'Coordinate system',
              })}
            </label>
            <input
              id="cc-ab-coordinate"
              value={form.coordinate_system}
              onChange={(e) => set('coordinate_system', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.coordinate_system_ph', {
                defaultValue: 'e.g. Site grid',
              })}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ab-source" className={labelCls}>
              {t('construction_control.field.source_kind', { defaultValue: 'Source' })}
            </label>
            <select
              id="cc-ab-source"
              value={form.source_kind}
              onChange={(e) => set('source_kind', e.target.value as SourceKind)}
              className={inputCls}
            >
              {SOURCE_KINDS.map((s) => (
                <option key={s} value={s}>
                  {t(`construction_control.source_kind.${s}`, {
                    defaultValue: SOURCE_KIND_LABELS[s] ?? s.replace(/_/g, ' '),
                  })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-ab-criterion" className={labelCls}>
              {t('construction_control.field.criterion', {
                defaultValue: 'Acceptance criterion (optional)',
              })}
            </label>
            <select
              id="cc-ab-criterion"
              value={form.criterion_id}
              onChange={(e) => set('criterion_id', e.target.value)}
              className={inputCls}
            >
              <option value="">
                {t('construction_control.field.no_criterion', { defaultValue: 'No criterion' })}
              </option>
              {criteria.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} - {c.title}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label htmlFor="cc-ab-measured" className={labelCls}>
            {t('construction_control.field.measured_value', {
              defaultValue: 'Measured value (optional)',
            })}
          </label>
          <input
            id="cc-ab-measured"
            value={form.measured_value}
            onChange={(e) => set('measured_value', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.field.measured_value_ph', {
              defaultValue: 'Recorded now or later at survey',
            })}
          />
          <p className="mt-1 text-xs text-content-tertiary">
            {t('construction_control.asbuilt.measured_hint', {
              defaultValue:
                'The tolerance result is computed against the linked criterion when the survey is recorded.',
            })}
          </p>
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending || !canSubmit}
          icon={<Plus className="h-4 w-4" />}
        >
          {t('construction_control.asbuilt.create', { defaultValue: 'Create record' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// -- Import-from-scan modal -----------------------------------------------------

function ImportFromScanModal({
  projectId,
  criteria,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  criteria: AcceptanceCriterion[];
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    project_id: string;
    registration_id: string;
    title: string;
    discipline?: string | null;
    criterion_id?: string | null;
  }) => void;
}) {
  const { t } = useTranslation();
  const [registrationId, setRegistrationId] = useState('');
  const [title, setTitle] = useState('');
  const [discipline, setDiscipline] = useState('');
  const [criterionId, setCriterionId] = useState('');
  const [touched, setTouched] = useState(false);
  const canSubmit = registrationId.trim().length > 0 && title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      project_id: projectId,
      registration_id: registrationId.trim(),
      title: title.trim(),
      discipline: discipline.trim() || null,
      criterion_id: criterionId || null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.asbuilt.import', { defaultValue: 'Import from scan' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">
          {t('construction_control.asbuilt.import_hint', {
            defaultValue:
              'Create a draft as-built from a point-cloud scan registration. Its deviation result, RMS accuracy and target element are carried across.',
          })}
        </p>
        <div>
          <label htmlFor="cc-ab-reg" className={labelCls}>
            {t('construction_control.field.registration_id', {
              defaultValue: 'Scan registration ID',
            })}
          </label>
          <input
            id="cc-ab-reg"
            value={registrationId}
            onChange={(e) => setRegistrationId(e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.field.registration_id_ph', {
              defaultValue: 'The point-cloud registration identifier',
            })}
          />
          {touched && registrationId.trim().length === 0 && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.field.registration_required', {
                defaultValue: 'A scan registration ID is required.',
              })}
            </p>
          )}
        </div>
        <div>
          <label htmlFor="cc-ab-import-title" className={labelCls}>
            {t('construction_control.col.title', { defaultValue: 'Title' })}
          </label>
          <input
            id="cc-ab-import-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.asbuilt.title_ph', {
              defaultValue: 'e.g. Slab level survey - Level 2',
            })}
          />
          {touched && title.trim().length === 0 && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.field.title_required', {
                defaultValue: 'A title is required.',
              })}
            </p>
          )}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ab-import-discipline" className={labelCls}>
              {t('construction_control.field.discipline', { defaultValue: 'Discipline' })}
            </label>
            <input
              id="cc-ab-import-discipline"
              value={discipline}
              onChange={(e) => setDiscipline(e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.discipline_ph', {
                defaultValue: 'e.g. Structural',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-import-criterion" className={labelCls}>
              {t('construction_control.field.criterion', {
                defaultValue: 'Acceptance criterion (optional)',
              })}
            </label>
            <select
              id="cc-ab-import-criterion"
              value={criterionId}
              onChange={(e) => setCriterionId(e.target.value)}
              className={inputCls}
            >
              <option value="">
                {t('construction_control.field.no_criterion', { defaultValue: 'No criterion' })}
              </option>
              {criteria.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} - {c.title}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending || !canSubmit}
          icon={<ScanLine className="h-4 w-4" />}
        >
          {t('construction_control.asbuilt.import_action', { defaultValue: 'Import record' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// -- Record-survey modal --------------------------------------------------------

function RecordSurveyModal({
  record,
  isPending,
  onClose,
  onSubmit,
}: {
  record: AsBuiltRecord;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    measured_value?: string | null;
    deviation_value?: string | null;
    accuracy_value?: string | null;
    accuracy_unit?: string | null;
    survey_date?: string | null;
    notes?: string | null;
  }) => void;
}) {
  const { t } = useTranslation();
  const [measuredValue, setMeasuredValue] = useState(record.measured_value ?? '');
  const [deviationValue, setDeviationValue] = useState('');
  const [accuracyValue, setAccuracyValue] = useState(record.accuracy_value ?? '');
  const [accuracyUnit, setAccuracyUnit] = useState(record.accuracy_unit ?? '');
  const [surveyDate, setSurveyDate] = useState('');
  const [notes, setNotes] = useState('');

  const handleSubmit = () => {
    onSubmit({
      measured_value: measuredValue.trim() || null,
      deviation_value: deviationValue.trim() || null,
      accuracy_value: accuracyValue.trim() || null,
      accuracy_unit: accuracyUnit.trim() || null,
      survey_date: surveyDate || null,
      notes: notes.trim() || null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.asbuilt.survey_for', {
        defaultValue: 'Record survey for {{number}}',
        number: record.record_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{record.title}</p>
        <p className="flex items-start gap-1.5 text-xs text-content-tertiary">
          <Ruler className="mt-0.5 h-3.5 w-3.5 shrink-0 text-oe-blue" />
          {t('construction_control.asbuilt.survey_hint', {
            defaultValue:
              'The tolerance result is computed against the linked acceptance criterion. An out-of-tolerance value raises a workmanship NCR when the record is verified.',
          })}
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ab-survey-measured" className={labelCls}>
              {t('construction_control.field.measured_value', { defaultValue: 'Measured value' })}
            </label>
            <input
              id="cc-ab-survey-measured"
              value={measuredValue}
              onChange={(e) => setMeasuredValue(e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.measured_value_survey_ph', {
                defaultValue: 'The captured value',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-survey-deviation" className={labelCls}>
              {t('construction_control.field.deviation_value', { defaultValue: 'Deviation' })}
            </label>
            <input
              id="cc-ab-survey-deviation"
              value={deviationValue}
              onChange={(e) => setDeviationValue(e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.deviation_value_ph', {
                defaultValue: 'e.g. 3.5',
              })}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="cc-ab-survey-accuracy-value" className={labelCls}>
              {t('construction_control.field.accuracy_value', { defaultValue: 'Accuracy value' })}
            </label>
            <input
              id="cc-ab-survey-accuracy-value"
              value={accuracyValue}
              onChange={(e) => setAccuracyValue(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-survey-accuracy-unit" className={labelCls}>
              {t('construction_control.field.accuracy_unit', { defaultValue: 'Accuracy unit' })}
            </label>
            <input
              id="cc-ab-survey-accuracy-unit"
              value={accuracyUnit}
              onChange={(e) => setAccuracyUnit(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="cc-ab-survey-date" className={labelCls}>
              {t('construction_control.field.survey_date', { defaultValue: 'Survey date' })}
            </label>
            <input
              id="cc-ab-survey-date"
              type="date"
              value={surveyDate}
              onChange={(e) => setSurveyDate(e.target.value)}
              className={inputCls}
            />
          </div>
        </div>

        <div>
          <label htmlFor="cc-ab-survey-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-ab-survey-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.asbuilt.survey_notes_ph', {
              defaultValue: 'Survey conditions, registration reference, follow-up...',
            })}
          />
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button variant="primary" onClick={handleSubmit} loading={isPending} disabled={isPending}>
          {t('construction_control.asbuilt.save_survey', { defaultValue: 'Save survey' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// -- Verify modal ---------------------------------------------------------------

function VerifyModal({
  record,
  isPending,
  onClose,
  onSubmit,
}: {
  record: AsBuiltRecord;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: { notes?: string | null; ncr_severity?: NcrSeverity | null }) => void;
}) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState('');
  const [severity, setSeverity] = useState<NcrSeverity>('major');
  const outOfTolerance = record.tolerance_result === 'out_of_tolerance';

  const handleSubmit = () => {
    onSubmit({
      notes: notes.trim() || null,
      ncr_severity: outOfTolerance ? severity : null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.asbuilt.verify_for', {
        defaultValue: 'Verify {{number}}',
        number: record.record_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{record.title}</p>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-content-tertiary">
            {t('construction_control.col.tolerance_result', { defaultValue: 'Tolerance' })}:
          </span>
          {record.tolerance_result ? (
            <StatusBadge status={record.tolerance_result} variants={TOLERANCE_VARIANTS} />
          ) : (
            <span className="text-content-tertiary">-</span>
          )}
        </div>

        {outOfTolerance && (
          <div className="space-y-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/40 p-3">
            <p className="flex items-start gap-1.5 text-xs text-semantic-error">
              <AlertOctagon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t('construction_control.asbuilt.verify_ncr_hint', {
                defaultValue:
                  'This record is out of tolerance. Verifying it raises a workmanship NCR automatically.',
              })}
            </p>
            <div>
              <label htmlFor="cc-ab-verify-severity" className={labelCls}>
                {t('construction_control.field.ncr_severity', { defaultValue: 'NCR severity' })}
              </label>
              <select
                id="cc-ab-verify-severity"
                value={severity}
                onChange={(e) => setSeverity(e.target.value as NcrSeverity)}
                className={inputCls}
              >
                {NCR_SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {t(`construction_control.ncr_severity.${s}`, { defaultValue: NCR_SEVERITY_LABELS[s] ?? s })}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        <div>
          <label htmlFor="cc-ab-verify-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-ab-verify-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.asbuilt.verify_notes_ph', {
              defaultValue: 'Verification basis, reviewer observations...',
            })}
          />
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending}
          icon={<CheckCircle2 className="h-4 w-4" />}
        >
          {t('construction_control.asbuilt.verify', { defaultValue: 'Verify' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// -- Sign-validity modal --------------------------------------------------------

function SignValidityModal({
  record,
  isPending,
  onClose,
  onSubmit,
}: {
  record: AsBuiltRecord;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: { valid: boolean; notes?: string | null }) => void;
}) {
  const { t } = useTranslation();
  const [valid, setValid] = useState(true);
  const [notes, setNotes] = useState('');

  const handleSubmit = () => {
    onSubmit({ valid, notes: notes.trim() || null });
  };

  return (
    <ModalShell
      title={t('construction_control.asbuilt.sign_for', {
        defaultValue: 'Sign validity for {{number}}',
        number: record.record_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{record.title}</p>
        <p className="flex items-start gap-1.5 text-xs text-content-tertiary">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-success" />
          {t('construction_control.asbuilt.sign_hint', {
            defaultValue:
              'Attesting the record valid for the legal record captures your e-signature (signer, time, IP and a content hash) and marks the record recorded.',
          })}
        </p>

        <div>
          <span className={labelCls}>
            {t('construction_control.asbuilt.attestation', { defaultValue: 'Attestation' })}
          </span>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setValid(true)}
              data-testid="cc-ab-sign-valid"
              className={`flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-3 text-center transition-all ${
                valid
                  ? 'border-semantic-success/40 text-semantic-success ring-2 ring-oe-blue/20'
                  : 'border-border bg-surface-primary text-content-tertiary hover:bg-surface-secondary'
              }`}
            >
              <ShieldCheck className="h-5 w-5" />
              <span className="text-xs font-medium">
                {t('construction_control.asbuilt.attest_valid', {
                  defaultValue: 'Valid for legal record',
                })}
              </span>
            </button>
            <button
              type="button"
              onClick={() => setValid(false)}
              data-testid="cc-ab-sign-decline"
              className={`flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-3 text-center transition-all ${
                !valid
                  ? 'border-semantic-error/40 text-semantic-error ring-2 ring-oe-blue/20'
                  : 'border-border bg-surface-primary text-content-tertiary hover:bg-surface-secondary'
              }`}
            >
              <XCircle className="h-5 w-5" />
              <span className="text-xs font-medium">
                {t('construction_control.asbuilt.attest_decline', { defaultValue: 'Decline' })}
              </span>
            </button>
          </div>
          {!valid && (
            <p className="mt-2 text-xs text-content-tertiary">
              {t('construction_control.asbuilt.decline_hint', {
                defaultValue: 'Declining records that you did not attest; the record stays verified.',
              })}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="cc-ab-sign-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-ab-sign-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.asbuilt.sign_notes_ph', {
              defaultValue: 'Basis of attestation, references...',
            })}
          />
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending}
          icon={<ShieldCheck className="h-4 w-4" />}
        >
          {valid
            ? t('construction_control.asbuilt.sign_submit', { defaultValue: 'Sign attestation' })
            : t('construction_control.asbuilt.decline_submit', { defaultValue: 'Record decline' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// -- Modal primitives (inlined; shared.tsx is owned by another section) --------

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-surface-elevated shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h3 className="text-lg font-semibold text-content-primary">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ModalFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
      {children}
    </div>
  );
}

export default AsBuiltSection;
