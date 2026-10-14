// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The records that prove something: a test result, a checklist, a document.
// Nothing is uploaded here. A proof, a credit, a stage or a survey points at a
// record another module already holds, and the server reads the outcome from
// that record, so a proof is delivered when the record says so and not when
// somebody ticks a box.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link2, Trash2 } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { getErrorMessage } from '@/shared/lib/api';

import { addLink, removeLink, type Capable, type LinkOwnerKind } from './api';
import { useEvidenceLinks, useLinkCandidates, useQcWrite } from './hooks';
import { ClosedReasons } from './ClosedReasons';
import { FACT_OUTCOME, LINK_KIND, gate, vocab, type TFn } from './labels';
import { Hint, RefusalNote, inputCls } from './QualityBits';

const ALL_KINDS = Object.keys(LINK_KIND);

export interface EvidenceLinksProps {
  projectId: string;
  ownerKind: LinkOwnerKind;
  ownerId: string;
  /** The kinds of record that can prove this item; all kinds when the catalogue does not narrow it. */
  allowedKinds?: string[];
  /** The record the links belong to; its flag says whether this reader may add or remove one. */
  row?: Capable | null;
}

export function EvidenceLinks({ projectId, ownerKind, ownerId, allowedKinds, row }: EvidenceLinksProps) {
  const { t } = useTranslation();
  const lock = gate(t as TFn, row, 'link_evidence');
  const write = useQcWrite(projectId);
  const confirmState = useConfirm();
  const links = useEvidenceLinks(projectId, ownerKind, ownerId);
  const kinds = allowedKinds && allowedKinds.length > 0 ? allowedKinds : ALL_KINDS;
  const [pickedKind, setKind] = useState('');
  const kind = kinds.includes(pickedKind) ? pickedKind : (kinds[0] ?? '');
  const [q, setQ] = useState('');
  const [linkId, setLinkId] = useState('');
  const [retestOf, setRetestOf] = useState('');
  const all = links.data ?? [];
  const linkName = (id: string | null) => {
    const hit = all.find((x) => x.id === id);
    return hit ? hit.label || vocab(t as TFn, LINK_KIND, hit.link_kind) : '';
  };
  const candidates = useLinkCandidates(projectId, kind, q);
  const linked = new Set((links.data ?? []).filter((l) => l.link_kind === kind).map((l) => l.link_id));
  const offered = (candidates.data ?? []).filter((c) => !linked.has(c.id));

  return (
    <div className="space-y-2 rounded-md bg-surface-secondary p-3" data-testid="evidence-links">
      <ConfirmDialog {...confirmState} />
      <p className="text-xs font-semibold text-content-secondary">
        {t('qualityConcept.evidence.title', { defaultValue: 'Linked records' })}
      </p>
      <RefusalNote refusal={write.refusal} />
      <ClosedReasons row={row} actions={['link_evidence']} />
      {links.isLoading ? (
        <p className="text-xs text-content-tertiary">{t('qualityConcept.common.loading', { defaultValue: 'Loading...' })}</p>
      ) : links.isError ? (
        <p className="text-xs text-semantic-error">{getErrorMessage(links.error)}</p>
      ) : (links.data ?? []).length === 0 ? (
        <Hint testId="evidence-empty">
          {t('qualityConcept.evidence.empty', {
            defaultValue: 'Nothing linked yet. Pick the record that proves this, for example a test result or a signed checklist.',
          })}
        </Hint>
      ) : (
        <ul className="space-y-1" data-testid="evidence-list">
          {(links.data ?? []).map((l) => (
            <li key={l.id} className="flex flex-wrap items-center gap-2 text-sm" data-testid="evidence-entry">
              <Link2 size={12} className="text-content-tertiary" aria-hidden />
              <span className="text-content-primary">{vocab(t as TFn, LINK_KIND, l.link_kind)}</span>
              {l.label && <span className="text-content-secondary">{l.label}</span>}
              {l.fact?.outcome && (
                <Badge size="sm" variant={l.fact.outcome === 'pass' ? 'success' : l.fact.outcome === 'fail' ? 'error' : 'neutral'}>
                  {vocab(t as TFn, FACT_OUTCOME, l.fact.outcome)}
                </Badge>
              )}
              {l.fact?.calibration_expired && (
                <Badge size="sm" variant="warning">
                  {t('qualityConcept.evidence.calibration_expired', { defaultValue: 'Calibration expired' })}
                </Badge>
              )}
              {(l.fact === null || l.exists === false) && (
                <span className="text-xs text-content-tertiary">
                  {t('qualityConcept.evidence.record_gone', { defaultValue: 'The record is no longer there' })}
                </span>
              )}
              {l.retest_of && (
                <span className="text-xs text-content-secondary" data-testid="evidence-retest">
                  {linkName(l.retest_of)
                    ? t('qualityConcept.evidence.retest_of', { defaultValue: 'Retest of {{name}}', name: linkName(l.retest_of) })
                    : t('qualityConcept.evidence.retest', { defaultValue: 'Retest' })}
                </span>
              )}
              {l.note && <span className="text-xs text-content-secondary">{l.note}</span>}
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                icon={<Trash2 size={14} />}
                aria-label={t('qualityConcept.evidence.unlink', { defaultValue: 'Remove link' })}
                loading={write.pending}
                disabled={lock.disabled}
                title={lock.title}
                onClick={async () => {
                  if (
                    await confirmState.confirm({
                      title: t('qualityConcept.evidence.unlink_title', { defaultValue: 'Remove this link?' }),
                      message: t('qualityConcept.evidence.unlink_body', {
                        defaultValue: 'The record stays where it is. It no longer counts as proof for this item.',
                      }),
                      confirmLabel: t('qualityConcept.evidence.unlink', { defaultValue: 'Remove link' }),
                    })
                  ) {
                    write.send(() => removeLink(projectId, l.id));
                  }
                }}
              />
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-2 md:grid-cols-12">
        <select
          className={`${inputCls} md:col-span-3`}
          value={kind}
          aria-label={t('qualityConcept.evidence.kind', { defaultValue: 'Kind of record' })}
          onChange={(e) => {
            setKind(e.target.value);
            setLinkId('');
          }}
          data-testid="evidence-kind"
        >
          {kinds.map((k) => (
            <option key={k} value={k}>
              {vocab(t as TFn, LINK_KIND, k)}
            </option>
          ))}
        </select>
        <input
          className={`${inputCls} md:col-span-3`}
          value={q}
          aria-label={t('qualityConcept.evidence.search', { defaultValue: 'Search records' })}
          placeholder={t('qualityConcept.evidence.search', { defaultValue: 'Search records' })}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          className={`${inputCls} md:col-span-4`}
          value={linkId}
          aria-label={t('qualityConcept.evidence.record', { defaultValue: 'Record' })}
          onChange={(e) => setLinkId(e.target.value)}
          data-testid="evidence-candidate"
        >
          <option value="">
            {candidates.isLoading
              ? t('qualityConcept.common.loading', { defaultValue: 'Loading...' })
              : offered.length === 0
                ? t('qualityConcept.evidence.no_candidates', { defaultValue: 'No record of this kind in the project' })
                : t('qualityConcept.evidence.choose', { defaultValue: 'Choose a record' })}
          </option>
          {offered.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        {all.length > 0 && (
          <select
            className={`${inputCls} md:col-span-10`}
            value={retestOf}
            aria-label={t('qualityConcept.evidence.retest_pick', { defaultValue: 'Repeats an earlier record' })}
            onChange={(e) => setRetestOf(e.target.value)}
            data-testid="evidence-retest-of"
          >
            <option value="">{t('qualityConcept.evidence.not_a_retest', { defaultValue: 'Not a retest' })}</option>
            {all.map((l) => (
              <option key={l.id} value={l.id}>
                {t('qualityConcept.evidence.retest_of', { defaultValue: 'Retest of {{name}}', name: linkName(l.id) })}
              </option>
            ))}
          </select>
        )}
        <Button
          size="sm"
          variant="secondary"
          className="md:col-span-2"
          disabled={!linkId || lock.disabled}
          title={lock.title}
          loading={write.pending}
          onClick={() =>
            write.send(
              () =>
                addLink(projectId, {
                  owner_kind: ownerKind,
                  owner_id: ownerId,
                  link_kind: kind,
                  link_id: linkId,
                  ...(retestOf ? { retest_of: retestOf } : {}),
                }),
              () => {
                setLinkId('');
                setRetestOf('');
              },
            )
          }
          data-testid="evidence-add"
        >
          {t('qualityConcept.evidence.link', { defaultValue: 'Link record' })}
        </Button>
      </div>
    </div>
  );
}
