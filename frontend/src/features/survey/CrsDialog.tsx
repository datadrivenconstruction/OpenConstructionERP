// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Set project CRS: suggestions from the project pin and the active pack, a
 * search over the EPSG catalogue for what the person types, a plain warning,
 * and a typed confirmation once points exist. Nothing is applied silently.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import { Button, ConfidenceBadge, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { searchCrs, setProjectCrs, type ProjectCrsInput, type ProjectCrsState } from './api';
import { changeNeedsTypedConfirm, crsWarning, mergeOptions, normaliseQuery, preselect, typedConfirmMatches } from './crsPicker';

const LABEL = 'oe-label';
const INPUT = 'oe-input w-full';

interface Props {
  open: boolean;
  projectId: string;
  state: ProjectCrsState | undefined;
  onClose: () => void;
}

function numOrNull(v: string): number | null {
  const n = Number(v.replace(',', '.'));
  return v.trim() !== '' && Number.isFinite(n) ? n : null;
}

export function CrsDialog({ open, projectId, state, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const current = state?.crs ?? null;
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [local, setLocal] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [verticalEpsg, setVerticalEpsg] = useState('');
  const [origin, setOrigin] = useState({ e: '', n: '', rot: '', scale: '' });
  const [typed, setTyped] = useState('');

  const q = normaliseQuery(query);
  const search = useQuery({
    queryKey: ['survey', 'crs-search', q],
    queryFn: () => searchCrs(q),
    enabled: open && q !== '',
    staleTime: 5 * 60_000,
  });
  const options = useMemo(() => mergeOptions(state?.suggestions ?? [], search.data ?? []), [state, search.data]);

  useEffect(() => {
    if (!open) return;
    setSelected(preselect(options, current?.horizontal_epsg ?? null));
    setLocal(current?.is_local_grid ?? false);
    setVerticalEpsg(current?.vertical_epsg ? String(current.vertical_epsg) : '');
    setTyped('');
    // Preselect once per opening, not on every search keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, current]);

  const chosen = options.find((o) => o.epsg === selected);
  const warning = local ? null : crsWarning(chosen);
  const needsTyped = changeNeedsTypedConfirm(current, state?.point_count ?? 0, local ? null : selected, local);
  const canSave = (local || selected != null) && (!needsTyped || typedConfirmMatches(typed, selected, local));

  const save = useMutation({
    mutationFn: () => {
      const body: ProjectCrsInput = {
        horizontal_epsg: local ? null : selected,
        vertical_mode: verticalEpsg.trim() ? 'epsg' : 'same_as_source',
        vertical_epsg: numOrNull(verticalEpsg),
        is_local_grid: local,
        local_origin_e: local ? numOrNull(origin.e) : null,
        local_origin_n: local ? numOrNull(origin.n) : null,
        local_rotation_deg: local ? numOrNull(origin.rot) : null,
        local_scale_factor: local ? numOrNull(origin.scale) : null,
        source: chosen?.reason === 'detected' ? 'detected' : 'user',
        detected_confidence: chosen?.reason === 'detected' ? chosen.confidence ?? null : null,
        confirm_text: needsTyped ? typed.trim() : '',
      };
      return setProjectCrs(projectId, body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['survey'] });
      addToast({ type: 'success', title: t('survey.crs.saved', { defaultValue: 'Project coordinate system saved' }) });
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const reasonText = (reason?: string, pack?: string) => {
    if (reason === 'project_location') return t('survey.crs.reason_location', { defaultValue: 'fits project location' });
    if (reason === 'pack') return t('survey.crs.reason_pack', { defaultValue: 'used in {{country}}', country: pack ?? '' });
    if (reason === 'detected') return t('survey.crs.reason_detected', { defaultValue: 'found in your file, please confirm' });
    if (reason === 'geographic') return t('survey.crs.reason_geographic', { defaultValue: 'lat/lon, not for volumes or areas' });
    return '';
  };

  const useLabel = local
    ? t('survey.crs.use_local', { defaultValue: 'Use local grid' })
    : selected != null
      ? t('survey.crs.use_epsg', { defaultValue: 'Use EPSG {{code}}', code: selected })
      : t('survey.action.set_crs', { defaultValue: 'Set project CRS' });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      title={t('survey.crs.title', { defaultValue: 'Project coordinate system' })}
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" disabled={!canSave} loading={save.isPending} onClick={() => save.mutate()} data-testid="survey-crs-save">
            {useLabel}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <div>
          <label className={LABEL} htmlFor="survey-crs-search">
            {t('survey.crs.search_label', { defaultValue: 'Search by EPSG code or name' })}
          </label>
          <input
            id="survey-crs-search"
            className={INPUT}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="32633"
            title={t('survey.crs.search_tip', { defaultValue: 'EPSG code (a number such as 32633) or part of the name' })}
            disabled={local}
          />
        </div>

        <fieldset disabled={local}>
          <legend className="text-xs font-medium text-content-secondary mb-1">
            {t('survey.crs.suggested', { defaultValue: 'Suggested for this project' })}
          </legend>
          <div className="max-h-64 overflow-y-auto rounded-lg border border-border-light divide-y divide-border-light">
            {options.length === 0 && (
              <p className="p-3 text-sm text-content-secondary">
                {t('survey.crs.no_options', { defaultValue: 'Type an EPSG code or a name to search.' })}
              </p>
            )}
            {options.map((o) => (
              <label key={o.epsg} className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer hover:bg-surface-secondary">
                <input type="radio" name="survey-crs" checked={selected === o.epsg} onChange={() => setSelected(o.epsg)} />
                <bdi dir="ltr" className="font-mono w-24 shrink-0">EPSG {o.epsg}</bdi>
                <span className="flex-1 min-w-0 truncate">{o.name}</span>
                {o.reason && <span className="text-xs text-content-tertiary">{reasonText(o.reason, o.pack_country)}</span>}
                {o.confidence != null && <ConfidenceBadge score={o.confidence} showScore size="sm" />}
              </label>
            ))}
          </div>
        </fieldset>

        {warning && (
          <p className="text-sm text-semantic-warning">
            {warning === 'geographic'
              ? t('survey.crs.warn_geographic', {
                  defaultValue: 'Latitude and longitude are angles, not metres. Volumes and areas need a projected system.',
                })
              : t('survey.crs.warn_vertical', { defaultValue: 'This is a height system. Pick it under Heights in Advanced options.' })}
          </p>
        )}

        <div className="flex gap-2 rounded-lg bg-surface-secondary p-3 text-sm">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" aria-hidden />
          <span>
            {t('survey.crs.warning', {
              defaultValue:
                'Pick the system your surveyor used. A wrong choice moves every point by metres and nobody will notice. We never convert silently.',
            })}
          </span>
        </div>

        <button type="button" className="text-sm text-oe-blue hover:underline" onClick={() => setAdvanced((v) => !v)} aria-expanded={advanced}>
          {t('survey.action.advanced', { defaultValue: 'Advanced options' })}
        </button>
        {advanced && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className={LABEL} htmlFor="survey-crs-vertical">
                {t('survey.crs.vertical', { defaultValue: 'Heights: vertical EPSG (empty = same as source, no conversion)' })}
              </label>
              <input id="survey-crs-vertical" className={INPUT} inputMode="numeric" value={verticalEpsg} onChange={(e) => setVerticalEpsg(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={local} onChange={(e) => setLocal(e.target.checked)} />
              {t('survey.crs.local_grid', { defaultValue: 'Local site grid (not tied to the earth)' })}
            </label>
            {local && (
              <>
                {(
                  [
                    ['e', t('survey.crs.origin_e', { defaultValue: 'Origin E (m)' })],
                    ['n', t('survey.crs.origin_n', { defaultValue: 'Origin N (m)' })],
                    ['rot', t('survey.crs.rotation', { defaultValue: 'Rotation (degrees)' })],
                    ['scale', t('survey.crs.scale', { defaultValue: 'Scale factor' })],
                  ] as const
                ).map(([key, label]) => (
                  <div key={key}>
                    <label className={LABEL} htmlFor={`survey-crs-${key}`}>{label}</label>
                    <input
                      id={`survey-crs-${key}`}
                      className={INPUT}
                      inputMode="decimal"
                      title={label}
                      value={origin[key]}
                      onChange={(e) => setOrigin((o) => ({ ...o, [key]: e.target.value }))}
                    />
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {needsTyped && (
          <div className="rounded-lg border border-semantic-error/40 p-3 space-y-2">
            <p className="text-sm">
              {t('survey.crs.change_warning', {
                defaultValue:
                  'This project already has {{count}} points. Changing the system does not move them; it changes what they mean. Type {{code}} to confirm.',
                count: state?.point_count ?? 0,
                code: local ? 'LOCAL' : String(selected ?? ''),
              })}
            </p>
            <input className={INPUT} value={typed} onChange={(e) => setTyped(e.target.value)} aria-label={t('survey.crs.type_code', { defaultValue: 'Type the code to confirm' })} />
          </div>
        )}
      </div>
    </WideModal>
  );
}
