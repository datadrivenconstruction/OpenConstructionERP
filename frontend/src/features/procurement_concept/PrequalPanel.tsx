// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Prequalification of one package: the profile the companies are measured on,
// the candidates with their scores and evidence, and the step that turns the
// short list into a confirmed one. The short list is confirmed only when it
// meets the rules; the refusal lists what is missing.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, Download, Pencil, Plus, Trash2, Users } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { fmtDate } from '@/shared/lib/formatters';

import {
  confirmShortlist,
  deleteCandidate,
  deleteProfile,
  deleteReference,
  downloadExport,
  type Capability,
  type Candidate,
  type CandidateList,
  type Concept,
  type PackageView,
  type PinnedCatalogue,
  type PrequalProfile,
} from './api';
import { CandidateDialog, ReferenceDialog, ScoresDialog } from './CandidateDialogs';
import { refusalText, useCandidates, useRefusalToast } from './hooks';
import { CANDIDATE_LIST, CANDIDATE_SOURCE, catalogueName, vocab, type LabelContext } from './labels';
import { FIELD_CLASS, FindingList, Money, ReasonedButton, RefusalBox, ToneBadge } from './ProcurementBits';
import { ProfileDialog } from './ProfileDialog';
import { capVerdict, notApplicable, offer, steerVerdict } from './rules';
import type { BadgeVariant } from '@/shared/ui/Badge';

const LIST_TONE: Record<CandidateList, BadgeVariant> = { long: 'neutral', short: 'success', excluded: 'error' };

type Open =
  | { kind: 'candidate'; candidate: Candidate | null }
  | { kind: 'scores'; candidate: Candidate }
  | { kind: 'reference'; candidate: Candidate }
  | { kind: 'profile' }
  | null;

export interface PrequalPanelProps {
  projectId: string;
  concept: Concept;
  packages: PackageView[];
  profiles: PrequalProfile[];
  /** Whether the reader may set up a profile, from the profile list. */
  profileCreate?: Capability;
  catalogue: PinnedCatalogue | null;
  packageId: string | null;
  labels: LabelContext;
  onSelectPackage: (packageId: string) => void;
  onGoToPackages: () => void;
  onChanged: () => void;
}

export function PrequalPanel({
  projectId,
  concept,
  packages,
  profiles,
  profileCreate,
  catalogue,
  packageId,
  labels,
  onSelectPackage,
  onGoToPackages,
  onChanged,
}: PrequalPanelProps) {
  const { t } = useTranslation();
  const toastRefusal = useRefusalToast();
  const planned = packages.filter((p) => p.award);
  const current = planned.find((p) => p.contract_package.id === packageId) ?? planned[0] ?? null;
  const currentId = current?.contract_package.id ?? null;
  const matrixQ = useCandidates(projectId, currentId);
  const [open, setOpen] = useState<Open>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const steer = steerVerdict(concept);

  const confirm = useMutation({
    mutationFn: () => confirmShortlist(projectId, currentId as string),
    onSuccess: onChanged,
  });
  const remove = useMutation({
    mutationFn: (candidateId: string) => deleteCandidate(projectId, candidateId),
    onSuccess: () => {
      setRemoving(null);
      onChanged();
    },
    onError: toastRefusal,
  });
  const removeReference = useMutation({
    mutationFn: (r: { candidateId: string; referenceId: string }) => deleteReference(projectId, r.candidateId, r.referenceId),
    onSuccess: onChanged,
    onError: toastRefusal,
  });
  const [removingProfile, setRemovingProfile] = useState<string | null>(null);
  const removeProfile = useMutation({
    mutationFn: (profileId: string) => deleteProfile(projectId, profileId),
    onSuccess: () => {
      setRemovingProfile(null);
      onChanged();
    },
    onError: toastRefusal,
  });
  const exportList = useMutation({
    mutationFn: () => downloadExport(projectId, 'shortlist', 'xlsx', currentId as string),
    onError: toastRefusal,
  });

  if (!current || !currentId) {
    return (
      <EmptyState
        icon={<Users size={28} />}
        title={t('procurement_concept.ui.prequal.empty_title', { defaultValue: 'No package has an award plan yet' })}
        description={t('procurement_concept.ui.prequal.empty_body', {
          defaultValue:
            'Candidates are kept per package. Plan the award of a package first, then collect the companies you consider for it here.',
        })}
        action={{
          label: t('procurement_concept.tabs.packages', { defaultValue: 'Packages' }),
          onClick: onGoToPackages,
        }}
      />
    );
  }

  const matrix = matrixQ.data;
  const criteria = matrix?.profile?.criteria ?? [];
  const profileRow = matrix?.profile ? (profiles.find((p) => p.id === matrix.profile?.id) ?? null) : null;
  const names = new Map((matrix?.items ?? []).map((c) => [c.id, c.name]));
  const refLabel = (ref: string) => names.get(ref) ?? ref;
  const shortCount = (matrix?.items ?? []).filter((c) => c.list === 'short').length;
  const confirmed = current.award?.state === 'shortlisted';
  // Each button follows the flag the server sent with the list. Until the list is there, steering stands in.
  const can = matrix?.can;
  const v = (key: keyof NonNullable<typeof can>) => (can ? capVerdict(can[key], 'permission_denied') : steer);
  const confirmVerdict = v('confirm_shortlist');
  // Offered while the short list can still be confirmed; a list with open findings stays visible with the reason.
  const canConfirm = !!can && offer(can.confirm_shortlist).show;
  const profileVerdict = profileRow ? capVerdict(profileRow.can?.edit, 'permission_denied') : capVerdict(profileCreate, 'permission_denied');
  const close = () => setOpen(null);

  return (
    <div className="space-y-4" data-testid="prequal-panel">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem]">
          <label htmlFor="pq-package" className="mb-1 block text-xs font-medium text-content-secondary">
            {t('procurement_concept.ui.prequal.package', { defaultValue: 'Package' })}
          </label>
          <select id="pq-package" className={FIELD_CLASS} value={currentId} onChange={(e) => onSelectPackage(e.target.value)}>
            {planned.map((p) => (
              <option key={p.contract_package.id} value={p.contract_package.id}>
                {`${p.contract_package.code} ${p.contract_package.title}`}
              </option>
            ))}
          </select>
        </div>
        <div className="ml-auto flex flex-wrap items-start gap-2">
          <Button size="sm" variant="ghost" icon={<Download size={14} />} loading={exportList.isPending} onClick={() => exportList.mutate()}>
            {t('procurement_concept.ui.prequal.export', { defaultValue: 'Short list (XLSX)' })}
          </Button>
          {!notApplicable(can?.add) && (
            <ReasonedButton quiet verdict={v('add')} size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setOpen({ kind: 'candidate', candidate: null })} data-testid="candidate-add">
              {t('procurement_concept.ui.prequal.add_candidate', { defaultValue: 'Add candidate' })}
            </ReasonedButton>
          )}
          {canConfirm && (
            <ReasonedButton size="sm" verdict={confirmVerdict} loading={confirm.isPending} onClick={() => confirm.mutate()} data-testid="shortlist-confirm">
              {t('procurement_concept.actions.confirm_shortlist', { defaultValue: 'Confirm short list' })}
            </ReasonedButton>
          )}
        </div>
      </div>

      {confirmed && (
        <p className="flex items-center gap-2 rounded-md bg-semantic-success-bg px-3 py-2 text-sm text-content-primary" data-testid="shortlist-confirmed">
          <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />
          {t('procurement_concept.ui.prequal.confirmed', { defaultValue: 'The short list of this package is confirmed.' })}
        </p>
      )}
      {confirm.error ? <RefusalBox error={confirm.error} refLabel={refLabel} /> : null}

      {matrixQ.isLoading ? (
        <SkeletonTable rows={4} columns={5} />
      ) : matrixQ.isError || !matrix ? (
        <ErrorState
          title={t('procurement_concept.ui.prequal.load_failed', { defaultValue: 'The candidates could not be loaded' })}
          hint={refusalText(labels.t, matrixQ.error)}
          onRetry={() => matrixQ.refetch()}
        />
      ) : (
        <>
          <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="profile-summary">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-content-primary">
                  {profileRow?.name || t('procurement_concept.ui.prequal.profile', { defaultValue: 'Prequalification profile' })}
                </h3>
                {matrix.profile ? (
                  <p className="mt-0.5 text-xs text-content-secondary">
                    {t('procurement_concept.ui.prequal.profile_facts', {
                      defaultValue: 'Pass mark {{mark}} of 100. At least {{min}} companies on the short list for this procedure.',
                      mark: matrix.profile.pass_mark,
                      min: matrix.min_bidders,
                    })}
                  </p>
                ) : (
                  <p className="mt-0.5 text-xs text-content-secondary" data-testid="profile-missing">
                    {t('procurement_concept.ui.prequal.no_profile', {
                      defaultValue: 'No profile yet. Without one the candidates cannot be scored.',
                    })}
                  </p>
                )}
              </div>
              {!notApplicable(profileRow ? profileRow.can?.edit : profileCreate) && (
                <ReasonedButton
                  size="sm"
                  variant="secondary"
                  icon={<Pencil size={14} />}
                  verdict={profileVerdict}
                  onClick={() => setOpen({ kind: 'profile' })}
                  data-testid="profile-edit"
                >
                  {matrix.profile
                    ? t('procurement_concept.ui.prequal.edit_profile', { defaultValue: 'Change profile' })
                    : t('procurement_concept.ui.prequal.new_profile', { defaultValue: 'Set up profile' })}
                </ReasonedButton>
              )}
            </div>
            {profiles.length > 0 && (
              <div className="mt-3 border-t border-border-light pt-2" data-testid="profile-list">
                <h4 className="text-xs font-medium text-content-secondary">
                  {t('procurement_concept.ui.prequal.profiles_title', { defaultValue: 'Profiles of this project' })}
                </h4>
                <ul className="mt-1 space-y-1">
                  {profiles.map((p) => (
                    <li key={p.id} className="flex flex-wrap items-center gap-2 text-sm" data-testid="profile-row" data-profile={p.id}>
                      <span className="text-content-primary">{p.name}</span>
                      <span className="text-xs text-content-tertiary">
                        {p.in_use
                          ? t('procurement_concept.ui.prequal.profile_in_use', { defaultValue: 'In use' })
                          : t('procurement_concept.ui.prequal.profile_unused', { defaultValue: 'Not used by any package' })}
                      </span>
                      {removingProfile === p.id ? (
                        <span className="ml-auto flex flex-wrap items-center gap-2">
                          <span className="text-xs text-content-primary">
                            {t('procurement_concept.ui.prequal.profile_remove_confirm', { defaultValue: 'Remove the profile {{name}}?', name: p.name })}
                          </span>
                          <Button size="sm" variant="danger" loading={removeProfile.isPending} onClick={() => removeProfile.mutate(p.id)} data-testid="profile-remove-yes">
                            {t('procurement_concept.ui.remove', { defaultValue: 'Remove' })}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setRemovingProfile(null)}>
                            {t('procurement_concept.ui.keep', { defaultValue: 'Not now' })}
                          </Button>
                        </span>
                      ) : (
                        !notApplicable(p.can?.delete) && (
                          <span className="ml-auto">
                            <ReasonedButton
                              quiet
                              size="sm"
                              variant="ghost"
                              verdict={capVerdict(p.can?.delete, 'permission_denied')}
                              icon={<Trash2 size={14} />}
                              aria-label={t('procurement_concept.ui.prequal.profile_remove', { defaultValue: 'Remove the profile {{name}}', name: p.name })}
                              onClick={() => setRemovingProfile(p.id)}
                              data-testid="profile-remove"
                            >
                              {null}
                            </ReasonedButton>
                          </span>
                        )
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {matrix.items.length === 0 ? (
            <EmptyState
              icon={<Users size={28} />}
              title={t('procurement_concept.ui.prequal.no_candidates_title', { defaultValue: 'No candidates for this package yet' })}
              description={t('procurement_concept.ui.prequal.no_candidates_body', {
                defaultValue:
                  'Add the companies you consider, score them against the profile and move the suitable ones to the short list. Then confirm the short list.',
              })}
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated shadow-sm">
              <table className="w-full text-left text-sm" data-testid="candidate-matrix">
                <thead className="bg-surface-secondary text-xs text-content-tertiary">
                  <tr>
                    <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.prequal.col_company', { defaultValue: 'Company' })}</th>
                    <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.candidate.list', { defaultValue: 'List' })}</th>
                    {criteria.map((c) => (
                      <th key={c.code} className="px-3 py-2 font-medium">
                        {catalogueName(labels, 'criterion', c.code)}
                      </th>
                    ))}
                    <th className="px-3 py-2 font-medium">{t('procurement_concept.ui.prequal.col_total', { defaultValue: 'Total' })}</th>
                    <th className="px-3 py-2 font-medium">
                      <span className="sr-only">{t('procurement_concept.ui.actions', { defaultValue: 'Actions' })}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {matrix.items.map((c) => (
                    <tr key={c.id} className="border-t border-border-light align-top" data-testid="candidate-row">
                      <td className="px-3 py-2.5">
                        <div className="font-medium text-content-primary">{c.name}</div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-content-tertiary">
                          <span>{vocab(labels.t, CANDIDATE_SOURCE, c.source)}</span>
                          {!c.registered && (
                            <span className="text-semantic-warning" data-testid="candidate-unregistered">
                              {t('procurement_concept.ui.candidate.not_registered', { defaultValue: 'Not registered yet' })}
                            </span>
                          )}
                          {c.conflict_of_interest_declared && (
                            <span className="text-semantic-error">
                              {t('procurement_concept.ui.prequal.conflict_declared', { defaultValue: 'Conflict of interest declared' })}
                            </span>
                          )}
                        </div>
                        {c.evidence.length > 0 && (
                          <ul className="mt-1 flex flex-wrap gap-1.5 text-2xs text-content-secondary">
                            {c.evidence.map((e) => (
                              <li key={e.ref} className="rounded-full border border-border-light px-2 py-0.5">
                                {e.kind === 'certificate'
                                  ? t('procurement_concept.ui.prequal.evidence_certificate', { defaultValue: 'Certificate' })
                                  : t('procurement_concept.ui.prequal.evidence_prequal', { defaultValue: 'Prequalification on file' })}
                                {e.expires && (
                                  <>
                                    {' '}
                                    {t('procurement_concept.ui.prequal.evidence_until', {
                                      defaultValue: 'until {{date}}',
                                      date: fmtDate(e.expires),
                                    })}
                                  </>
                                )}
                              </li>
                            ))}
                          </ul>
                        )}
                        {c.references.length > 0 && (
                          <ul className="mt-1 space-y-0.5 text-xs text-content-secondary" data-testid="candidate-references">
                            {c.references.map((r) => (
                              <li key={r.id} className="flex flex-wrap items-center gap-x-2">
                                <span className="text-content-primary">{r.project_name}</span>
                                {r.year && <span>{r.year}</span>}
                                {r.value && <Money value={r.value} currency={r.currency} />}
                                {r.verified && (
                                  <span className="text-semantic-success">
                                    {t('procurement_concept.ui.reference.verified', { defaultValue: 'Checked with the client' })}
                                  </span>
                                )}
                                <button
                                  type="button"
                                  className="text-content-tertiary hover:text-semantic-error"
                                  aria-label={t('procurement_concept.ui.reference.remove', {
                                    defaultValue: 'Remove reference {{name}}',
                                    name: r.project_name,
                                  })}
                                  onClick={() => removeReference.mutate({ candidateId: c.id, referenceId: r.id })}
                                >
                                  <Trash2 size={12} aria-hidden />
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                        {c.decision_rationale && <p className="mt-1 text-xs text-content-secondary">{c.decision_rationale}</p>}
                      </td>
                      <td className="px-3 py-2.5">
                        <ToneBadge tone={LIST_TONE[c.list]} testId="candidate-list">
                          {vocab(labels.t, CANDIDATE_LIST, c.list)}
                        </ToneBadge>
                      </td>
                      {criteria.map((cr) => {
                        const s = c.scores.find((x) => x.criterion_code === cr.code);
                        return (
                          <td key={cr.code} className="px-3 py-2.5 tabular-nums text-content-primary">
                            {s?.passed === true
                              ? t('procurement_concept.ui.scores.pass', { defaultValue: 'Pass' })
                              : s?.passed === false
                                ? t('procurement_concept.ui.scores.fail', { defaultValue: 'Fail' })
                                : s?.score != null
                                  ? s.score
                                  : '-'}
                          </td>
                        );
                      })}
                      <td className="px-3 py-2.5 font-medium tabular-nums text-content-primary" data-testid="candidate-total">
                        {c.total_score}
                        {c.missing_criteria.length > 0 && (
                          <div className="text-2xs font-normal text-content-tertiary">
                            {t('procurement_concept.ui.prequal.missing', {
                              defaultValue: 'Not assessed: {{n}}',
                              n: c.missing_criteria.length,
                            })}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        {removing === c.id ? (
                          <div className="space-y-1.5">
                            <p className="text-xs text-content-primary">
                              {t('procurement_concept.ui.prequal.remove_confirm', {
                                defaultValue: 'Remove {{name}} with its scores and references?',
                                name: c.name,
                              })}
                            </p>
                            <div className="flex gap-2">
                              <Button size="sm" variant="danger" loading={remove.isPending} onClick={() => remove.mutate(c.id)} data-testid="candidate-remove-yes">
                                {t('procurement_concept.ui.remove', { defaultValue: 'Remove' })}
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setRemoving(null)}>
                                {t('procurement_concept.ui.keep', { defaultValue: 'Not now' })}
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex flex-wrap justify-end gap-1.5">
                            {!notApplicable(can?.score) && (
                              <ReasonedButton quiet verdict={v('score')} size="sm" variant="secondary" disabled={criteria.length === 0} onClick={() => setOpen({ kind: 'scores', candidate: c })} data-testid="candidate-score">
                                {t('procurement_concept.ui.prequal.score', { defaultValue: 'Score' })}
                              </ReasonedButton>
                            )}
                            {!notApplicable(can?.add) && (
                              <ReasonedButton quiet verdict={v('add')} size="sm" variant="ghost" onClick={() => setOpen({ kind: 'candidate', candidate: c })} data-testid="candidate-edit">
                                {t('procurement_concept.ui.prequal.edit', { defaultValue: 'Change' })}
                              </ReasonedButton>
                            )}
                            {!notApplicable(can?.reference) && (
                              <ReasonedButton quiet verdict={v('reference')} size="sm" variant="ghost" onClick={() => setOpen({ kind: 'reference', candidate: c })} data-testid="candidate-reference">
                                {t('procurement_concept.ui.prequal.add_reference', { defaultValue: 'Add reference' })}
                              </ReasonedButton>
                            )}
                            {!notApplicable(can?.delete) && (
                              <ReasonedButton
                                quiet
                                size="sm"
                                variant="ghost"
                                verdict={v('delete')}
                                icon={<Trash2 size={14} />}
                                aria-label={t('procurement_concept.ui.prequal.remove_candidate', { defaultValue: 'Remove {{name}}', name: c.name })}
                                onClick={() => setRemoving(c.id)}
                                data-testid="candidate-remove"
                              >
                                {null}
                              </ReasonedButton>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {matrix.items.length > 0 && (
            <section className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="shortlist-check">
              <h3 className="mb-1 text-sm font-semibold text-content-primary">
                {t('procurement_concept.ui.prequal.check_title', { defaultValue: 'Is the short list ready?' })}
              </h3>
              <p className="mb-2 text-xs text-content-secondary">
                {t('procurement_concept.ui.prequal.check_summary', {
                  defaultValue: 'On the short list: {{have}}. Needed for this procedure: {{need}}.',
                  have: shortCount,
                  need: matrix.min_bidders,
                })}
              </p>
              {matrix.findings.length === 0 ? (
                <p className="flex items-center gap-2 text-sm text-content-secondary">
                  <CheckCircle2 size={16} className="text-semantic-success" aria-hidden />
                  {t('procurement_concept.ui.prequal.check_ok', { defaultValue: 'The short list meets every rule.' })}
                </p>
              ) : (
                <FindingList findings={matrix.findings} refLabel={refLabel} testId="shortlist-findings" />
              )}
            </section>
          )}
        </>
      )}

      {open?.kind === 'candidate' && (
        <CandidateDialog open onClose={close} projectId={projectId} packageId={currentId} candidate={open.candidate} listVerdict={v('set_list')} labels={labels} onSaved={onChanged} />
      )}
      {open?.kind === 'scores' && (
        <ScoresDialog open onClose={close} projectId={projectId} candidate={open.candidate} criteria={criteria} labels={labels} onSaved={onChanged} />
      )}
      {open?.kind === 'reference' && (
        <ReferenceDialog open onClose={close} projectId={projectId} candidate={open.candidate} labels={labels} onSaved={onChanged} />
      )}
      {open?.kind === 'profile' && (
        <ProfileDialog
          open
          onClose={close}
          projectId={projectId}
          packageId={currentId}
          packageCode={current.contract_package.code}
          profile={profileRow}
          criteria={catalogue?.prequal_criteria ?? []}
          labels={labels}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}
