// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The link from a schedule of values line to the bill it measures.
//
// "Populate from progress" bills each schedule line at the latest progress
// reading of the BOQ position the line is linked to, and a line with no link is
// skipped. The link lived in the line's metadata and nothing on screen could
// set it, so a monthly claim could only be filled in through the API. This is
// that screen: pick the BOQ position the line measures and the line's code in
// the project's own classification standard, whichever that is.
//
// The link is reference data rather than money, so the server takes it on a
// signed contract and on a line a claim has already billed, where every other
// change to the line is refused.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link2 } from 'lucide-react';

import { Button } from '@/shared/ui';
import { SearchableSelect, type SearchableSelectOption } from '@/shared/ui/SearchableSelect';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { useToastStore } from '@/stores/useToastStore';
import { updateContractLine, type ContractLine } from './api';

/** Where the server keeps the link on a line; the progress bridge reads the same key. */
export const BOQ_POSITION_META_KEY = 'boq_position_id';

interface BoqSummary {
  id: string;
  name: string;
}

interface BoqPositionForLink {
  id: string;
  parent_id: string | null;
  ordinal: string;
  description: string;
  unit: string;
  classification?: Record<string, unknown> | null;
}

const INPUT_CLS =
  'rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm text-content-primary';

/** The BOQ position a line is linked to, or '' when it has none. */
export function linkedPositionId(line: ContractLine): string {
  const raw = line.metadata?.[BOQ_POSITION_META_KEY];
  return typeof raw === 'string' ? raw : '';
}

/** The line's own classification codes, keyed by standard. */
export function lineClassification(line: ContractLine): Record<string, string> {
  const raw = line.metadata?.classification;
  if (!raw || typeof raw !== 'object') return {};
  const out: Record<string, string> = {};
  for (const [std, code] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof code === 'string' && code) out[std] = code;
  }
  return out;
}

function positionLabel(p: BoqPositionForLink): string {
  return p.ordinal ? `${p.ordinal}  ${p.description}` : p.description;
}

/**
 * Edit one line's link and classification code.
 *
 * The BOQ list, the positions and the project's classification standard are
 * read here, each under the key the rest of the app reads it by, so opening
 * the editor on a second line costs nothing. Section headers are not offered:
 * progress is recorded against the positions under them.
 */
export function SovLineLinkEditor({
  line,
  contractId,
  projectId,
  onDone,
}: {
  line: ContractLine;
  contractId: string;
  projectId: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const projectQ = useQuery({
    queryKey: ['projects', 'detail', projectId],
    queryFn: () => projectsApi.get(projectId),
    enabled: !!projectId,
  });
  const standard = projectQ.data?.classification_standard ?? '';

  const boqsQ = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () =>
      apiGet<BoqSummary[]>(`/v1/boq/boqs/?project_id=${encodeURIComponent(projectId)}`),
    enabled: !!projectId,
  });
  const boqs = boqsQ.data ?? [];
  const [pickedBoqId, setPickedBoqId] = useState('');
  const boqId = pickedBoqId || boqs[0]?.id || '';

  const positionsQ = useQuery({
    queryKey: ['contracts', 'sov-link-positions', boqId],
    queryFn: () =>
      apiGet<{ positions: BoqPositionForLink[] }>(`/v1/boq/boqs/${encodeURIComponent(boqId)}`).then(
        (b) => b.positions ?? [],
      ),
    enabled: !!boqId,
  });
  const positions = useMemo(() => positionsQ.data ?? [], [positionsQ.data]);

  const options = useMemo<SearchableSelectOption[]>(() => {
    const parents = new Set(positions.map((p) => p.parent_id).filter(Boolean));
    return positions
      .filter((p) => !parents.has(p.id))
      .map((p) => ({ value: p.id, label: p.description || p.ordinal, hint: p.ordinal, keywords: p.unit }));
  }, [positions]);

  const [positionId, setPositionId] = useState(() => linkedPositionId(line));
  const [code, setCode] = useState<string | null>(null);
  const stored = lineClassification(line);
  // The code field starts on the line's own code for the project's standard,
  // and follows the picked position's code until the person types one.
  const pickedPosition = positions.find((p) => p.id === positionId);
  const positionCode =
    standard && pickedPosition?.classification && typeof pickedPosition.classification[standard] === 'string'
      ? (pickedPosition.classification[standard] as string)
      : '';
  const shownCode = code ?? (stored[standard] || positionCode);

  const saveMut = useMutation({
    mutationFn: () => {
      const metadata: Record<string, unknown> = { [BOQ_POSITION_META_KEY]: positionId || null };
      if (standard) {
        const next = { ...stored };
        if (shownCode.trim()) next[standard] = shownCode.trim();
        else delete next[standard];
        metadata.classification = next;
      }
      return updateContractLine(line.id, { metadata });
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['contracts', 'lines', contractId] });
      qc.invalidateQueries({ queryKey: ['contracts', 'compliance-gate', contractId] });
      addToast({
        type: 'success',
        title: t('contracts.sov_link_saved', { defaultValue: 'Line linked to the bill' }),
      });
      onDone();
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const standardName = standard
    ? t(`validation.rs_label_${standard}`, { defaultValue: standard })
    : '';

  return (
    <div
      data-testid={`sov-link-editor-${line.id}`}
      className="space-y-2 rounded-lg border border-dashed border-border-light bg-surface-secondary/40 p-3"
    >
      <p className="flex items-center gap-2 text-xs text-content-secondary">
        <Link2 size={13} className="text-oe-blue" />
        {t('contracts.sov_link_hint', {
          defaultValue:
            'Populate from progress bills this line at the latest progress reading of the position it is linked to.',
        })}
      </p>
      {boqsQ.isLoading ? (
        <p className="text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </p>
      ) : boqs.length === 0 ? (
        <p className="text-sm text-content-tertiary">
          {t('contracts.sov_link_no_boq', { defaultValue: 'This project has no BOQ to link to yet.' })}
        </p>
      ) : (
        <div className="flex flex-wrap items-end gap-2">
          {boqs.length > 1 && (
            <label className="flex min-w-[8rem] flex-col gap-1 text-xs text-content-secondary">
              {t('contracts.sov_link_boq', { defaultValue: 'BOQ' })}
              <select
                data-testid="sov-link-boq"
                className={INPUT_CLS}
                value={boqId}
                onChange={(e) => {
                  setPickedBoqId(e.target.value);
                  setPositionId('');
                }}
              >
                {boqs.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="flex min-w-[14rem] flex-[2] flex-col gap-1 text-xs text-content-secondary">
            <span id={`sov-link-position-label-${line.id}`}>
              {t('contracts.sov_link_position', { defaultValue: 'BOQ position' })}
            </span>
            <SearchableSelect
              value={positionId}
              onChange={setPositionId}
              options={options}
              loading={positionsQ.isLoading}
              allowEmpty
              emptyLabel={t('contracts.sov_link_none', { defaultValue: 'Not linked' })}
              placeholder={t('contracts.sov_link_pick', { defaultValue: 'Pick the position this line measures' })}
              data-testid="sov-link-position"
            />
          </div>
          {standard && (
            <label className="flex min-w-[8rem] flex-1 flex-col gap-1 text-xs text-content-secondary">
              {t('contracts.sov_link_code', {
                defaultValue: '{{standard}} code',
                standard: standardName,
              })}
              <input
                type="text"
                data-testid="sov-link-code"
                className={INPUT_CLS}
                value={shownCode}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
          )}
          <div className="flex gap-1">
            <Button
              size="sm"
              data-testid="sov-link-save"
              onClick={() => saveMut.mutate()}
              loading={saveMut.isPending}
            >
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button size="sm" variant="secondary" onClick={onDone}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </div>
      )}
      {pickedPosition && (
        <p className="text-xs text-content-tertiary" data-testid="sov-link-picked">
          {positionLabel(pickedPosition)}
          {pickedPosition.unit ? ` (${pickedPosition.unit})` : ''}
        </p>
      )}
    </div>
  );
}

/**
 * What the row shows about the link: the position's number and the line's
 * code, or an offer to link it. The row holds the position id only, so the
 * number comes from the position itself.
 */
export function SovLineLinkSummary({
  line,
  canLink,
  onOpen,
}: {
  line: ContractLine;
  canLink: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const positionId = linkedPositionId(line);
  const codes = Object.values(lineClassification(line));
  const positionQ = useQuery({
    queryKey: ['boq-position', positionId],
    queryFn: () => apiGet<BoqPositionForLink>(`/v1/boq/positions/${encodeURIComponent(positionId)}`),
    enabled: !!positionId,
    retry: false,
  });
  const linked = positionId
    ? t('contracts.sov_link_linked', {
        defaultValue: 'BOQ {{position}}',
        position: positionQ.data?.ordinal || positionQ.data?.description || '…',
      })
    : '';
  const text = [linked, ...codes].filter(Boolean).join(' · ');

  if (!canLink) {
    return text ? <span className="block text-xs text-content-tertiary">{text}</span> : null;
  }
  return (
    <button
      type="button"
      data-testid={`sov-link-open-${line.id}`}
      onClick={onOpen}
      className="flex items-center gap-1 text-xs text-oe-blue hover:underline"
    >
      <Link2 size={11} />
      {text || t('contracts.sov_link_open', { defaultValue: 'Link to BOQ' })}
    </button>
  );
}
