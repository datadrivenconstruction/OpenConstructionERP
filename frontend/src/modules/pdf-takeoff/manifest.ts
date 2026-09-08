// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Ruler } from 'lucide-react';
import type { ModuleManifest } from '../_types';

// internal build lineage: ddc-lineage:a17f93c4-takeoff-02
export const manifest: ModuleManifest = {
  id: 'pdf-takeoff',
  name: 'modules.pdf_takeoff.name',
  description: 'modules.pdf_takeoff.description',
  version: '1.0.0',
  icon: Ruler,
  category: 'tools',
  defaultEnabled: true,
  // The viewer this module owns is not retired — `TakeoffViewerModule` is
  // mounted by `features/takeoff/TakeoffPage.tsx`, on the Measurements tab of
  // `/takeoff`, which the sidebar offers as `nav.pdf_measurements`. What is
  // retired is the standalone `/takeoff-viewer` route this manifest used to
  // register: it mounted the same component with none of the props TakeoffPage
  // passes (document library, filmstrip, annotation deep-link), so it was a
  // strictly poorer second door, and nothing under `frontend/src` ever linked
  // to it. `App.tsx` now redirects `/takeoff-viewer` to
  // `/takeoff?tab=measurements` so old bookmarks keep working whatever this
  // module's enabled-state is, the way `/risk-analysis` was retired in #71.
  //
  // With no route and no nav item, the manifest is a name, a description and a
  // translations bundle: nothing reads `isModuleEnabled('pdf-takeoff')`, and
  // TakeoffPage does not gate the embed on it. Turning this module off in the
  // Modules page therefore changes nothing on screen today. Left as-is rather
  // than flipped, because the flag is the natural gate should the takeoff tab
  // ever want one, and `defaultEnabled` is pinned by `_registry.test.ts`.
  routes: [],
  navItems: [],
  translations: {
    en: {
      'modules.pdf_takeoff.name': 'PDF Takeoff Viewer',
      'modules.pdf_takeoff.description': 'View PDFs and take measurements directly on drawings',
    },
    de: {
      'modules.pdf_takeoff.name': 'PDF-Aufmaß-Viewer',
      'modules.pdf_takeoff.description': 'PDF-Pläne ansehen und Mengen direkt in der Zeichnung aufmessen',
    },
    fr: {
      'modules.pdf_takeoff.name': 'Visionneuse de métré PDF',
      'modules.pdf_takeoff.description': 'Visualisez des PDF et effectuez des mesures directement sur les plans',
    },
    es: {
      'modules.pdf_takeoff.name': 'Visor de mediciones en PDF',
      'modules.pdf_takeoff.description': 'Visualice PDF y tome medidas directamente sobre los planos',
    },
    'es-MX': {
      'modules.pdf_takeoff.name': 'Visor de mediciones en PDF',
      'modules.pdf_takeoff.description': 'Visualice PDF y tome medidas directamente sobre los planos',
    },
    'es-CL': {
      'modules.pdf_takeoff.name': 'Visor de mediciones en PDF',
      'modules.pdf_takeoff.description': 'Visualice PDF y tome medidas directamente sobre los planos',
    },
    'es-CO': {
      'modules.pdf_takeoff.name': 'Visor de mediciones en PDF',
      'modules.pdf_takeoff.description': 'Visualice PDF y tome medidas directamente sobre los planos',
    },
    pt: {
      'modules.pdf_takeoff.name': 'Visualizador de levantamento em PDF',
      'modules.pdf_takeoff.description': 'Visualize PDF e faça medições diretamente sobre os desenhos',
    },
    'pt-BR': {
      'modules.pdf_takeoff.name': 'Visualizador de levantamento em PDF',
      'modules.pdf_takeoff.description': 'Visualize PDFs e faça medições diretamente sobre os desenhos',
    },
    ru: {
      'modules.pdf_takeoff.name': 'Просмотр PDF-подсчётов',
      'modules.pdf_takeoff.description': 'Просматривайте PDF и снимайте размеры прямо на чертеже',
    },
    zh: {
      'modules.pdf_takeoff.name': 'PDF 算量查看器',
      'modules.pdf_takeoff.description': '查看 PDF 并直接在图纸上进行测量',
    },
    ar: {
      'modules.pdf_takeoff.name': 'عارض حصر الكميات من PDF',
      'modules.pdf_takeoff.description': 'اعرض ملفات PDF وخذ القياسات مباشرة على المخططات',
    },
    hi: {
      'modules.pdf_takeoff.name': 'PDF टेकऑफ़ व्यूअर',
      'modules.pdf_takeoff.description': 'PDF देखें और चित्रों पर सीधे माप लें',
    },
    tr: {
      'modules.pdf_takeoff.name': 'PDF Metraj Görüntüleyici',
      'modules.pdf_takeoff.description': 'PDF\'leri görüntüleyin ve ölçümleri doğrudan çizimler üzerinde alın',
    },
    it: {
      'modules.pdf_takeoff.name': 'Visualizzatore di computo da PDF',
      'modules.pdf_takeoff.description': 'Visualizza i PDF e prendi misure direttamente sugli elaborati',
    },
    nl: {
      'modules.pdf_takeoff.name': 'PDF-hoeveelhedenviewer',
      'modules.pdf_takeoff.description': 'Bekijk PDF\'s en neem metingen rechtstreeks op de tekeningen',
    },
    pl: {
      'modules.pdf_takeoff.name': 'Przeglądarka obmiaru PDF',
      'modules.pdf_takeoff.description': 'Przeglądaj pliki PDF i wykonuj pomiary bezpośrednio na rysunkach',
    },
    cs: {
      'modules.pdf_takeoff.name': 'Prohlížeč výkazu výměr z PDF',
      'modules.pdf_takeoff.description': 'Prohlížejte PDF a provádějte měření přímo ve výkresech',
    },
    ja: {
      'modules.pdf_takeoff.name': 'PDF数量拾いビューア',
      'modules.pdf_takeoff.description': 'PDFを表示し、図面上で直接測定します',
    },
    ko: {
      'modules.pdf_takeoff.name': 'PDF 물량산출 뷰어',
      'modules.pdf_takeoff.description': 'PDF를 보고 도면 위에서 직접 측정합니다',
    },
    sv: {
      'modules.pdf_takeoff.name': 'PDF-mängdavtagningsvisare',
      'modules.pdf_takeoff.description': 'Visa PDF:er och ta mått direkt på ritningarna',
    },
    no: {
      'modules.pdf_takeoff.name': 'PDF-mengdeuttaksviser',
      'modules.pdf_takeoff.description': 'Vis PDF-er og ta mål direkte på tegningene',
    },
    da: {
      'modules.pdf_takeoff.name': 'PDF-opmålingsviewer',
      'modules.pdf_takeoff.description': 'Se PDF\'er, og tag mål direkte på tegningerne',
    },
    fi: {
      'modules.pdf_takeoff.name': 'PDF-määrälaskennan katseluohjelma',
      'modules.pdf_takeoff.description': 'Katsele PDF-tiedostoja ja ota mittoja suoraan piirustuksista',
    },
    bg: {
      'modules.pdf_takeoff.name': 'Преглед на PDF измервания',
      'modules.pdf_takeoff.description': 'Преглеждайте PDF файлове и вземайте размери директно върху чертежите',
    },
    hr: {
      'modules.pdf_takeoff.name': 'Preglednik PDF iskaza količina',
      'modules.pdf_takeoff.description': 'Pregledavajte PDF-ove i mjerite izravno na nacrtima',
    },
    id: {
      'modules.pdf_takeoff.name': 'Penampil Takeoff PDF',
      'modules.pdf_takeoff.description': 'Lihat PDF dan ambil pengukuran langsung pada gambar',
    },
    ro: {
      'modules.pdf_takeoff.name': 'Vizualizator de antemăsurătoare PDF',
      'modules.pdf_takeoff.description': 'Vizualizați fișiere PDF și efectuați măsurători direct pe planșe',
    },
    th: {
      'modules.pdf_takeoff.name': 'โปรแกรมดูการถอดปริมาณจาก PDF',
      'modules.pdf_takeoff.description': 'ดูไฟล์ PDF และวัดขนาดโดยตรงบนแบบ',
    },
    vi: {
      'modules.pdf_takeoff.name': 'Trình xem bóc tách khối lượng PDF',
      'modules.pdf_takeoff.description': 'Xem tệp PDF và đo trực tiếp trên bản vẽ',
    },
    ky: {
      'modules.pdf_takeoff.name': 'PDF өлчөө көрүүчүсү',
      'modules.pdf_takeoff.description': 'PDF файлдарын көрүңүз жана чиймелерде түз өлчөмдөрдү алыңыз',
    },
    et: {
      'modules.pdf_takeoff.name': 'PDF-mõõdistuse vaatur',
      'modules.pdf_takeoff.description': 'Vaadake PDF-e ja tehke mõõtmisi otse joonistel',
    },
    bn: {
      'modules.pdf_takeoff.name': 'PDF টেকঅফ ভিউয়ার',
      'modules.pdf_takeoff.description': 'PDF দেখুন এবং সরাসরি অঙ্কনে পরিমাপ নিন',
    },
    kk: {
      'modules.pdf_takeoff.name': 'PDF өлшеу қарау құралы',
      'modules.pdf_takeoff.description': 'PDF файлдарын қарап, сызбаларда тікелей өлшемдер алыңыз',
    },
    fil: {
      'modules.pdf_takeoff.name': 'Viewer ng Sukat sa PDF',
      'modules.pdf_takeoff.description': 'Tingnan ang mga PDF at kumuha ng sukat direkta sa mga plano',
    },
    ur: {
      'modules.pdf_takeoff.name': 'PDF پیمائش ویور',
      'modules.pdf_takeoff.description': 'PDF دیکھیں اور ڈرائنگز پر براہ راست پیمائش کریں',
    },
    fa: {
      'modules.pdf_takeoff.name': 'نمایشگر متره PDF',
      'modules.pdf_takeoff.description': 'فایلهای PDF را مشاهده کنید و اندازهگیریها را مستقیماً روی نقشهها انجام دهید',
    },
    he: {
      'modules.pdf_takeoff.name': 'מציג כימות PDF',
      'modules.pdf_takeoff.description': 'צפו בקבצי PDF וקחו מדידות ישירות על הכתבים',
    },
    el: {
      'modules.pdf_takeoff.name': 'Πρόγραμμα προβολής επιμέτρησης PDF',
      'modules.pdf_takeoff.description': 'Προβάλετε PDF και λάβετε μετρήσεις απευθείας πάνω στα σχέδια',
    },
  },
};
