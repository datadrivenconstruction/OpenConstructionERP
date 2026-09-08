// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wave 5 Epic I — Regional Exchange module manifest.
 *
 * Replaces the 20 standalone country manifests (au-boq, br-sinapi, ca-boq,
 * cn-boq, cz-boq, de-din276, es-pbc, fr-dpgf, in-boq, it-computo, jp-sekisan,
 * kr-boq, nl-stabu, nordic-ns3420, pl-knr, ru-gesn, tr-birimfiyat, uae-boq,
 * uk-nrm, us-masterformat) with ONE manifest that registers a route per
 * country pack.
 *
 * Each route maps an old deep-link URL (e.g. `/es-pbc-exchange`) to the
 * polymorphic `RegionalExchangePage` with the matching template prop, so
 * bookmarks, sidebar links and search results from previous versions all
 * keep working.
 */

import { lazy, type ComponentType } from 'react';
import { Globe2 } from 'lucide-react';
import type { ModuleManifest } from '../_types';
import { COUNTRY_TEMPLATES } from './regionalRegistry';

/**
 * Lazy-loaded page component. React.lazy needs a `default`-shaped
 * import, so the page file uses a default export. We wrap with the
 * template-prop at route-render time using a closure factory.
 */
const RegionalExchangePage = lazy(() => import('./RegionalExchangePage'));

/**
 * One-time factory that returns a *new* React component bound to a
 * specific template. We do this so each old route mounts the same
 * underlying page but with its own template prop — without making
 * the user touch URL parameters or the registry plumbing.
 */
function makeBoundComponent(templateId: string): ComponentType<unknown> {
  const Bound: ComponentType<unknown> = () => {
    // Resolve fresh on every render so HMR + lazy template edits work.
    const template = COUNTRY_TEMPLATES.find((t) => t.id === templateId);
    if (!template) {
      // Should never happen — manifest is generated from the registry.
      return null;
    }
    // RegionalExchangePage is itself wrapped in React.lazy, so it's
    // already a LazyExoticComponent; rendering it directly is fine.
    return <RegionalExchangePage template={template} />;
  };
  Bound.displayName = `RegionalExchangePage[${templateId}]`;
  return Bound;
}

/**
 * Build the per-country routes from the registry. One source of truth: add an
 * entry to COUNTRY_TEMPLATES and the route and the i18n bundle pick it up
 * automatically.
 *
 * Each per-country route mounts the SAME polymorphic page, but each
 * goes through its own `React.lazy(...)` boundary so the route has a
 * stable component identity in DevTools and React Router cache.
 *
 * `title` stays a literal here, unlike every other manifest string. A country
 * label is the name of a measurement standard carrying its country
 * ("United Kingdom NRM 1/2", "Russia ГЭСН / ФЕР / ТЕР"), and the standard half
 * is not translated in any language. Keying all 20 would translate the country
 * word alone and split one recognisable name across two sources.
 */
const countryRoutes = COUNTRY_TEMPLATES.map((tpl) => ({
  path: `/${tpl.routeSlug}`,
  title: tpl.label,
  component: lazy<ComponentType<unknown>>(async () => ({
    default: makeBoundComponent(tpl.id),
  })),
}));

/**
 * The hub that picks among the twenty. It goes FIRST so `routes[0]` is the
 * route the module is entered by rather than whichever country happens to sort
 * first in the registry.
 *
 * Unlike the country routes above, this one's title is an i18n key: the page
 * speaks for the module, not for a national standard, so there is nothing here
 * that has to stay in its own language.
 *
 * The key is `boq.preset_regional` ("Regional standards") rather than this
 * module's own `nav.regional_exchange`, and it is the key the page's `<h1>`
 * uses too, so the top bar and the heading say one thing. `nav.regional_exchange`
 * is answered by the `translations` block below and by no locale file, which is
 * fine while only `translateManifestText` reads it, and not fine for a page that
 * has to name itself in 43 languages.
 */
const hubRoute = {
  path: '/regional-exchange',
  title: 'boq.preset_regional',
  component: lazy<ComponentType<unknown>>(() => import('./RegionalExchangeHubPage')),
};

const routes = [hubRoute, ...countryRoutes];

export const manifest: ModuleManifest = {
  id: 'regional-exchange',
  name: 'nav.regional_exchange',
  description: 'modules.regional_exchange.description',
  version: '1.0.0',
  icon: Globe2,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes,
  // No per-country sidebar items, by the #217 decision: twenty country rows
  // would swamp the menu, so the way in is a link from a BOQ, the way
  // `gaeb-exchange` is reached from `BOQListPage` and `BOQToolbar`.
  //
  // That link did not exist when this module was collapsed out of twenty, and
  // the comment here said so plainly rather than claiming otherwise: nothing
  // under `frontend/src` navigated to any of the twenty routes, so they were
  // reachable only by typing the URL. It exists now. `RegionalExchangeHubPage`
  // is the landing page that picks, and `BOQListPage` offers it from the BOQ
  // intro card under the same module-enabled gate the GAEB link uses.
  //
  // Not one row either, and not through `getModuleNavItems('regional')`: the
  // sidebar's `regional` group was deleted (see the note at the foot of
  // `app/layout/navCatalog.ts`), so a nav item in that group would render
  // nowhere at all. `navItems` staying empty is the shipped behaviour, not an
  // omission, and `modules/_registry.test.ts` pins it.
  navItems: [],
  translations: {
    en: {
      'nav.regional_exchange': 'Regional BOQ Exchange',
      'modules.regional_exchange.description':
        'Polymorphic BOQ import / export across 20 regional cost standards (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'regional.intro_title': "Speak your country's tender format",
      'regional.intro_body':
        "Import and export BOQ data in your region's native structure (NRM in the UK, MasterFormat in the US, DPGF in France and others), with the right trade-section breakdown applied. The data lands in or comes from a normal BOQ, so the same estimate moves across markets without re-keying.",
      'regional.tab_import': 'Import',
      'regional.tab_export': 'Export',
      'regional.import_complete': 'Import complete',
      'regional.import_summary': '{{n}} positions imported',
      'regional.import_count_unknown':
        'The server did not report how many positions were imported',
      'regional.import_errors': '{{n}} rows could not be imported',
      'regional.import_timeout':
        'The server did not respond within 90 seconds. Try a smaller file.',
      'regional.read_by': 'read by {{format}}',
      'regional.export_complete': 'Export complete',
      'regional.import_failed': 'Import failed',
      'regional.export_failed': 'Export failed',
      'regional.drop_file': 'Drop a file here, or',
      'regional.browse': 'Browse files',
      'regional.formats_hint': 'Supported: {{exts}}',
      'regional.classification': 'Classification',
      'regional.preview': 'Preview',
      'regional.positions': 'positions',
      'regional.positions_found': 'positions found',
      'regional.positions_imported': 'positions imported',
      'regional.show_less': 'Show less',
      'regional.show_all': 'Show all',
      'regional.target_boq': 'Import Target',
      'regional.select_project': 'Select project',
      'regional.select_boq': 'Select BOQ',
      'regional.importing': 'Importing…',
      'regional.import_btn': 'Import positions',
      'regional.export_btn': 'Export as CSV',
      'regional.print_btn': 'Print / PDF',
      'regional.parsed_ok': 'File parsed successfully',
      'regional.parse_error':
        'No positions found in the file. Ensure the file matches the expected layout.',
      'regional.parse_error_generic': 'Failed to parse the file.',
      'regional.source_boq': '1. Select BOQ to Export',
      'regional.export_summary': '2. Export Summary',
      'regional.hide_preview': 'Hide preview',
      'regional.show_preview': 'Show preview',
      'regional.sections': 'Sections',
      'regional.format_label': 'Format',
      'regional.prices_label': 'Prices',
      'regional.format_detailed': 'Detailed (with prices)',
      'regional.format_summary': 'Summary (quantities only)',
      'regional.detailed_short': 'Detailed',
      'regional.summary_short': 'Summary',
      'regional.no_positions': 'No positions to export',
      'regional.no_positions_msg': 'This BOQ has no positions to export.',
      'regional.trades_ref': '{{standard}} Reference',
      'regional.download_sample': 'Download a sample file to try it',
      'regional.clear_file': 'Clear file',
      'regional.open_boq': 'Open in BOQ editor to review & validate →',
      'regional.info':
        '{{label}} is the standard cost reference / measurement framework for this region. Imports are validated against the {{packs}} rule packs before positions are added to the BOQ.',
    },
    de: {
      'nav.regional_exchange': 'Regionaler LV-Austausch',
      'modules.regional_exchange.description':
        'Ein Import / Export für 20 regionale Kostenstandards (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'regional.tab_import': 'Importieren',
      'regional.tab_export': 'Exportieren',
      'regional.import_complete': 'Import abgeschlossen',
      'regional.export_complete': 'Export abgeschlossen',
      'regional.drop_file': 'Datei hier ablegen, oder',
      'regional.browse': 'Datei wählen',
    },
    ru: {
      'modules.regional_exchange.description': 'Один импорт / экспорт для 20 региональных стандартов стоимости (NRM, MasterFormat, DIN 276, PBC, ГЭСН, …).',
      'nav.regional_exchange': 'Региональный обмен сметами',
      'regional.tab_import': 'Импорт',
      'regional.tab_export': 'Экспорт',
      'regional.import_complete': 'Импорт завершён',
      'regional.export_complete': 'Экспорт завершён',
      'regional.drop_file': 'Перетащите файл сюда, или',
      'regional.browse': 'Выбрать файл',
    },
    es: {
      'modules.regional_exchange.description': 'Una importación / exportación para 20 estándares regionales de costes (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Intercambio Regional de BOQ',
      'regional.tab_import': 'Importar',
      'regional.tab_export': 'Exportar',
      'regional.drop_file': 'Suelte un archivo aquí, o',
      'regional.browse': 'Examinar archivos',
    },
    fr: {
      'modules.regional_exchange.description': 'Un import / export pour 20 référentiels de coûts régionaux (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Échange BOQ Régional',
      'regional.tab_import': 'Importer',
      'regional.tab_export': 'Exporter',
      'regional.drop_file': 'Déposez un fichier ici, ou',
      'regional.browse': 'Parcourir',
    },
    it: {
      'modules.regional_exchange.description': 'Un import / export per 20 standard di costo regionali (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Scambio BOQ Regionale',
      'regional.tab_import': 'Importa',
      'regional.tab_export': 'Esporta',
      'regional.drop_file': 'Rilascia un file qui, oppure',
      'regional.browse': 'Sfoglia file',
    },
    pl: {
      'modules.regional_exchange.description': 'Jeden import / eksport dla 20 regionalnych standardów kosztowych (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Regionalna Wymiana BOQ',
      'regional.tab_import': 'Importuj',
      'regional.tab_export': 'Eksportuj',
      'regional.drop_file': 'Upuść plik tutaj lub',
      'regional.browse': 'Przeglądaj',
    },
    cs: {
      'modules.regional_exchange.description': 'Jeden import / export pro 20 regionálních nákladových standardů (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Regionální výměna BOQ',
      'regional.tab_import': 'Importovat',
      'regional.tab_export': 'Exportovat',
    },
    nl: {
      'modules.regional_exchange.description': 'Eén import / export voor 20 regionale kostenstandaarden (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Regionale BOQ-uitwisseling',
      'regional.tab_import': 'Importeren',
      'regional.tab_export': 'Exporteren',
    },
    pt: {
      'modules.regional_exchange.description': 'Uma importação / exportação para 20 normas regionais de custos (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Intercâmbio Regional de BOQ',
      'regional.tab_import': 'Importar',
      'regional.tab_export': 'Exportar',
    },
    tr: {
      'modules.regional_exchange.description': '20 bölgesel maliyet standardı için tek bir içe / dışa aktarma (NRM, MasterFormat, DIN 276, PBC, GESN, …).',
      'nav.regional_exchange': 'Bölgesel BOQ Değişimi',
      'regional.tab_import': 'İçeri Aktar',
      'regional.tab_export': 'Dışarı Aktar',
    },
    ja: {
      'modules.regional_exchange.description': '20 の地域別コスト標準 (NRM、MasterFormat、DIN 276、PBC、GESN、…) に対応する単一のインポート / エクスポートです。',
      'nav.regional_exchange': '地域BOQ交換',
      'regional.tab_import': 'インポート',
      'regional.tab_export': 'エクスポート',
    },
    ko: {
      'modules.regional_exchange.description': '20개 지역 원가 표준(NRM, MasterFormat, DIN 276, PBC, GESN, …)을 위한 단일 가져오기 / 내보내기입니다.',
      'nav.regional_exchange': '지역 BOQ 교환',
      'regional.tab_import': '가져오기',
      'regional.tab_export': '내보내기',
    },
    zh: {
      'modules.regional_exchange.description': '面向 20 种地区造价标准（NRM、MasterFormat、DIN 276、PBC、GESN、…）的统一导入 / 导出。',
      'nav.regional_exchange': '区域工程量交换',
      'regional.tab_import': '导入',
      'regional.tab_export': '导出',
    },
    ar: {
      'modules.regional_exchange.description': 'استيراد / تصدير واحد لـ 20 معيار تكلفة إقليمي (NRM، MasterFormat، DIN 276، PBC، GESN، …).',
      'nav.regional_exchange': 'تبادل BOQ الإقليمي',
      'regional.tab_import': 'استيراد',
      'regional.tab_export': 'تصدير',
    },
    hi: {
      'modules.regional_exchange.description': '20 क्षेत्रीय लागत मानकों (NRM, MasterFormat, DIN 276, PBC, GESN, …) के लिए एक ही आयात / निर्यात।',
      'nav.regional_exchange': 'क्षेत्रीय BOQ विनिमय',
      'regional.tab_import': 'आयात',
      'regional.tab_export': 'निर्यात',
    },
  },
};
