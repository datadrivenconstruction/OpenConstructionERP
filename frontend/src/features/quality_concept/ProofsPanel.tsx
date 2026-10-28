// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The proof register: which evidence each package owes, who delivers it, by
// when, and how far it has come. A proof is never ticked off by hand. Its
// state is read from the records linked to it, and the only decisions a
// person takes are to accept a delivered proof or to waive one with a reason.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ClipboardCheck, Pencil, Plus, ListPlus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtDate, fmtNumber } from '@/shared/lib/formatters';

import {
  createProof,
  decideWaiver,
  deleteProof,
  generateProofs,
  patchProof,
  proofAction,
  requestWaiver,
  type AcceptanceUnit,
  type Proof,
  type QuantityRule,
} from './api';
import { EvidenceLinks } from './EvidenceLinks';
import { ExportButtons } from './ExportButtons';
import { useAcceptanceUnits, useCoverage, useProofs, useQcWrite, useStageMatrix } from './hooks';
import { ClosedReasons, SharedReasons } from './ClosedReasons';
import { OptionPicker } from './OptionPicker';
import { PermitConditionsSection } from './PermitConditionsSection';
import { DELIVERER_ROLE, PROOF_ACTION, PROOF_STATE, REQUIRED_BY_KIND, gate, nameIn, vocab, type TFn } from './labels';
import { packageName, type PanelProps } from './panel';
import {
  Field,
  FindingList,
  FormDialog,
  Hint,
  PROOF_TONE,
  RefusalNote,
  ReviewBadge,
  Section,
  StateBadge,
  VocabSelect,
  inputCls,
} from './QualityBits';
import { percent, pointsString, proofActions, refChange, sharedReasons, waiverPending, type ProofAction } from './rules';

const DELIVERERS = ['designer', 'contractor', 'supplier', 'independent_expert', 'owner', 'authority'] as const;
const DUE_KINDS = ['stage', 'acceptance_unit', 'activity', 'date'] as const;

/** How a quantity rule reads: one proof per so much of a unit, or nothing when the proof is a single document. */
function QuantityRuleText({ rule }: { rule: QuantityRule | null | undefined }) {
  const { t } = useTranslation();
  if (!rule?.per_quantity) return null;
  return (
    <span className="text-xs text-content-tertiary" data-testid="quantity-rule">
      {t('qualityConcept.proofs.quantity_rule', {
        defaultValue: 'One per {{quantity}} {{unit}}',
        quantity: fmtNumber(rule.per_quantity, 0),
        unit: rule.unit ?? '',
      })}
    </span>
  );
}

const proofButtons = (p: Proof): string[] => ['edit', 'delete', ...proofActions(p)];

export function ProofsPanel(props: PanelProps) {
  const { projectId, concept, catalogue, labels, personName, editable, openTab } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const proofs = useProofs(projectId);
  const coverage = useCoverage(projectId);
  const units = useAcceptanceUnits(projectId);
  const matrix = useStageMatrix(projectId);
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState<Proof | 'new' | null>(null);
  const [waiving, setWaiving] = useState<Proof | null>(null);
  const [removing, setRemoving] = useState<Proof | null>(null);
  const [linksOf, setLinksOf] = useState<string | null>(null);

  const dueName = useMemo(() => {
    const unitById = new Map<string, AcceptanceUnit>((units.data ?? []).map((u) => [u.id, u]));
    return (kind: string, ref: string): string => {
      if (kind === 'stage') return nameIn(labels, catalogue?.commissioning_stages, ref);
      if (kind === 'acceptance_unit') {
        const u = unitById.get(ref);
        return u ? [u.code, u.title].filter(Boolean).join(' ') : ref;
      }
      if (kind === 'date') return fmtDate(ref);
      return ref;
    };
  }, [units.data, labels, catalogue]);

  if (proofs.isLoading) return <SkeletonTable rows={6} columns={5} />;
  if (proofs.isError) {
    return (
      <ErrorState
        title={t('qualityConcept.proofs.load_failed', { defaultValue: 'The proofs could not be loaded' })}
        hint={getErrorMessage(proofs.error)}
        onRetry={() => proofs.refetch()}
      />
    );
  }
  const rows = proofs.data ?? [];
  const packages = concept.applicable_packages;
  const hasStages = (matrix.data?.stages ?? []).length > 0;

  const run = (proof: Proof, action: ProofAction) => {
    if (action === 'request_waiver') setWaiving(proof);
    else if (action === 'approve_waiver') write.send(() => decideWaiver(projectId, proof.id, true));
    else if (action === 'reject_waiver') write.send(() => decideWaiver(projectId, proof.id, false));
    else write.send(() => proofAction(projectId, proof.id, action));
  };

  const toolbar = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <ExportButtons
        projectId={projectId}
        what="proofs"
        label={t('qualityConcept.export.proof_list', { defaultValue: 'Proof list' })}
      />
      <ExportButtons
        projectId={projectId}
        what="proof_matrix"
        label={t('qualityConcept.export.proof_matrix', { defaultValue: 'Proof matrix' })}
      />
      <Button variant="secondary" icon={<Plus size={14} />} disabled={!editable} onClick={() => setEditing('new')} data-testid="proof-add">
        {t('qualityConcept.proofs.add', { defaultValue: 'Add proof' })}
      </Button>
      <Button icon={<ListPlus size={14} />} disabled={!editable || packages.length === 0} onClick={() => setGenerating(true)} data-testid="proof-generate">
        {t('qualityConcept.proofs.generate', { defaultValue: 'Propose proofs for a package' })}
      </Button>
    </div>
  );

  const dialogs = (
    <>
      {generating && <GenerateDialog {...props} dueName={dueName} onClose={() => setGenerating(false)} />}
      {editing && (
        <ProofDialog
          {...props}
          proof={editing === 'new' ? null : editing}
          units={units.data ?? []}
          stageCodes={(matrix.data?.stages ?? []).map((s) => s.code)}
          onClose={() => setEditing(null)}
        />
      )}
      {waiving && <WaiverDialog {...props} proof={waiving} onClose={() => setWaiving(null)} />}
      <ConfirmDialog
        open={!!removing}
        variant="danger"
        loading={write.pending}
        title={t('qualityConcept.proofs.remove_title', { defaultValue: 'Remove this proof?' })}
        message={t('qualityConcept.proofs.remove_body', {
          defaultValue: 'The proof is taken out of the plan. The linked records themselves stay where they are.',
        })}
        confirmLabel={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('qualityConcept.common.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const row = removing;
          setRemoving(null);
          if (row) write.send(() => deleteProof(projectId, row.id));
        }}
      />
    </>
  );

  if (rows.length === 0) {
    const noPackages = packages.length === 0;
    return (
      <div className="space-y-4" data-testid="proofs-panel">
        <RefusalNote refusal={write.refusal} />
        <EmptyState
          icon={<ClipboardCheck size={28} />}
          title={t('qualityConcept.proofs.empty_title', { defaultValue: 'No proofs planned yet' })}
          description={
            noPackages
              ? t('qualityConcept.proofs.empty_no_packages', {
                  defaultValue:
                    'Proofs are planned per work package: test results, certificates, as-built documents. Name the packages on the Concept tab first.',
                })
              : !hasStages
                ? t('qualityConcept.proofs.empty_no_stages', {
                    defaultValue:
                      'Each proof is due at a commissioning stage or an acceptance. Set up the stages on the Commissioning stages tab first.',
                  })
                : t('qualityConcept.proofs.empty_body', {
                    defaultValue:
                      'Let the catalogue propose the usual proofs for a package, then keep the ones that apply. You can also add a single proof by hand.',
                  })
          }
          action={
            noPackages
              ? {
                  label: t('qualityConcept.proofs.to_concept', { defaultValue: 'Name the packages' }),
                  onClick: () => openTab('concept'),
                }
              : !hasStages
                ? {
                    label: t('qualityConcept.proofs.to_stages', { defaultValue: 'Set up the stages' }),
                    onClick: () => openTab('stages'),
                  }
                : editable
                  ? {
                      label: t('qualityConcept.proofs.generate', { defaultValue: 'Propose proofs for a package' }),
                      onClick: () => setGenerating(true),
                    }
                  : undefined
          }
        />
        {dialogs}
      </div>
    );
  }

  const groups = new Map<string, Proof[]>();
  for (const p of rows) {
    const key = p.package_ref ?? '';
    groups.set(key, [...(groups.get(key) ?? []), p]);
  }

  return (
    <div className="space-y-4" data-testid="proofs-panel">
      {toolbar}
      <RefusalNote refusal={write.refusal} violations={write.violations} />

      <Section
        testId="proof-coverage"
        title={t('qualityConcept.proofs.coverage_title', { defaultValue: 'Coverage per package' })}
        description={t('qualityConcept.proofs.coverage_body', {
          defaultValue: 'A proof counts as done once it is accepted or waived.',
        })}
      >
        <ul className="space-y-2">
          {(coverage.data?.items ?? []).map((c) => (
            <li key={c.package_ref ?? ''} className="text-sm" data-testid="coverage-row">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-content-primary">
                  {c.package_ref
                    ? packageName(concept, c.package_ref)
                    : t('qualityConcept.proofs.no_package', { defaultValue: 'Whole project' })}
                </span>
                <span className="text-content-secondary">
                  {t('qualityConcept.common.of', { defaultValue: '{{done}} of {{total}}', done: c.done, total: c.total })}
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-secondary" aria-hidden>
                <div className="h-full rounded-full bg-semantic-success" style={{ width: `${percent(c.done, c.total)}%` }} />
              </div>
            </li>
          ))}
        </ul>
        <FindingList findings={coverage.data?.findings ?? []} className="mt-3" />
      </Section>

      <PermitConditionsSection projectId={projectId} />

      {[...groups.entries()].map(([ref, list]) => (
        <Section
          key={ref}
          testId="proof-group"
          title={ref ? packageName(concept, ref) : t('qualityConcept.proofs.no_package', { defaultValue: 'Whole project' })}
        >
          <SharedReasons codes={sharedReasons(list, proofButtons)} />
          <ul className="divide-y divide-border-light">
            {list.map((p) => (
              <li key={p.id} className="py-2" data-testid="proof-entry">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-medium text-content-primary">
                    {nameIn(labels, catalogue?.evidence_types, p.evidence_type)}
                  </span>
                  {p.title && <span className="text-content-secondary">{p.title}</span>}
                  <StateBadge map={PROOF_STATE} tones={PROOF_TONE} code={p.state} testId="proof-state" />
                  <span className="text-xs text-content-tertiary" data-testid="proof-count">
                    {t('qualityConcept.proofs.count', {
                      defaultValue: '{{counted}} of {{required}} delivered',
                      counted: p.counted,
                      required: p.required,
                    })}
                  </span>
                  <QuantityRuleText rule={p.quantity_rule} />
                </div>
                <p className="mt-0.5 text-xs text-content-secondary">
                  {t('qualityConcept.proofs.who_when', {
                    defaultValue: 'Delivered by {{who}}. Due at {{kind}}: {{due}}.',
                    who: vocab(t as TFn, DELIVERER_ROLE, p.deliverer_role),
                    kind: vocab(t as TFn, REQUIRED_BY_KIND, p.required_by_kind),
                    due: dueName(p.required_by_kind, p.required_by_ref),
                  })}
                </p>
                {waiverPending(p) && (
                  <p className="mt-1 text-xs text-content-primary" data-testid="waiver-pending">
                    {(p.requested_by_name ?? personName(p.requested_by))
                      ? t('qualityConcept.proofs.waiver_pending_by', {
                          defaultValue: 'Waiver requested by {{name}}: {{reason}}',
                          name: p.requested_by_name ?? personName(p.requested_by),
                          reason: p.decision_rationale,
                        })
                      : t('qualityConcept.proofs.waiver_pending', {
                          defaultValue: 'Waiver requested: {{reason}}',
                          reason: p.decision_rationale,
                        })}
                  </p>
                )}
                {p.decision === 'waived' && p.decision_rationale && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {(p.decided_by_name ?? personName(p.decided_by))
                      ? t('qualityConcept.proofs.waived_by', {
                          defaultValue: 'Waiver approved by {{name}}: {{reason}}',
                          name: p.decided_by_name ?? personName(p.decided_by),
                          reason: p.decision_rationale,
                        })
                      : t('qualityConcept.proofs.waived_because', {
                          defaultValue: 'Waived because: {{reason}}',
                          reason: p.decision_rationale,
                        })}
                  </p>
                )}
                <FindingList findings={p.findings} className="mt-1" />
                <div className="mt-1 flex flex-wrap gap-1">
                  {proofActions(p).map((action) => (
                    <Button
                      key={action}
                      size="sm"
                      variant={action === 'accept' ? 'secondary' : 'ghost'}
                      loading={write.pending}
                      {...gate(t as TFn, p, action)}
                      onClick={() => run(p, action)}
                      data-testid={`proof-action-${action}`}
                    >
                      {vocab(t as TFn, PROOF_ACTION, action)}
                    </Button>
                  ))}
                  <Button size="sm" variant="ghost" onClick={() => setLinksOf(linksOf === p.id ? null : p.id)} aria-expanded={linksOf === p.id} data-testid="proof-links-toggle">
                    {t('qualityConcept.evidence.title', { defaultValue: 'Linked records' })}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    {...gate(t as TFn, p, 'edit', editable)}
                    icon={<Pencil size={14} />}
                    aria-label={t('qualityConcept.common.edit', { defaultValue: 'Edit' })}
                    onClick={() => setEditing(p)}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    {...gate(t as TFn, p, 'delete', editable)}
                    icon={<Trash2 size={14} />}
                    aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
                    onClick={() => setRemoving(p)}
                  />
                  <ClosedReasons row={p} actions={proofButtons(p)} skip={sharedReasons(list, proofButtons)} />
                </div>
                {linksOf === p.id && (
                  <div className="mt-2">
                    <EvidenceLinks
                      projectId={projectId}
                      ownerKind="proof"
                      ownerId={p.id}
                      row={p}
                      allowedKinds={catalogue?.evidence_types.find((e) => e.code === p.evidence_type)?.fulfilled_by}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Section>
      ))}
      {dialogs}
    </div>
  );
}

function GenerateDialog({
  projectId,
  concept,
  catalogue,
  labels,
  dueName,
  onClose,
}: PanelProps & { dueName: (kind: string, ref: string) => string; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const packages = concept.applicable_packages;
  const [pkg, setPkg] = useState(packages[0]?.ref ?? '');
  // The same route previews and creates: without `confirm` it only answers what it would create.
  const preview = useQuery({
    queryKey: ['quality-concept', projectId, 'proof-preview', pkg],
    queryFn: () => generateProofs(projectId, { package_ref: pkg }),
    enabled: !!pkg,
    retry: false,
  });
  const [unchecked, setUnchecked] = useState<Set<string>>(new Set());
  const fresh = (preview.data?.items ?? []).filter((r) => !r.exists);
  const chosen = fresh.filter((r) => !unchecked.has(r.evidence_type)).map((r) => r.evidence_type);
  const problem = preview.isLoading
    ? t('qualityConcept.common.loading', { defaultValue: 'Loading...' })
    : chosen.length === 0
      ? t('qualityConcept.generate.problem_none', { defaultValue: 'Tick at least one proof to create' })
      : null;

  return (
    <FormDialog
      open
      size="lg"
      testId="generate-dialog"
      title={t('qualityConcept.generate.title', { defaultValue: 'Propose proofs for a package' })}
      subtitle={t('qualityConcept.generate.body', {
        defaultValue:
          'The catalogue lists the proofs such a package usually owes. Untick what does not apply. Nothing is created until you confirm.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal ?? (preview.isError ? getErrorMessage(preview.error) : null)}
      problem={problem}
      submitLabel={t('qualityConcept.generate.confirm', { defaultValue: 'Create the ticked proofs: {{n}}', n: chosen.length })}
      onSubmit={() => write.send(() => generateProofs(projectId, { package_ref: pkg, confirm: chosen }), onClose)}
    >
      <Field required label={t('qualityConcept.generate.package', { defaultValue: 'Package' })}>
        <select
          className={inputCls}
          value={pkg}
          onChange={(e) => {
            setPkg(e.target.value);
            setUnchecked(new Set());
          }}
          data-testid="generate-package"
        >
          {packages.map((p) => (
            <option key={p.ref} value={p.ref}>
              {packageName(concept, p.ref)}
            </option>
          ))}
        </select>
      </Field>
      {preview.data && (
        <ul className="divide-y divide-border-light" data-testid="generate-preview">
          {preview.data.items.map((r) => (
            <li key={r.evidence_type} className="flex flex-wrap items-center gap-2 py-1.5 text-sm" data-testid="generate-row">
              <input
                type="checkbox"
                disabled={r.exists}
                checked={!r.exists && !unchecked.has(r.evidence_type)}
                aria-label={nameIn(labels, catalogue?.evidence_types, r.evidence_type)}
                onChange={(e) =>
                  setUnchecked((old) => {
                    const next = new Set(old);
                    if (e.target.checked) next.delete(r.evidence_type);
                    else next.add(r.evidence_type);
                    return next;
                  })
                }
              />
              <span className="font-medium text-content-primary">{nameIn(labels, catalogue?.evidence_types, r.evidence_type)}</span>
              <span className="text-xs text-content-secondary">
                {t('qualityConcept.proofs.who_when', {
                  defaultValue: 'Delivered by {{who}}. Due at {{kind}}: {{due}}.',
                  who: vocab(t as TFn, DELIVERER_ROLE, r.deliverer_role),
                  kind: vocab(t as TFn, REQUIRED_BY_KIND, r.required_by_kind),
                  due: dueName(r.required_by_kind, r.required_by_ref),
                })}
              </span>
              <QuantityRuleText rule={r.quantity_rule} />
              {r.quantity_rule?.per_quantity && <ReviewBadge status={r.quantity_rule_review_status} />}
              {r.exists && (
                <span className="ml-auto text-xs text-content-tertiary">
                  {t('qualityConcept.generate.exists', { defaultValue: 'Already planned' })}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </FormDialog>
  );
}

function ProofDialog({
  projectId,
  concept,
  catalogue,
  labels,
  proof,
  units,
  stageCodes,
  onClose,
}: PanelProps & { proof: Proof | null; units: AcceptanceUnit[]; stageCodes: string[]; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const types = catalogue?.evidence_types ?? [];
  const [pkg, setPkg] = useState(proof?.package_ref ?? concept.applicable_packages[0]?.ref ?? '');
  const [pickedType, setType] = useState(proof?.evidence_type ?? '');
  const type = pickedType || types[0]?.code || '';
  const [title, setTitle] = useState(proof?.title ?? '');
  const [person, setPerson] = useState(proof?.deliverer_contact_id ?? '');
  const [system, setSystem] = useState('');
  const [pickedDeliverer, setDeliverer] = useState(proof?.deliverer_role ?? '');
  const deliverer = pickedDeliverer || types.find((e) => e.code === type)?.default_deliverer || 'contractor';
  const [dueKind, setDueKind] = useState(proof?.required_by_kind ?? 'stage');
  const [dueRef, setDueRef] = useState(proof?.required_by_ref ?? '');
  const [perQuantity, setPerQuantity] = useState(proof?.quantity_rule?.per_quantity ?? '');
  const [unit, setUnit] = useState(proof?.quantity_rule?.unit ?? '');
  const ref = dueRef || (dueKind === 'stage' ? (stageCodes[0] ?? '') : dueKind === 'acceptance_unit' ? (units[0]?.id ?? '') : '');
  const cleanQuantity = perQuantity.trim() ? pointsString(perQuantity) : '';
  const problem = !type
    ? t('qualityConcept.proofs.problem_type', { defaultValue: 'Choose the kind of proof' })
    : !ref
      ? t('qualityConcept.proofs.problem_due', { defaultValue: 'Say by when the proof is due' })
      : cleanQuantity === null || (cleanQuantity && !unit.trim())
        ? t('qualityConcept.proofs.problem_quantity', { defaultValue: 'Enter the quantity as a number and name its unit' })
        : null;
  const rule = cleanQuantity ? { per_quantity: cleanQuantity, unit: unit.trim(), min_count: 1 } : null;

  return (
    <FormDialog
      open
      testId="proof-dialog"
      title={
        proof
          ? t('qualityConcept.proofs.edit_title', { defaultValue: 'Edit proof' })
          : t('qualityConcept.proofs.add', { defaultValue: 'Add proof' })
      }
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      violations={write.violations}
      problem={problem}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(
          () =>
            proof
              ? patchProof(projectId, proof.id, {
                  title: title.trim(),
                  deliverer_role: deliverer,
                  required_by_kind: dueKind,
                  required_by_ref: ref,
                  // An emptied field clears a rule the proof had; a proof without one is left alone.
                  ...(rule ? { quantity_rule: rule } : proof.quantity_rule.per_quantity ? { quantity_rule: null } : {}),
                  ...refChange('deliverer_contact_id', proof.deliverer_contact_id, person),
                })
              : createProof(projectId, {
                  package_ref: pkg || null,
                  evidence_type: type,
                  title: title.trim(),
                  deliverer_role: deliverer,
                  required_by_kind: dueKind,
                  required_by_ref: ref,
                  quantity_rule: rule,
                  ...refChange('deliverer_contact_id', null, person),
                  ...refChange('cx_system_id', null, system),
                }),
          onClose,
        )
      }
    >
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={t('qualityConcept.generate.package', { defaultValue: 'Package' })}>
          <select className={inputCls} value={pkg} disabled={!!proof} onChange={(e) => setPkg(e.target.value)}>
            <option value="">{t('qualityConcept.proofs.no_package', { defaultValue: 'Whole project' })}</option>
            {concept.applicable_packages.map((p) => (
              <option key={p.ref} value={p.ref}>
                {packageName(concept, p.ref)}
              </option>
            ))}
          </select>
        </Field>
        <Field required label={t('qualityConcept.proofs.type', { defaultValue: 'Kind of proof' })}>
          <select className={inputCls} value={type} disabled={!!proof} onChange={(e) => setType(e.target.value)} data-testid="proof-type">
            {types.map((e) => (
              <option key={e.code} value={e.code}>
                {nameIn(labels, types, e.code)}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={t('qualityConcept.proofs.title_field', { defaultValue: 'What exactly (optional)' })}>
        <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      <div className="grid gap-3 md:grid-cols-3">
        <Field required label={t('qualityConcept.proofs.deliverer', { defaultValue: 'Who delivers it' })}>
          <VocabSelect map={DELIVERER_ROLE} codes={DELIVERERS} value={deliverer} onChange={setDeliverer} />
        </Field>
        <Field required label={t('qualityConcept.proofs.due_kind', { defaultValue: 'Due at' })}>
          <VocabSelect
            map={REQUIRED_BY_KIND}
            codes={DUE_KINDS}
            value={dueKind}
            onChange={(v) => {
              setDueKind(v);
              setDueRef('');
            }}
            testId="proof-due-kind"
          />
        </Field>
        <Field required label={vocab(t as TFn, REQUIRED_BY_KIND, dueKind)}>
          {dueKind === 'stage' ? (
            <select className={inputCls} value={ref} onChange={(e) => setDueRef(e.target.value)} data-testid="proof-due-ref">
              {stageCodes.map((c) => (
                <option key={c} value={c}>
                  {nameIn(labels, catalogue?.commissioning_stages, c)}
                </option>
              ))}
            </select>
          ) : dueKind === 'acceptance_unit' ? (
            <select className={inputCls} value={ref} onChange={(e) => setDueRef(e.target.value)} data-testid="proof-due-ref">
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {[u.code, u.title].filter(Boolean).join(' ')}
                </option>
              ))}
            </select>
          ) : (
            <input
              type={dueKind === 'date' ? 'date' : 'text'}
              className={inputCls}
              value={dueRef}
              onChange={(e) => setDueRef(e.target.value)}
              data-testid="proof-due-ref"
            />
          )}
        </Field>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field
          label={t('qualityConcept.proofs.per_quantity', { defaultValue: 'One proof per quantity (optional)' })}
          hint={t('qualityConcept.proofs.per_quantity_hint', {
            defaultValue: 'For repeated tests, such as one cube test per so many cubic metres placed.',
          })}
        >
          <input className={inputCls} inputMode="decimal" value={perQuantity} onChange={(e) => setPerQuantity(e.target.value)} />
        </Field>
        <Field label={t('qualityConcept.requirements.unit', { defaultValue: 'Unit' })}>
          <input className={inputCls} value={unit} onChange={(e) => setUnit(e.target.value)} />
        </Field>
      </div>
      <Field label={t('qualityConcept.proofs.deliverer_contact', { defaultValue: 'Contact who delivers it' })}>
        <OptionPicker projectId={projectId} kind="contact" value={person} onChange={setPerson} currentLabel={proof?.deliverer_contact_label} testId="proof-contact" />
      </Field>
      {!proof && (
        <Field label={t('qualityConcept.proofs.system', { defaultValue: 'Building system it belongs to' })}>
          <OptionPicker projectId={projectId} kind="cx_system" value={system} onChange={setSystem} testId="proof-system" />
        </Field>
      )}
    </FormDialog>
  );
}

function WaiverDialog({ projectId, proof, catalogue, labels, onClose }: PanelProps & { proof: Proof; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [reason, setReason] = useState('');

  return (
    <FormDialog
      open
      size="sm"
      testId="waiver-dialog"
      title={t('qualityConcept.actions.requestWaiver', { defaultValue: 'Request waiver' })}
      subtitle={nameIn(labels, catalogue?.evidence_types, proof.evidence_type)}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={reason.trim() ? null : t('qualityConcept.common.problem_reason', { defaultValue: 'Write down the reason' })}
      submitLabel={t('qualityConcept.actions.requestWaiver', { defaultValue: 'Request waiver' })}
      onSubmit={() => write.send(() => requestWaiver(projectId, proof.id, reason.trim()), onClose)}
    >
      <Hint>
        {t('qualityConcept.proofs.waiver_hint', {
          defaultValue: 'A waiver says this proof will not be delivered. It counts only once it is approved.',
        })}
      </Hint>
      <Field required label={t('qualityConcept.common.reason', { defaultValue: 'Reason' })}>
        <textarea rows={3} className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="waiver-reason" />
      </Field>
    </FormDialog>
  );
}
