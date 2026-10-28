// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pillar 2: Material records (EN 10204 digital passport) + ISO/IEC 17025 lab
// test results.
//
// Fully interactive, mirroring the AcceptanceInspectionsSection reference:
//   * list material records for the active project, create one (cert grade,
//     supplier / heat / batch / lot traceability), and record a conformity
//     decision (accept / reject / conditional), where a reject or conditional
//     auto-raises a material non-conformance report (surfaced as a chip),
//   * list lab test results (optionally filtered to a selected material),
//     create one with the ISO/IEC 17025 laboratory + accreditation fields, and
//     record a pass / fail / conditional outcome against a standard reference,
//     where a fail or conditional auto-raises a linked NCR.
//
// All writes go through react-query mutations with toast + query invalidation;
// loading / empty / error states are preserved.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  X,
  Boxes,
  FlaskConical,
  CheckCircle2,
  XCircle,
  AlertCircle,
  AlertOctagon,
} from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listMaterials,
  createMaterial,
  reviewMaterial,
  listTestResults,
  createTestResult,
  recordTestResult,
  type MaterialRecord,
  type MaterialCreatePayload,
  type MaterialReviewPayload,
  type TestResult,
  type TestResultCreatePayload,
  type TestResultRecordPayload,
  type CertType,
  type ResultDecision,
} from '../api';
import { SectionToolbar, StatusBadge, ElementLinks, inputCls, labelCls, textareaCls } from './shared';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

// EN 10204 inspection-document grades plus the EU CPR / UKCA markings and a
// generic certificate of conformity. Mirrors CERT_TYPE_PATTERN in the schema.
const CERT_TYPES: CertType[] = ['2.1', '2.2', '3.1', '3.2', 'dop', 'ce', 'ukca', 'coc', 'other'];

const CERT_TYPE_LABEL: Record<CertType, string> = {
  '2.1': '2.1 - Declaration of compliance',
  '2.2': '2.2 - Test report',
  '3.1': '3.1 - Inspection certificate',
  '3.2': '3.2 - Inspection certificate (3rd party)',
  dop: 'DoP - Declaration of Performance',
  ce: 'CE marking',
  ukca: 'UKCA marking',
  coc: 'Certificate of Conformity',
  other: 'Other',
};

const MATERIAL_STATUS_VARIANTS: Record<
  string,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  draft: 'neutral',
  submitted: 'blue',
  under_review: 'blue',
  accepted: 'success',
  rejected: 'error',
  expired: 'warning',
  superseded: 'neutral',
};

const TEST_STATUS_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  recorded: 'success',
  void: 'neutral',
};

// A material is still open for a conformity decision in these states.
const MATERIAL_REVIEWABLE = ['draft', 'submitted', 'under_review'];

interface SectionProps {
  projectId: string;
}

export function MaterialsLabsSection({ projectId }: SectionProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [showCreateMaterial, setShowCreateMaterial] = useState(false);
  const [reviewTarget, setReviewTarget] = useState<MaterialRecord | null>(null);
  const [showCreateTest, setShowCreateTest] = useState(false);
  const [recordTarget, setRecordTarget] = useState<TestResult | null>(null);
  // When set, the lab-test list is scoped to a single material record.
  const [materialFilter, setMaterialFilter] = useState<string>('');

  const materialsQuery = useQuery({
    queryKey: ['cc', 'materials', projectId],
    queryFn: () => listMaterials(projectId),
    enabled: !!projectId,
  });
  const testsQuery = useQuery({
    queryKey: ['cc', 'test-results', projectId, materialFilter || null],
    queryFn: () =>
      listTestResults(projectId, materialFilter ? { material_record_id: materialFilter } : {}),
    enabled: !!projectId,
  });

  const materials = useMemo(() => materialsQuery.data ?? [], [materialsQuery.data]);
  const tests = testsQuery.data ?? [];

  const materialById = useMemo(() => {
    const map = new Map<string, MaterialRecord>();
    materials.forEach((m) => map.set(m.id, m));
    return map;
  }, [materials]);

  const invalidateMaterials = () =>
    void qc.invalidateQueries({ queryKey: ['cc', 'materials', projectId] });
  const invalidateTests = () =>
    void qc.invalidateQueries({ queryKey: ['cc', 'test-results', projectId] });

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Something went wrong' }),
      message: (e as Error).message,
    });

  // ── Material mutations ────────────────────────────────────────────────────

  const createMaterialMutationOnce = useSingleFlight();
  const createMaterialMutation = useMutation({
    mutationFn: createMaterial,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.material.created_title', {
          defaultValue: 'Material record created',
        }),
        message: t('construction_control.material.created_msg', {
          defaultValue: 'The material record has been added to this project.',
        }),
      });
      setShowCreateMaterial(false);
      invalidateMaterials();
    },
    onError: toastError,
  });

  const reviewMaterialMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: MaterialReviewPayload }) =>
      reviewMaterial(id, payload),
    onSuccess: (updated) => {
      const raisedNcr = !!updated.raised_ncr_id;
      addToast({
        type: raisedNcr ? 'warning' : 'success',
        title: raisedNcr
          ? t('construction_control.material.review_ncr_title', {
              defaultValue: 'Decision recorded - NCR raised',
            })
          : t('construction_control.material.review_title', {
              defaultValue: 'Decision recorded',
            }),
        message: raisedNcr
          ? t('construction_control.material.review_ncr_msg', {
              defaultValue: 'A material non-conformance report was raised automatically and linked.',
            })
          : t('construction_control.material.review_ok_msg', {
              defaultValue: 'The material was accepted.',
            }),
      });
      setReviewTarget(null);
      invalidateMaterials();
    },
    onError: toastError,
  });

  // ── Test-result mutations ─────────────────────────────────────────────────

  const createTestMutationOnce = useSingleFlight();
  const createTestMutation = useMutation({
    mutationFn: createTestResult,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.test.created_title', {
          defaultValue: 'Test result created',
        }),
        message: t('construction_control.test.created_msg', {
          defaultValue: 'The lab test result has been added to this project.',
        }),
      });
      setShowCreateTest(false);
      invalidateTests();
    },
    onError: toastError,
  });

  const recordTestMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: TestResultRecordPayload }) =>
      recordTestResult(id, payload),
    onSuccess: (updated) => {
      const raisedNcr = !!updated.raised_ncr_id;
      addToast({
        type: raisedNcr ? 'warning' : 'success',
        title: raisedNcr
          ? t('construction_control.test.record_ncr_title', {
              defaultValue: 'Result recorded - NCR raised',
            })
          : t('construction_control.test.record_title', {
              defaultValue: 'Result recorded',
            }),
        message: raisedNcr
          ? t('construction_control.test.record_ncr_msg', {
              defaultValue: 'A non-conformance report was raised automatically and linked.',
            })
          : t('construction_control.test.record_ok_msg', {
              defaultValue: 'The test passed.',
            }),
      });
      setRecordTarget(null);
      invalidateTests();
    },
    onError: toastError,
  });

  return (
    <div className="space-y-8">
      {/* ── Material records ─────────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionToolbar
          title={t('construction_control.materials_heading', {
            defaultValue: 'Material records',
          })}
          count={materials.length}
        >
          <Button
            variant="primary"
            size="sm"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => setShowCreateMaterial(true)}
          >
            {t('construction_control.material.new', { defaultValue: 'New material' })}
          </Button>
        </SectionToolbar>

        {materialsQuery.isLoading ? (
          <SkeletonTable rows={4} columns={5} />
        ) : materialsQuery.isError ? (
          <Card>
            <div className="p-6 text-sm text-semantic-error">
              {t('construction_control.material.load_error', {
                defaultValue: 'Could not load material records. Please try again.',
              })}
            </div>
          </Card>
        ) : materials.length === 0 ? (
          <EmptyState
            icon={<Boxes size={26} strokeWidth={1.5} />}
            title={t('construction_control.material.empty_title', {
              defaultValue: 'No material records yet',
            })}
            description={t('construction_control.material.empty_desc', {
              defaultValue:
                'Material records carry the EN 10204 conformity certificate, CE / UKCA marking and batch / heat / lot traceability. A rejected submittal automatically opens a non-conformance report.',
            })}
            action={{
              label: t('construction_control.material.new', { defaultValue: 'New material' }),
              onClick: () => setShowCreateMaterial(true),
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
                      {t('construction_control.col.material', { defaultValue: 'Material' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.certificate', { defaultValue: 'Certificate' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.traceability', {
                        defaultValue: 'Traceability',
                      })}
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
                  {materials.map((m) => {
                    const canReview = MATERIAL_REVIEWABLE.includes(m.status);
                    return (
                      <tr
                        key={m.id}
                        className="border-b border-border-light/60 last:border-b-0 align-top"
                        data-testid={`cc-material-row-${m.id}`}
                      >
                        <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                          {m.record_number}
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-content-primary">{m.name}</div>
                          {m.spec_grade && (
                            <div className="text-xs text-content-tertiary">{m.spec_grade}</div>
                          )}
                          {(m.manufacturer || m.supplier) && (
                            <div className="text-xs text-content-tertiary">
                              {[m.manufacturer, m.supplier].filter(Boolean).join(' / ')}
                            </div>
                          )}
                          <div className="mt-1">
                            <ElementLinks elements={m.elements} />
                          </div>
                        </td>
                        <td className="px-4 py-3 text-content-secondary">
                          {m.cert_type ? (
                            <div>
                              <span className="font-medium text-content-primary">
                                {m.cert_type}
                              </span>
                              {m.cert_number ? ` ${m.cert_number}` : ''}
                              {(m.ce_marking || m.ukca_marking) && (
                                <div className="mt-0.5 flex gap-1">
                                  {m.ce_marking && (
                                    <Badge variant="neutral" size="sm">
                                      CE
                                    </Badge>
                                  )}
                                  {m.ukca_marking && (
                                    <Badge variant="neutral" size="sm">
                                      UKCA
                                    </Badge>
                                  )}
                                </div>
                              )}
                            </div>
                          ) : (
                            <span className="text-content-tertiary">
                              {t('construction_control.none', { defaultValue: '-' })}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-content-secondary">
                          {formatTraceability(m, t) || (
                            <span className="text-content-tertiary">
                              {t('construction_control.none', { defaultValue: '-' })}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            <StatusBadge status={m.status} variants={MATERIAL_STATUS_VARIANTS} />
                            {m.is_expired && (
                              <Badge variant="warning" size="sm">
                                {t('construction_control.material.expired', {
                                  defaultValue: 'Expired',
                                })}
                              </Badge>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            {m.raised_ncr_id && (
                              <span className="inline-flex items-center gap-1 rounded-md bg-semantic-error-bg px-2 py-0.5 text-2xs font-medium text-semantic-error">
                                <AlertOctagon className="h-3 w-3" />
                                {t('construction_control.ncr_linked', { defaultValue: 'NCR' })}
                              </span>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setMaterialFilter(m.id)}
                            >
                              {t('construction_control.material.view_tests', {
                                defaultValue: 'Tests',
                              })}
                            </Button>
                            {canReview && (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => setReviewTarget(m)}
                              >
                                {t('construction_control.material.review', {
                                  defaultValue: 'Review',
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
      </section>

      {/* ── Lab test results ─────────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionToolbar
          title={t('construction_control.tests_heading', { defaultValue: 'Lab test results' })}
          count={tests.length}
        >
          <Button
            variant="primary"
            size="sm"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => setShowCreateTest(true)}
          >
            {t('construction_control.test.new', { defaultValue: 'New test result' })}
          </Button>
        </SectionToolbar>

        {materialFilter && (
          <div className="flex items-center gap-2 text-xs text-content-secondary">
            <span>
              {t('construction_control.test.filtered_by', {
                defaultValue: 'Showing tests for {{name}}',
                name: materialById.get(materialFilter)?.record_number ?? materialFilter,
              })}
            </span>
            <button
              type="button"
              onClick={() => setMaterialFilter('')}
              className="inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-0.5 text-2xs text-content-secondary hover:bg-surface-secondary"
              data-testid="cc-test-clear-filter"
            >
              <X className="h-3 w-3" />
              {t('construction_control.clear_filter', { defaultValue: 'Clear' })}
            </button>
          </div>
        )}

        {testsQuery.isLoading ? (
          <SkeletonTable rows={4} columns={5} />
        ) : testsQuery.isError ? (
          <Card>
            <div className="p-6 text-sm text-semantic-error">
              {t('construction_control.test.load_error', {
                defaultValue: 'Could not load lab test results. Please try again.',
              })}
            </div>
          </Card>
        ) : tests.length === 0 ? (
          <EmptyState
            icon={<FlaskConical size={26} strokeWidth={1.5} />}
            title={t('construction_control.test.empty_title', {
              defaultValue: 'No lab test results yet',
            })}
            description={t('construction_control.test.empty_desc', {
              defaultValue:
                'Lab test results capture the sample, method, laboratory and ISO/IEC 17025 accreditation, and judge the measured value against the criterion. A failed test automatically opens a non-conformance report.',
            })}
            action={{
              label: t('construction_control.test.new', { defaultValue: 'New test result' }),
              onClick: () => setShowCreateTest(true),
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
                      {t('construction_control.col.method', { defaultValue: 'Method' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.measured', { defaultValue: 'Measured' })}
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
                  {tests.map((x) => {
                    const canRecord = x.status === 'draft';
                    const material = x.material_record_id
                      ? materialById.get(x.material_record_id)
                      : undefined;
                    return (
                      <tr
                        key={x.id}
                        className="border-b border-border-light/60 last:border-b-0 align-top"
                        data-testid={`cc-test-row-${x.id}`}
                      >
                        <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                          {x.result_number}
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-content-primary">{x.title}</div>
                          {x.lab_name && (
                            <div className="text-xs text-content-tertiary">
                              {x.lab_name}
                              {x.is_accredited && x.lab_accreditation
                                ? ` (ISO/IEC 17025 ${x.lab_accreditation})`
                                : ''}
                            </div>
                          )}
                          {material && (
                            <div className="text-2xs text-content-tertiary">
                              {t('construction_control.test.for_material', {
                                defaultValue: 'Material {{number}}',
                                number: material.record_number,
                              })}
                            </div>
                          )}
                          <div className="mt-1">
                            <ElementLinks elements={x.elements} />
                          </div>
                        </td>
                        <td className="px-4 py-3 text-content-secondary">
                          {x.test_method || (
                            <span className="text-content-tertiary">
                              {t('construction_control.none', { defaultValue: '-' })}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-content-secondary whitespace-nowrap">
                          {x.measured_value ? (
                            <span>
                              {x.measured_value}
                              {x.unit ? ` ${x.unit}` : ''}
                            </span>
                          ) : (
                            <span className="text-content-tertiary">
                              {t('construction_control.none', { defaultValue: '-' })}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            <StatusBadge status={x.status} variants={TEST_STATUS_VARIANTS} />
                            {x.result && (
                              <span className="text-2xs text-content-tertiary">
                                {t(`construction_control.result.${x.result}`, {
                                  defaultValue: x.result,
                                })}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            {x.raised_ncr_id && (
                              <span className="inline-flex items-center gap-1 rounded-md bg-semantic-error-bg px-2 py-0.5 text-2xs font-medium text-semantic-error">
                                <AlertOctagon className="h-3 w-3" />
                                {t('construction_control.ncr_linked', { defaultValue: 'NCR' })}
                              </span>
                            )}
                            {canRecord && (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => setRecordTarget(x)}
                              >
                                {t('construction_control.test.record', {
                                  defaultValue: 'Record result',
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
      </section>

      {showCreateMaterial && (
        <CreateMaterialModal
          projectId={projectId}
          isPending={createMaterialMutation.isPending}
          onClose={() => setShowCreateMaterial(false)}
          onSubmit={(payload) => createMaterialMutationOnce(() => createMaterialMutation.mutateAsync(payload))}
        />
      )}

      {reviewTarget && (
        <ReviewMaterialModal
          material={reviewTarget}
          isPending={reviewMaterialMutation.isPending}
          onClose={() => setReviewTarget(null)}
          onSubmit={(payload) =>
            reviewMaterialMutation.mutate({ id: reviewTarget.id, payload })
          }
        />
      )}

      {showCreateTest && (
        <CreateTestModal
          projectId={projectId}
          materials={materials}
          defaultMaterialId={materialFilter}
          isPending={createTestMutation.isPending}
          onClose={() => setShowCreateTest(false)}
          onSubmit={(payload) => createTestMutationOnce(() => createTestMutation.mutateAsync(payload))}
        />
      )}

      {recordTarget && (
        <RecordTestModal
          test={recordTarget}
          isPending={recordTestMutation.isPending}
          onClose={() => setRecordTarget(null)}
          onSubmit={(payload) => recordTestMutation.mutate({ id: recordTarget.id, payload })}
        />
      )}
    </div>
  );
}

function formatTraceability(
  m: MaterialRecord,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  const parts: string[] = [];
  if (m.batch_number)
    parts.push(`${t('construction_control.field.batch_short', { defaultValue: 'batch' })} ${m.batch_number}`);
  if (m.heat_number)
    parts.push(`${t('construction_control.field.heat_short', { defaultValue: 'heat' })} ${m.heat_number}`);
  if (m.lot_number)
    parts.push(`${t('construction_control.field.lot_short', { defaultValue: 'lot' })} ${m.lot_number}`);
  return parts.join(' / ');
}

// ── Create-material modal ────────────────────────────────────────────────────

interface MaterialForm {
  name: string;
  spec_grade: string;
  manufacturer: string;
  supplier: string;
  cert_type: '' | CertType;
  cert_number: string;
  cert_issuer: string;
  ce_marking: boolean;
  ukca_marking: boolean;
  valid_until: string;
  batch_number: string;
  heat_number: string;
  lot_number: string;
  quantity: string;
  unit: string;
  status: 'draft' | 'submitted';
}

const EMPTY_MATERIAL: MaterialForm = {
  name: '',
  spec_grade: '',
  manufacturer: '',
  supplier: '',
  cert_type: '',
  cert_number: '',
  cert_issuer: '',
  ce_marking: false,
  ukca_marking: false,
  valid_until: '',
  batch_number: '',
  heat_number: '',
  lot_number: '',
  quantity: '',
  unit: '',
  status: 'submitted',
};

function CreateMaterialModal({
  projectId,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: MaterialCreatePayload) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<MaterialForm>(EMPTY_MATERIAL);
  const [touched, setTouched] = useState(false);
  const canSubmit = form.name.trim().length > 0;

  const set = <K extends keyof MaterialForm>(key: K, value: MaterialForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      project_id: projectId,
      name: form.name.trim(),
      spec_grade: form.spec_grade.trim() || null,
      manufacturer: form.manufacturer.trim() || null,
      supplier: form.supplier.trim() || null,
      cert_type: form.cert_type || null,
      cert_number: form.cert_number.trim() || null,
      cert_issuer: form.cert_issuer.trim() || null,
      ce_marking: form.ce_marking,
      ukca_marking: form.ukca_marking,
      valid_until: form.valid_until || null,
      batch_number: form.batch_number.trim() || null,
      heat_number: form.heat_number.trim() || null,
      lot_number: form.lot_number.trim() || null,
      quantity: form.quantity.trim() || null,
      unit: form.unit.trim() || null,
      status: form.status,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.material.new', { defaultValue: 'New material' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div>
          <label htmlFor="cc-mat-name" className={labelCls}>
            {t('construction_control.col.material', { defaultValue: 'Material' })}
          </label>
          <input
            id="cc-mat-name"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.material.name_ph', {
              defaultValue: 'e.g. Reinforcing steel B500B',
            })}
          />
          {touched && !canSubmit && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.field.name_required', {
                defaultValue: 'A material name is required.',
              })}
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-mat-grade" className={labelCls}>
              {t('construction_control.field.spec_grade', {
                defaultValue: 'Specification / grade',
              })}
            </label>
            <input
              id="cc-mat-grade"
              value={form.spec_grade}
              onChange={(e) => set('spec_grade', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.spec_grade_ph', {
                defaultValue: 'e.g. EN 10080',
              })}
            />
          </div>
          <div>
            <label htmlFor="cc-mat-manufacturer" className={labelCls}>
              {t('construction_control.field.manufacturer', { defaultValue: 'Manufacturer' })}
            </label>
            <input
              id="cc-mat-manufacturer"
              value={form.manufacturer}
              onChange={(e) => set('manufacturer', e.target.value)}
              className={inputCls}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-mat-supplier" className={labelCls}>
              {t('construction_control.field.supplier', { defaultValue: 'Supplier' })}
            </label>
            <input
              id="cc-mat-supplier"
              value={form.supplier}
              onChange={(e) => set('supplier', e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="cc-mat-status" className={labelCls}>
              {t('construction_control.col.status', { defaultValue: 'Status' })}
            </label>
            <select
              id="cc-mat-status"
              value={form.status}
              onChange={(e) => set('status', e.target.value as 'draft' | 'submitted')}
              className={inputCls}
            >
              <option value="draft">
                {t('construction_control.material_status.draft', { defaultValue: 'Draft' })}
              </option>
              <option value="submitted">
                {t('construction_control.material_status.submitted', {
                  defaultValue: 'Submitted for review',
                })}
              </option>
            </select>
          </div>
        </div>

        {/* Conformity certificate (EN 10204 grade + EU CPR / UKCA markings). */}
        <fieldset className="rounded-lg border border-border-light p-3">
          <legend className="px-1 text-xs font-medium text-content-secondary">
            {t('construction_control.material.certificate_legend', {
              defaultValue: 'Conformity certificate (EN 10204)',
            })}
          </legend>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="cc-mat-cert-type" className={labelCls}>
                {t('construction_control.field.cert_type', { defaultValue: 'Certificate type' })}
              </label>
              <select
                id="cc-mat-cert-type"
                value={form.cert_type}
                onChange={(e) => set('cert_type', e.target.value as '' | CertType)}
                className={inputCls}
              >
                <option value="">
                  {t('construction_control.field.no_cert', { defaultValue: 'None' })}
                </option>
                {CERT_TYPES.map((c) => (
                  <option key={c} value={c}>
                    {CERT_TYPE_LABEL[c]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="cc-mat-cert-number" className={labelCls}>
                {t('construction_control.field.cert_number', {
                  defaultValue: 'Certificate number',
                })}
              </label>
              <input
                id="cc-mat-cert-number"
                value={form.cert_number}
                onChange={(e) => set('cert_number', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="cc-mat-cert-issuer" className={labelCls}>
                {t('construction_control.field.cert_issuer', { defaultValue: 'Issued by' })}
              </label>
              <input
                id="cc-mat-cert-issuer"
                value={form.cert_issuer}
                onChange={(e) => set('cert_issuer', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="cc-mat-valid-until" className={labelCls}>
                {t('construction_control.field.valid_until', { defaultValue: 'Valid until' })}
              </label>
              <input
                id="cc-mat-valid-until"
                type="date"
                value={form.valid_until}
                onChange={(e) => set('valid_until', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm text-content-secondary">
              <input
                type="checkbox"
                checked={form.ce_marking}
                onChange={(e) => set('ce_marking', e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              {t('construction_control.field.ce_marking', { defaultValue: 'CE marking' })}
            </label>
            <label className="flex items-center gap-2 text-sm text-content-secondary">
              <input
                type="checkbox"
                checked={form.ukca_marking}
                onChange={(e) => set('ukca_marking', e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              {t('construction_control.field.ukca_marking', { defaultValue: 'UKCA marking' })}
            </label>
          </div>
        </fieldset>

        {/* Traceability (batch / heat / lot). */}
        <fieldset className="rounded-lg border border-border-light p-3">
          <legend className="px-1 text-xs font-medium text-content-secondary">
            {t('construction_control.material.traceability_legend', {
              defaultValue: 'Traceability',
            })}
          </legend>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="cc-mat-batch" className={labelCls}>
                {t('construction_control.field.batch', { defaultValue: 'Batch number' })}
              </label>
              <input
                id="cc-mat-batch"
                value={form.batch_number}
                onChange={(e) => set('batch_number', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="cc-mat-heat" className={labelCls}>
                {t('construction_control.field.heat', { defaultValue: 'Heat number' })}
              </label>
              <input
                id="cc-mat-heat"
                value={form.heat_number}
                onChange={(e) => set('heat_number', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="cc-mat-lot" className={labelCls}>
                {t('construction_control.field.lot', { defaultValue: 'Lot number' })}
              </label>
              <input
                id="cc-mat-lot"
                value={form.lot_number}
                onChange={(e) => set('lot_number', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="cc-mat-qty" className={labelCls}>
                {t('construction_control.field.quantity', { defaultValue: 'Quantity' })}
              </label>
              <input
                id="cc-mat-qty"
                value={form.quantity}
                onChange={(e) => set('quantity', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="cc-mat-unit" className={labelCls}>
                {t('construction_control.field.unit', { defaultValue: 'Unit' })}
              </label>
              <input
                id="cc-mat-unit"
                value={form.unit}
                onChange={(e) => set('unit', e.target.value)}
                className={inputCls}
                placeholder={t('construction_control.field.unit_ph', { defaultValue: 'e.g. t, m3' })}
              />
            </div>
          </div>
        </fieldset>
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
          {t('construction_control.material.create', { defaultValue: 'Create material' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Review-material modal ────────────────────────────────────────────────────

const DECISION_OPTIONS: { value: ResultDecision; icon: typeof CheckCircle2; tone: string }[] = [
  { value: 'pass', icon: CheckCircle2, tone: 'text-semantic-success border-semantic-success/40' },
  { value: 'fail', icon: XCircle, tone: 'text-semantic-error border-semantic-error/40' },
  { value: 'conditional', icon: AlertCircle, tone: 'text-[#b45309] border-amber-400/50' },
];

const DECISION_LABEL: Record<ResultDecision, string> = {
  pass: 'Accept',
  fail: 'Reject',
  conditional: 'Conditional',
};

function ReviewMaterialModal({
  material,
  isPending,
  onClose,
  onSubmit,
}: {
  material: MaterialRecord;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: MaterialReviewPayload) => void;
}) {
  const { t } = useTranslation();
  const [decision, setDecision] = useState<ResultDecision>('pass');
  const [notes, setNotes] = useState('');

  return (
    <ModalShell
      title={t('construction_control.material.review_for', {
        defaultValue: 'Review material {{number}}',
        number: material.record_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{material.name}</p>
        {material.is_expired && (
          <p className="flex items-start gap-1.5 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-[#b45309]">
            <AlertOctagon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {t('construction_control.material.expired_warning', {
              defaultValue:
                'The certificate validity window for this material has lapsed. Review carefully before accepting.',
            })}
          </p>
        )}
        <div>
          <span className={labelCls}>
            {t('construction_control.field.decision', { defaultValue: 'Decision' })}
          </span>
          <div className="grid grid-cols-3 gap-2">
            {DECISION_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const selected = decision === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDecision(opt.value)}
                  data-testid={`cc-decision-${opt.value}`}
                  className={`flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-3 text-center transition-all ${
                    selected
                      ? `${opt.tone} ring-2 ring-oe-blue/20`
                      : 'border-border bg-surface-primary text-content-tertiary hover:bg-surface-secondary'
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  <span className="text-xs font-medium">
                    {t(`construction_control.decision.${opt.value}`, {
                      defaultValue: DECISION_LABEL[opt.value],
                    })}
                  </span>
                </button>
              );
            })}
          </div>
          {decision !== 'pass' && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-content-tertiary">
              <AlertOctagon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-error" />
              {t('construction_control.material.review_ncr_hint', {
                defaultValue:
                  'A material non-conformance report will be raised automatically and linked to this record.',
              })}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="cc-review-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-review-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.material.review_notes_ph', {
              defaultValue: 'Conformity findings, deviations, conditions of acceptance...',
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
          onClick={() => onSubmit({ decision, notes: notes.trim() || null })}
          loading={isPending}
          disabled={isPending}
        >
          {t('construction_control.material.save_review', { defaultValue: 'Save decision' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Create-test modal ────────────────────────────────────────────────────────

interface TestForm {
  title: string;
  material_record_id: string;
  test_method: string;
  sample_id: string;
  lab_name: string;
  lab_accreditation: string;
  is_accredited: boolean;
  measured_value: string;
  unit: string;
  specimen_age_days: string;
}

const EMPTY_TEST: TestForm = {
  title: '',
  material_record_id: '',
  test_method: '',
  sample_id: '',
  lab_name: '',
  lab_accreditation: '',
  is_accredited: false,
  measured_value: '',
  unit: '',
  specimen_age_days: '',
};

function CreateTestModal({
  projectId,
  materials,
  defaultMaterialId,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  materials: MaterialRecord[];
  defaultMaterialId: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: TestResultCreatePayload) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<TestForm>({
    ...EMPTY_TEST,
    material_record_id: defaultMaterialId || '',
  });
  const [touched, setTouched] = useState(false);
  const canSubmit = form.title.trim().length > 0;

  const set = <K extends keyof TestForm>(key: K, value: TestForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    const ageParsed = Number.parseInt(form.specimen_age_days, 10);
    onSubmit({
      project_id: projectId,
      title: form.title.trim(),
      material_record_id: form.material_record_id || null,
      test_method: form.test_method.trim() || null,
      sample_id: form.sample_id.trim() || null,
      lab_name: form.lab_name.trim() || null,
      lab_accreditation: form.lab_accreditation.trim() || null,
      is_accredited: form.is_accredited,
      measured_value: form.measured_value.trim() || null,
      unit: form.unit.trim() || null,
      specimen_age_days: Number.isFinite(ageParsed) && ageParsed >= 0 ? ageParsed : null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.test.new', { defaultValue: 'New test result' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div>
          <label htmlFor="cc-test-title" className={labelCls}>
            {t('construction_control.col.title', { defaultValue: 'Title' })}
          </label>
          <input
            id="cc-test-title"
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.test.title_ph', {
              defaultValue: 'e.g. Concrete cube compressive strength - 28 day',
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
            <label htmlFor="cc-test-material" className={labelCls}>
              {t('construction_control.field.material_link', {
                defaultValue: 'Material record (optional)',
              })}
            </label>
            <select
              id="cc-test-material"
              value={form.material_record_id}
              onChange={(e) => set('material_record_id', e.target.value)}
              className={inputCls}
            >
              <option value="">
                {t('construction_control.field.no_material', { defaultValue: 'No material link' })}
              </option>
              {materials.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.record_number} - {m.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-test-method" className={labelCls}>
              {t('construction_control.col.method', { defaultValue: 'Method' })}
            </label>
            <input
              id="cc-test-method"
              value={form.test_method}
              onChange={(e) => set('test_method', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.method_ph', {
                defaultValue: 'e.g. EN 12390-3',
              })}
            />
          </div>
        </div>

        {/* Laboratory + ISO/IEC 17025 accreditation. */}
        <fieldset className="rounded-lg border border-border-light p-3">
          <legend className="px-1 text-xs font-medium text-content-secondary">
            {t('construction_control.test.lab_legend', {
              defaultValue: 'Laboratory (ISO/IEC 17025)',
            })}
          </legend>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="cc-test-lab" className={labelCls}>
                {t('construction_control.field.lab_name', { defaultValue: 'Laboratory' })}
              </label>
              <input
                id="cc-test-lab"
                value={form.lab_name}
                onChange={(e) => set('lab_name', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="cc-test-accred" className={labelCls}>
                {t('construction_control.field.lab_accreditation', {
                  defaultValue: 'Accreditation reference',
                })}
              </label>
              <input
                id="cc-test-accred"
                value={form.lab_accreditation}
                onChange={(e) => set('lab_accreditation', e.target.value)}
                className={inputCls}
                placeholder={t('construction_control.field.lab_accreditation_ph', {
                  defaultValue: 'e.g. UKAS 1234',
                })}
              />
            </div>
          </div>
          <div className="mt-3">
            <label className="flex items-center gap-2 text-sm text-content-secondary">
              <input
                type="checkbox"
                checked={form.is_accredited}
                onChange={(e) => set('is_accredited', e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              {t('construction_control.field.is_accredited', {
                defaultValue: 'Laboratory is accredited for this method',
              })}
            </label>
          </div>
        </fieldset>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="cc-test-sample" className={labelCls}>
              {t('construction_control.field.sample_id', { defaultValue: 'Sample ID' })}
            </label>
            <input
              id="cc-test-sample"
              value={form.sample_id}
              onChange={(e) => set('sample_id', e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="cc-test-measured" className={labelCls}>
              {t('construction_control.field.measured_value', { defaultValue: 'Measured value' })}
            </label>
            <input
              id="cc-test-measured"
              value={form.measured_value}
              onChange={(e) => set('measured_value', e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="cc-test-unit" className={labelCls}>
              {t('construction_control.field.unit', { defaultValue: 'Unit' })}
            </label>
            <input
              id="cc-test-unit"
              value={form.unit}
              onChange={(e) => set('unit', e.target.value)}
              className={inputCls}
              placeholder={t('construction_control.field.unit_test_ph', { defaultValue: 'e.g. MPa' })}
            />
          </div>
        </div>

        <div className="sm:w-1/3">
          <label htmlFor="cc-test-age" className={labelCls}>
            {t('construction_control.field.specimen_age', {
              defaultValue: 'Specimen age (days)',
            })}
          </label>
          <input
            id="cc-test-age"
            type="number"
            min={0}
            value={form.specimen_age_days}
            onChange={(e) => set('specimen_age_days', e.target.value)}
            className={inputCls}
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
          disabled={isPending || !canSubmit}
          icon={<Plus className="h-4 w-4" />}
        >
          {t('construction_control.test.create', { defaultValue: 'Create test result' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Record-test-result modal ─────────────────────────────────────────────────

function RecordTestModal({
  test,
  isPending,
  onClose,
  onSubmit,
}: {
  test: TestResult;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: TestResultRecordPayload) => void;
}) {
  const { t } = useTranslation();
  const [result, setResult] = useState<ResultDecision>('pass');
  const [measuredValue, setMeasuredValue] = useState(test.measured_value ?? '');
  const [notes, setNotes] = useState('');

  return (
    <ModalShell
      title={t('construction_control.test.record_for', {
        defaultValue: 'Record result for {{number}}',
        number: test.result_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{test.title}</p>
        {test.test_method && (
          <p className="text-xs text-content-tertiary">
            {t('construction_control.test.method_line', {
              defaultValue: 'Method: {{method}}',
              method: test.test_method,
            })}
          </p>
        )}
        <div>
          <span className={labelCls}>
            {t('construction_control.field.outcome', { defaultValue: 'Outcome' })}
          </span>
          <div className="grid grid-cols-3 gap-2">
            {DECISION_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const selected = result === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setResult(opt.value)}
                  data-testid={`cc-test-result-${opt.value}`}
                  className={`flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-3 text-center transition-all ${
                    selected
                      ? `${opt.tone} ring-2 ring-oe-blue/20`
                      : 'border-border bg-surface-primary text-content-tertiary hover:bg-surface-secondary'
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  <span className="text-xs font-medium">
                    {t(`construction_control.result.${opt.value}`, { defaultValue: opt.value })}
                  </span>
                </button>
              );
            })}
          </div>
          {result !== 'pass' && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-content-tertiary">
              <AlertOctagon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-error" />
              {t('construction_control.test.record_ncr_hint', {
                defaultValue:
                  'A non-conformance report will be raised automatically and linked to this test.',
              })}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="cc-test-record-measured" className={labelCls}>
            {t('construction_control.field.measured_value', { defaultValue: 'Measured value' })}
            {test.unit ? ` (${test.unit})` : ''}
          </label>
          <input
            id="cc-test-record-measured"
            value={measuredValue}
            onChange={(e) => setMeasuredValue(e.target.value)}
            className={inputCls}
          />
        </div>

        <div>
          <label htmlFor="cc-test-record-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-test-record-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.test.record_notes_ph', {
              defaultValue: 'Observations, deviations, follow-up actions...',
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
          onClick={() =>
            onSubmit({
              result,
              measured_value: measuredValue.trim() || null,
              notes: notes.trim() || null,
            })
          }
          loading={isPending}
          disabled={isPending}
        >
          {t('construction_control.test.save_result', { defaultValue: 'Save result' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Modal primitives (local helpers) ─────────────────────────────────────────

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

export default MaterialsLabsSection;
