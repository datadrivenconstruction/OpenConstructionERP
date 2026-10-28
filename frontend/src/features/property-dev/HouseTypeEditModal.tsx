// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * HouseTypeEditModal — create / edit a tenant-owned entry in the
 * house-type catalogue.
 *
 * Design notes:
 *   * Country picker uses the full ISO 3166-1 alpha-2 dataset via
 *     <CountryCombobox> with searchable type-ahead AND a "Custom
 *     region (free text)" escape hatch for non-country scopes (DACH,
 *     EU-wide, GCC, …).
 *   * Two-column dense layout for ≥md viewports with a live "preview"
 *     panel that mirrors what catalogue consumers will see (code +
 *     name + flag + key specs).
 *   * Required fields (code, name, project) are gated on blur with
 *     inline red-border feedback; numeric fields are coerced to numbers
 *     on submit so the API receives correctly-typed JSON.
 *   * On submit we send `null` (not "") for empty optional strings so
 *     the backend stores SQL NULL rather than the empty sentinel.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, X } from 'lucide-react';

import {
  Button,
  CountryFlag,
  WideModal,
  WideModalField,
  WideModalSection,
} from '@/shared/ui';
import { CountryCombobox, CUSTOM_SENTINEL } from '@/shared/ui/CountryCombobox';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { onlyChangedFields } from '@/shared/lib/apiHelpers';
import { getCountry } from '@/shared/lib/countries';

import {
  createHouseTypeCatalogue,
  updateHouseTypeCatalogue,
  type CreateHouseTypeCataloguePayload,
  type HouseTypeCatalogueEntry,
  type UpdateHouseTypeCataloguePayload,
} from './api';
import type { ProjectStub } from './HouseTypeSettingsPage';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const inputErrCls =
  'h-9 w-full rounded-lg border border-semantic-error bg-surface-primary px-3 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-semantic-error/30';
const textAreaCls =
  'min-h-[72px] w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const ISO_CURRENCY_RE = /^[A-Z]{3}$/;
const COMMON_CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'PLN', 'RUB', 'TRY', 'JPY', 'CNY', 'AED'];
const CONSTRUCTION_TYPES = [
  'masonry',
  'concrete',
  'timber_frame',
  'steel_frame',
  'modular_prefab',
  'mixed',
];
const ENERGY_CLASSES = ['A++', 'A+', 'A', 'B', 'C', 'D', 'E', 'F', 'G'];
const SALES_CHANNELS = ['direct', 'broker', 'mixed'];

interface FormState {
  project_id: string;
  countryValue: string; // ISO code OR CUSTOM_SENTINEL OR ""
  customRegion: string;
  code: string;
  name: string;
  description: string;
  area_typical_m2: string;
  floors_typical: string;
  typical_bedrooms: string;
  typical_bathrooms: string;
  parking_spots: string;
  typical_price_min: string;
  typical_price_max: string;
  currency: string;
  construction_type: string;
  energy_class: string;
  sales_channel: string;
}

function blankState(): FormState {
  return {
    project_id: '',
    countryValue: '',
    customRegion: '',
    code: '',
    name: '',
    description: '',
    area_typical_m2: '',
    floors_typical: '',
    typical_bedrooms: '',
    typical_bathrooms: '',
    parking_spots: '',
    typical_price_min: '',
    typical_price_max: '',
    currency: '',
    construction_type: '',
    energy_class: '',
    sales_channel: '',
  };
}

function stateFromEntry(entry: HouseTypeCatalogueEntry): FormState {
  return {
    project_id: entry.project_id ?? '',
    countryValue: entry.country_code ?? (entry.region_label ? CUSTOM_SENTINEL : ''),
    customRegion: entry.region_label ?? '',
    code: entry.code,
    name: entry.name,
    description: entry.description ?? '',
    area_typical_m2: entry.area_typical_m2 ?? '',
    floors_typical: entry.floors_typical?.toString() ?? '',
    typical_bedrooms: entry.typical_bedrooms?.toString() ?? '',
    typical_bathrooms: entry.typical_bathrooms?.toString() ?? '',
    parking_spots: entry.parking_spots?.toString() ?? '',
    typical_price_min: entry.typical_price_min ?? '',
    typical_price_max: entry.typical_price_max ?? '',
    currency: entry.currency ?? '',
    construction_type: entry.construction_type ?? '',
    energy_class: entry.energy_class ?? '',
    sales_channel: entry.sales_channel ?? '',
  };
}

function toIntOrNull(v: string): number | null {
  if (!v.trim()) return null;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

function toStringOrNull(v: string): string | null {
  const trimmed = v.trim();
  return trimmed ? trimmed : null;
}

export interface HouseTypeEditModalProps {
  entry: HouseTypeCatalogueEntry | null;
  projects: ProjectStub[];
  onClose: () => void;
}

export function HouseTypeEditModal({
  entry,
  projects,
  onClose,
}: HouseTypeEditModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = entry !== null;

  const [form, setForm] = useState<FormState>(() =>
    entry ? stateFromEntry(entry) : blankState(),
  );
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  // If the parent flips between create / edit while the modal is mounted,
  // reset to the new initial state.
  useEffect(() => {
    setForm(entry ? stateFromEntry(entry) : blankState());
    setTouched({});
  }, [entry]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const markTouched = (key: string) =>
    setTouched((prev) => ({ ...prev, [key]: true }));

  // Field validation.
  const codeErr =
    touched.code && !form.code.trim()
      ? t('property_dev.house_type.code_required', {
          defaultValue: 'Code is required',
        })
      : '';
  const nameErr =
    touched.name && !form.name.trim()
      ? t('property_dev.house_type.name_required', {
          defaultValue: 'Name is required',
        })
      : '';
  const projectErr =
    !isEdit && touched.project_id && !form.project_id
      ? t('property_dev.house_type.project_required', {
          defaultValue: 'Pick a project',
        })
      : '';
  const customRegionErr =
    form.countryValue === CUSTOM_SENTINEL && touched.customRegion && !form.customRegion.trim()
      ? t('property_dev.house_type.custom_region_required', {
          defaultValue: 'Describe the custom region',
        })
      : '';
  const currencyErr =
    touched.currency && form.currency && !ISO_CURRENCY_RE.test(form.currency)
      ? t('property_dev.house_type.currency_invalid', {
          defaultValue: 'Currency must be a 3-letter ISO code (e.g. EUR)',
        })
      : '';

  const formValid =
    !!form.code.trim() &&
    !!form.name.trim() &&
    (isEdit || !!form.project_id) &&
    (form.countryValue !== CUSTOM_SENTINEL || !!form.customRegion.trim()) &&
    (!form.currency || ISO_CURRENCY_RE.test(form.currency));

  // Preview values.
  const previewCountry = useMemo(() => {
    if (form.countryValue && form.countryValue !== CUSTOM_SENTINEL) {
      return getCountry(form.countryValue);
    }
    return null;
  }, [form.countryValue]);

  const buildPayload = (): CreateHouseTypeCataloguePayload | UpdateHouseTypeCataloguePayload => {
    const isCustom = form.countryValue === CUSTOM_SENTINEL;
    const country_code = isCustom || !form.countryValue ? null : form.countryValue;
    const region_label = isCustom ? form.customRegion.trim() : null;
    const common = {
      country_code,
      region_label,
      name: form.name.trim(),
      description: toStringOrNull(form.description),
      area_typical_m2: toStringOrNull(form.area_typical_m2),
      floors_typical: toIntOrNull(form.floors_typical),
      typical_bedrooms: toIntOrNull(form.typical_bedrooms),
      typical_bathrooms: toIntOrNull(form.typical_bathrooms),
      parking_spots: toIntOrNull(form.parking_spots),
      typical_price_min: toStringOrNull(form.typical_price_min),
      typical_price_max: toStringOrNull(form.typical_price_max),
      currency: toStringOrNull(form.currency),
      construction_type: toStringOrNull(form.construction_type),
      energy_class: toStringOrNull(form.energy_class),
      sales_channel: toStringOrNull(form.sales_channel),
    };

    if (isEdit) {
      return common as UpdateHouseTypeCataloguePayload;
    }
    return {
      ...common,
      project_id: form.project_id,
      code: form.code.trim(),
    } as CreateHouseTypeCataloguePayload;
  };

  /**
   * The edit patch: only the fields the user actually moved. Sending the whole
   * record back rewrote every column with the catalogue entry as this modal
   * had loaded it, so a colleague's concurrent correction to a field nobody
   * touched here was silently reverted. The update route dumps with
   * `exclude_unset=True`, so an omitted field is left alone. The baseline comes
   * from `stateFromEntry`, the same function that seeded the form.
   */
  const buildPatch = (current: HouseTypeCatalogueEntry): UpdateHouseTypeCataloguePayload => {
    const { country_code, region_label, ...named } = buildPayload() as UpdateHouseTypeCataloguePayload;
    const base = stateFromEntry(current);
    const patch = onlyChangedFields(named, form, base) as UpdateHouseTypeCataloguePayload;
    // country_code and region_label are two projections of the same pair of
    // inputs, so no form field carries either name. They are held out of the
    // key-name diff above (which sends an unmatched key unconditionally) and
    // travel together only when one of the two inputs behind them moved.
    if (form.countryValue !== base.countryValue || form.customRegion !== base.customRegion) {
      patch.country_code = country_code;
      patch.region_label = region_label;
    }
    return patch;
  };

  const saveMu = useMutation({
    mutationFn: () =>
      isEdit && entry
        ? updateHouseTypeCatalogue(entry.id, buildPatch(entry))
        : createHouseTypeCatalogue(buildPayload() as CreateHouseTypeCataloguePayload),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: isEdit
          ? t('property_dev.house_type.updated', { defaultValue: 'House type updated' })
          : t('property_dev.house_type.created', { defaultValue: 'House type created' }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'house-type-catalogue'] });
      onClose();
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const handleSubmit = () => {
    setTouched({
      code: true,
      name: true,
      project_id: true,
      customRegion: true,
    });
    if (!formValid) return;
    saveMu.mutate();
  };

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      busy={saveMu.isPending}
      title={
        isEdit
          ? t('property_dev.house_type.edit_title', { defaultValue: 'Edit house type' })
          : t('property_dev.house_type.new_title', { defaultValue: 'New house type' })
      }
      subtitle={t('property_dev.house_type.modal_subtitle', {
        defaultValue:
          'Define a tenant-owned house type so plots and price-matrix rules can reference it. Any country supported; pick "Custom region" for cross-border or non-country scopes.',
      })}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} icon={<X size={14} />}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            icon={<Save size={14} />}
            loading={saveMu.isPending}
            disabled={!formValid}
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('property_dev.house_type.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_280px]">
        {/* Form column */}
        <div>
          <WideModalSection
            title={t('property_dev.house_type.section_identity', {
              defaultValue: 'Identity',
            })}
            description={t('property_dev.house_type.section_identity_desc', {
              defaultValue:
                'Internal code (immutable), display name, and the country / region the house type belongs to.',
            })}
            columns={2}
          >
            {!isEdit && (
              <WideModalField
                label={t('property_dev.house_type.project_label', {
                  defaultValue: 'Project',
                })}
                required
                error={projectErr}
                span={2}
              >
                <select
                  value={form.project_id}
                  onChange={(e) => set('project_id', e.target.value)}
                  onBlur={() => markTouched('project_id')}
                  className={projectErr ? inputErrCls : inputCls}
                  disabled={projects.length === 0}
                >
                  <option value="">
                    — {t('property_dev.house_type.pick_project', {
                      defaultValue: 'Pick a project',
                    })}
                    —
                  </option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </WideModalField>
            )}
            <WideModalField
              label={t('property_dev.house_type.code_label', { defaultValue: 'Code' })}
              required
              error={codeErr}
              hint={t('property_dev.house_type.code_hint', {
                defaultValue: 'Short, unique, uppercase: TYPE-A, VILLA-EU-3, …',
              })}
            >
              <input
                type="text"
                value={form.code}
                onChange={(e) => set('code', e.target.value.toUpperCase())}
                onBlur={() => markTouched('code')}
                maxLength={32}
                disabled={isEdit /* code is immutable once shipped */}
                placeholder="TYPE-A"
                className={codeErr ? inputErrCls : inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.name_label', { defaultValue: 'Display name' })}
              required
              error={nameErr}
            >
              <input
                type="text"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                onBlur={() => markTouched('name')}
                maxLength={120}
                placeholder="2-bed coastal townhouse"
                className={nameErr ? inputErrCls : inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.country_label', { defaultValue: 'Country / region' })}
              hint={t('property_dev.house_type.country_hint', {
                defaultValue:
                  'Pick any of the 180+ ISO countries, or switch to "Custom region" for cross-border scopes.',
              })}
              error={customRegionErr}
              span={2}
            >
              <CountryCombobox
                value={form.countryValue}
                customValue={form.customRegion}
                allowEmpty
                allowCustom
                placeholder={t('property_dev.house_type.country_placeholder', {
                  defaultValue: 'Global / no country',
                })}
                onChange={(v) => {
                  set('countryValue', v);
                  if (v !== CUSTOM_SENTINEL) {
                    set('customRegion', '');
                  }
                }}
                onCustomChange={(v) => {
                  set('customRegion', v);
                  markTouched('customRegion');
                }}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.description_label', {
                defaultValue: 'Description',
              })}
              hint={t('property_dev.house_type.description_hint', {
                defaultValue: 'One sentence shown to sales reps in the picker.',
              })}
              span={2}
            >
              <textarea
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                maxLength={500}
                className={textAreaCls}
                rows={2}
              />
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('property_dev.house_type.section_dimensions', {
              defaultValue: 'Dimensions & layout',
            })}
            columns={3}
          >
            <WideModalField
              label={t('property_dev.house_type.area_typical_label', {
                defaultValue: 'Typical area (m²)',
              })}
            >
              <input
                type="number"
                inputMode="decimal"
                min="0"
                step="0.1"
                value={form.area_typical_m2}
                onChange={(e) => set('area_typical_m2', e.target.value)}
                placeholder="120"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.floors_typical_label', {
                defaultValue: 'Floors',
              })}
            >
              <input
                type="number"
                inputMode="numeric"
                min="0"
                max="50"
                value={form.floors_typical}
                onChange={(e) => set('floors_typical', e.target.value)}
                placeholder="2"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.parking_spots_label', {
                defaultValue: 'Parking spots',
              })}
            >
              <input
                type="number"
                inputMode="numeric"
                min="0"
                max="20"
                value={form.parking_spots}
                onChange={(e) => set('parking_spots', e.target.value)}
                placeholder="1"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.bedrooms_label', {
                defaultValue: 'Bedrooms',
              })}
            >
              <input
                type="number"
                inputMode="numeric"
                min="0"
                max="20"
                value={form.typical_bedrooms}
                onChange={(e) => set('typical_bedrooms', e.target.value)}
                placeholder="2"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.bathrooms_label', {
                defaultValue: 'Bathrooms',
              })}
            >
              <input
                type="number"
                inputMode="numeric"
                min="0"
                max="20"
                value={form.typical_bathrooms}
                onChange={(e) => set('typical_bathrooms', e.target.value)}
                placeholder="1"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.energy_class_label', {
                defaultValue: 'Energy class',
              })}
            >
              <select
                value={form.energy_class}
                onChange={(e) => set('energy_class', e.target.value)}
                className={inputCls}
              >
                <option value="">—</option>
                {ENERGY_CLASSES.map((cls) => (
                  <option key={cls} value={cls}>
                    {cls}
                  </option>
                ))}
              </select>
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('property_dev.house_type.section_cost', {
              defaultValue: 'Indicative price band',
            })}
            description={t('property_dev.house_type.section_cost_desc', {
              defaultValue:
                'Optional range. Used as a sanity-check tooltip when plots are priced; never overrides the live price-matrix.',
            })}
            columns={3}
          >
            <WideModalField
              label={t('property_dev.house_type.price_min_label', {
                defaultValue: 'Min price',
              })}
            >
              <input
                type="number"
                inputMode="decimal"
                min="0"
                value={form.typical_price_min}
                onChange={(e) => set('typical_price_min', e.target.value)}
                placeholder="180000"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.price_max_label', {
                defaultValue: 'Max price',
              })}
            >
              <input
                type="number"
                inputMode="decimal"
                min="0"
                value={form.typical_price_max}
                onChange={(e) => set('typical_price_max', e.target.value)}
                placeholder="240000"
                className={inputCls}
              />
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.currency_label', {
                defaultValue: 'Currency',
              })}
              error={currencyErr}
            >
              <input
                type="text"
                value={form.currency}
                onChange={(e) =>
                  set(
                    'currency',
                    e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3),
                  )
                }
                onBlur={() => markTouched('currency')}
                list="house-type-currency-list"
                maxLength={3}
                placeholder="EUR"
                className={currencyErr ? inputErrCls : inputCls}
              />
              <datalist id="house-type-currency-list">
                {COMMON_CURRENCIES.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </WideModalField>
          </WideModalSection>

          <WideModalSection
            title={t('property_dev.house_type.section_meta', {
              defaultValue: 'Construction & sales',
            })}
            columns={2}
          >
            <WideModalField
              label={t('property_dev.house_type.construction_type_label', {
                defaultValue: 'Construction type',
              })}
            >
              <select
                value={form.construction_type}
                onChange={(e) => set('construction_type', e.target.value)}
                className={inputCls}
              >
                <option value="">—</option>
                {CONSTRUCTION_TYPES.map((ct) => (
                  <option key={ct} value={ct}>
                    {ct.replace('_', ' ')}
                  </option>
                ))}
              </select>
            </WideModalField>
            <WideModalField
              label={t('property_dev.house_type.sales_channel_label', {
                defaultValue: 'Sales channel',
              })}
            >
              <select
                value={form.sales_channel}
                onChange={(e) => set('sales_channel', e.target.value)}
                className={inputCls}
              >
                <option value="">—</option>
                {SALES_CHANNELS.map((ch) => (
                  <option key={ch} value={ch}>
                    {ch}
                  </option>
                ))}
              </select>
            </WideModalField>
          </WideModalSection>
        </div>

        {/* Live preview column */}
        <aside className="hidden lg:flex flex-col gap-3">
          <div className="sticky top-2 rounded-xl border border-border-light bg-surface-secondary p-4">
            <div className="text-[10px] uppercase tracking-wide text-content-tertiary">
              {t('property_dev.house_type.preview_label', { defaultValue: 'Live preview' })}
            </div>
            <div className="mt-3 flex items-center gap-2">
              {previewCountry ? (
                <CountryFlag code={previewCountry.code} size={20} />
              ) : form.countryValue === CUSTOM_SENTINEL ? (
                <span className="inline-flex h-5 w-7 items-center justify-center rounded-[2px] bg-oe-blue/15 text-[10px] font-semibold text-oe-blue">
                  ✱
                </span>
              ) : (
                <span className="inline-flex h-5 w-7 items-center justify-center rounded-[2px] bg-content-tertiary/15 text-[10px] text-content-tertiary">
                  ⌀
                </span>
              )}
              <div className="min-w-0">
                <div className="truncate text-xs text-content-tertiary font-mono">
                  {form.code || 'TYPE-?'}
                </div>
                <div className="truncate text-sm font-semibold text-content-primary">
                  {form.name ||
                    t('property_dev.house_type.preview_unnamed', {
                      defaultValue: '(unnamed)',
                    })}
                </div>
              </div>
            </div>
            <div className="mt-3 text-xs text-content-secondary leading-relaxed">
              {form.description ||
                t('property_dev.house_type.preview_no_description', {
                  defaultValue: 'No description set.',
                })}
            </div>
            <ul className="mt-3 grid grid-cols-2 gap-y-1.5 text-[11px] text-content-secondary">
              <li>
                <span className="text-content-tertiary">m²:</span>{' '}
                {form.area_typical_m2 || '—'}
              </li>
              <li>
                <span className="text-content-tertiary">
                  {t('property_dev.house_type.preview_floors', {
                    defaultValue: 'Floors',
                  })}
                  :
                </span>{' '}
                {form.floors_typical || '—'}
              </li>
              <li>
                <span className="text-content-tertiary">
                  {t('property_dev.house_type.preview_bd', {
                    defaultValue: 'Bd',
                  })}
                  :
                </span>{' '}
                {form.typical_bedrooms || '—'}
              </li>
              <li>
                <span className="text-content-tertiary">
                  {t('property_dev.house_type.preview_ba', {
                    defaultValue: 'Ba',
                  })}
                  :
                </span>{' '}
                {form.typical_bathrooms || '—'}
              </li>
              <li>
                <span className="text-content-tertiary">
                  {t('property_dev.house_type.preview_parking', {
                    defaultValue: 'Park.',
                  })}
                  :
                </span>{' '}
                {form.parking_spots || '—'}
              </li>
              <li>
                <span className="text-content-tertiary">
                  {t('property_dev.house_type.preview_energy', {
                    defaultValue: 'EE',
                  })}
                  :
                </span>{' '}
                {form.energy_class || '—'}
              </li>
            </ul>
            {(form.typical_price_min || form.typical_price_max) && (
              <div className="mt-3 rounded-md border border-border-light/60 bg-surface-primary px-2 py-1.5 text-[11px] text-content-secondary">
                {form.typical_price_min || '—'} – {form.typical_price_max || '—'}{' '}
                {form.currency || ''}
              </div>
            )}
          </div>
          <div className="rounded-xl border border-border-light/60 bg-surface-primary p-3 text-[11px] leading-relaxed text-content-tertiary">
            {t('property_dev.house_type.preview_tip', {
              defaultValue:
                'Tip: keep code short and stable - it appears in BOQ rollups, plot drawers, and tender exports.',
            })}
          </div>
        </aside>
      </div>
    </WideModal>
  );
}
