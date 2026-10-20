// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Box } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'ddc-ifc-converter',
  name: 'converter.ifc.name',
  description: 'modules.ddc_ifc_converter.description',
  version: '1.0.0',
  icon: Box,
  category: 'converter',
  defaultEnabled: false,
  depends: [],
  routes: [],
  navItems: [],
  translations: {
    en: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC Converter',
      'converter.ifc.desc': 'Convert IFC files to DataFrame + COLLADA geometry',
      'modules.ddc_ifc_converter.description':
        'Converts IFC (Industry Foundation Classes) files into element data (DataFrame) and 3D geometry (COLLADA). Enables automatic extraction of walls, slabs, columns, beams, doors, windows, MEP elements with quantities, properties, and storey classification.',
    },
    de: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC Konverter',
      'converter.ifc.desc': 'IFC-Dateien in DataFrame + COLLADA-Geometrie konvertieren',
      'modules.ddc_ifc_converter.description':
        'Wandelt IFC-Dateien (Industry Foundation Classes) in Bauteildaten (DataFrame) und 3D-Geometrie (COLLADA) um. Wände, Decken, Stützen, Träger, Türen, Fenster und TGA-Bauteile werden mit Mengen, Eigenschaften und Geschosszuordnung automatisch ausgelesen.',
    },
    fr: {
      'converter.ifc.name': 'DDC Converters 2.0 - Convertisseur IFC',
      'modules.ddc_ifc_converter.description': 'Convertit les fichiers IFC (Industry Foundation Classes) en données d\'éléments (DataFrame) et en géométrie 3D (COLLADA). Permet l\'extraction automatique des murs, dalles, poteaux, poutres, portes, fenêtres et éléments techniques avec leurs quantités, propriétés et répartition par étage.',
    },
    es: {
      'converter.ifc.name': 'DDC Converters 2.0 - Conversor IFC',
      'modules.ddc_ifc_converter.description': 'Convierte archivos IFC (Industry Foundation Classes) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Permite extraer automáticamente muros, forjados, pilares, vigas, puertas, ventanas y elementos de instalaciones con sus cantidades, propiedades y clasificación por planta.',
    },
    'es-MX': {
      'converter.ifc.name': 'DDC Converters 2.0 - Conversor IFC',
      'modules.ddc_ifc_converter.description': 'Convierte archivos IFC (Industry Foundation Classes) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Permite extraer automáticamente muros, losas, columnas, trabes, puertas, ventanas y elementos de instalaciones con sus cantidades, propiedades y clasificación por nivel.',
    },
    'es-CL': {
      'converter.ifc.name': 'DDC Converters 2.0 - Conversor IFC',
      'modules.ddc_ifc_converter.description': 'Convierte archivos IFC (Industry Foundation Classes) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Permite extraer automáticamente muros, losas, columnas, vigas, puertas, ventanas y elementos de instalaciones con sus cantidades, propiedades y clasificación por nivel.',
    },
    'es-CO': {
      'converter.ifc.name': 'DDC Converters 2.0 - Conversor IFC',
      'modules.ddc_ifc_converter.description': 'Convierte archivos IFC (Industry Foundation Classes) en datos de elementos (DataFrame) y geometría 3D (COLLADA). Permite extraer automáticamente muros, losas, columnas, vigas, puertas, ventanas y elementos de instalaciones con sus cantidades, propiedades y clasificación por nivel.',
    },
    pt: {
      'converter.ifc.name': 'DDC Converters 2.0 - Conversor IFC',
      'modules.ddc_ifc_converter.description': 'Converte ficheiros IFC (Industry Foundation Classes) em dados de elementos (DataFrame) e geometria 3D (COLLADA). Permite a extração automática de paredes, lajes, pilares, vigas, portas, janelas e elementos de instalações técnicas, com as respetivas quantidades, propriedades e classificação por piso.',
    },
    'pt-BR': {
      'converter.ifc.name': 'DDC Converters 2.0 - Conversor IFC',
      'modules.ddc_ifc_converter.description': 'Converte arquivos IFC (Industry Foundation Classes) em dados de elementos (DataFrame) e geometria 3D (COLLADA). Permite a extração automática de paredes, lajes, pilares, vigas, portas, janelas e elementos de instalações, com quantidades, propriedades e classificação por pavimento.',
    },
    zh: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC 转换器',
      'modules.ddc_ifc_converter.description': '将 IFC（Industry Foundation Classes）文件转换为构件数据（DataFrame）和三维几何（COLLADA）。可自动提取墙体、楼板、柱、梁、门、窗及机电构件的工程量、属性和楼层分类。',
    },
    ar: {
      'converter.ifc.name': 'DDC Converters 2.0 - محول IFC',
      'modules.ddc_ifc_converter.description': 'يحوّل ملفات IFC (Industry Foundation Classes) إلى بيانات عناصر (DataFrame) وهندسة ثلاثية الأبعاد (COLLADA). يتيح الاستخراج التلقائي للجدران والبلاطات والأعمدة والكمرات والأبواب والنوافذ وعناصر الأنظمة الكهروميكانيكية مع الكميات والخصائص وتصنيف الطوابق.',
    },
    hi: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC कनवर्टर',
      'modules.ddc_ifc_converter.description': 'IFC (Industry Foundation Classes) फ़ाइलों को एलिमेंट डेटा (DataFrame) और 3D ज्यामिति (COLLADA) में बदलता है। दीवारों, स्लैब, स्तंभों, बीमों, दरवाज़ों, खिड़कियों और MEP तत्वों को मात्रा, गुणों और तल-वर्गीकरण के साथ स्वतः निकालने में सक्षम बनाता है।',
    },
    tr: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC Dönüştürücü',
      'modules.ddc_ifc_converter.description': 'IFC (Industry Foundation Classes) dosyalarını eleman verisine (DataFrame) ve 3B geometriye (COLLADA) dönüştürür. Duvarların, döşemelerin, kolonların, kirişlerin, kapıların, pencerelerin ve tesisat elemanlarının miktar, özellik ve kat sınıflandırmasıyla otomatik olarak çıkarılmasını sağlar.',
    },
    it: {
      'converter.ifc.name': 'DDC Converters 2.0 - Convertitore IFC',
      'modules.ddc_ifc_converter.description': 'Converte i file IFC (Industry Foundation Classes) in dati di elementi (DataFrame) e geometria 3D (COLLADA). Consente l\'estrazione automatica di muri, solai, pilastri, travi, porte, finestre ed elementi impiantistici con quantità, proprietà e classificazione per piano.',
    },
    nl: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC Converter',
      'modules.ddc_ifc_converter.description': 'Zet IFC-bestanden (Industry Foundation Classes) om in elementgegevens (DataFrame) en 3D-geometrie (COLLADA). Maakt automatische extractie mogelijk van wanden, vloeren, kolommen, balken, deuren, ramen en installatie-elementen met hoeveelheden, eigenschappen en verdiepingsindeling.',
    },
    pl: {
      'converter.ifc.name': 'DDC Converters 2.0 - Konwerter IFC',
      'modules.ddc_ifc_converter.description': 'Konwertuje pliki IFC (Industry Foundation Classes) na dane elementów (DataFrame) i geometrię 3D (COLLADA). Umożliwia automatyczne wyodrębnianie ścian, stropów, słupów, belek, drzwi, okien i elementów instalacyjnych wraz z ilościami, właściwościami i przypisaniem do kondygnacji.',
    },
    cs: {
      'converter.ifc.name': 'DDC Converters 2.0 - Konvertor IFC',
      'modules.ddc_ifc_converter.description': 'Převádí soubory IFC (Industry Foundation Classes) na data prvků (DataFrame) a 3D geometrii (COLLADA). Umožňuje automatickou extrakci stěn, stropů, sloupů, nosníků, dveří, oken a prvků TZB s množstvím, vlastnostmi a rozdělením podle podlaží.',
    },
    ja: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC コンバーター',
      'modules.ddc_ifc_converter.description': 'IFC（Industry Foundation Classes）ファイルを要素データ（DataFrame）と3Dジオメトリ（COLLADA）に変換します。壁、床版、柱、梁、ドア、窓、設備要素を数量・属性・階層分類とともに自動抽出できます。',
    },
    ko: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC 변환기',
      'modules.ddc_ifc_converter.description': 'IFC(Industry Foundation Classes) 파일을 요소 데이터(DataFrame)와 3D 지오메트리(COLLADA)로 변환합니다. 벽, 슬래브, 기둥, 보, 문, 창, 설비 요소를 물량, 속성, 층 분류와 함께 자동으로 추출할 수 있습니다.',
    },
    sv: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC-konverterare',
      'modules.ddc_ifc_converter.description': 'Konverterar IFC-filer (Industry Foundation Classes) till elementdata (DataFrame) och 3D-geometri (COLLADA). Möjliggör automatisk extraktion av väggar, bjälklag, pelare, balkar, dörrar, fönster och installationselement med mängder, egenskaper och våningsklassificering.',
    },
    no: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC-konverterer',
      'modules.ddc_ifc_converter.description': 'Konverterer IFC-filer (Industry Foundation Classes) til elementdata (DataFrame) og 3D-geometri (COLLADA). Muliggjør automatisk uttrekk av vegger, dekker, søyler, bjelker, dører, vinduer og tekniske elementer med mengder, egenskaper og etasjeklassifisering.',
    },
    da: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC-konverter',
      'modules.ddc_ifc_converter.description': 'Konverterer IFC-filer (Industry Foundation Classes) til elementdata (DataFrame) og 3D-geometri (COLLADA). Muliggør automatisk udtræk af vægge, dæk, søjler, bjælker, døre, vinduer og installationselementer med mængder, egenskaber og etageklassifikation.',
    },
    fi: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC-muunnin',
      'modules.ddc_ifc_converter.description': 'Muuntaa IFC-tiedostot (Industry Foundation Classes) elementtitiedoiksi (DataFrame) ja 3D-geometriaksi (COLLADA). Mahdollistaa seinien, laattojen, pilareiden, palkkien, ovien, ikkunoiden ja talotekniikan elementtien automaattisen poiminnan määrineen, ominaisuuksineen ja kerrosluokitteluineen.',
    },
    bg: {
      'converter.ifc.name': 'DDC Converters 2.0 - Конвертор IFC',
      'modules.ddc_ifc_converter.description': 'Преобразува файлове IFC (Industry Foundation Classes) в данни за елементи (DataFrame) и 3D геометрия (COLLADA). Позволява автоматично извличане на стени, плочи, колони, греди, врати, прозорци и инсталационни елементи с количества, свойства и класификация по етажи.',
    },
    hr: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC konverter',
      'modules.ddc_ifc_converter.description': 'Pretvara IFC datoteke (Industry Foundation Classes) u podatke o elementima (DataFrame) i 3D geometriju (COLLADA). Omogućuje automatsko izdvajanje zidova, ploča, stupova, greda, vrata, prozora i instalacijskih elemenata s količinama, svojstvima i razvrstavanjem po katovima.',
    },
    id: {
      'converter.ifc.name': 'DDC Converters 2.0 - Konverter IFC',
      'modules.ddc_ifc_converter.description': 'Mengonversi file IFC (Industry Foundation Classes) menjadi data elemen (DataFrame) dan geometri 3D (COLLADA). Memungkinkan ekstraksi otomatis dinding, pelat lantai, kolom, balok, pintu, jendela, dan elemen MEP beserta kuantitas, properti, dan klasifikasi lantai.',
    },
    ro: {
      'converter.ifc.name': 'DDC Converters 2.0 - Convertor IFC',
      'modules.ddc_ifc_converter.description': 'Convertește fișierele IFC (Industry Foundation Classes) în date de elemente (DataFrame) și geometrie 3D (COLLADA). Permite extragerea automată a pereților, plăcilor, stâlpilor, grinzilor, ușilor, ferestrelor și elementelor de instalații, cu cantități, proprietăți și clasificare pe niveluri.',
    },
    th: {
      'converter.ifc.name': 'DDC Converters 2.0 - ตัวแปลง IFC',
      'modules.ddc_ifc_converter.description': 'แปลงไฟล์ IFC (Industry Foundation Classes) เป็นข้อมูลองค์ประกอบ (DataFrame) และรูปทรงเรขาคณิต 3 มิติ (COLLADA) รองรับการดึงข้อมูลผนัง พื้น เสา คาน ประตู หน้าต่าง และองค์ประกอบงานระบบโดยอัตโนมัติ พร้อมปริมาณ คุณสมบัติ และการจำแนกตามชั้น',
    },
    vi: {
      'converter.ifc.name': 'DDC Converters 2.0 - Bộ chuyển đổi IFC',
      'modules.ddc_ifc_converter.description': 'Chuyển đổi tệp IFC (Industry Foundation Classes) thành dữ liệu cấu kiện (DataFrame) và hình học 3D (COLLADA). Cho phép tự động trích xuất tường, sàn, cột, dầm, cửa đi, cửa sổ và các cấu kiện cơ điện cùng khối lượng, thuộc tính và phân loại theo tầng.',
    },
    ky: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC конвертери',
      'modules.ddc_ifc_converter.description': 'IFC (Industry Foundation Classes) файлдарын элемент дайындарына (DataFrame) жана 3D геометрияга (COLLADA) айландырат. Дубалдарды, плиталарды, мамыларды, тирөөчтөрдү, эшиктерди, терезелерди жана инженердик тармактардын элементтерин көлөмдөрү, касиеттери жана кабат боюнча классификациясы менен автоматтык түрдө алууга мүмкүндүк берет.',
    },
    et: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC konverter',
      'modules.ddc_ifc_converter.description': 'Teisendab IFC-failid (Industry Foundation Classes) elementide andmeteks (DataFrame) ja 3D-geomeetriaks (COLLADA). Võimaldab automaatselt eraldada seinu, plaate, sambaid, talasid, uksi, aknaid ja tehnosüsteemide elemente koos mahtude, omaduste ja korruseliigitusega.',
    },
    bn: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC কনভার্টার',
      'modules.ddc_ifc_converter.description': 'IFC (Industry Foundation Classes) ফাইলগুলোকে এলিমেন্ট ডেটা (DataFrame) ও 3D জ্যামিতিতে (COLLADA) রূপান্তর করে। দেয়াল, স্ল্যাব, কলাম, বিম, দরজা, জানালা এবং MEP উপাদানগুলো পরিমাণ, বৈশিষ্ট্য ও তলা-শ্রেণিবিন্যাস সহ স্বয়ংক্রিয়ভাবে বের করা যায়।',
    },
    kk: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC конвертері',
      'modules.ddc_ifc_converter.description': 'IFC (Industry Foundation Classes) файлдарын элемент деректеріне (DataFrame) және 3D геометрияға (COLLADA) түрлендіреді. Қабырғаларды, плиталарды, бағаналарды, арқалықтарды, есіктерді, терезелерді және инженерлік жүйелер элементтерін көлемдерімен, қасиеттерімен және қабат бойынша жіктелуімен автоматты түрде алуға мүмкіндік береді.',
    },
    fil: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC Converter',
      'modules.ddc_ifc_converter.description': 'Nagko-convert ng mga IFC file (Industry Foundation Classes) sa element data (DataFrame) at 3D geometry (COLLADA). Nagbibigay-daan sa awtomatikong pagkuha ng mga dingding, slab, haligi, biga, pinto, bintana, at MEP element kasama ang dami, katangian, at pag-uuri ayon sa palapag.',
    },
    ur: {
      'converter.ifc.name': 'DDC Converters 2.0 - IFC کنورٹر',
      'modules.ddc_ifc_converter.description': 'IFC (Industry Foundation Classes) فائلوں کو element ڈیٹا (DataFrame) اور 3D جیومیٹری (COLLADA) میں تبدیل کرتا ہے۔ دیواروں، سلیبوں، ستونوں، شہتیروں، دروازوں، کھڑکیوں اور MEP عناصر کو مقدار، خصوصیات اور منزل کی درجہ بندی کے ساتھ خودکار طور پر نکالنے کے قابل بناتا ہے۔',
    },
    fa: {
      'converter.ifc.name': 'DDC Converters 2.0 - مبدل IFC',
      'modules.ddc_ifc_converter.description': 'فایلهای IFC (Industry Foundation Classes) را به دادههای عنصر (DataFrame) و هندسه سهبعدی (COLLADA) تبدیل میکند. استخراج خودکار دیوارها، دالها، ستونها، تیرها، درها، پنجرهها و عناصر تأسیساتی را همراه با مقادیر، ویژگیها و طبقهبندی طبقات ممکن میسازد.',
    },
    he: {
      'converter.ifc.name': 'DDC Converters 2.0 - ממיר IFC',
      'modules.ddc_ifc_converter.description': 'ממיר קבצי IFC (Industry Foundation Classes) לנתוני אלמנטים (DataFrame) וגאומטריה תלת-ממדית (COLLADA). מאפשר חילוץ אוטומטי של קירות, תקרות, עמודים, קורות, דלתות, חלונות ואלמנטים מערכתיים, עם כמויות, מאפיינים וסיווג לפי קומה.',
    },
    el: {
      'converter.ifc.name': 'DDC Converters 2.0 - Μετατροπέας IFC',
      'modules.ddc_ifc_converter.description': 'Μετατρέπει αρχεία IFC (Industry Foundation Classes) σε δεδομένα στοιχείων (DataFrame) και τρισδιάστατη γεωμετρία (COLLADA). Επιτρέπει την αυτόματη εξαγωγή τοίχων, πλακών, υποστυλωμάτων, δοκών, θυρών, παραθύρων και ηλεκτρομηχανολογικών στοιχείων με ποσότητες, ιδιότητες και ταξινόμηση ανά όροφο.',
    },
    ru: {
      'modules.ddc_ifc_converter.description': 'Преобразует файлы IFC (Industry Foundation Classes) в данные элементов (DataFrame) и 3D-геометрию (COLLADA). Позволяет автоматически извлекать стены, перекрытия, колонны, балки, двери, окна, инженерные элементы с объёмами, свойствами и разбивкой по этажам.',
      'converter.ifc.name': 'DDC Converters 2.0 - IFC Конвертер',
      'converter.ifc.desc': 'Конвертация IFC файлов в DataFrame + COLLADA геометрию',
    },
  },
};
