/**
 * Tests for shared resource-type helpers — ensures all 21 supported
 * locales translate the canonical types and the helper falls back
 * gracefully for missing keys / unknown values.
 */
import { describe, it, expect } from 'vitest';
import {
  RESOURCE_TYPES,
  getResourceTypeLabel,
  getResourceTypeI18nKey,
} from './boqResourceTypes';
import { fallbackResources } from '../../app/i18n-fallbacks';

/* ── Expected translations ─────────────────────────────────────────────
 * Construction-industry vocabulary; mirrors the table in
 * `scripts/inject_resource_type_i18n.mjs` (one-shot helper). When you
 * touch this list, also update the i18n bundle for the same locale.
 */
const EXPECTED_TRANSLATIONS: Record<string, Record<string, string>> = {
  en: { material: 'Material', labor: 'Labor', equipment: 'Equipment', operator: 'Operator', subcontractor: 'Subcontractor', electricity: 'Electricity', composite: 'Composite', other: 'Other' },
  de: { material: 'Material', labor: 'Arbeit', equipment: 'Gerät', operator: 'Bediener', subcontractor: 'Nachunternehmer', electricity: 'Energie', composite: 'Verbundposition', other: 'Sonstige' },
  fr: { material: 'Matériel', labor: "Main-d'œuvre", equipment: 'Équipement', operator: 'Opérateur', subcontractor: 'Sous-traitant', electricity: 'Électricité', composite: 'Composé', other: 'Autre' },
  es: { material: 'Material', labor: 'Mano de obra', equipment: 'Equipo', operator: 'Operario', subcontractor: 'Subcontratista', electricity: 'Electricidad', composite: 'Composición', other: 'Otro' },
  pt: { material: 'Material', labor: 'Mão de obra', equipment: 'Equipamento', operator: 'Operador', subcontractor: 'Subempreiteiro', electricity: 'Eletricidade', composite: 'Composto', other: 'Outro' },
  ru: { material: 'Материалы', labor: 'Труд', equipment: 'Оборудование', operator: 'Машинист', subcontractor: 'Субподряд', electricity: 'Электроэнергия', composite: 'Составная', other: 'Прочее' },
  zh: { material: '材料', labor: '人工', equipment: '设备', operator: '操作员', subcontractor: '分包', electricity: '电力', composite: '复合', other: '其他' },
  ar: { material: 'مواد', labor: 'عمالة', equipment: 'معدات', operator: 'مشغل', subcontractor: 'مقاول من الباطن', electricity: 'كهرباء', composite: 'مركب', other: 'أخرى' },
  hi: { material: 'सामग्री', labor: 'श्रम', equipment: 'उपकरण', operator: 'ऑपरेटर', subcontractor: 'उप-ठेकेदार', electricity: 'बिजली', composite: 'संयुक्त', other: 'अन्य' },
  tr: { material: 'Malzeme', labor: 'İşçilik', equipment: 'Ekipman', operator: 'Operatör', subcontractor: 'Taşeron', electricity: 'Elektrik', composite: 'Bileşik', other: 'Diğer' },
  it: { material: 'Materiale', labor: 'Manodopera', equipment: 'Attrezzatura', operator: 'Operatore', subcontractor: 'Subappaltatore', electricity: 'Elettricità', composite: 'Composto', other: 'Altro' },
  nl: { material: 'Materiaal', labor: 'Arbeid', equipment: 'Materieel', operator: 'Operator', subcontractor: 'Onderaannemer', electricity: 'Elektriciteit', composite: 'Samengesteld', other: 'Overig' },
  pl: { material: 'Materiał', labor: 'Robocizna', equipment: 'Sprzęt', operator: 'Operator', subcontractor: 'Podwykonawca', electricity: 'Energia elektryczna', composite: 'Złożony', other: 'Inne' },
  cs: { material: 'Materiál', labor: 'Práce', equipment: 'Vybavení', operator: 'Obsluha', subcontractor: 'Subdodavatel', electricity: 'Elektřina', composite: 'Složená', other: 'Ostatní' },
  ja: { material: '資材', labor: '労務', equipment: '機械', operator: 'オペレーター', subcontractor: '下請', electricity: '電力', composite: '複合', other: 'その他' },
  ko: { material: '자재', labor: '인건비', equipment: '장비', operator: '운전자', subcontractor: '외주', electricity: '전기', composite: '복합', other: '기타' },
  sv: { material: 'Material', labor: 'Arbete', equipment: 'Utrustning', operator: 'Operatör', subcontractor: 'Underleverantör', electricity: 'El', composite: 'Sammansatt', other: 'Övrigt' },
  no: { material: 'Materialer', labor: 'Arbeidskraft', equipment: 'Utstyr', operator: 'Operatør', subcontractor: 'Underleverandør', electricity: 'Strøm', composite: 'Sammensatt', other: 'Annet' },
  da: { material: 'Materialer', labor: 'Arbejdskraft', equipment: 'Udstyr', operator: 'Operatør', subcontractor: 'Underleverandør', electricity: 'El', composite: 'Sammensat', other: 'Andet' },
  fi: { material: 'Materiaali', labor: 'Työ', equipment: 'Kalusto', operator: 'Käyttäjä', subcontractor: 'Aliurakoitsija', electricity: 'Sähkö', composite: 'Yhdistetty', other: 'Muu' },
  bg: { material: 'Материали', labor: 'Труд', equipment: 'Оборудване', operator: 'Оператор', subcontractor: 'Подизпълнител', electricity: 'Електричество', composite: 'Съставна', other: 'Други' },
};

describe('boqResourceTypes — RESOURCE_TYPES list', () => {
  it('exposes the canonical 8 types in expected order', () => {
    expect(RESOURCE_TYPES.map((rt) => rt.value)).toEqual([
      'material',
      'labor',
      'equipment',
      'operator',
      'subcontractor',
      'electricity',
      'composite',
      'other',
    ]);
  });

  it('every entry has a unique boq.resource_type_* i18n key', () => {
    const keys = RESOURCE_TYPES.map((rt) => rt.i18nKey);
    expect(new Set(keys).size).toBe(keys.length);
    keys.forEach((k) => expect(k).toMatch(/^boq\.resource_type_[a-z]+$/));
  });
});

describe('boqResourceTypes — getResourceTypeLabel', () => {
  it('returns English fallback when no `t` is provided', () => {
    expect(getResourceTypeLabel('material')).toBe('Material');
    expect(getResourceTypeLabel('labor')).toBe('Labor');
    expect(getResourceTypeLabel('subcontractor')).toBe('Subcontractor');
  });

  it('returns the unmapped value verbatim for unknown types', () => {
    expect(getResourceTypeLabel('weird-legacy-type')).toBe('weird-legacy-type');
    expect(getResourceTypeLabel('')).toBe('');
  });

  it('passes the canonical i18n key + English defaultValue to `t`', () => {
    const calls: Array<[string, Record<string, string> | undefined]> = [];
    const fakeT = (key: string, opts?: Record<string, string>) => {
      calls.push([key, opts]);
      return `[${key}]`;
    };
    expect(getResourceTypeLabel('equipment', fakeT)).toBe('[boq.resource_type_equipment]');
    expect(calls).toEqual([['boq.resource_type_equipment', { defaultValue: 'Equipment' }]]);
  });
});

describe('boqResourceTypes — getResourceTypeI18nKey', () => {
  it('maps canonical values to their i18n key', () => {
    expect(getResourceTypeI18nKey('material')).toBe('boq.resource_type_material');
    expect(getResourceTypeI18nKey('composite')).toBe('boq.resource_type_composite');
  });

  it('falls back to the `other` key for unknown values', () => {
    expect(getResourceTypeI18nKey('legacy_unmapped')).toBe('boq.resource_type_other');
    expect(getResourceTypeI18nKey('')).toBe('boq.resource_type_other');
  });
});

describe('i18n bundle — every locale ships every resource-type key', () => {
  // Every canonical type must have a translation in every supported
  // locale. Missing entries fall back to English at runtime, but they
  // would be a regression — i18next would log a warning and the chip
  // would render as English in an otherwise-localised UI.
  for (const [locale, dict] of Object.entries(EXPECTED_TRANSLATIONS)) {
    describe(locale, () => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const bundle = (fallbackResources as any)[locale]?.translation as
        | Record<string, string>
        | undefined;

      it('has a translation bundle', () => {
        expect(bundle).toBeDefined();
      });

      for (const rt of RESOURCE_TYPES) {
        it(`translates ${rt.value}`, () => {
          const key = rt.i18nKey;
          const expected = dict[rt.value];
          expect(bundle?.[key], `missing ${key} for ${locale}`).toBe(expected);
        });
      }
    });
  }
});

describe('integration — getResourceTypeLabel hooked up to live bundles', () => {
  // Simulate i18next behaviour: lookup key in bundle, return defaultValue
  // when key is missing.
  const makeT = (locale: string) => (key: string, opts?: Record<string, string>) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const bundle = (fallbackResources as any)[locale]?.translation as
      | Record<string, string>
      | undefined;
    return bundle?.[key] ?? opts?.defaultValue ?? key;
  };

  for (const [locale, dict] of Object.entries(EXPECTED_TRANSLATIONS)) {
    it(`renders all canonical types for ${locale}`, () => {
      const t = makeT(locale);
      for (const rt of RESOURCE_TYPES) {
        expect(getResourceTypeLabel(rt.value, t)).toBe(dict[rt.value]);
      }
    });
  }
});
