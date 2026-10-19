"""‌⁠‍Backfill 10 new bim.geometry_* / bim.loading_* i18n keys into 26 non-EN locales.

Idempotent: replaces existing values, inserts after `bim.no_elements` when absent.

The English source-of-truth lives in `frontend/src/app/locales/en.ts`; we do not
touch it. All new keys are placed in the bim.* block immediately after the line
matching `"bim.no_elements"`.

Usage:
    python scripts/backfill_bim_viewer_i18n.py

After running, verify:
    cd frontend && npx tsc --noEmit
    grep -c "bim.geometry_load_failed" frontend/src/app/locales/*.ts  # → 27
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ordered list of the 10 new keys (insert in this exact order)
KEY_ORDER = [
    "bim.geometry_load_failed",
    "bim.geometry_retry",
    "bim.geometry_dismiss",
    "bim.geometry_show_diagnostic",
    "bim.geometry_copy_diagnostic",
    "bim.loading_geometry",
    "bim.loading_finalising",
    "bim.loading_streaming",
    "bim.loading_parsing",
    "bim.loading_navigate_hint",
]

# Per-locale translation table.
# Keep technical terms (3D, MB, GB, BIM) as-is.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "ar": {
        "bim.geometry_load_failed": "تعذّر تحميل هندسة 3D",
        "bim.geometry_retry": "إعادة المحاولة",
        "bim.geometry_dismiss": "إغلاق",
        "bim.geometry_show_diagnostic": "إظهار التشخيص",
        "bim.geometry_copy_diagnostic": "نسخ التشخيص",
        "bim.loading_geometry": "جارٍ تحميل هندسة 3D…",
        "bim.loading_finalising": "جارٍ إنهاء المشهد…",
        "bim.loading_streaming": "جارٍ بثّ الهندسة من الخادم…",
        "bim.loading_parsing": "جارٍ تحليل هندسة 3D — قد يستغرق ذلك 20-60 ثانية للنماذج الكبيرة (>50 MB)؛ لا تُحدِّث الصفحة",
        "bim.loading_navigate_hint": "يمكنك التنقل إلى صفحات أخرى — سيستمر التحميل في الخلفية",
    },
    "bg": {
        "bim.geometry_load_failed": "3D геометрията не може да бъде заредена",
        "bim.geometry_retry": "Опитай отново",
        "bim.geometry_dismiss": "Затвори",
        "bim.geometry_show_diagnostic": "Покажи диагностика",
        "bim.geometry_copy_diagnostic": "Копирай диагностика",
        "bim.loading_geometry": "Зареждане на 3D геометрия…",
        "bim.loading_finalising": "Финализиране на сцената…",
        "bim.loading_streaming": "Стриймване на геометрия от сървъра…",
        "bim.loading_parsing": "Парсване на 3D геометрия — за големи модели (>50 MB) това може да отнеме 20-60 сек; не презареждайте",
        "bim.loading_navigate_hint": "Можете да навигирате до други страници — зареждането ще продължи във фонов режим",
    },
    "cs": {
        "bim.geometry_load_failed": "3D geometrii se nepodařilo načíst",
        "bim.geometry_retry": "Zkusit znovu",
        "bim.geometry_dismiss": "Zavřít",
        "bim.geometry_show_diagnostic": "Zobrazit diagnostiku",
        "bim.geometry_copy_diagnostic": "Kopírovat diagnostiku",
        "bim.loading_geometry": "Načítání 3D geometrie…",
        "bim.loading_finalising": "Dokončování scény…",
        "bim.loading_streaming": "Streamování geometrie ze serveru…",
        "bim.loading_parsing": "Zpracování 3D geometrie — u velkých modelů (>50 MB) to může trvat 20-60 s; neobnovujte stránku",
        "bim.loading_navigate_hint": "Můžete přejít na jiné stránky — načítání bude pokračovat na pozadí",
    },
    "da": {
        "bim.geometry_load_failed": "3D-geometrien kunne ikke indlæses",
        "bim.geometry_retry": "Prøv igen",
        "bim.geometry_dismiss": "Luk",
        "bim.geometry_show_diagnostic": "Vis diagnostik",
        "bim.geometry_copy_diagnostic": "Kopiér diagnostik",
        "bim.loading_geometry": "Indlæser 3D-geometri…",
        "bim.loading_finalising": "Færdiggør scene…",
        "bim.loading_streaming": "Streamer geometri fra serveren…",
        "bim.loading_parsing": "Parser 3D-geometri — for store modeller (>50 MB) kan dette tage 20-60 s; opdater ikke siden",
        "bim.loading_navigate_hint": "Du kan navigere til andre sider — indlæsningen fortsætter i baggrunden",
    },
    "de": {
        "bim.geometry_load_failed": "3D-Geometrie konnte nicht geladen werden",
        "bim.geometry_retry": "Erneut versuchen",
        "bim.geometry_dismiss": "Schließen",
        "bim.geometry_show_diagnostic": "Diagnose anzeigen",
        "bim.geometry_copy_diagnostic": "Diagnose kopieren",
        "bim.loading_geometry": "3D-Geometrie wird geladen…",
        "bim.loading_finalising": "Szene wird fertiggestellt…",
        "bim.loading_streaming": "Geometrie wird vom Server gestreamt…",
        "bim.loading_parsing": "3D-Geometrie wird verarbeitet — bei großen Modellen (>50 MB) kann dies 20-60 s dauern; Seite nicht neu laden",
        "bim.loading_navigate_hint": "Sie können zu anderen Seiten navigieren — das Laden wird im Hintergrund fortgesetzt",
    },
    "es": {
        "bim.geometry_load_failed": "No se pudo cargar la geometría 3D",
        "bim.geometry_retry": "Reintentar",
        "bim.geometry_dismiss": "Descartar",
        "bim.geometry_show_diagnostic": "Mostrar diagnóstico",
        "bim.geometry_copy_diagnostic": "Copiar diagnóstico",
        "bim.loading_geometry": "Cargando geometría 3D…",
        "bim.loading_finalising": "Finalizando escena…",
        "bim.loading_streaming": "Transmitiendo geometría desde el servidor…",
        "bim.loading_parsing": "Procesando geometría 3D — para modelos grandes (>50 MB) puede tardar 20-60 s; no actualice la página",
        "bim.loading_navigate_hint": "Puede navegar a otras páginas — la carga continuará en segundo plano",
    },
    "fi": {
        "bim.geometry_load_failed": "3D-geometriaa ei voitu ladata",
        "bim.geometry_retry": "Yritä uudelleen",
        "bim.geometry_dismiss": "Sulje",
        "bim.geometry_show_diagnostic": "Näytä diagnostiikka",
        "bim.geometry_copy_diagnostic": "Kopioi diagnostiikka",
        "bim.loading_geometry": "Ladataan 3D-geometriaa…",
        "bim.loading_finalising": "Viimeistellään näkymää…",
        "bim.loading_streaming": "Suoratoistetaan geometriaa palvelimelta…",
        "bim.loading_parsing": "Jäsennetään 3D-geometriaa — suurilla malleilla (>50 MB) tämä voi kestää 20-60 s; älä päivitä sivua",
        "bim.loading_navigate_hint": "Voit siirtyä muille sivuille — lataus jatkuu taustalla",
    },
    "fr": {
        "bim.geometry_load_failed": "Impossible de charger la géométrie 3D",
        "bim.geometry_retry": "Réessayer",
        "bim.geometry_dismiss": "Fermer",
        "bim.geometry_show_diagnostic": "Afficher le diagnostic",
        "bim.geometry_copy_diagnostic": "Copier le diagnostic",
        "bim.loading_geometry": "Chargement de la géométrie 3D…",
        "bim.loading_finalising": "Finalisation de la scène…",
        "bim.loading_streaming": "Diffusion de la géométrie depuis le serveur…",
        "bim.loading_parsing": "Analyse de la géométrie 3D — pour les modèles volumineux (>50 MB), cela peut prendre 20-60 s ; ne pas actualiser",
        "bim.loading_navigate_hint": "Vous pouvez naviguer vers d'autres pages — le chargement se poursuivra en arrière-plan",
    },
    "hi": {
        "bim.geometry_load_failed": "3D ज्यामिति लोड नहीं की जा सकी",
        "bim.geometry_retry": "पुनः प्रयास करें",
        "bim.geometry_dismiss": "बंद करें",
        "bim.geometry_show_diagnostic": "डायग्नोस्टिक दिखाएँ",
        "bim.geometry_copy_diagnostic": "डायग्नोस्टिक कॉपी करें",
        "bim.loading_geometry": "3D ज्यामिति लोड हो रही है…",
        "bim.loading_finalising": "दृश्य अंतिम रूप दिया जा रहा है…",
        "bim.loading_streaming": "सर्वर से ज्यामिति स्ट्रीम हो रही है…",
        "bim.loading_parsing": "3D ज्यामिति पार्स की जा रही है — बड़े मॉडल (>50 MB) के लिए इसमें 20-60 सेकंड लग सकते हैं; पेज रिफ्रेश न करें",
        "bim.loading_navigate_hint": "आप अन्य पृष्ठों पर जा सकते हैं — लोडिंग पृष्ठभूमि में जारी रहेगी",
    },
    "hr": {
        "bim.geometry_load_failed": "3D geometriju nije moguće učitati",
        "bim.geometry_retry": "Pokušaj ponovno",
        "bim.geometry_dismiss": "Zatvori",
        "bim.geometry_show_diagnostic": "Prikaži dijagnostiku",
        "bim.geometry_copy_diagnostic": "Kopiraj dijagnostiku",
        "bim.loading_geometry": "Učitavanje 3D geometrije…",
        "bim.loading_finalising": "Završavanje scene…",
        "bim.loading_streaming": "Strujanje geometrije s poslužitelja…",
        "bim.loading_parsing": "Parsiranje 3D geometrije — za velike modele (>50 MB) može potrajati 20-60 s; ne osvježavajte stranicu",
        "bim.loading_navigate_hint": "Možete se kretati po drugim stranicama — učitavanje će se nastaviti u pozadini",
    },
    "id": {
        "bim.geometry_load_failed": "Tidak dapat memuat geometri 3D",
        "bim.geometry_retry": "Coba lagi",
        "bim.geometry_dismiss": "Tutup",
        "bim.geometry_show_diagnostic": "Tampilkan diagnostik",
        "bim.geometry_copy_diagnostic": "Salin diagnostik",
        "bim.loading_geometry": "Memuat geometri 3D…",
        "bim.loading_finalising": "Menyelesaikan adegan…",
        "bim.loading_streaming": "Streaming geometri dari server…",
        "bim.loading_parsing": "Mem-parse geometri 3D — untuk model besar (>50 MB) ini dapat memakan waktu 20-60 detik; jangan refresh",
        "bim.loading_navigate_hint": "Anda dapat berpindah ke halaman lain — pemuatan akan berlanjut di latar belakang",
    },
    "it": {
        "bim.geometry_load_failed": "Impossibile caricare la geometria 3D",
        "bim.geometry_retry": "Riprova",
        "bim.geometry_dismiss": "Chiudi",
        "bim.geometry_show_diagnostic": "Mostra diagnostica",
        "bim.geometry_copy_diagnostic": "Copia diagnostica",
        "bim.loading_geometry": "Caricamento geometria 3D…",
        "bim.loading_finalising": "Finalizzazione scena…",
        "bim.loading_streaming": "Trasmissione geometria dal server…",
        "bim.loading_parsing": "Analisi geometria 3D — per modelli grandi (>50 MB) può richiedere 20-60 s; non aggiornare la pagina",
        "bim.loading_navigate_hint": "Puoi navigare su altre pagine — il caricamento continuerà in background",
    },
    "ja": {
        "bim.geometry_load_failed": "3Dジオメトリを読み込めませんでした",
        "bim.geometry_retry": "再試行",
        "bim.geometry_dismiss": "閉じる",
        "bim.geometry_show_diagnostic": "診断を表示",
        "bim.geometry_copy_diagnostic": "診断をコピー",
        "bim.loading_geometry": "3Dジオメトリを読み込み中…",
        "bim.loading_finalising": "シーンを最終処理中…",
        "bim.loading_streaming": "サーバーからジオメトリをストリーミング中…",
        "bim.loading_parsing": "3Dジオメトリを解析中 — 大きなモデル(>50 MB)では 20〜60 秒かかる場合があります。更新しないでください",
        "bim.loading_navigate_hint": "他のページに移動できます — 読み込みはバックグラウンドで続行されます",
    },
    "ko": {
        "bim.geometry_load_failed": "3D 지오메트리를 로드할 수 없습니다",
        "bim.geometry_retry": "다시 시도",
        "bim.geometry_dismiss": "닫기",
        "bim.geometry_show_diagnostic": "진단 표시",
        "bim.geometry_copy_diagnostic": "진단 복사",
        "bim.loading_geometry": "3D 지오메트리 로드 중…",
        "bim.loading_finalising": "장면 마무리 중…",
        "bim.loading_streaming": "서버에서 지오메트리 스트리밍 중…",
        "bim.loading_parsing": "3D 지오메트리 파싱 중 — 대용량 모델(>50 MB)의 경우 20-60초가 걸릴 수 있습니다. 새로 고치지 마세요",
        "bim.loading_navigate_hint": "다른 페이지로 이동할 수 있습니다 — 로드는 백그라운드에서 계속됩니다",
    },
    "mn": {
        "bim.geometry_load_failed": "3D геометрийг ачаалж чадсангүй",
        "bim.geometry_retry": "Дахин оролдох",
        "bim.geometry_dismiss": "Хаах",
        "bim.geometry_show_diagnostic": "Оношилгоог харуулах",
        "bim.geometry_copy_diagnostic": "Оношилгоог хуулах",
        "bim.loading_geometry": "3D геометр ачаалж байна…",
        "bim.loading_finalising": "Дүр зургийг эцэслэж байна…",
        "bim.loading_streaming": "Серверээс геометрийг дамжуулж байна…",
        "bim.loading_parsing": "3D геометрийг боловсруулж байна — том загваруудын хувьд (>50 MB) 20-60 сек үргэлжилж болно; хуудсыг шинэчилж болохгүй",
        "bim.loading_navigate_hint": "Та бусад хуудас руу шилжиж болно — ачаалал арын дэвсгэрт үргэлжилнэ",
    },
    "nl": {
        "bim.geometry_load_failed": "3D-geometrie kon niet worden geladen",
        "bim.geometry_retry": "Opnieuw proberen",
        "bim.geometry_dismiss": "Sluiten",
        "bim.geometry_show_diagnostic": "Diagnose weergeven",
        "bim.geometry_copy_diagnostic": "Diagnose kopiëren",
        "bim.loading_geometry": "3D-geometrie wordt geladen…",
        "bim.loading_finalising": "Scène afronden…",
        "bim.loading_streaming": "Geometrie streamen vanaf de server…",
        "bim.loading_parsing": "3D-geometrie wordt verwerkt — bij grote modellen (>50 MB) kan dit 20-60 s duren; pagina niet vernieuwen",
        "bim.loading_navigate_hint": "U kunt naar andere pagina's navigeren — het laden gaat op de achtergrond door",
    },
    "no": {
        "bim.geometry_load_failed": "3D-geometrien kunne ikke lastes",
        "bim.geometry_retry": "Prøv igjen",
        "bim.geometry_dismiss": "Lukk",
        "bim.geometry_show_diagnostic": "Vis diagnostikk",
        "bim.geometry_copy_diagnostic": "Kopier diagnostikk",
        "bim.loading_geometry": "Laster inn 3D-geometri…",
        "bim.loading_finalising": "Fullfører scene…",
        "bim.loading_streaming": "Strømmer geometri fra serveren…",
        "bim.loading_parsing": "Tolker 3D-geometri — for store modeller (>50 MB) kan dette ta 20-60 s; ikke oppdater siden",
        "bim.loading_navigate_hint": "Du kan navigere til andre sider — innlasting fortsetter i bakgrunnen",
    },
    "pl": {
        "bim.geometry_load_failed": "Nie można załadować geometrii 3D",
        "bim.geometry_retry": "Spróbuj ponownie",
        "bim.geometry_dismiss": "Zamknij",
        "bim.geometry_show_diagnostic": "Pokaż diagnostykę",
        "bim.geometry_copy_diagnostic": "Kopiuj diagnostykę",
        "bim.loading_geometry": "Ładowanie geometrii 3D…",
        "bim.loading_finalising": "Finalizowanie sceny…",
        "bim.loading_streaming": "Strumieniowanie geometrii z serwera…",
        "bim.loading_parsing": "Parsowanie geometrii 3D — w przypadku dużych modeli (>50 MB) może to potrwać 20-60 s; nie odświeżaj strony",
        "bim.loading_navigate_hint": "Możesz przejść do innych stron — ładowanie będzie kontynuowane w tle",
    },
    "pt": {
        "bim.geometry_load_failed": "Não foi possível carregar a geometria 3D",
        "bim.geometry_retry": "Tentar novamente",
        "bim.geometry_dismiss": "Fechar",
        "bim.geometry_show_diagnostic": "Mostrar diagnóstico",
        "bim.geometry_copy_diagnostic": "Copiar diagnóstico",
        "bim.loading_geometry": "A carregar geometria 3D…",
        "bim.loading_finalising": "A finalizar cena…",
        "bim.loading_streaming": "A transmitir geometria do servidor…",
        "bim.loading_parsing": "A processar geometria 3D — para modelos grandes (>50 MB) pode demorar 20-60 s; não atualize a página",
        "bim.loading_navigate_hint": "Pode navegar para outras páginas — o carregamento continuará em segundo plano",
    },
    "ro": {
        "bim.geometry_load_failed": "Geometria 3D nu a putut fi încărcată",
        "bim.geometry_retry": "Reîncearcă",
        "bim.geometry_dismiss": "Închide",
        "bim.geometry_show_diagnostic": "Afișează diagnosticul",
        "bim.geometry_copy_diagnostic": "Copiază diagnosticul",
        "bim.loading_geometry": "Se încarcă geometria 3D…",
        "bim.loading_finalising": "Se finalizează scena…",
        "bim.loading_streaming": "Se transmite geometria de pe server…",
        "bim.loading_parsing": "Se analizează geometria 3D — pentru modele mari (>50 MB) poate dura 20-60 s; nu reîmprospăta pagina",
        "bim.loading_navigate_hint": "Poți naviga la alte pagini — încărcarea va continua în fundal",
    },
    "ru": {
        "bim.geometry_load_failed": "Не удалось загрузить 3D-геометрию",
        "bim.geometry_retry": "Повторить",
        "bim.geometry_dismiss": "Закрыть",
        "bim.geometry_show_diagnostic": "Показать диагностику",
        "bim.geometry_copy_diagnostic": "Скопировать диагностику",
        "bim.loading_geometry": "Загрузка 3D-геометрии…",
        "bim.loading_finalising": "Завершение сцены…",
        "bim.loading_streaming": "Передача геометрии с сервера…",
        "bim.loading_parsing": "Парсинг 3D-геометрии — для больших моделей (>50 MB) это может занять 20-60 с; не обновляйте страницу",
        "bim.loading_navigate_hint": "Вы можете перейти на другие страницы — загрузка продолжится в фоне",
    },
    "sv": {
        "bim.geometry_load_failed": "Kunde inte ladda 3D-geometri",
        "bim.geometry_retry": "Försök igen",
        "bim.geometry_dismiss": "Stäng",
        "bim.geometry_show_diagnostic": "Visa diagnostik",
        "bim.geometry_copy_diagnostic": "Kopiera diagnostik",
        "bim.loading_geometry": "Laddar 3D-geometri…",
        "bim.loading_finalising": "Slutför scen…",
        "bim.loading_streaming": "Strömmar geometri från servern…",
        "bim.loading_parsing": "Tolkar 3D-geometri — för stora modeller (>50 MB) kan detta ta 20-60 s; uppdatera inte sidan",
        "bim.loading_navigate_hint": "Du kan navigera till andra sidor — inläsningen fortsätter i bakgrunden",
    },
    "th": {
        "bim.geometry_load_failed": "ไม่สามารถโหลดเรขาคณิต 3D",
        "bim.geometry_retry": "ลองอีกครั้ง",
        "bim.geometry_dismiss": "ปิด",
        "bim.geometry_show_diagnostic": "แสดงการวินิจฉัย",
        "bim.geometry_copy_diagnostic": "คัดลอกการวินิจฉัย",
        "bim.loading_geometry": "กำลังโหลดเรขาคณิต 3D…",
        "bim.loading_finalising": "กำลังจัดทำฉากให้เสร็จสมบูรณ์…",
        "bim.loading_streaming": "กำลังสตรีมเรขาคณิตจากเซิร์ฟเวอร์…",
        "bim.loading_parsing": "กำลังวิเคราะห์เรขาคณิต 3D — สำหรับโมเดลขนาดใหญ่ (>50 MB) อาจใช้เวลา 20-60 วินาที ห้ามรีเฟรชหน้า",
        "bim.loading_navigate_hint": "คุณสามารถไปยังหน้าอื่นได้ — การโหลดจะดำเนินต่อในเบื้องหลัง",
    },
    "tr": {
        "bim.geometry_load_failed": "3D geometri yüklenemedi",
        "bim.geometry_retry": "Tekrar dene",
        "bim.geometry_dismiss": "Kapat",
        "bim.geometry_show_diagnostic": "Tanılamayı göster",
        "bim.geometry_copy_diagnostic": "Tanılamayı kopyala",
        "bim.loading_geometry": "3D geometri yükleniyor…",
        "bim.loading_finalising": "Sahne sonlandırılıyor…",
        "bim.loading_streaming": "Geometri sunucudan akıtılıyor…",
        "bim.loading_parsing": "3D geometri ayrıştırılıyor — büyük modeller (>50 MB) için 20-60 sn sürebilir; sayfayı yenilemeyin",
        "bim.loading_navigate_hint": "Diğer sayfalara gidebilirsiniz — yükleme arka planda devam edecek",
    },
    "vi": {
        "bim.geometry_load_failed": "Không thể tải hình học 3D",
        "bim.geometry_retry": "Thử lại",
        "bim.geometry_dismiss": "Đóng",
        "bim.geometry_show_diagnostic": "Hiển thị chẩn đoán",
        "bim.geometry_copy_diagnostic": "Sao chép chẩn đoán",
        "bim.loading_geometry": "Đang tải hình học 3D…",
        "bim.loading_finalising": "Đang hoàn tất cảnh…",
        "bim.loading_streaming": "Đang truyền hình học từ máy chủ…",
        "bim.loading_parsing": "Đang phân tích hình học 3D — với mô hình lớn (>50 MB) có thể mất 20-60 giây; đừng làm mới trang",
        "bim.loading_navigate_hint": "Bạn có thể chuyển sang các trang khác — quá trình tải sẽ tiếp tục ở chế độ nền",
    },
    "zh": {
        "bim.geometry_load_failed": "无法加载 3D 几何体",
        "bim.geometry_retry": "重试",
        "bim.geometry_dismiss": "关闭",
        "bim.geometry_show_diagnostic": "显示诊断信息",
        "bim.geometry_copy_diagnostic": "复制诊断信息",
        "bim.loading_geometry": "正在加载 3D 几何体…",
        "bim.loading_finalising": "正在完成场景…",
        "bim.loading_streaming": "正在从服务器流式传输几何体…",
        "bim.loading_parsing": "正在解析 3D 几何体 — 大型模型 (>50 MB) 可能需要 20-60 秒；请勿刷新页面",
        "bim.loading_navigate_hint": "您可以浏览其他页面 — 加载将在后台继续",
    },
}


def _escape_value(value: str) -> str:
    """‌⁠‍Escape value for TS double-quoted string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def patch_locale(path: Path, translations: dict[str, str]) -> bool:
    """‌⁠‍Idempotently insert/replace the 10 keys into `path`.

    Returns True if file was modified.
    """
    # Read preserving line endings: Path.read_text has no newline= and would
    # translate CRLF to LF, which turns a one-key edit into a whole-file diff.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    original = text

    # Step 1: remove any existing occurrences of the 10 keys (replace mode)
    for key in KEY_ORDER:
        # Match a full line that defines this key, including trailing newline.
        # Format we expect: <indent>"key": "value",\n  (or without trailing comma)
        pattern = re.compile(
            r'^[ \t]*"' + re.escape(key) + r'"\s*:\s*"(?:\\.|[^"\\])*"[ \t]*,?[ \t]*\r?\n',
            re.MULTILINE,
        )
        text = pattern.sub("", text)

    # Step 2: locate the `bim.no_elements` anchor line
    anchor_pat = re.compile(
        r'^([ \t]*)"bim\.no_elements"\s*:\s*"(?:\\.|[^"\\])*"[ \t]*,?[ \t]*\r?\n',
        re.MULTILINE,
    )
    m = anchor_pat.search(text)
    if not m:
        raise RuntimeError(f"Anchor 'bim.no_elements' not found in {path.name}")

    indent = m.group(1)
    insert_at = m.end()

    # Step 3: build the block of 10 new lines
    lines = []
    for key in KEY_ORDER:
        value = translations[key]
        lines.append(f'{indent}"{key}": "{_escape_value(value)}",{eol}')
    block = "".join(lines)

    text = text[:insert_at] + block + text[insert_at:]

    if text != original:
        path.write_text(text, encoding="utf-8", newline="")
        return True
    return False


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    locales_dir = repo_root / "frontend" / "src" / "app" / "locales"
    if not locales_dir.is_dir():
        print(f"ERROR: locales directory not found: {locales_dir}", file=sys.stderr)
        return 1

    expected = {
        "ar",
        "bg",
        "cs",
        "da",
        "de",
        "es",
        "fi",
        "fr",
        "hi",
        "hr",
        "id",
        "it",
        "ja",
        "ko",
        "mn",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sv",
        "th",
        "tr",
        "vi",
        "zh",
    }
    missing = expected - set(TRANSLATIONS)
    if missing:
        print(f"ERROR: translations missing for: {sorted(missing)}", file=sys.stderr)
        return 1

    touched = 0
    for code in sorted(expected):
        path = locales_dir / f"{code}.ts"
        if not path.is_file():
            print(f"WARN: locale file missing: {path}", file=sys.stderr)
            continue
        changed = patch_locale(path, TRANSLATIONS[code])
        status = "patched" if changed else "no-op"
        print(f"  {code}: {status}")
        if changed:
            touched += 1

    print(f"\nDone. {touched}/{len(expected)} locales modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
