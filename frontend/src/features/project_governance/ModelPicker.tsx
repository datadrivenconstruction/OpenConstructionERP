// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Choosing the phase model a project runs through. Setting it the first time
// is one click. Changing it once gates are decided needs a phase mapping, so
// the decided history keeps a place in the new model; that step only appears
// when it is needed.

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowRight, Layers } from 'lucide-react';
import clsx from 'clsx';

import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { fmtList } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';

import {
  changeModel,
  getProjectCountry,
  governanceErrorCode,
  governanceKeys,
  listCatalogues,
  setModel,
  updateModelSettings,
  type CatalogueSummary,
  type GovernanceGate,
  type GovernanceModel,
} from './api';
import { canManage, frozenInReview, type Verdict } from './access';
import { RoutePin } from './RoutePin';
import { ReasonedButton, VerdictReason } from './GovernanceBits';
import { catalogueName, errorText, humanizeCode, refusalText, type LabelContext } from './labels';

export interface ModelPickerProps {
  projectId: string;
  model: GovernanceModel | null;
  /** Without a model: the server's word on whether the reader may set one. */
  canSet?: boolean | null;
  gates: GovernanceGate[];
  labels: LabelContext;
  onDone: () => void;
}

function catalogueTitle(labels: LabelContext, c: CatalogueSummary): string {
  if (c.name?.key && labels.exists(c.name.key)) return labels.t(c.name.key);
  if (c.name?.text) return c.name.text[labels.language] ?? c.name.text.en ?? Object.values(c.name.text)[0] ?? c.code;
  return humanizeCode(c.code);
}

export function ModelPicker({ projectId, model, canSet = null, gates, labels, onDone }: ModelPickerProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  // Before a model exists the flag comes with the `model_missing` answer.
  // A server that sends none leaves the picker open, and its refusal of the
  // first try is what closes it. The reason then stays on the button.
  const [refused, setRefused] = useState<Verdict>(null);
  const verdict: Verdict = model ? canManage(model) : canSet === false ? 'role_manage' : refused;
  // The country matters only for the first choice: it lets the server mark
  // the model to start with. A project that cannot be read simply gets none.
  const countryQ = useQuery({
    queryKey: [...governanceKeys.model(projectId), 'country'],
    queryFn: () => getProjectCountry(projectId),
    enabled: !model,
    retry: false,
  });
  const country = countryQ.data ?? null;
  const catalogues = useQuery({
    queryKey: [...governanceKeys.catalogues, country ?? ''],
    queryFn: () => listCatalogues(country).then((p) => p.items),
    enabled: !!model || countryQ.isFetched,
  });
  const [selected, setSelected] = useState<string>('');
  // The server's default is offered once, as a selection the reader can change before saving.
  const offeredDefault = useRef(false);
  useEffect(() => {
    if (model || offeredDefault.current || !catalogues.data) return;
    offeredDefault.current = true;
    const preset = catalogues.data.find((c) => c.default && c.state === 'published');
    if (preset) setSelected(`${preset.source}:${preset.id}`);
  }, [model, catalogues.data]);
  const [fourEyes, setFourEyes] = useState(true);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [askMapping, setAskMapping] = useState(false);
  const decided = gates.some((g) => g.status === 'decided');
  const needsMapping = !!model && (decided || askMapping);
  const choice = catalogues.data?.find((c) => `${c.source}:${c.id}` === selected) ?? null;

  const oldPhases = useMemo(() => [...(model?.phases ?? [])].sort((a, b) => a.order - b.order), [model]);

  const save = useMutation({
    mutationFn: async () => {
      if (!choice) return null;
      const base = {
        catalogue_source: choice.source,
        catalogue_id: choice.id,
        catalogue_version: choice.latest_version ?? undefined,
      };
      if (!model) return setModel(projectId, { ...base, four_eyes: fourEyes });
      return changeModel(projectId, { ...base, mapping: needsMapping ? mapping : {} });
    },
    onSuccess: () => {
      setSelected('');
      setMapping({});
      setAskMapping(false);
      onDone();
    },
    onError: (err) => {
      if (governanceErrorCode(err) === 'phase_mapping_missing') {
        setAskMapping(true);
        return;
      }
      if (!model && err instanceof ApiError && err.status === 403) {
        setRefused('role_manage');
        return;
      }
      addToast({ type: 'error', title: refusalText(t, err) });
    },
  });
  const toggleFourEyes = useMutation({
    mutationFn: (value: boolean) => updateModelSettings(projectId, { four_eyes: value }),
    onSuccess: onDone,
    onError: (err) => addToast({ type: 'error', title: refusalText(t, err) }),
  });

  if (catalogues.isPending) return <SkeletonTable rows={4} columns={2} />;
  if (catalogues.isError) {
    return (
      <ErrorState
        title={t('governance.project.model.load_failed', { defaultValue: 'The phase models could not be loaded' })}
        hint={getErrorMessage(catalogues.error)}
        onRetry={() => catalogues.refetch()}
      />
    );
  }
  const items = (catalogues.data ?? []).filter((c) => c.state === 'published');
  const mappingIncomplete = needsMapping && oldPhases.some((p) => !mapping[p.code]);

  return (
    <div className="space-y-4" data-testid="model-picker">
      {model && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface-elevated shadow-sm p-3 text-sm">
          <Layers size={16} className="text-content-tertiary" aria-hidden />
          <span className="text-content-secondary">
            {t('governance.project.model.current', { defaultValue: 'Current phase model' })}
          </span>
          <span className="font-semibold text-content-primary">
            {(() => {
              const current = catalogues.data?.find((c) => c.id === model.catalogue_id);
              return current ? catalogueTitle(labels, current) : humanizeCode(model.catalogue_id);
            })()}
          </span>
          <span className="text-xs text-content-tertiary">
            {t('governance.project.model.version', { defaultValue: 'Version {{n}}', n: model.catalogue_version })}
          </span>
          <div className="ml-auto flex flex-col items-end gap-1">
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={model.four_eyes}
                disabled={!!verdict || !!frozenInReview(gates) || toggleFourEyes.isPending}
                onChange={(e) => toggleFourEyes.mutate(e.target.checked)}
              />
              {t('governance.project.model.four_eyes', { defaultValue: 'Four-eyes rule: an area owner may not decide a gate' })}
            </label>
            <VerdictReason verdict={verdict ?? frozenInReview(gates)} />
          </div>
        </div>
      )}

      {model && (
        <div className="space-y-3" id="governance-routes">
          <RoutePin projectId={projectId} model={model} kind="gate" onDone={onDone} />
          <RoutePin projectId={projectId} model={model} kind="change" onDone={onDone} />
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-content-primary">
          {model
            ? t('governance.project.model.change_title', { defaultValue: 'Change the phase model' })
            : t('governance.project.model.choose_title', { defaultValue: 'Choose a phase model' })}
        </h3>
        {items.length === 0 && (
          <p className="text-sm text-content-secondary" data-testid="model-picker-empty">
            {t('governance.project.model.none_published', {
              defaultValue:
                'No published phase model is available. A governance manager publishes one in the governance settings of the organisation.',
            })}
          </p>
        )}
        <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3" role="radiogroup">
          {items.map((c) => {
            const key = `${c.source}:${c.id}`;
            const isCurrent = model?.catalogue_id === c.id && model.catalogue_source === c.source;
            return (
              <label
                key={key}
                className={clsx(
                  'flex cursor-pointer flex-col gap-1 rounded-lg border p-3 text-sm',
                  selected === key ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light hover:border-border',
                  isCurrent && 'opacity-60',
                )}
              >
                <span className="flex items-center gap-2 font-medium text-content-primary">
                  <input
                    type="radio"
                    name="catalogue"
                    value={key}
                    disabled={isCurrent || !!verdict}
                    checked={selected === key}
                    onChange={() => setSelected(key)}
                  />
                  {catalogueTitle(labels, c)}
                </span>
                <span className="text-xs text-content-tertiary">
                  {c.source === 'tenant'
                    ? t('governance.project.model.source_tenant', { defaultValue: 'Your organisation' })
                    : c.source === 'pack'
                      ? t('governance.project.model.source_pack', { defaultValue: 'From the active pack' })
                      : t('governance.project.model.source_shipped', { defaultValue: 'Included with the platform' })}
                  {c.default &&
                    ` · ${t('governance.project.model.recommended', { defaultValue: 'Suggested for this project' })}`}
                  {c.jurisdiction_countries.length > 0 && ` · ${fmtList(c.jurisdiction_countries)}`}
                </span>
                {c.review_status === 'unconfirmed' && (
                  <span className="text-2xs text-[#b45309]">
                    {t('governance.project.model.unconfirmed', {
                      defaultValue: 'Some entries are not yet verified against the primary source.',
                    })}
                  </span>
                )}
                {isCurrent && (
                  <span className="text-2xs text-content-tertiary">
                    {t('governance.project.model.in_use', { defaultValue: 'In use' })}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      </div>

      {!model && (
        <label className="inline-flex items-center gap-2 text-sm">
          <input type="checkbox" checked={fourEyes} onChange={(e) => setFourEyes(e.target.checked)} disabled={!!verdict} />
          {t('governance.project.model.four_eyes', { defaultValue: 'Four-eyes rule: an area owner may not decide a gate' })}
        </label>
      )}

      {choice && needsMapping && (
        <section className="rounded-lg border border-semantic-warning/40 bg-semantic-warning-bg p-3" data-testid="phase-mapping">
          <h4 className="text-sm font-semibold text-content-primary">
            {t('governance.project.model.mapping_title', { defaultValue: 'Map the phases' })}
          </h4>
          <p className="mb-2 text-xs text-content-secondary">
            {t('governance.project.model.mapping_body', {
              defaultValue: 'Gates on this project are already decided. Say where each current phase lands in the new model; decided gates are kept.',
            })}
          </p>
          <div className="grid gap-2 md:grid-cols-2">
            {oldPhases.map((p) => (
              <label key={p.code} className="flex items-center gap-2 text-sm">
                <span className="w-40 shrink-0 truncate text-content-primary">
                  {catalogueName(labels, { kind: 'phase', code: p.code, catalogueId: model?.catalogue_id, label: p.name })}
                </span>
                <ArrowRight size={14} aria-hidden className="shrink-0 text-content-tertiary" />
                {choice.phases && choice.phases.length > 0 ? (
                  <select
                    className="flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
                    value={mapping[p.code] ?? ''}
                    onChange={(e) => setMapping((m) => ({ ...m, [p.code]: e.target.value }))}
                  >
                    <option value="">{t('governance.project.model.mapping_choose', { defaultValue: 'Choose phase' })}</option>
                    {[...choice.phases]
                      .sort((a, b) => a.order - b.order)
                      .map((np) => (
                        <option key={np.code} value={np.code}>
                          {catalogueName(labels, { kind: 'phase', code: np.code, catalogueId: choice.id, label: np.name })}
                        </option>
                      ))}
                  </select>
                ) : (
                  <input
                    className="flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
                    placeholder={t('governance.project.model.mapping_code', { defaultValue: 'Phase code in the new model' })}
                    value={mapping[p.code] ?? ''}
                    onChange={(e) => setMapping((m) => ({ ...m, [p.code]: e.target.value.trim() }))}
                  />
                )}
              </label>
            ))}
          </div>
        </section>
      )}

      {save.isError && governanceErrorCode(save.error) && governanceErrorCode(save.error) !== 'phase_mapping_missing' && (
        <p className="text-sm text-semantic-error">{errorText(t, governanceErrorCode(save.error) as string)}</p>
      )}

      <ReasonedButton
        verdict={verdict}
        disabled={!choice || mappingIncomplete}
        loading={save.isPending}
        onClick={() => save.mutate()}
        data-testid="model-save"
      >
        {model
          ? t('governance.project.model.change_apply', { defaultValue: 'Change phase model' })
          : t('governance.project.model.set_apply', { defaultValue: 'Use this phase model' })}
      </ReasonedButton>
    </div>
  );
}
