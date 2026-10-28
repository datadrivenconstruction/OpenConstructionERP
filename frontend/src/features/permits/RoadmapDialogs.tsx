// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The writes of the permit roadmap: starting it from a catalogue, taking the
// permits the confirmed route implies, adding or editing one permit, and
// saying which permit has to come before which.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';

import { ProjectPeopleSelect } from '@/shared/ui/ProjectPeopleSelect';

import {
  acceptProposals,
  createRequirement,
  proposeRequirements,
  setDependencies,
  setRoadmap,
  updateRequirement,
  type ApplicantRole,
  type DependencyOn,
  type RequirementInput,
  type RequirementRow,
  type Roadmap,
  type RoadmapInput,
} from './api';
import { refusalText, useCatalogueTypes, useCatalogues, usePermitAction } from './hooks';
import { APPLICANT_ROLE, DEPENDENCY_ON, PROPOSE_REASON, labelText, typeName, vocab, type LabelContext, type TFn } from './labels';
import { Field, FormDialog, Refusal, fieldClass } from './PermitBits';
import { ChangeRequestField, changeRequestProblem } from './ChangeRequestField';
import { changedOnly } from './rules';

const ROLES: ApplicantRole[] = ['owner', 'designer', 'contractor', 'operator'];

/* ── Roadmap setup ────────────────────────────────────────────────────── */

export interface RoadmapSetupDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** null while the project has no roadmap yet. */
  roadmap: Roadmap | null;
  labels: LabelContext;
}

export function RoadmapSetupDialog({ open, onClose, projectId, roadmap, labels }: RoadmapSetupDialogProps) {
  const { t } = useTranslation();
  const cataloguesQ = useCatalogues(open);
  const [catalogue, setCatalogue] = useState('');
  const [jurisdiction, setJurisdiction] = useState('');
  const [internalReview, setInternalReview] = useState(false);
  const [escalationDays, setEscalationDays] = useState('');
  const [bufferDays, setBufferDays] = useState('');

  useEffect(() => {
    if (!open) return;
    setCatalogue(roadmap ? `${roadmap.catalogue_source}:${roadmap.catalogue_id}` : '');
    setJurisdiction(roadmap?.jurisdiction ?? '');
    setInternalReview(roadmap?.internal_review ?? false);
    setEscalationDays(roadmap ? String(roadmap.escalation_days) : '');
    setBufferDays(roadmap ? String(roadmap.buffer_days) : '');
  }, [open, roadmap]);

  const action = usePermitAction(projectId, (body: RoadmapInput) => setRoadmap(projectId, body), onClose);
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const problems: string[] = [];
  if (jurisdiction.trim() && !/^[A-Za-z]{2}(-[A-Za-z0-9]{1,3})?$/.test(jurisdiction.trim())) {
    problems.push(
      t('permits.ui.setup.problem_jurisdiction', {
        defaultValue: 'Write the jurisdiction as a country code, optionally with a region, for example DE or DE-BY.',
      }),
    );
  }
  if (roadmap?.jurisdiction && !jurisdiction.trim()) {
    problems.push(
      t('permits.ui.setup.problem_jurisdiction_empty', {
        defaultValue: 'Enter the jurisdiction. Once set, it cannot be left empty.',
      }),
    );
  }
  for (const value of [escalationDays, bufferDays]) {
    const days = value.trim();
    if (roadmap ? !/^\d{1,3}$/.test(days) || Number(days) > 365 : !!days && (!/^\d{1,3}$/.test(days) || Number(days) > 365)) {
      problems.push(t('permits.ui.setup.problem_days', { defaultValue: 'Days are whole numbers from 0 to 365.' }));
      break;
    }
  }

  const send = () => {
    const body: RoadmapInput = {};
    const current = roadmap ? `${roadmap.catalogue_source}:${roadmap.catalogue_id}` : '';
    if (catalogue && catalogue !== current) {
      const cut = catalogue.indexOf(':');
      body.catalogue_source = catalogue.slice(0, cut) as 'shipped' | 'tenant';
      body.catalogue_id = catalogue.slice(cut + 1);
    }
    if (jurisdiction.trim()) body.jurisdiction = jurisdiction.trim().toUpperCase();
    if (roadmap || internalReview) body.internal_review = internalReview;
    if (escalationDays.trim()) body.escalation_days = Number(escalationDays.trim());
    if (bufferDays.trim()) body.buffer_days = Number(bufferDays.trim());
    action.run(body);
  };

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="roadmap-setup"
      title={
        roadmap
          ? t('permits.ui.setup.title_edit', { defaultValue: 'Roadmap settings' })
          : t('permits.ui.setup.title_new', { defaultValue: 'Start the permit roadmap' })
      }
      subtitle={t('permits.ui.setup.subtitle', {
        defaultValue: 'The catalogue brings the permit types of a jurisdiction with their decision periods.',
      })}
      submitLabel={
        roadmap
          ? t('permits.ui.save', { defaultValue: 'Save' })
          : t('permits.ui.setup.submit_new', { defaultValue: 'Start roadmap' })
      }
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={send}
    >
      <Field
        label={t('permits.ui.setup.catalogue', { defaultValue: 'Permit catalogue' })}
        hint={t('permits.ui.setup.catalogue_hint', {
          defaultValue: 'Left on automatic, the catalogue follows the country of the project.',
        })}
      >
        {(id) => (
          <select
            id={id}
            className={fieldClass}
            value={catalogue}
            disabled={cataloguesQ.isLoading}
            onChange={(e) => setCatalogue(e.target.value)}
          >
            {cataloguesQ.isLoading && roadmap && <option value={catalogue}>{t('permits.ui.loading', { defaultValue: 'Loading...' })}</option>}
            {!roadmap && (
              <option value="">{t('permits.ui.setup.catalogue_auto', { defaultValue: 'Automatic, by project country' })}</option>
            )}
            {(cataloguesQ.data ?? []).map((c) => (
              <option key={`${c.source}:${c.id}`} value={`${c.source}:${c.id}`}>
                {labelText(labels, c.name, c.code)}
              </option>
            ))}
          </select>
        )}
      </Field>
      {cataloguesQ.isError && <Refusal>{refusalText(t as TFn, cataloguesQ.error)}</Refusal>}
      <Field
        label={t('permits.ui.setup.jurisdiction', { defaultValue: 'Jurisdiction' })}
        hint={t('permits.ui.setup.jurisdiction_hint', {
          defaultValue: 'Country code, optionally with a region: DE, DE-BY, GB. Empty means the project country.',
        })}
      >
        {(id) => (
          <input id={id} className={fieldClass} value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} />
        )}
      </Field>
      <label className="flex items-start gap-2 text-sm text-content-primary">
        <input
          type="checkbox"
          className="mt-1"
          checked={internalReview}
          onChange={(e) => setInternalReview(e.target.checked)}
        />
        <span>
          {t('permits.ui.setup.internal_review', { defaultValue: 'Release every application internally before it is submitted' })}
          <span className="block text-xs text-content-tertiary">
            {t('permits.ui.setup.internal_review_hint', {
              defaultValue: 'A manager releases the application before it goes to the authority.',
            })}
          </span>
        </span>
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label={t('permits.ui.setup.buffer_days', { defaultValue: 'Buffer before the needed date, in days' })}
          hint={t('permits.ui.setup.buffer_days_hint', {
            defaultValue: 'How long before the date a permit is needed its decision should be in hand.',
          })}
        >
          {(id) => (
            <input id={id} inputMode="numeric" className={fieldClass} value={bufferDays} onChange={(e) => setBufferDays(e.target.value)} />
          )}
        </Field>
        <Field
          label={t('permits.ui.setup.escalation_days', { defaultValue: 'Escalate an overdue condition after, in days' })}
          hint={t('permits.ui.setup.escalation_days_hint', {
            defaultValue: 'After this many days overdue, the owner of the management area is told.',
          })}
        >
          {(id) => (
            <input
              id={id}
              inputMode="numeric"
              className={fieldClass}
              value={escalationDays}
              onChange={(e) => setEscalationDays(e.target.value)}
            />
          )}
        </Field>
      </div>
    </FormDialog>
  );
}

/* ── Proposals from the permit route ──────────────────────────────────── */

export interface ProposeDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  roadmap: Roadmap | null;
  labels: LabelContext;
}

export function ProposeDialog({ open, onClose, projectId, roadmap, labels }: ProposeDialogProps) {
  const { t } = useTranslation();
  // Asking is a read: the endpoint writes nothing until the reader accepts.
  const proposalQ = useQuery({
    queryKey: ['permits', projectId, 'propose'],
    queryFn: () => proposeRequirements(projectId),
    enabled: open,
    retry: false,
    gcTime: 0,
  });
  const offered = useMemo(
    () => (proposalQ.data?.proposals ?? []).filter((p) => !p.already_present).map((p) => p.permit_type_code),
    [proposalQ.data],
  );
  const [picked, setPicked] = useState<string[]>([]);
  useEffect(() => setPicked(offered), [offered]);
  const [changeRequest, setChangeRequest] = useState('');
  useEffect(() => {
    if (open) setChangeRequest('');
  }, [open]);

  const action = usePermitAction(
    projectId,
    (codes: string[]) =>
      acceptProposals(projectId, {
        permit_type_codes: codes,
        route_assessment_id: proposalQ.data?.route_assessment_id,
        ...(changeRequest ? { change_request_id: changeRequest } : {}),
      }),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const toggle = (code: string) =>
    setPicked((list) => (list.includes(code) ? list.filter((c) => c !== code) : [...list, code]));
  const problems = [
    ...(picked.length === 0 ? [t('permits.ui.propose.problem_none', { defaultValue: 'Tick at least one permit to add.' })] : []),
    ...changeRequestProblem(t as TFn, roadmap, changeRequest),
  ];
  const data = proposalQ.data;

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="propose-dialog"
      title={t('permits.ui.propose.title', { defaultValue: 'Permits the confirmed route needs' })}
      subtitle={t('permits.ui.propose.subtitle', {
        defaultValue: 'Read from the confirmed permit route of this project. Nothing is added until you confirm.',
      })}
      submitLabel={t('permits.ui.propose.submit', { defaultValue: 'Add the ticked permits' })}
      busy={action.busy}
      error={action.error}
      problems={problems}
      hideSubmit={!proposalQ.isLoading && offered.length === 0}
      onSubmit={() => action.run(picked)}
    >
      <p className="text-sm text-content-secondary" data-testid="propose-route-hint">
        {t('permits.ui.propose.route_hint', {
          defaultValue:
            'The permit route is the answer to which procedure the works go through: a full permit, a simplified one, a notification, or none. It is settled once for the project, and the permits listed here follow from it.',
        })}
      </p>
      {proposalQ.isLoading && (
        <p className="text-sm text-content-tertiary">{t('permits.ui.loading', { defaultValue: 'Loading...' })}</p>
      )}
      {proposalQ.isError && <Refusal testId="propose-refusal">{refusalText(t as TFn, proposalQ.error)}</Refusal>}
      {data?.reason && (
        <p className="text-sm text-content-secondary" data-testid="propose-reason">
          {vocab(t, PROPOSE_REASON, data.reason)}
        </p>
      )}
      {data && data.proposals.length > 0 && (
        <ul className="space-y-1.5" data-testid="propose-list">
          {data.proposals.map((p) => (
            <li key={p.permit_type_code}>
              <label className="flex items-start gap-2 rounded-md border border-border-light bg-surface-elevated p-2.5 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  disabled={p.already_present}
                  checked={!p.already_present && picked.includes(p.permit_type_code)}
                  onChange={() => toggle(p.permit_type_code)}
                />
                <span className="min-w-0">
                  <span className="font-medium text-content-primary">{typeName(labels, p.permit_type_code, p.name_key)}</span>
                  <span className="block text-xs text-content-tertiary">
                    {p.already_present
                      ? t('permits.ui.propose.already_present', { defaultValue: 'Already on the roadmap' })
                      : t('permits.ui.propose.applicant', {
                          defaultValue: 'Applicant: {{role}}',
                          role: vocab(t, APPLICANT_ROLE, p.applicant_role),
                        })}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {data && data.proposals.length > 0 && offered.length === 0 && (
        <p className="text-sm text-content-secondary" data-testid="propose-all-present">
          {t('permits.ui.propose.all_present', { defaultValue: 'Every permit of the route is already on the roadmap.' })}
        </p>
      )}
      {offered.length > 0 && (
        <ChangeRequestField projectId={projectId} roadmap={roadmap} value={changeRequest} onChange={setChangeRequest} enabled={open} />
      )}
    </FormDialog>
  );
}

/* ── One permit of the roadmap ────────────────────────────────────────── */

export interface RequirementDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  roadmap: Roadmap;
  /** The row being edited, or null to add one. */
  requirement: RequirementRow | null;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
}

export function RequirementDialog({
  open,
  onClose,
  projectId,
  roadmap,
  requirement,
  labels,
  personName,
}: RequirementDialogProps) {
  const { t } = useTranslation();
  const typesQ = useCatalogueTypes(roadmap, open && !requirement);
  const types = typesQ.data ?? [];
  const shipped = roadmap.catalogue_source === 'shipped';
  const [changeRequest, setChangeRequest] = useState('');
  const [code, setCode] = useState('');
  const [title, setTitle] = useState('');
  const [role, setRole] = useState<ApplicantRole | ''>('');
  const [roleWhy, setRoleWhy] = useState('');
  const [party, setParty] = useState('');
  const [responsible, setResponsible] = useState('');
  const [plannedSubmit, setPlannedSubmit] = useState('');
  const [neededBy, setNeededBy] = useState('');
  const [expected, setExpected] = useState('');
  const [applicable, setApplicable] = useState(true);
  const [naWhy, setNaWhy] = useState('');
  const [conflictAccepted, setConflictAccepted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCode(requirement?.permit_type_code ?? '');
    setTitle(requirement?.title ?? '');
    setRole(requirement?.applicant_role ?? '');
    setRoleWhy(requirement?.applicant_rationale ?? '');
    setParty(requirement?.applicant_party ?? '');
    setResponsible(requirement?.responsible_user_id ?? '');
    setPlannedSubmit(requirement?.planned_submit_date ?? '');
    setNeededBy(requirement?.needed_by_date ?? '');
    setExpected(requirement?.expected_decision_date ?? '');
    setApplicable(requirement?.applicable ?? true);
    setNaWhy(requirement?.applicability_rationale ?? '');
    setConflictAccepted(requirement?.conflict_accepted ?? false);
    setChangeRequest('');
  }, [open, requirement]);

  const action = usePermitAction(
    projectId,
    (body: RequirementInput) =>
      requirement ? updateRequirement(projectId, requirement.id, body) : createRequirement(projectId, body),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const problems: string[] = [];
  if (!requirement && !code.trim()) {
    problems.push(t('permits.ui.requirement.problem_type', { defaultValue: 'Choose the kind of permit.' }));
  }
  if (!applicable && !naWhy.trim()) {
    problems.push(
      t('permits.ui.requirement.problem_na', { defaultValue: 'Say why this permit is not needed for the project.' }),
    );
  }

  // Adding a permit, or saying an existing one is not needed, changes what the roadmap lists.
  const structural = !requirement || applicable !== requirement.applicable;
  if (structural) problems.push(...changeRequestProblem(t as TFn, roadmap, changeRequest));

  const send = () => {
    const draft: RequirementInput = {
      title: title.trim(),
      applicant_rationale: roleWhy.trim(),
      applicant_party: party.trim(),
      responsible_user_id: responsible || null,
      planned_submit_date: plannedSubmit || null,
      needed_by_date: neededBy || null,
      expected_decision_date: expected || null,
      applicable,
      applicability_rationale: naWhy.trim(),
    };
    if (role) draft.applicant_role = role;
    if (!requirement) {
      action.run({ ...draft, permit_type_code: code.trim(), ...(changeRequest ? { change_request_id: changeRequest } : {}) });
      return;
    }
    const changed = changedOnly(requirement, { ...draft, conflict_accepted: conflictAccepted });
    // A new applicant is refused without its reason, so the reason travels with it.
    if ('applicant_role' in changed) changed.applicant_rationale = draft.applicant_rationale;
    if ('applicable' in changed && changeRequest) changed.change_request_id = changeRequest;
    action.run(changed);
  };

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="requirement-dialog"
      size="lg"
      title={
        requirement
          ? t('permits.ui.requirement.title_edit', { defaultValue: 'Edit permit on the roadmap' })
          : t('permits.ui.requirement.title_new', { defaultValue: 'Add a permit to the roadmap' })
      }
      submitLabel={
        requirement
          ? t('permits.ui.save', { defaultValue: 'Save' })
          : t('permits.ui.requirement.submit_new', { defaultValue: 'Add permit' })
      }
      busy={action.busy}
      error={action.error}
      problems={problems}
      onSubmit={send}
    >
      {!requirement && (
        <Field label={t('permits.ui.requirement.type', { defaultValue: 'Kind of permit' })} required>
          {(id) =>
            shipped ? (
              <select id={id} className={fieldClass} value={code} disabled={typesQ.isLoading} onChange={(e) => setCode(e.target.value)}>
                <option value="">
                  {typesQ.isLoading
                    ? t('permits.ui.loading', { defaultValue: 'Loading...' })
                    : t('permits.ui.requirement.type_choose', { defaultValue: 'Choose from the catalogue' })}
                </option>
                {types.map((type) => (
                  <option key={type.code} value={type.code}>
                    {typeName(labels, type.code, type.name_key)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                className={fieldClass}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder={t('permits.ui.requirement.type_code', { defaultValue: 'Type code from your catalogue' })}
              />
            )
          }
        </Field>
      )}
      {!requirement && typesQ.isError && <Refusal>{refusalText(t as TFn, typesQ.error)}</Refusal>}
      <Field
        label={t('permits.ui.requirement.title_field', { defaultValue: 'What it is for' })}
        hint={t('permits.ui.requirement.title_hint', {
          defaultValue: 'A short name the team will recognise, for example "Road occupation for the crane".',
        })}
      >
        {(id) => <input id={id} className={fieldClass} value={title} onChange={(e) => setTitle(e.target.value)} />}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label={t('permits.ui.requirement.applicant_role', { defaultValue: 'Who applies' })}
          hint={t('permits.ui.requirement.applicant_role_hint', {
            defaultValue: 'A choice other than the catalogue default needs a reason.',
          })}
        >
          {(id) => (
            <select id={id} className={fieldClass} value={role} onChange={(e) => setRole(e.target.value as ApplicantRole | '')}>
              {(!requirement || !requirement.applicant_role) && (
                <option value="">{t('permits.ui.requirement.applicant_default', { defaultValue: 'As the catalogue says' })}</option>
              )}
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {vocab(t, APPLICANT_ROLE, r)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('permits.ui.requirement.applicant_party', { defaultValue: 'Applying company' })}>
          {(id) => <input id={id} className={fieldClass} value={party} onChange={(e) => setParty(e.target.value)} />}
        </Field>
      </div>
      {role && (
        <Field label={t('permits.ui.requirement.applicant_rationale', { defaultValue: 'Why this applicant' })}>
          {(id) => <input id={id} className={fieldClass} value={roleWhy} onChange={(e) => setRoleWhy(e.target.value)} />}
        </Field>
      )}
      <Field label={t('permits.ui.requirement.responsible', { defaultValue: 'Responsible person' })}>
        {(id) => (
          <ProjectPeopleSelect
            id={id}
            projectId={projectId}
            value={responsible}
            displayValue={personName(responsible) ?? undefined}
            onChange={(userId) => setResponsible(userId)}
            placeholder={t('permits.ui.requirement.responsible', { defaultValue: 'Responsible person' })}
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t('permits.ui.requirement.planned_submit', { defaultValue: 'Planned submission' })}>
          {(id) => (
            <input id={id} type="date" className={fieldClass} value={plannedSubmit} onChange={(e) => setPlannedSubmit(e.target.value)} />
          )}
        </Field>
        <Field label={t('permits.ui.requirement.needed_by', { defaultValue: 'Needed by' })}>
          {(id) => <input id={id} type="date" className={fieldClass} value={neededBy} onChange={(e) => setNeededBy(e.target.value)} />}
        </Field>
        <Field
          label={t('permits.ui.requirement.expected_decision', { defaultValue: 'Expected decision' })}
          hint={t('permits.ui.requirement.expected_decision_hint', {
            defaultValue: 'Only where the law sets no decision period.',
          })}
        >
          {(id) => <input id={id} type="date" className={fieldClass} value={expected} onChange={(e) => setExpected(e.target.value)} />}
        </Field>
      </div>
      {requirement && (
        <>
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input type="checkbox" className="mt-1" checked={!applicable} onChange={(e) => setApplicable(!e.target.checked)} />
            {t('permits.ui.requirement.not_applicable', { defaultValue: 'This permit is not needed for the project' })}
          </label>
          {!applicable && (
            <Field label={t('permits.ui.requirement.na_rationale', { defaultValue: 'Why it is not needed' })} required>
              {(id) => (
                <textarea id={id} rows={2} className={fieldClass} value={naWhy} onChange={(e) => setNaWhy(e.target.value)} />
              )}
            </Field>
          )}
          <label className="flex items-start gap-2 text-sm text-content-primary">
            <input
              type="checkbox"
              className="mt-1"
              checked={conflictAccepted}
              onChange={(e) => setConflictAccepted(e.target.checked)}
            />
            <span>
              {t('permits.ui.requirement.conflict_accepted', { defaultValue: 'Accept a decision later than the needed date' })}
              <span className="block text-xs text-content-tertiary">
                {t('permits.ui.requirement.conflict_accepted_hint', {
                  defaultValue: 'The conflict stays visible but no longer blocks readiness.',
                })}
              </span>
            </span>
          </label>
        </>
      )}
      {structural && (
        <ChangeRequestField projectId={projectId} roadmap={roadmap} value={changeRequest} onChange={setChangeRequest} enabled={open} />
      )}
    </FormDialog>
  );
}

/* ── Which permit comes first ─────────────────────────────────────────── */

export interface DependenciesDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  roadmap: Roadmap;
  requirement: RequirementRow;
  /** Every roadmap row; the edited one is left out of the choice. */
  all: RequirementRow[];
  labels: LabelContext;
}

export function DependenciesDialog({ open, onClose, projectId, roadmap, requirement, all, labels }: DependenciesDialogProps) {
  const { t } = useTranslation();
  const [chosen, setChosen] = useState<Record<string, DependencyOn>>({});
  const [changeRequest, setChangeRequest] = useState('');
  useEffect(() => {
    if (!open) return;
    setChangeRequest('');
    const next: Record<string, DependencyOn> = {};
    for (const d of requirement.depends_on) next[d.id] = d.on;
    setChosen(next);
  }, [open, requirement]);

  const action = usePermitAction(
    projectId,
    (deps: Record<string, DependencyOn>) =>
      setDependencies(
        projectId,
        requirement.id,
        Object.entries(deps).map(([depends_on_id, on]) => ({ depends_on_id, on })),
        changeRequest || undefined,
      ),
    onClose,
  );
  useEffect(() => {
    if (!open) action.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const others = all.filter((r) => r.id !== requirement.id);
  const toggle = (id: string) =>
    setChosen((c) => {
      const next = { ...c };
      if (id in next) delete next[id];
      else next[id] = 'granted';
      return next;
    });

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      testId="dependencies-dialog"
      title={t('permits.ui.dependencies.title', { defaultValue: 'What has to come first' })}
      subtitle={t('permits.ui.dependencies.subtitle', {
        defaultValue: 'Tick the permits this one waits for. Its latest submission date follows from them.',
      })}
      submitLabel={t('permits.ui.save', { defaultValue: 'Save' })}
      busy={action.busy}
      error={action.error}
      problems={changeRequestProblem(t as TFn, roadmap, changeRequest)}
      onSubmit={() => action.run(chosen)}
    >
      {others.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('permits.ui.dependencies.none', { defaultValue: 'There is no other permit on the roadmap yet.' })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {others.map((r) => {
            const name = r.title || typeName(labels, r.permit_type_code, r.name_key);
            return (
              <li key={r.id} className="flex flex-wrap items-center gap-2 rounded-md border border-border-light bg-surface-elevated p-2.5 text-sm">
                <label className="flex min-w-0 flex-1 items-center gap-2">
                  <input type="checkbox" checked={r.id in chosen} onChange={() => toggle(r.id)} />
                  <span className="truncate text-content-primary">{name}</span>
                </label>
                {r.id in chosen && (
                  <select
                    aria-label={t('permits.ui.dependencies.on', { defaultValue: 'How far {{name}} must be', name })}
                    className={`${fieldClass} w-auto`}
                    value={chosen[r.id]}
                    onChange={(e) => setChosen((c) => ({ ...c, [r.id]: e.target.value as DependencyOn }))}
                  >
                    {(['granted', 'submitted'] as DependencyOn[]).map((on) => (
                      <option key={on} value={on}>
                        {vocab(t, DEPENDENCY_ON, on)}
                      </option>
                    ))}
                  </select>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <ChangeRequestField projectId={projectId} roadmap={roadmap} value={changeRequest} onChange={setChangeRequest} enabled={open} />
    </FormDialog>
  );
}
