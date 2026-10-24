// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { FileText, FileInput } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const GAEBExchangeModule = lazy(() => import('./GAEBExchangeModule'));

// schema ref: ddc-lineage:a17f93c4-gaeb-01
export const manifest: ModuleManifest = {
  id: 'gaeb-exchange',
  name: 'gaeb.title',
  description: 'modules.gaeb_exchange.description',
  version: '1.0.0',
  icon: FileText,
  category: 'regional',
  defaultEnabled: true,
  depends: ['boq'],
  routes: [
    {
      path: '/gaeb-exchange',
      title: 'nav.gaeb_exchange',
      component: GAEBExchangeModule,
    },
  ],
  // Issue #217 — reached from /boq (regional import/export); no duplicate sidebar entry.
  // Issue #439: that line above stated an intention, not a fact, because nothing
  // in the BOQ workflow linked here. The doors are the BOQ editor's Export menu
  // and the BOQ overview intro panel, both of which pass the open project and
  // BOQ on the query string. Move or rename either one and this module goes
  // back to being reachable only by typing its URL.
  navItems: [],
  actions: [
    {
      id: 'gaeb.import',
      titleKey: 'palette.action.gaeb_import',
      defaultTitle: 'Import GAEB file',
      keywordsKey: 'palette.keywords.gaeb_import',
      defaultKeywords: 'gaeb, x81, x83, x84, lv, tender file, import',
      group: 'import',
      icon: FileInput,
      defaultShortcut: 'I G',
      run: (ctx) =>
        ctx.navigate(
          ctx.projectId
            ? `/gaeb-exchange?project_id=${encodeURIComponent(ctx.projectId)}&tab=import`
            : '/gaeb-exchange?tab=import',
        ),
    },
  ],
  translations: {
    en: {
      'nav.gaeb_exchange': 'GAEB Exchange',
      'gaeb.title': 'GAEB XML 3.3 Import / Export',
      'modules.gaeb_exchange.description':
        'Exchange BOQ data in GAEB DA XML 3.3 format - import X81/X83/X84 files and export tender/bid documents',
      'gaeb.subtitle': 'Exchange BOQ data in GAEB DA XML format (X81 / X83 / X84)',
      'gaeb.intro_title': 'Trade tender data the DACH way',
      'gaeb.intro_body':
        'Import a GAEB DA XML file (X81 tender specification, X83 invitation to tender or X84 priced bid) straight into a BOQ, or export your BOQ back out in the same family of exchange phases. Imports run through validation on the way in, so your Leistungsverzeichnis arrives structured and checked.',
      'gaeb.tab_import': 'Import',
      'gaeb.tab_export': 'Export',
      'gaeb.import_complete': 'GAEB import complete',
      'gaeb.export_complete': 'GAEB export complete',
    },
    de: {
      'nav.gaeb_exchange': 'GAEB-Austausch',
      'gaeb.title': 'GAEB DA XML 3.3 Import / Export',
      'modules.gaeb_exchange.description':
        'Leistungsverzeichnisse im Format GAEB DA XML 3.3 austauschen - X81/X83/X84 einlesen sowie Ausschreibungen und Angebote ausgeben',
      'gaeb.subtitle': 'Leistungsverzeichnisse im GAEB DA XML-Format austauschen (X81 / X83 / X84)',
      'gaeb.tab_import': 'Importieren',
      'gaeb.tab_export': 'Exportieren',
      'gaeb.import_complete': 'GAEB-Import abgeschlossen',
      'gaeb.export_complete': 'GAEB-Export abgeschlossen',
      'gaeb.x83_desc': 'Angebotsaufforderung (Ausschreibung)',
      'gaeb.x84_desc': 'Angebotsabgabe (bepreistes Angebot)',
      'gaeb.x81_desc': 'Leistungsverzeichnis (ohne Preise)',
      'gaeb.drop_file': 'GAEB XML-Datei hierher ziehen, oder',
      'gaeb.browse': 'Datei auswählen',
    },
    es: {
      'modules.gaeb_exchange.description': 'Intercambie datos de presupuesto en formato GAEB DA XML 3.3: importe archivos X81/X83/X84 y exporte documentos de licitación u oferta',
    },
    'es-MX': {
      'modules.gaeb_exchange.description': 'Intercambie datos de presupuesto en formato GAEB DA XML 3.3: importe archivos X81/X83/X84 y exporte documentos de licitación u oferta',
    },
    'es-CL': {
      'modules.gaeb_exchange.description': 'Intercambie datos de presupuesto en formato GAEB DA XML 3.3: importe archivos X81/X83/X84 y exporte documentos de licitación u oferta',
    },
    'es-CO': {
      'modules.gaeb_exchange.description': 'Intercambie datos de presupuesto en formato GAEB DA XML 3.3: importe archivos X81/X83/X84 y exporte documentos de licitación u oferta',
    },
    pt: {
      'modules.gaeb_exchange.description': 'Troque dados de planilha orçamentária no formato GAEB DA XML 3.3 - importe ficheiros X81/X83/X84 e exporte documentos de concurso/proposta',
    },
    'pt-BR': {
      'modules.gaeb_exchange.description': 'Troque dados de planilha orçamentária no formato GAEB DA XML 3.3 - importe arquivos X81/X83/X84 e exporte documentos de licitação/proposta',
    },
    zh: {
      'modules.gaeb_exchange.description': '以 GAEB DA XML 3.3 格式交换工程量清单数据 - 导入 X81/X83/X84 文件并导出招标/投标文件',
    },
    ar: {
      'modules.gaeb_exchange.description': 'تبادل بيانات جدول الكميات بصيغة GAEB DA XML 3.3 - استيراد ملفات X81/X83/X84 وتصدير مستندات المناقصة/العرض',
    },
    hi: {
      'modules.gaeb_exchange.description': 'GAEB DA XML 3.3 फ़ॉर्मेट में मात्रा विवरण डेटा का आदान-प्रदान करें - X81/X83/X84 फ़ाइलें आयात करें और निविदा/बोली दस्तावेज़ निर्यात करें',
    },
    tr: {
      'modules.gaeb_exchange.description': 'Keşif verilerini GAEB DA XML 3.3 formatında değiştirin - X81/X83/X84 dosyalarını içe aktarın, ihale/teklif belgelerini dışa aktarın',
    },
    it: {
      'modules.gaeb_exchange.description': 'Scambia i dati del computo in formato GAEB DA XML 3.3 - importa file X81/X83/X84 ed esporta documenti di gara/offerta',
    },
    nl: {
      'modules.gaeb_exchange.description': 'Wissel ramingsgegevens uit in GAEB DA XML 3.3-formaat - importeer X81/X83/X84-bestanden en exporteer aanbestedings-/inschrijvingsdocumenten',
    },
    pl: {
      'modules.gaeb_exchange.description': 'Wymieniaj dane kosztorysu w formacie GAEB DA XML 3.3 - importuj pliki X81/X83/X84 i eksportuj dokumenty przetargowe/ofertowe',
    },
    cs: {
      'modules.gaeb_exchange.description': 'Vyměňujte data rozpočtu ve formátu GAEB DA XML 3.3 - importujte soubory X81/X83/X84 a exportujte dokumenty výběrového řízení/nabídky',
    },
    ja: {
      'modules.gaeb_exchange.description': 'GAEB DA XML 3.3形式で数量明細データを交換します - X81/X83/X84ファイルをインポートし、入札書類を出力します',
    },
    ko: {
      'modules.gaeb_exchange.description': 'GAEB DA XML 3.3 형식으로 내역서 데이터를 교환합니다 - X81/X83/X84 파일을 가져오고 입찰 서류를 내보냅니다',
    },
    sv: {
      'modules.gaeb_exchange.description': 'Utbyt mängdförteckningsdata i formatet GAEB DA XML 3.3 - importera X81/X83/X84-filer och exportera förfrågnings-/anbudsdokument',
    },
    no: {
      'modules.gaeb_exchange.description': 'Utveksle mengdefortegnelsesdata i formatet GAEB DA XML 3.3 - importer X81/X83/X84-filer og eksporter anbuds-/tilbudsdokumenter',
    },
    da: {
      'modules.gaeb_exchange.description': 'Udveksl data fra tilbudslisten i formatet GAEB DA XML 3.3 - importér X81/X83/X84-filer, og eksportér udbuds-/tilbudsdokumenter',
    },
    fi: {
      'modules.gaeb_exchange.description': 'Vaihda määräluettelotietoja GAEB DA XML 3.3 -muodossa - tuo X81/X83/X84-tiedostoja ja vie tarjouspyyntö-/tarjousasiakirjoja',
    },
    bg: {
      'modules.gaeb_exchange.description': 'Обменяйте данни от количествената сметка във формат GAEB DA XML 3.3 - импортирайте файлове X81/X83/X84 и експортирайте документи за търг/оферта',
    },
    hr: {
      'modules.gaeb_exchange.description': 'Razmjenjujte podatke troškovnika u formatu GAEB DA XML 3.3 - uvezite datoteke X81/X83/X84 i izvezite natječajnu/ponudbenu dokumentaciju',
    },
    id: {
      'modules.gaeb_exchange.description': 'Pertukaran data daftar kuantitas dalam format GAEB DA XML 3.3 - impor file X81/X83/X84 dan ekspor dokumen tender/penawaran',
    },
    ro: {
      'modules.gaeb_exchange.description': 'Faceți schimb de date din listă în format GAEB DA XML 3.3 - importați fișiere X81/X83/X84 și exportați documente de licitație/ofertă',
    },
    th: {
      'modules.gaeb_exchange.description': 'แลกเปลี่ยนข้อมูลปริมาณงานในรูปแบบ GAEB DA XML 3.3 - นำเข้าไฟล์ X81/X83/X84 และส่งออกเอกสารประกวดราคา/ยื่นซอง',
    },
    vi: {
      'modules.gaeb_exchange.description': 'Trao đổi dữ liệu bảng khối lượng theo định dạng GAEB DA XML 3.3 - nhập tệp X81/X83/X84 và xuất tài liệu đấu thầu/hồ sơ dự thầu',
    },
    ky: {
      'modules.gaeb_exchange.description': 'Смета маалыматтарын GAEB DA XML 3.3 форматында алмаштырыңыз - X81/X83/X84 файлдарын импорттоңуз жана тендер/сунуш документтерин экспорттоңуз',
    },
    et: {
      'modules.gaeb_exchange.description': 'Vahetage mahutabeli andmeid GAEB DA XML 3.3 vormingus - importige X81/X83/X84 faile ja eksportige hanke-/pakkumisdokumente',
    },
    bn: {
      'modules.gaeb_exchange.description': 'GAEB DA XML 3.3 ফরম্যাটে বিল অফ কোয়ান্টিটিজের ডেটা বিনিময় করুন - X81/X83/X84 ফাইল ইম্পোর্ট করুন এবং টেন্ডার/বিড নথি এক্সপোর্ট করুন',
    },
    kk: {
      'modules.gaeb_exchange.description': 'Көлемдер ведомостісінің деректерін GAEB DA XML 3.3 форматында алмастырыңыз - X81/X83/X84 файлдарын импорттаңыз және тендер/ұсыныс құжаттарын экспорттаңыз',
    },
    fil: {
      'modules.gaeb_exchange.description': 'Magpalitan ng datos ng BOQ sa format na GAEB DA XML 3.3 - mag-import ng mga X81/X83/X84 file at mag-export ng mga dokumento ng tender/bid',
    },
    ur: {
      'modules.gaeb_exchange.description': 'GAEB DA XML 3.3 فارمیٹ میں مقدار کے بل کا ڈیٹا تبادلہ کریں - X81/X83/X84 فائلیں درآمد کریں اور ٹینڈر/بولی دستاویزات برآمد کریں',
    },
    fa: {
      'modules.gaeb_exchange.description': 'دادههای صورت مقادیر را در قالب GAEB DA XML 3.3 مبادله کنید - فایلهای X81/X83/X84 را وارد کنید و اسناد مناقصه/پیشنهاد را خروجی بگیرید',
    },
    he: {
      'modules.gaeb_exchange.description': 'החליפו נתוני כתב כמויות בפורמט GAEB DA XML 3.3 - ייבאו קבצי X81/X83/X84 וייצאו מסמכי מכרז/הצעה',
    },
    el: {
      'modules.gaeb_exchange.description': 'Ανταλλάξτε δεδομένα προμέτρησης σε μορφή GAEB DA XML 3.3 - εισαγάγετε αρχεία X81/X83/X84 και εξαγάγετε έγγραφα διαγωνισμού/προσφοράς',
    },
    fr: {
      'modules.gaeb_exchange.description': 'Échangez les données de DQE au format GAEB DA XML 3.3 - importez des fichiers X81/X83/X84 et exportez des documents d\'appel d\'offres ou de soumission',
      'nav.gaeb_exchange': 'Échange GAEB',
      'gaeb.title': 'GAEB DA XML 3.3 Import / Export',
      'gaeb.subtitle': 'Échanger les données de DQE au format GAEB DA XML (X81 / X83 / X84)',
      'gaeb.tab_import': 'Importer',
      'gaeb.tab_export': 'Exporter',
      'gaeb.import_complete': 'Import GAEB terminé',
      'gaeb.export_complete': 'Export GAEB terminé',
    },
    ru: {
      'modules.gaeb_exchange.description': 'Обмен данными сметы в формате GAEB DA XML 3.3 - импорт файлов X81/X83/X84 и экспорт документов тендера/предложения',
      'nav.gaeb_exchange': 'GAEB Обмен',
      'gaeb.title': 'GAEB DA XML 3.3 Импорт / Экспорт',
      'gaeb.subtitle': 'Обмен данными сметы в формате GAEB DA XML (X81 / X83 / X84)',
      'gaeb.tab_import': 'Импорт',
      'gaeb.tab_export': 'Экспорт',
      'gaeb.import_complete': 'Импорт GAEB завершён',
      'gaeb.export_complete': 'Экспорт GAEB завершён',
      'gaeb.x83_desc': 'Приглашение к подаче предложений (Ausschreibung)',
      'gaeb.x84_desc': 'Подача предложения (с ценами)',
      'gaeb.x81_desc': 'Спецификация (без цен)',
    },
  },
};
