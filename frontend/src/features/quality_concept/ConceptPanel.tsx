// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The concept itself: where it stands, what still stops it from going to
// approval, which packages it covers and which standards and requirements it
// rests on. Submitting is the one primary action; approval then happens at
// the governance gate, never here.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Send, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  applyDocumentationSet,
  approveConcept,
  conceptAction,
  patchConcept,
  pinCatalogue,
  reopenConcept,
  submitConcept,
  type CatalogueChoice,
  type Finding,
} from './api';
import { ReasonLines } from './ClosedReasons';
import { useCatalogues, useQcWrite, useRevisions } from './hooks';
import {
  CATALOGUE_SOURCE,
  CONCEPT_STATE,
  PACKAGE_PROBLEM,
  REVISION_REASON,
  SUBMIT_REASON,
  catalogueName,
  nameIn,
  vocab,
  type TFn,
} from './labels';
import { packageName, type PanelProps } from './panel';
import {
  CONCEPT_TONE,
  Field,
  FindingList,
  FormDialog,
  Hint,
  RefusalNote,
  ReviewBadge,
  Section,
  StateBadge,
  inputCls,
} from './QualityBits';
import { CONCEPT_ACTIONS, conceptEditable, filledPackages, packageScopeProblem, type PackageDraft } from './rules';
import { StandardsSection } from './StandardsSection';

let rowSeq = 0;
type PackageRow = PackageDraft & { rowId: string };
function newRow(from?: PackageDraft): PackageRow {
  rowSeq += 1;
  return { rowId: `p${rowSeq}`, ref: '', code: '', title: '', no_proofs_rationale: '', ...from };
}

export function ConceptPanel(props: PanelProps) {
  const { projectId, concept, catalogue, labels, personName, editable, openTab } = props;
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const revisions = useRevisions(projectId);
  const catalogues = useCatalogues(projectId);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [catalogueOpen, setCatalogueOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const mayApproveHere = !!concept.can.approve_applies && concept.state === 'in_review';
  const mayReopenHere = !!concept.can.reopen_applies && concept.state === 'binding';
  const closedHere = [
    ...(mayApproveHere && !concept.can.approve && concept.can.approve_reason ? [concept.can.approve_reason] : []),
    ...(mayReopenHere && !concept.can.reopen && concept.can.reopen_reason ? [concept.can.reopen_reason] : []),
  ];
  const [setApplied, setSetApplied] = useState<number | null>(null);

  const actions = CONCEPT_ACTIONS[concept.state] ?? [];
  // Why the plan is closed to this reader: the concept is past its draft, or the reader does not manage it.
  // A project without gates has nobody else to approve or reopen the concept, so both happen on this page.
  const noGates = concept.gates_in_use === false;
  const planClosed = editable
    ? []
    : [
        conceptEditable(concept.state)
          ? 'manage_required'
          : noGates && concept.state === 'binding'
            ? 'binding_requires_reopen'
            : 'concept_not_editable',
      ];
  const blocking = concept.findings.filter((f) => f.severity === 'error');
  const refName = (f: Finding) =>
    f.code.startsWith('stage_')
      ? nameIn(labels, catalogue?.commissioning_stages, f.ref)
      : packageName(concept, f.ref) || f.ref;

  return (
    <div className="space-y-4" data-testid="concept-panel">
      <RefusalNote refusal={write.refusal} violations={write.violations} refName={refName} />

      <Section
        testId="concept-status"
        title={t('qualityConcept.concept.status_title', { defaultValue: 'Where the concept stands' })}
        description={
          noGates
            ? t('qualityConcept.concept.status_body_no_gates', {
                defaultValue:
                  'A draft is yours to edit. Once it is complete you submit it. This project does not use gates, so a second person approves it on this page.',
              })
            : t('qualityConcept.concept.status_body', {
                defaultValue:
                  'A draft is yours to edit. Once it is complete you submit it, and it is approved at the project governance gate.',
              })
        }
        action={
          <div className="flex flex-wrap items-start gap-2">
            {actions.includes('submit') && (
              <Button
                icon={<Send size={14} />}
                disabled={!concept.can.submit}
                loading={write.pending}
                onClick={() => write.send(() => submitConcept(projectId))}
                data-testid="concept-submit"
              >
                {t('qualityConcept.actions.submit', { defaultValue: 'Submit for approval' })}
              </Button>
            )}
            {actions.includes('return') && (
              <Button
                variant="secondary"
                loading={write.pending}
                onClick={() => write.send(() => conceptAction(projectId, 'return'))}
                data-testid="concept-return"
              >
                {t('qualityConcept.concept.return', { defaultValue: 'Take back to draft' })}
              </Button>
            )}
            {mayApproveHere && (
              <Button
                disabled={!concept.can.approve}
                loading={write.pending}
                onClick={() => write.send(() => approveConcept(projectId))}
                data-testid="concept-approve"
              >
                {t('qualityConcept.concept.approve', { defaultValue: 'Approve the concept' })}
              </Button>
            )}
            {mayReopenHere && (
              <Button variant="secondary" disabled={!concept.can.reopen} onClick={() => setReopenOpen(true)} data-testid="concept-reopen">
                {t('qualityConcept.concept.reopen', { defaultValue: 'Reopen the concept' })}
              </Button>
            )}
            <ReasonLines codes={closedHere} testId="concept-closed-reason" />
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <StateBadge map={CONCEPT_STATE} tones={CONCEPT_TONE} code={concept.state} testId="concept-state" />
          <span className="text-content-secondary">
            {t('qualityConcept.concept.catalogue', {
              defaultValue: 'Catalogue: {{name}}',
              name:
                catalogueName(labels, {
                  code: concept.catalogue_id,
                  name_key: concept.catalogue_label.key ?? undefined,
                  labels: concept.catalogue_label.text,
                }) || concept.catalogue_id,
            })}
          </span>
          <ReviewBadge status={concept.catalogue_review_status} />
          {concept.governance_document && (
            <span className="text-content-secondary" data-testid="concept-frame-document">
              {t('qualityConcept.concept.frame_document', {
                defaultValue: 'Frame document: {{name}}',
                name: catalogueName(labels, {
                  code: concept.governance_document.code,
                  name_key: concept.governance_document.label.key ?? undefined,
                  labels: concept.governance_document.label.text,
                }),
              })}
            </span>
          )}
          {catalogues.data?.can.pin && (
            <Button variant="ghost" size="sm" onClick={() => setCatalogueOpen(true)} data-testid="catalogue-change">
              {t('qualityConcept.catalogues.change', { defaultValue: 'Change catalogue' })}
            </Button>
          )}
          {concept.revision_no > 0 && (
            <span className="text-content-tertiary">
              {t('qualityConcept.concept.revision', { defaultValue: 'Revision {{no}}', no: concept.revision_no })}
            </span>
          )}
        </div>
        <p className="mt-2 text-sm text-content-secondary" data-testid="concept-next-step">
          {noGates && concept.state === 'in_review'
            ? t('qualityConcept.concept.next_in_review_no_gates', {
                defaultValue:
                  'The concept is with the approver. This project does not use gates, so it is approved on this page, by someone other than the person who submitted it.',
              })
            : noGates && concept.state === 'binding'
              ? t('qualityConcept.concept.next_binding_no_gates', {
                  defaultValue:
                    'The concept is binding. This project does not use gates. To change the concept, reopen it on this page and give the reason.',
                })
              : concept.state === 'in_review'
            ? t('qualityConcept.concept.next_in_review', {
                defaultValue:
                  'The concept is with the approver. It is approved as a frame document at the governance gate, not on this page.',
              })
            : concept.state === 'approved'
              ? t('qualityConcept.concept.next_approved', {
                  defaultValue: 'The concept is approved. It becomes binding when the governance gate is decided.',
                })
              : concept.state === 'binding'
                ? t('qualityConcept.concept.next_binding', {
                    defaultValue:
                      'The concept is binding. It changes only through a change request on its frame document.',
                  })
                : concept.can.submit
                  ? t('qualityConcept.concept.next_ready', {
                      defaultValue: 'Nothing is missing. You can submit the concept for approval.',
                    })
                  : vocab(t as TFn, SUBMIT_REASON, concept.can.submit_reason ?? 'concept_incomplete')}
        </p>
        {concept.findings.length > 0 && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-semibold text-content-secondary">
              {t('qualityConcept.concept.open_points', {
                defaultValue: 'Open points: {{blocking}} stop the submission, {{total}} in all',
                blocking: blocking.length,
                total: concept.findings.length,
              })}
            </p>
            <FindingList findings={concept.findings} refName={refName} />
          </div>
        )}
      </Section>

      <Section
        testId="concept-scope"
        title={t('qualityConcept.packages.title', { defaultValue: 'Packages in scope' })}
        description={t('qualityConcept.packages.body', {
          defaultValue:
            'The work packages this concept covers. Every package needs its proofs and an acceptance, or a reason why it needs none.',
        })}
        action={
          <div className="flex flex-col items-end gap-1">
            <Button variant="secondary" size="sm" disabled={!editable} onClick={() => setScopeOpen(true)} data-testid="scope-edit">
              {t('qualityConcept.packages.edit', { defaultValue: 'Edit packages' })}
            </Button>
            <ReasonLines codes={planClosed} testId="scope-closed-reason" />
          </div>
        }
      >
        {concept.applicable_packages.length === 0 ? (
          <Hint testId="scope-empty">
            {t('qualityConcept.packages.empty', {
              defaultValue:
                'No packages yet. Name the work packages first: proofs are planned per package on the Proofs tab.',
            })}
          </Hint>
        ) : (
          <ul className="divide-y divide-border-light" data-testid="scope-list">
            {concept.applicable_packages.map((p) => (
              <li key={p.ref} className="flex flex-wrap items-baseline gap-2 py-1.5 text-sm">
                <span className="font-medium text-content-primary">{packageName(concept, p.ref)}</span>
                {p.no_proofs_rationale && (
                  <span className="text-xs text-content-secondary">
                    {t('qualityConcept.packages.no_proofs_because', {
                      defaultValue: 'No proofs needed: {{reason}}',
                      reason: p.no_proofs_rationale,
                    })}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Field
            label={t('qualityConcept.concept.documentation_set', { defaultValue: 'Handover documentation set' })}
            hint={t('qualityConcept.concept.documentation_set_hint', {
              defaultValue: 'Decides which documents the handover to operation expects.',
            })}
          >
            <select
              className={inputCls}
              disabled={!editable || write.pending}
              value={concept.documentation_set_code ?? ''}
              data-testid="documentation-set"
              onChange={(e) =>
                write.send(() => patchConcept(projectId, { documentation_set_code: e.target.value || null }))
              }
            >
              <option value="">{t('qualityConcept.common.none', { defaultValue: 'None' })}</option>
              {(catalogue?.documentation_sets ?? []).map((d) => (
                <option key={d.code} value={d.code}>
                  {catalogueName(labels, d)}
                </option>
              ))}
            </select>
          </Field>
          <div className="flex flex-col items-start justify-end gap-1">
            <Button
              variant="secondary"
              size="sm"
              disabled={!editable || !concept.documentation_set_code}
              loading={write.pending}
              onClick={() =>
                write.send(
                  () => applyDocumentationSet(projectId),
                  (created) => setSetApplied(Object.values(created).reduce((n, refs) => n + refs.length, 0)),
                )
              }
              data-testid="documentation-set-apply"
            >
              {t('qualityConcept.concept.documentation_set_apply', { defaultValue: 'Create the handover documents of this set' })}
            </Button>
            <ReasonLines codes={planClosed} testId="documentation-set-closed-reason" />
            {editable && !concept.documentation_set_code && (
              <span className="text-xs text-content-tertiary" data-testid="documentation-set-needed">
                {t('qualityConcept.concept.documentation_set_needed', { defaultValue: 'Choose a documentation set first.' })}
              </span>
            )}
            {setApplied !== null && (
              <span role="status" className="text-xs text-content-secondary" data-testid="documentation-set-applied">
                {t('qualityConcept.concept.documentation_set_applied', {
                  defaultValue: 'Handover documents and data deliverables created: {{n}}',
                  n: setApplied,
                })}
              </span>
            )}
          </div>
        </div>
        {concept.applicable_packages.length > 0 && (
          <div className="mt-3">
            <Button variant="ghost" size="sm" onClick={() => openTab('proofs')}>
              {t('qualityConcept.packages.to_proofs', { defaultValue: 'Plan the proofs per package' })}
            </Button>
          </div>
        )}
      </Section>

      <StandardsSection {...props} />

      <Section
        testId="concept-revisions"
        title={t('qualityConcept.revisions.title', { defaultValue: 'Revisions' })}
        description={t('qualityConcept.revisions.body', {
          defaultValue: 'Every submission keeps a snapshot of the concept as it was sent.',
        })}
      >
        {(revisions.data ?? []).length === 0 ? (
          <Hint>
            {t('qualityConcept.revisions.empty', {
              defaultValue: 'No revision yet. The first one is recorded when the concept is submitted.',
            })}
          </Hint>
        ) : (
          <ul className="space-y-1 text-sm" data-testid="revision-list">
            {(revisions.data ?? []).map((r) => (
              <li key={r.id} className="flex flex-wrap gap-3">
                <span className="font-medium text-content-primary">
                  {t('qualityConcept.concept.revision', { defaultValue: 'Revision {{no}}', no: r.revision_no })}
                </span>
                {REVISION_REASON[r.reason] && <span className="text-content-primary">{vocab(t as TFn, REVISION_REASON, r.reason)}</span>}
                {(r.created_by_name ?? personName(r.created_by)) && (
                  <span className="text-content-secondary">{r.created_by_name ?? personName(r.created_by)}</span>
                )}
                {r.created_at && <span className="text-content-tertiary">{fmtDate(r.created_at)}</span>}
                {r.snapshot?.reopen_reason && <span className="basis-full text-content-secondary">{r.snapshot.reopen_reason}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {scopeOpen && (
        <ScopeDialog
          {...props}
          onClose={() => setScopeOpen(false)}
        />
      )}
      {reopenOpen && <ReopenDialog {...props} onClose={() => setReopenOpen(false)} />}
      {catalogueOpen && (
        <CatalogueDialog {...props} choices={catalogues.data?.items ?? []} onClose={() => setCatalogueOpen(false)} />
      )}
    </div>
  );
}

function CatalogueDialog({
  projectId,
  concept,
  labels,
  choices,
  onClose,
}: PanelProps & { choices: CatalogueChoice[]; onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [picked, setPicked] = useState(choices.find((c) => c.pinned)?.id ?? '');
  const choice = choices.find((c) => c.id === picked) ?? null;

  return (
    <FormDialog
      open
      testId="catalogue-dialog"
      title={t('qualityConcept.catalogues.title', { defaultValue: 'Choose the catalogue' })}
      subtitle={t('qualityConcept.catalogues.body', {
        defaultValue:
          'The catalogue supplies the evidence types, the stages and the acceptance regimes the concept is built from.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={
        !choice
          ? t('qualityConcept.catalogues.problem_none', { defaultValue: 'Choose a catalogue' })
          : choice.pinned && choice.latest_version === concept.catalogue_version
            ? t('qualityConcept.catalogues.problem_same', { defaultValue: 'The concept already uses this catalogue' })
            : null
      }
      submitLabel={t('qualityConcept.catalogues.pin', { defaultValue: 'Use this catalogue' })}
      onSubmit={() => {
        if (!choice) return;
        write.send(
          () =>
            pinCatalogue(projectId, {
              catalogue_source: choice.source,
              catalogue_id: choice.id,
              catalogue_version: choice.latest_version,
            }),
          onClose,
        );
      }}
    >
      <ul className="space-y-2">
        {choices.map((c) => (
          <li key={`${c.source}:${c.id}`}>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 text-sm">
              <input
                type="radio"
                name="qc-catalogue"
                className="mt-1"
                checked={picked === c.id}
                onChange={() => setPicked(c.id)}
                data-testid="catalogue-choice"
              />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-content-primary">
                    {catalogueName(labels, { code: c.code, name_key: c.name.key ?? undefined, labels: c.name.text }) || c.code}
                  </span>
                  <ReviewBadge status={c.review_status} />
                </span>
                <span className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-content-tertiary">
                  <span>{vocab(t as TFn, CATALOGUE_SOURCE, c.source)}</span>
                  {c.latest_version != null && (
                    <span>{t('qualityConcept.catalogues.version', { defaultValue: 'Version {{no}}', no: c.latest_version })}</span>
                  )}
                  {c.jurisdiction_countries.length > 0 && <span>{fmtList(c.jurisdiction_countries)}</span>}
                  {c.pinned && <span>{t('qualityConcept.catalogues.pinned', { defaultValue: 'In use' })}</span>}
                  {c.default && <span>{t('qualityConcept.catalogues.default', { defaultValue: 'Default' })}</span>}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </FormDialog>
  );
}

function ReopenDialog({ projectId, onClose }: PanelProps & { onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [reason, setReason] = useState('');

  return (
    <FormDialog
      open
      testId="reopen-dialog"
      title={t('qualityConcept.concept.reopen', { defaultValue: 'Reopen the concept' })}
      subtitle={t('qualityConcept.concept.reopen_body', {
        defaultValue:
          'The concept goes back to revision and its plan can be edited again. It is binding again once it is submitted and approved.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      problem={reason.trim() ? null : t('qualityConcept.concept.reopen_problem', { defaultValue: 'Say why the concept is reopened' })}
      submitLabel={t('qualityConcept.concept.reopen', { defaultValue: 'Reopen the concept' })}
      onSubmit={() => write.send(() => reopenConcept(projectId, { rationale: reason.trim() }), onClose)}
    >
      <Field required label={t('qualityConcept.concept.reopen_reason', { defaultValue: 'Reason' })}>
        <textarea rows={3} className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="reopen-reason" />
      </Field>
    </FormDialog>
  );
}

function ScopeDialog({ projectId, concept, onClose }: PanelProps & { onClose: () => void }) {
  const { t } = useTranslation();
  const write = useQcWrite(projectId);
  const [rows, setRows] = useState<PackageRow[]>(() =>
    concept.packages.length > 0 ? concept.packages.map((p) => newRow(p)) : [newRow()],
  );
  const [holidays, setHolidays] = useState<string[]>(concept.holidays);
  const [day, setDay] = useState('');
  const problem = packageScopeProblem(rows);
  const set = (rowId: string, patch: Partial<PackageDraft>) =>
    setRows((all) => all.map((r) => (r.rowId === rowId ? { ...r, ...patch } : r)));

  return (
    <FormDialog
      open
      size="lg"
      testId="scope-dialog"
      title={t('qualityConcept.packages.dialog_title', { defaultValue: 'Packages in scope' })}
      subtitle={t('qualityConcept.packages.dialog_body', {
        defaultValue:
          'One line per work package. The reference is how proofs and acceptances point at the package, so keep it short and stable.',
      })}
      onClose={onClose}
      busy={write.pending}
      refusal={write.refusal}
      violations={write.violations}
      problem={problem ? vocab(t as TFn, PACKAGE_PROBLEM, problem) : null}
      submitLabel={t('qualityConcept.common.save', { defaultValue: 'Save' })}
      onSubmit={() =>
        write.send(() => patchConcept(projectId, { packages: filledPackages(rows), holidays }), onClose)
      }
    >
      <div className="space-y-2">
        {rows.map((r) => (
          <div key={r.rowId} className="grid gap-2 rounded-md bg-surface-secondary p-2 md:grid-cols-12" data-testid="package-row">
            <input
              className={`${inputCls} md:col-span-2`}
              value={r.ref}
              aria-label={t('qualityConcept.packages.ref', { defaultValue: 'Reference' })}
              placeholder={t('qualityConcept.packages.ref', { defaultValue: 'Reference' })}
              onChange={(e) => set(r.rowId, { ref: e.target.value })}
              data-testid="package-ref"
            />
            <input
              className={`${inputCls} md:col-span-2`}
              value={r.code}
              aria-label={t('qualityConcept.packages.code', { defaultValue: 'Code' })}
              placeholder={t('qualityConcept.packages.code', { defaultValue: 'Code' })}
              onChange={(e) => set(r.rowId, { code: e.target.value })}
            />
            <input
              className={`${inputCls} md:col-span-3`}
              value={r.title}
              aria-label={t('qualityConcept.packages.name', { defaultValue: 'Name of the package' })}
              placeholder={t('qualityConcept.packages.name', { defaultValue: 'Name of the package' })}
              onChange={(e) => set(r.rowId, { title: e.target.value })}
            />
            <input
              className={`${inputCls} md:col-span-4`}
              value={r.no_proofs_rationale}
              aria-label={t('qualityConcept.packages.no_proofs', { defaultValue: 'Why no proofs are needed (optional)' })}
              placeholder={t('qualityConcept.packages.no_proofs', { defaultValue: 'Why no proofs are needed (optional)' })}
              onChange={(e) => set(r.rowId, { no_proofs_rationale: e.target.value })}
            />
            <Button
              variant="ghost"
              size="sm"
              className="md:col-span-1"
              icon={<Trash2 size={14} />}
              aria-label={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
              onClick={() => setRows((all) => all.filter((x) => x.rowId !== r.rowId))}
            />
          </div>
        ))}
        <Button variant="ghost" size="sm" icon={<Plus size={14} />} onClick={() => setRows((all) => [...all, newRow()])} data-testid="package-add">
          {t('qualityConcept.packages.add', { defaultValue: 'Add package' })}
        </Button>
      </div>

      <div>
        <p className="text-xs font-medium text-content-secondary">
          {t('qualityConcept.concept.holidays', { defaultValue: 'Non-working days' })}
        </p>
        <p className="mb-1 text-2xs text-content-tertiary">
          {t('qualityConcept.concept.holidays_hint', {
            defaultValue: 'Deadlines counted in working days skip these days.',
          })}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            className={`${inputCls} w-auto`}
            value={day}
            aria-label={t('qualityConcept.concept.holidays', { defaultValue: 'Non-working days' })}
            onChange={(e) => setDay(e.target.value)} />
          <Button
            variant="secondary"
            size="sm"
            disabled={!day || holidays.includes(day)}
            onClick={() => {
              setHolidays((all) => [...all, day].sort());
              setDay('');
            }}
          >
            {t('qualityConcept.common.add', { defaultValue: 'Add' })}
          </Button>
          {holidays.map((h) => (
            <button
              key={h}
              type="button"
              className="rounded-full border border-border-light px-2 py-0.5 text-xs text-content-secondary"
              title={t('qualityConcept.common.remove', { defaultValue: 'Remove' })}
              onClick={() => setHolidays((all) => all.filter((x) => x !== h))}
            >
              {fmtDate(h)}
            </button>
          ))}
        </div>
      </div>
    </FormDialog>
  );
}
