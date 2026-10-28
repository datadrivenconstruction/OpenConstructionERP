import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { listAssets } from '@/features/assets/api';
import { compareNames } from '@/shared/lib/collator';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { useToastStore } from '@/stores/useToastStore';
import { updatePunchItem, type PunchAssetKind, type PunchItem } from './api';

const inputCls = 'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm';
const TAG = 'tag';

export interface PunchAssetLink {
  asset_kind: PunchAssetKind;
  asset_ref: string;
  asset_label: string;
}

/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ Zone, floor or room: free text, with the areas already used on the project offered. */
export function PunchAreaField({ value, onChange, suggestions = [], disabled = false, label, placeholder }: {
  value: string; onChange: (value: string) => void; suggestions?: string[]; disabled?: boolean;
  label: string; placeholder?: string;
}) {
  const id = useId();
  const listId = `${id}-areas`;
  return <div className="space-y-1.5">
    <label htmlFor={id} className="text-sm font-medium text-content-secondary">{label}</label>
    <input id={id} list={listId} value={value} disabled={disabled} placeholder={placeholder} className={inputCls}
      maxLength={255} onChange={event => onChange(event.target.value)} />
    <datalist id={listId}>{suggestions.map(area => <option key={area} value={area} />)}</datalist>
  </div>;
}

/** Picks an asset from the project's register, or takes a free tag for what nobody modelled. */
export function PunchAssetField({ projectId, value, onChange, disabled = false }: {
  projectId: string; value: PunchAssetLink | null; onChange: (value: PunchAssetLink | null) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const id = useId();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['punch-asset-options', projectId],
    queryFn: () => listAssets(projectId, { limit: 100 }),
    enabled: Boolean(projectId),
  });
  const assets = data?.items ?? [];
  const inRegister = value?.asset_kind === 'bim_element' && assets.some(a => a.id === value.asset_ref);
  const [tagMode, setTagMode] = useState(value != null && value.asset_kind !== 'bim_element');
  const selectValue = tagMode ? TAG : value?.asset_kind === 'bim_element' ? value.asset_ref : '';

  function pick(next: string) {
    if (next === TAG) { setTagMode(true); return; }
    setTagMode(false);
    const asset = assets.find(a => a.id === next);
    onChange(asset ? { asset_kind: 'bim_element', asset_ref: asset.id, asset_label: asset.name || asset.stable_id } : null);
  }

  return <div className="space-y-1.5">
    <label htmlFor={id} className="text-sm font-medium text-content-secondary">
      {t('punch.field_asset', { defaultValue: 'Asset' })}
    </label>
    <select id={id} value={selectValue ?? ''} disabled={disabled || isLoading} className={inputCls}
      onChange={event => pick(event.target.value)}>
      <option value="">{t('common.not_set')}</option>
      {value?.asset_kind === 'bim_element' && !inRegister && !isLoading
        && <option value={value.asset_ref}>{value.asset_label || value.asset_ref}</option>}
      {assets.map(asset => <option key={asset.id} value={asset.id}>
        {asset.name || asset.stable_id}{asset.storey ? ` (${asset.storey})` : ''}
      </option>)}
      <option value={TAG}>{t('punch.asset_other', { defaultValue: 'Other asset (enter a tag)' })}</option>
    </select>
    {tagMode && <input aria-label={t('punch.asset_tag', { defaultValue: 'Asset tag or id' })} className={inputCls}
      disabled={disabled} maxLength={100} value={value && value.asset_kind !== 'bim_element' ? value.asset_ref : ''}
      placeholder={t('punch.asset_tag', { defaultValue: 'Asset tag or id' })}
      onChange={event => {
        const tag = event.target.value.trim();
        onChange(tag ? { asset_kind: 'tag', asset_ref: tag, asset_label: tag } : null);
      }} />}
    {isError && <p role="alert" className="text-sm text-semantic-error">{t('common.error')}</p>}
  </div>;
}

/** Area and asset of an existing item, saved as they change. */
export function PunchLocationAssignment({ item, areaSuggestions = [], onSaved }: {
  item: PunchItem; areaSuggestions?: string[]; onSaved: () => unknown;
}) {
  const { t } = useTranslation();
  const canEdit = useHasPermission('punchlist.update');
  const toast = useToastStore(s => s.addToast);
  const [area, setArea] = useState(item.area ?? '');
  const mutation = useMutation({
    mutationFn: (patch: Parameters<typeof updatePunchItem>[1]) => updatePunchItem(item.id, patch),
    onSuccess: async () => { await onSaved(); },
    onError: (error: Error) => toast({ type: 'error', title: t('common.error'), message: error.message }),
  });
  const link: PunchAssetLink | null = item.asset_ref
    ? { asset_kind: item.asset_kind ?? 'tag', asset_ref: item.asset_ref, asset_label: item.asset_label ?? item.asset_ref }
    : null;
  return <div className="space-y-3">
    <div onBlur={() => { if (area.trim() !== (item.area ?? '')) mutation.mutate({ area: area.trim() || null }); }}>
      <PunchAreaField value={area} onChange={setArea} suggestions={areaSuggestions}
        disabled={!canEdit || mutation.isPending} label={t('punch.field_location', { defaultValue: 'Location' })} />
    </div>
    <PunchAssetField projectId={item.project_id} value={link} disabled={!canEdit || mutation.isPending}
      onChange={next => mutation.mutate(next ? { ...next } : { asset_ref: null })} />
  </div>;
}

/** Distinct areas and assets across items, plus the values currently filtered on. */
export function locationOptions(
  items: Pick<PunchItem, 'area' | 'asset_ref' | 'asset_label'>[],
  selectedArea = '',
  selectedAsset = '',
): { areas: string[]; assets: { ref: string; label: string }[] } {
  const areas = new Set<string>();
  const assets = new Map<string, string>();
  for (const item of items) {
    if (item.area) areas.add(item.area);
    if (item.asset_ref && !assets.has(item.asset_ref)) assets.set(item.asset_ref, item.asset_label || item.asset_ref);
  }
  if (selectedArea) areas.add(selectedArea);
  if (selectedAsset && !assets.has(selectedAsset)) assets.set(selectedAsset, selectedAsset);
  return {
    areas: [...areas].sort((a, b) => compareNames(a, b)),
    assets: [...assets].map(([ref, label]) => ({ ref, label })).sort((a, b) => compareNames(a.label, b.label)),
  };
}
