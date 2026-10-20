// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Box } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'ddc-rvt-converter',
  name: 'converter.rvt.name',
  description: 'modules.ddc_rvt_converter.description',
  version: '1.0.0',
  icon: Box,
  category: 'converter',
  defaultEnabled: false,
  depends: [],
  routes: [],
  navItems: [],
  translations: {
    en: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT Converter',
      'converter.rvt.desc': 'Convert RVT (.rvt) files to DataFrame + COLLADA geometry',
      'modules.ddc_rvt_converter.description':
        'Converts RVT (.rvt) files into element data (DataFrame) and 3D geometry (COLLADA). Extracts families, types, parameters, quantities, and spatial structure via the DDC Converters 2.0 pipeline - no BIM authoring software required.',
    },
    de: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT Konverter',
      'converter.rvt.desc': 'RVT-Dateien (.rvt) in DataFrame + COLLADA-Geometrie konvertieren',
      'modules.ddc_rvt_converter.description':
        'Wandelt RVT-Dateien (.rvt) in Bauteildaten (DataFrame) und 3D-Geometrie (COLLADA) um. Familien, Typen, Parameter, Mengen und Bauwerksstruktur liest DDC Converters 2.0 aus, ganz ohne BIM-Autorensoftware.',
    },
    fr: {
      'converter.rvt.name': 'DDC Converters 2.0 - Convertisseur RVT',
      'modules.ddc_rvt_converter.description': 'Convertit les fichiers RVT (.rvt) en données d\'éléments (DataFrame) et en géométrie 3D (COLLADA). Extrait les familles, types, paramètres, quantités et la structure spatiale via le pipeline DDC Converters 2.0, sans logiciel de modélisation BIM.',
    },
    es: {
      'converter.rvt.name': 'DDC Converters 2.0 - Conversor RVT',
      'modules.ddc_rvt_converter.description': 'Convierte archivos RVT (.rvt) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Extrae familias, tipos, parámetros, cantidades y estructura espacial mediante el pipeline DDC Converters 2.0, sin necesidad de software de modelado BIM.',
    },
    'es-MX': {
      'converter.rvt.name': 'DDC Converters 2.0 - Conversor RVT',
      'modules.ddc_rvt_converter.description': 'Convierte archivos RVT (.rvt) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Extrae familias, tipos, parámetros, cantidades y estructura espacial mediante el pipeline DDC Converters 2.0, sin necesidad de software de modelado BIM.',
    },
    'es-CL': {
      'converter.rvt.name': 'DDC Converters 2.0 - Conversor RVT',
      'modules.ddc_rvt_converter.description': 'Convierte archivos RVT (.rvt) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Extrae familias, tipos, parámetros, cantidades y estructura espacial mediante el pipeline DDC Converters 2.0, sin necesidad de software de modelado BIM.',
    },
    'es-CO': {
      'converter.rvt.name': 'DDC Converters 2.0 - Conversor RVT',
      'modules.ddc_rvt_converter.description': 'Convierte archivos RVT (.rvt) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Extrae familias, tipos, parámetros, cantidades y estructura espacial mediante el pipeline DDC Converters 2.0, sin necesidad de software de modelado BIM.',
    },
    pt: {
      'converter.rvt.name': 'DDC Converters 2.0 - Conversor RVT',
      'modules.ddc_rvt_converter.description': 'Converte ficheiros RVT (.rvt) em dados de elementos (DataFrame) e geometria 3D (COLLADA). Extrai famílias, tipos, parâmetros, quantidades e estrutura espacial através do pipeline DDC Converters 2.0, sem necessidade de software de modelação BIM.',
    },
    'pt-BR': {
      'converter.rvt.name': 'DDC Converters 2.0 - Conversor RVT',
      'modules.ddc_rvt_converter.description': 'Converte arquivos RVT (.rvt) em dados de elementos (DataFrame) e geometria 3D (COLLADA). Extrai famílias, tipos, parâmetros, quantidades e estrutura espacial pelo pipeline DDC Converters 2.0, sem necessidade de software de modelagem BIM.',
    },
    zh: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT 转换器',
      'modules.ddc_rvt_converter.description': '将 RVT（.rvt）文件转换为构件数据（DataFrame）和三维几何（COLLADA）。通过 DDC Converters 2.0 管线提取族、类型、参数、工程量和空间结构，无需 BIM 建模软件。',
    },
    ar: {
      'converter.rvt.name': 'DDC Converters 2.0 - محول RVT',
      'modules.ddc_rvt_converter.description': 'يحوّل ملفات RVT (.rvt) إلى بيانات عناصر (DataFrame) وهندسة ثلاثية الأبعاد (COLLADA). يستخرج العائلات والأنواع والمعاملات والكميات والبنية المكانية عبر خط أنابيب DDC Converters 2.0، دون الحاجة إلى برنامج تصميم BIM.',
    },
    hi: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT कनवर्टर',
      'modules.ddc_rvt_converter.description': 'RVT (.rvt) फ़ाइलों को एलिमेंट डेटा (DataFrame) और 3D ज्यामिति (COLLADA) में बदलता है। DDC Converters 2.0 पाइपलाइन के ज़रिए फ़ैमिलियाँ, प्रकार, पैरामीटर, मात्राएँ और स्थानिक संरचना निकालता है - किसी BIM ऑथरिंग सॉफ़्टवेयर की आवश्यकता नहीं।',
    },
    tr: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT Dönüştürücü',
      'modules.ddc_rvt_converter.description': 'RVT (.rvt) dosyalarını eleman verisine (DataFrame) ve 3B geometriye (COLLADA) dönüştürür. DDC Converters 2.0 hattı üzerinden aileleri, tipleri, parametreleri, miktarları ve mekansal yapıyı çıkarır - BIM modelleme yazılımına gerek kalmadan.',
    },
    it: {
      'converter.rvt.name': 'DDC Converters 2.0 - Convertitore RVT',
      'modules.ddc_rvt_converter.description': 'Converte i file RVT (.rvt) in dati di elementi (DataFrame) e geometria 3D (COLLADA). Estrae famiglie, tipi, parametri, quantità e struttura spaziale tramite la pipeline DDC Converters 2.0, senza bisogno di software di modellazione BIM.',
    },
    nl: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT Converter',
      'modules.ddc_rvt_converter.description': 'Zet RVT-bestanden (.rvt) om in elementgegevens (DataFrame) en 3D-geometrie (COLLADA). Haalt families, typen, parameters, hoeveelheden en ruimtelijke structuur op via de DDC Converters 2.0-pipeline - geen BIM-authoring-software nodig.',
    },
    pl: {
      'converter.rvt.name': 'DDC Converters 2.0 - Konwerter RVT',
      'modules.ddc_rvt_converter.description': 'Konwertuje pliki RVT (.rvt) na dane elementów (DataFrame) i geometrię 3D (COLLADA). Wydobywa rodziny, typy, parametry, ilości i strukturę przestrzenną poprzez potok DDC Converters 2.0 - bez potrzeby oprogramowania do modelowania BIM.',
    },
    cs: {
      'converter.rvt.name': 'DDC Converters 2.0 - Konvertor RVT',
      'modules.ddc_rvt_converter.description': 'Převádí soubory RVT (.rvt) na data prvků (DataFrame) a 3D geometrii (COLLADA). Extrahuje rodiny, typy, parametry, množství a prostorovou strukturu prostřednictvím pipeline DDC Converters 2.0 - bez nutnosti softwaru pro BIM modelování.',
    },
    ja: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT コンバーター',
      'modules.ddc_rvt_converter.description': 'RVT（.rvt）ファイルを要素データ（DataFrame）と3Dジオメトリ（COLLADA）に変換します。DDC Converters 2.0パイプラインによりファミリ、タイプ、パラメータ、数量、空間構造を抽出します。BIM作成ソフトウェアは不要です。',
    },
    ko: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT 변환기',
      'modules.ddc_rvt_converter.description': 'RVT(.rvt) 파일을 요소 데이터(DataFrame)와 3D 지오메트리(COLLADA)로 변환합니다. DDC Converters 2.0 파이프라인을 통해 패밀리, 유형, 매개변수, 물량, 공간 구조를 추출하며 BIM 저작 소프트웨어가 필요하지 않습니다.',
    },
    sv: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT-konverterare',
      'modules.ddc_rvt_converter.description': 'Konverterar RVT-filer (.rvt) till elementdata (DataFrame) och 3D-geometri (COLLADA). Extraherar familjer, typer, parametrar, mängder och rumslig struktur via DDC Converters 2.0-pipelinen - ingen BIM-modelleringsprogramvara krävs.',
    },
    no: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT-konverterer',
      'modules.ddc_rvt_converter.description': 'Konverterer RVT-filer (.rvt) til elementdata (DataFrame) og 3D-geometri (COLLADA). Trekker ut familier, typer, parametere, mengder og romlig struktur via DDC Converters 2.0-pipelinen - ingen BIM-modelleringsprogramvare kreves.',
    },
    da: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT-konverter',
      'modules.ddc_rvt_converter.description': 'Konverterer RVT-filer (.rvt) til elementdata (DataFrame) og 3D-geometri (COLLADA). Udtrækker familier, typer, parametre, mængder og rumlig struktur via DDC Converters 2.0-pipelinen - uden behov for BIM-modelleringssoftware.',
    },
    fi: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT-muunnin',
      'modules.ddc_rvt_converter.description': 'Muuntaa RVT-tiedostot (.rvt) elementtitiedoiksi (DataFrame) ja 3D-geometriaksi (COLLADA). Poimii perheet, tyypit, parametrit, määrät ja tilarakenteen DDC Converters 2.0 -putken kautta - ilman BIM-mallinnusohjelmistoa.',
    },
    bg: {
      'converter.rvt.name': 'DDC Converters 2.0 - Конвертор RVT',
      'modules.ddc_rvt_converter.description': 'Преобразува файлове RVT (.rvt) в данни за елементи (DataFrame) и 3D геометрия (COLLADA). Извлича фамилии, типове, параметри, количества и пространствена структура чрез конвейера DDC Converters 2.0 - без необходимост от софтуер за BIM моделиране.',
    },
    hr: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT konverter',
      'modules.ddc_rvt_converter.description': 'Pretvara RVT datoteke (.rvt) u podatke o elementima (DataFrame) i 3D geometriju (COLLADA). Izdvaja obitelji, tipove, parametre, količine i prostornu strukturu putem DDC Converters 2.0 cjevovoda - bez potrebe za softverom za BIM modeliranje.',
    },
    id: {
      'converter.rvt.name': 'DDC Converters 2.0 - Konverter RVT',
      'modules.ddc_rvt_converter.description': 'Mengonversi file RVT (.rvt) menjadi data elemen (DataFrame) dan geometri 3D (COLLADA). Mengekstrak famili, tipe, parameter, kuantitas, dan struktur spasial melalui pipeline DDC Converters 2.0 - tanpa perlu perangkat lunak pemodelan BIM.',
    },
    ro: {
      'converter.rvt.name': 'DDC Converters 2.0 - Convertor RVT',
      'modules.ddc_rvt_converter.description': 'Convertește fișierele RVT (.rvt) în date de elemente (DataFrame) și geometrie 3D (COLLADA). Extrage familii, tipuri, parametri, cantități și structura spațială prin pipeline-ul DDC Converters 2.0 - fără a fi nevoie de software de modelare BIM.',
    },
    th: {
      'converter.rvt.name': 'DDC Converters 2.0 - ตัวแปลง RVT',
      'modules.ddc_rvt_converter.description': 'แปลงไฟล์ RVT (.rvt) เป็นข้อมูลองค์ประกอบ (DataFrame) และรูปทรงเรขาคณิต 3 มิติ (COLLADA) ดึงข้อมูลตระกูล ประเภท พารามิเตอร์ ปริมาณ และโครงสร้างเชิงพื้นที่ผ่านไปป์ไลน์ DDC Converters 2.0 โดยไม่ต้องใช้ซอฟต์แวร์สร้างแบบจำลอง BIM',
    },
    vi: {
      'converter.rvt.name': 'DDC Converters 2.0 - Bộ chuyển đổi RVT',
      'modules.ddc_rvt_converter.description': 'Chuyển đổi tệp RVT (.rvt) thành dữ liệu cấu kiện (DataFrame) và hình học 3D (COLLADA). Trích xuất family, loại, tham số, khối lượng và cấu trúc không gian qua pipeline DDC Converters 2.0 - không cần phần mềm dựng mô hình BIM.',
    },
    ky: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT конвертери',
      'modules.ddc_rvt_converter.description': 'RVT (.rvt) файлдарын элемент дайындарына (DataFrame) жана 3D геометрияга (COLLADA) айландырат. DDC Converters 2.0 түтүгү аркылуу үй-бүлөлөрдү, түрлөрдү, параметрлерди, көлөмдөрдү жана мейкиндик түзүлүшүн алат - BIM моделдөө программасы талап кылынбайт.',
    },
    et: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT konverter',
      'modules.ddc_rvt_converter.description': 'Teisendab RVT-failid (.rvt) elementide andmeteks (DataFrame) ja 3D-geomeetriaks (COLLADA). Eraldab perekonnad, tüübid, parameetrid, mahud ja ruumilise struktuuri DDC Converters 2.0 konveieri kaudu - BIM-modelleerimistarkvara ei ole vaja.',
    },
    bn: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT কনভার্টার',
      'modules.ddc_rvt_converter.description': 'RVT (.rvt) ফাইলগুলোকে এলিমেন্ট ডেটা (DataFrame) ও 3D জ্যামিতিতে (COLLADA) রূপান্তর করে। DDC Converters 2.0 পাইপলাইনের মাধ্যমে ফ্যামিলি, টাইপ, প্যারামিটার, পরিমাণ ও স্থানিক গঠন বের করে - কোনো BIM অথরিং সফটওয়্যার ছাড়াই।',
    },
    kk: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT конвертері',
      'modules.ddc_rvt_converter.description': 'RVT (.rvt) файлдарын элемент деректеріне (DataFrame) және 3D геометрияға (COLLADA) түрлендіреді. DDC Converters 2.0 құбыры арқылы отбасыларды, түрлерді, параметрлерді, көлемдерді және кеңістіктік құрылымды алады - BIM моделдеу бағдарламалық жасақтамасы қажет емес.',
    },
    fil: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT Converter',
      'modules.ddc_rvt_converter.description': 'Nagko-convert ng mga RVT file (.rvt) sa element data (DataFrame) at 3D geometry (COLLADA). Kinukuha ang mga family, uri, parameter, dami, at spatial na istruktura sa pamamagitan ng DDC Converters 2.0 pipeline - walang kailangang BIM authoring software.',
    },
    ur: {
      'converter.rvt.name': 'DDC Converters 2.0 - RVT کنورٹر',
      'modules.ddc_rvt_converter.description': 'RVT (.rvt) فائلوں کو element ڈیٹا (DataFrame) اور 3D جیومیٹری (COLLADA) میں تبدیل کرتا ہے۔ DDC Converters 2.0 پائپ لائن کے ذریعے families، اقسام، پیرامیٹرز، مقدار اور مقامی ساخت نکالتا ہے - کسی BIM authoring سافٹ ویئر کی ضرورت نہیں۔',
    },
    fa: {
      'converter.rvt.name': 'DDC Converters 2.0 - مبدل RVT',
      'modules.ddc_rvt_converter.description': 'فایلهای RVT (.rvt) را به دادههای عنصر (DataFrame) و هندسه سهبعدی (COLLADA) تبدیل میکند. خانوادهها، انواع، پارامترها، مقادیر و ساختار فضایی را از طریق خط لوله DDC Converters 2.0 استخراج میکند - بدون نیاز به نرمافزار مدلسازی BIM.',
    },
    he: {
      'converter.rvt.name': 'DDC Converters 2.0 - ממיר RVT',
      'modules.ddc_rvt_converter.description': 'ממיר קבצי RVT (.rvt) לנתוני אלמנטים (DataFrame) וגאומטריה תלת-ממדית (COLLADA). מחלץ משפחות, סוגים, פרמטרים, כמויות ומבנה מרחבי דרך צינור DDC Converters 2.0 - ללא צורך בתוכנת מידול BIM.',
    },
    el: {
      'converter.rvt.name': 'DDC Converters 2.0 - Μετατροπέας RVT',
      'modules.ddc_rvt_converter.description': 'Μετατρέπει αρχεία RVT (.rvt) σε δεδομένα στοιχείων (DataFrame) και τρισδιάστατη γεωμετρία (COLLADA). Εξάγει οικογένειες, τύπους, παραμέτρους, ποσότητες και χωρική δομή μέσω του διαύλου DDC Converters 2.0 - χωρίς να απαιτείται λογισμικό μοντελοποίησης BIM.',
    },
    ru: {
      'modules.ddc_rvt_converter.description': 'Преобразует файлы RVT (.rvt) в данные элементов (DataFrame) и 3D-геометрию (COLLADA). Извлекает семейства, типы, параметры, объёмы и пространственную структуру через конвейер DDC Converters 2.0 - без программного обеспечения для BIM-моделирования.',
      'converter.rvt.name': 'DDC Converters 2.0 - RVT Конвертер',
      'converter.rvt.desc': 'Конвертация файлов RVT (.rvt) в DataFrame + COLLADA геометрию',
    },
  },
};
