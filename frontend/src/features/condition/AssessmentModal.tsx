// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Record a condition rating for an asset or element, usually from an
 * inspection. Severity, extent and intensity produce a suggested rating with a
 * confidence; the inspector sets the rating, and both are stored.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Sparkles, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtPercent } from '@/shared/lib/formatters';
import { todayLocalISO } from '@/shared/lib/dates';
import { useToastStore } from '@/stores/useToastStore';
import { createAssessment, fetchScales, suggestRating, type Assessment, type AssetKind } from './api';
import { intensityLabel, levelLabel, severityLabel } from './conditionLabels';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:border-oe-blue focus:outline-none';

function numOrNull(v: string): number | null {
  if (v.trim() === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function AssessmentModal({
  projectId,
  inspectionId,
  defaultArea,
  currency,
  onClose,
  onSaved,
}: {
  projectId: string;
  inspectionId?: string | null;
  defaultArea?: string | null;
  currency?: string | null;
  onClose: () => void;
  onSaved: (a: Assessment) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const scalesQ = useQuery({ queryKey: ['condition-scales', projectId], queryFn: () => fetchScales(projectId) });
  const [scaleKey, setScaleKey] = useState('default_6');
  const [elementName, setElementName] = useState('');
  const [assetKind, setAssetKind] = useState<AssetKind>('element');
  const [assetRef, setAssetRef] = useState('');
  const [area, setArea] = useState(defaultArea ?? '');
  const [severity, setSeverity] = useState('');
  const [extent, setExtent] = useState('');
  const [intensity, setIntensity] = useState('');
  const [rating, setRating] = useState<number | null>(null);
  const [defect, setDefect] = useState('');
  const [recommended, setRecommended] = useState('');
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState('');
  const [unitCost, setUnitCost] = useState('');
  const [assessedAt, setAssessedAt] = useState(todayLocalISO());

  const scale = useMemo(() => (scalesQ.data ?? []).find((s) => s.key === scaleKey), [scalesQ.data, scaleKey]);
  const sev = numOrNull(severity);
  const ext = numOrNull(extent);
  const inten = numOrNull(intensity);
  const suggestionQ = useQuery({
    queryKey: ['condition-suggest', projectId, scaleKey, sev, ext, inten],
    queryFn: () => suggestRating({ project_id: projectId, scale_key: scaleKey, severity: sev, extent_pct: ext, intensity: inten }),
    enabled: sev !== null,
  });

  useEffect(() => {
    if (rating !== null && scale && !scale.levels.some((l) => l.level === rating)) setRating(null);
  }, [scale, rating]);

  const saveMut = useMutation({
    mutationFn: () =>
      createAssessment({
        project_id: projectId,
        inspection_id: inspectionId ?? null,
        asset_kind: assetKind,
        asset_ref: assetRef.trim() || null,
        element_name: elementName.trim(),
        area: area.trim() || null,
        scale_key: scaleKey,
        rating: rating as number,
        severity: sev,
        extent_pct: ext,
        intensity: inten,
        defect_description: defect.trim() || null,
        recommended_action: recommended.trim() || null,
        quantity: quantity.trim() || null,
        unit: unit.trim() || null,
        unit_cost: unitCost.trim() || null,
        currency: unitCost.trim() && currency ? currency : null,
        assessed_at: assessedAt || null,
      }),
    onSuccess: (a) => {
      addToast({ type: 'success', title: t('condition.saved', { defaultValue: 'Condition rating recorded' }) });
      onSaved(a);
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const suggestion = suggestionQ.data;
  const canSave = elementName.trim().length > 0 && rating !== null && !saveMut.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-surface-elevated shadow-xl">
        <div className="flex items-center justify-between border-b border-border-light px-5 py-3">
          <h3 className="text-base font-semibold text-content-primary">
            {t('condition.new_rating', { defaultValue: 'Record condition' })}
          </h3>
          <button type="button" onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })}>
            <X size={18} className="text-content-tertiary" />
          </button>
        </div>
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          <label className="text-xs font-medium text-content-secondary sm:col-span-2">
            {t('condition.element', { defaultValue: 'Asset or element' })} *
            <input className={inputCls + ' mt-1'} value={elementName} onChange={(e) => setElementName(e.target.value)} data-testid="condition-element" />
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.asset_kind', { defaultValue: 'Linked to' })}
            <select className={inputCls + ' mt-1'} value={assetKind} onChange={(e) => setAssetKind(e.target.value as AssetKind)}>
              <option value="element">{t('condition.kind_element', { defaultValue: 'Building element' })}</option>
              <option value="bim_element">{t('condition.kind_bim', { defaultValue: 'Asset register (model element)' })}</option>
              <option value="plant_item">{t('condition.kind_plant', { defaultValue: 'Plant item' })}</option>
            </select>
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.asset_ref', { defaultValue: 'Reference (id or tag)' })}
            <input className={inputCls + ' mt-1'} value={assetRef} onChange={(e) => setAssetRef(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.area', { defaultValue: 'Area' })}
            <input className={inputCls + ' mt-1'} value={area} onChange={(e) => setArea(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.scale', { defaultValue: 'Scale' })}
            <select className={inputCls + ' mt-1'} value={scaleKey} onChange={(e) => setScaleKey(e.target.value)}>
              {(scalesQ.data ?? []).map((s) => (
                <option key={s.key} value={s.key}>
                  {s.key === 'default_6' ? t('condition.scale_default_6', { defaultValue: 'Condition scale, 6 levels' }) : s.name}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="grid gap-3 rounded-lg border border-border-light p-3 sm:col-span-2 sm:grid-cols-3">
            <legend className="px-1 text-xs font-semibold text-content-tertiary">
              {t('condition.defect_record', { defaultValue: 'Defect record' })}
            </legend>
            <label className="text-xs font-medium text-content-secondary">
              {t('condition.severity', { defaultValue: 'Severity' })}
              <select className={inputCls + ' mt-1'} value={severity} onChange={(e) => setSeverity(e.target.value)} data-testid="condition-severity">
                <option value="">-</option>
                {[1, 2, 3, 4].map((v) => (
                  <option key={v} value={v}>
                    {severityLabel(t, v)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-content-secondary">
              {t('condition.extent', { defaultValue: 'Extent affected (%)' })}
              <input type="number" min={0} max={100} className={inputCls + ' mt-1'} value={extent} onChange={(e) => setExtent(e.target.value)} />
            </label>
            <label className="text-xs font-medium text-content-secondary">
              {t('condition.intensity', { defaultValue: 'Intensity' })}
              <select className={inputCls + ' mt-1'} value={intensity} onChange={(e) => setIntensity(e.target.value)}>
                <option value="">-</option>
                {[1, 2, 3, 4].map((v) => (
                  <option key={v} value={v}>
                    {intensityLabel(t, v)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-content-secondary sm:col-span-3">
              {t('condition.defect_description', { defaultValue: 'What was found' })}
              <textarea className={inputCls + ' mt-1 h-16 py-2'} value={defect} onChange={(e) => setDefect(e.target.value)} />
            </label>
          </fieldset>

          <div className="sm:col-span-2">
            <p className="mb-1 text-xs font-medium text-content-secondary">{t('condition.rating', { defaultValue: 'Rating' })} *</p>
            {suggestion?.rating && (
              <div className="mb-2 flex items-center gap-2 rounded-lg bg-oe-blue/5 px-3 py-2 text-xs text-content-secondary" data-testid="condition-suggestion">
                <Sparkles size={13} className="text-oe-blue" />
                {t('condition.suggested', {
                  defaultValue: 'Suggested from the defect record: {{rating}} (confidence {{confidence}})',
                  rating: suggestion.rating,
                  confidence: fmtPercent(suggestion.confidence * 100, 0),
                })}
                <button type="button" className="font-medium text-oe-blue hover:underline" onClick={() => setRating(suggestion.rating)}>
                  {t('condition.use_suggestion', { defaultValue: 'Use' })}
                </button>
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {(scale?.levels ?? []).map((lv) => (
                <button
                  key={lv.level}
                  type="button"
                  onClick={() => setRating(lv.level)}
                  className={
                    'flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ' +
                    (rating === lv.level ? 'border-oe-blue bg-oe-blue/10 font-semibold text-content-primary' : 'border-border-light text-content-secondary')
                  }
                  data-testid={`condition-level-${lv.level}`}
                >
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: lv.color ?? '#94a3b8' }} />
                  {lv.level} · {levelLabel(t, scaleKey, lv)}
                </button>
              ))}
            </div>
          </div>

          <label className="text-xs font-medium text-content-secondary">
            {t('condition.quantity', { defaultValue: 'Quantity of the element' })}
            <input inputMode="decimal" className={inputCls + ' mt-1'} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.unit', { defaultValue: 'Unit' })}
            <input className={inputCls + ' mt-1'} value={unit} onChange={(e) => setUnit(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.unit_cost', { defaultValue: 'Unit cost of the work' })}
            {currency ? ` (${currency})` : ''}
            <input inputMode="decimal" className={inputCls + ' mt-1'} value={unitCost} onChange={(e) => setUnitCost(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-content-secondary">
            {t('condition.assessed_at', { defaultValue: 'Assessed on' })}
            <input type="date" className={inputCls + ' mt-1'} value={assessedAt} onChange={(e) => setAssessedAt(e.target.value)} />
          </label>
          <label className="text-xs font-medium text-content-secondary sm:col-span-2">
            {t('condition.recommended_action', { defaultValue: 'Recommended action' })}
            <input className={inputCls + ' mt-1'} value={recommended} onChange={(e) => setRecommended(e.target.value)} />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-border-light px-5 py-3">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" disabled={!canSave} loading={saveMut.isPending} onClick={() => saveMut.mutate()} data-testid="condition-save">
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}
