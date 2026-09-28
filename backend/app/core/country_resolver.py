# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resolve a free-text country name to an ISO 3166-1 alpha-2 code.

Best-effort, no external dependencies. When a user types "Deutschland"
instead of selecting from an autocomplete, the project's ``country_code``
stays null and every downstream consumer (compliance packs, markup
region, working calendar, VAT) answers "no opinion" for a project whose
country was stated plainly. This module closes that gap.

The mapping covers English names, German names, native endonyms and
common abbreviations. It is intentionally static so it imports without
a database and without any third-party package.
"""

from __future__ import annotations

# Name/abbreviation -> ISO 3166-1 alpha-2 (uppercase).
# Keys are written in their natural case for readability; the actual lookup
# dict ``_LOOKUP`` is derived at module load time by lowering every key.
# Grouped by language block for maintainability. Duplicates across blocks
# are fine; they all map to the same code.
_RAW_NAME_TO_CODE: dict[str, str] = {
    # ── English names (ISO 3166 short names + common variants) ──────────
    "afghanistan": "AF",
    "albania": "AL",
    "algeria": "DZ",
    "andorra": "AD",
    "angola": "AO",
    "argentina": "AR",
    "armenia": "AM",
    "australia": "AU",
    "austria": "AT",
    "azerbaijan": "AZ",
    "bahrain": "BH",
    "bangladesh": "BD",
    "belarus": "BY",
    "belgium": "BE",
    "benin": "BJ",
    "bhutan": "BT",
    "bolivia": "BO",
    "bosnia and herzegovina": "BA",
    "botswana": "BW",
    "brazil": "BR",
    "brunei": "BN",
    "bulgaria": "BG",
    "burkina faso": "BF",
    "burundi": "BI",
    "cambodia": "KH",
    "cameroon": "CM",
    "canada": "CA",
    "central african republic": "CF",
    "chad": "TD",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "congo": "CG",
    "costa rica": "CR",
    "croatia": "HR",
    "cuba": "CU",
    "cyprus": "CY",
    "czech republic": "CZ",
    "czechia": "CZ",
    "democratic republic of the congo": "CD",
    "denmark": "DK",
    "dominican republic": "DO",
    "ecuador": "EC",
    "egypt": "EG",
    "el salvador": "SV",
    "estonia": "EE",
    "ethiopia": "ET",
    "fiji": "FJ",
    "finland": "FI",
    "france": "FR",
    "gabon": "GA",
    "gambia": "GM",
    "georgia": "GE",
    "germany": "DE",
    "ghana": "GH",
    "greece": "GR",
    "guatemala": "GT",
    "guinea": "GN",
    "haiti": "HT",
    "honduras": "HN",
    "hungary": "HU",
    "iceland": "IS",
    "india": "IN",
    "indonesia": "ID",
    "iran": "IR",
    "iraq": "IQ",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "ivory coast": "CI",
    "jamaica": "JM",
    "japan": "JP",
    "jordan": "JO",
    "kazakhstan": "KZ",
    "kenya": "KE",
    "kuwait": "KW",
    "kyrgyzstan": "KG",
    "laos": "LA",
    "latvia": "LV",
    "lebanon": "LB",
    "libya": "LY",
    "liechtenstein": "LI",
    "lithuania": "LT",
    "luxembourg": "LU",
    "madagascar": "MG",
    "malawi": "MW",
    "malaysia": "MY",
    "mali": "ML",
    "malta": "MT",
    "mauritius": "MU",
    "mexico": "MX",
    "moldova": "MD",
    "monaco": "MC",
    "mongolia": "MN",
    "montenegro": "ME",
    "morocco": "MA",
    "mozambique": "MZ",
    "myanmar": "MM",
    "namibia": "NA",
    "nepal": "NP",
    "netherlands": "NL",
    "new zealand": "NZ",
    "nicaragua": "NI",
    "niger": "NE",
    "nigeria": "NG",
    "north korea": "KP",
    "north macedonia": "MK",
    "norway": "NO",
    "oman": "OM",
    "pakistan": "PK",
    "panama": "PA",
    "papua new guinea": "PG",
    "paraguay": "PY",
    "peru": "PE",
    "philippines": "PH",
    "poland": "PL",
    "portugal": "PT",
    "qatar": "QA",
    "romania": "RO",
    "russia": "RU",
    "rwanda": "RW",
    "saudi arabia": "SA",
    "senegal": "SN",
    "serbia": "RS",
    "sierra leone": "SL",
    "singapore": "SG",
    "slovakia": "SK",
    "slovenia": "SI",
    "somalia": "SO",
    "south africa": "ZA",
    "south korea": "KR",
    "spain": "ES",
    "sri lanka": "LK",
    "sudan": "SD",
    "sweden": "SE",
    "switzerland": "CH",
    "syria": "SY",
    "taiwan": "TW",
    "tajikistan": "TJ",
    "tanzania": "TZ",
    "thailand": "TH",
    "togo": "TG",
    "trinidad and tobago": "TT",
    "tunisia": "TN",
    "turkey": "TR",
    "turkmenistan": "TM",
    "uganda": "UG",
    "ukraine": "UA",
    "united arab emirates": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "united states of america": "US",
    "uruguay": "UY",
    "uzbekistan": "UZ",
    "venezuela": "VE",
    "vietnam": "VN",
    "yemen": "YE",
    "zambia": "ZM",
    "zimbabwe": "ZW",
    # ── Common abbreviations ────────────────────────────────────────────
    "usa": "US",
    "us": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "uk": "GB",
    "u.k.": "GB",
    "uae": "AE",
    "u.a.e.": "AE",
    "rsa": "ZA",
    "ksa": "SA",
    "drc": "CD",
    "prc": "CN",
    # ── German names ────────────────────────────────────────────────────
    "deutschland": "DE",
    "frankreich": "FR",
    "italien": "IT",
    "spanien": "ES",
    "grossbritannien": "GB",
    "vereinigtes koenigreich": "GB",
    "vereinigtes konigreich": "GB",
    "niederlande": "NL",
    "belgien": "BE",
    "schweiz": "CH",
    "oesterreich": "AT",
    "osterreich": "AT",
    "schweden": "SE",
    "norwegen": "NO",
    "daenemark": "DK",
    "danemark": "DK",
    "finnland": "FI",
    "polen": "PL",
    "tschechien": "CZ",
    "tschechische republik": "CZ",
    "ungarn": "HU",
    "rumaenien": "RO",
    "rumanien": "RO",
    "bulgarien": "BG",
    "griechenland": "GR",
    "tuerkei": "TR",
    "turkei": "TR",
    "russland": "RU",
    "indien": "IN",
    "brasilien": "BR",
    "mexiko": "MX",
    "kanada": "CA",
    "suedafrika": "ZA",
    "sudafrika": "ZA",
    "aegypten": "EG",
    "agypten": "EG",
    # "china" and "japan" already in English block
    "vereinigte staaten": "US",
    "vereinigte staaten von amerika": "US",
    "vereinigte arabische emirate": "AE",
    "irland": "IE",
    # "portugal" already in English block
    "kroatien": "HR",
    "serbien": "RS",
    "slowenien": "SI",
    "slowakei": "SK",
    "litauen": "LT",
    "lettland": "LV",
    "estland": "EE",
    "luxemburg": "LU",
    "island": "IS",
    "neuseeland": "NZ",
    "australien": "AU",
    "argentinien": "AR",
    "kolumbien": "CO",
    # "nigeria" already in English block
    "kenia": "KE",
    "saudi-arabien": "SA",
    # ── Native endonyms (local names) ───────────────────────────────────
    "brasil": "BR",
    "espana": "ES",
    "italia": "IT",
    "nederland": "NL",
    "norge": "NO",
    "sverige": "SE",
    "suomi": "FI",
    "polska": "PL",
    "cesko": "CZ",
    "ceska republika": "CZ",
    "magyarorszag": "HU",
    "hrvatska": "HR",
    "slovensko": "SK",
    "slovenija": "SI",
    "lietuva": "LT",
    "latvija": "LV",
    "eesti": "EE",
    "ellas": "GR",
    "ellada": "GR",
    "shqiperia": "AL",
    "crna gora": "ME",
    "srbija": "RS",
    "bosna i hercegovina": "BA",
    # "romania" already in English block
    "balgariya": "BG",
    "sakartvelo": "GE",
    "hayastan": "AM",
    "nippon": "JP",
    "nihon": "JP",
    "bharat": "IN",
    "zhongguo": "CN",
    "hanguk": "KR",
    "pilipinas": "PH",
    "muang thai": "TH",
    "prathet thai": "TH",
    "viet nam": "VN",
    # "indonesia" and "sri lanka" already in English block
    "misr": "EG",
    "al-jazair": "DZ",
    "al-maghrib": "MA",
    "lubnan": "LB",
    "al-urdun": "JO",
    "al-iraq": "IQ",
    "turkiye": "TR",
    # ── Russian names ───────────────────────────────────────────────────
    "\u0413\u0435\u0440\u043c\u0430\u043d\u0438\u044f": "DE",  # Германия
    "\u0424\u0440\u0430\u043d\u0446\u0438\u044f": "FR",  # Франция
    "\u0418\u0442\u0430\u043b\u0438\u044f": "IT",  # Италия
    "\u0418\u0441\u043f\u0430\u043d\u0438\u044f": "ES",  # Испания
    "\u0412\u0435\u043b\u0438\u043a\u043e\u0431\u0440\u0438\u0442\u0430\u043d\u0438\u044f": "GB",  # Великобритания
    "\u0420\u043e\u0441\u0441\u0438\u044f": "RU",  # Россия
    "\u041a\u0438\u0442\u0430\u0439": "CN",  # Китай
    "\u042f\u043f\u043e\u043d\u0438\u044f": "JP",  # Япония
    "\u0418\u043d\u0434\u0438\u044f": "IN",  # Индия
    "\u0411\u0440\u0430\u0437\u0438\u043b\u0438\u044f": "BR",  # Бразилия
    "\u041a\u0430\u043d\u0430\u0434\u0430": "CA",  # Канада
    "\u0410\u0432\u0441\u0442\u0440\u0430\u043b\u0438\u044f": "AU",  # Австралия
    "\u0410\u0432\u0441\u0442\u0440\u0438\u044f": "AT",  # Австрия
    "\u0428\u0432\u0435\u0439\u0446\u0430\u0440\u0438\u044f": "CH",  # Швейцария
    "\u041d\u0438\u0434\u0435\u0440\u043b\u0430\u043d\u0434\u044b": "NL",  # Нидерланды
    "\u041f\u043e\u043b\u044c\u0448\u0430": "PL",  # Польша
    "\u0421\u0428\u0410": "US",  # США
    "\u0423\u043a\u0440\u0430\u0438\u043d\u0430": "UA",  # Украина
    "\u041c\u0435\u043a\u0441\u0438\u043a\u0430": "MX",  # Мексика
    "\u0422\u0443\u0440\u0446\u0438\u044f": "TR",  # Турция
    "\u042e\u0436\u043d\u0430\u044f \u041a\u043e\u0440\u0435\u044f": "KR",  # Южная Корея
    "\u0421\u0430\u0443\u0434\u043e\u0432\u0441\u043a\u0430\u044f \u0410\u0440\u0430\u0432\u0438\u044f": "SA",  # Саудовская Аравия
    "\u041e\u0410\u042d": "AE",  # ОАЭ
    "\u0415\u0433\u0438\u043f\u0435\u0442": "EG",  # Египет
    "\u041d\u0438\u0433\u0435\u0440\u0438\u044f": "NG",  # Нигерия
    "\u0411\u043e\u043b\u0433\u0430\u0440\u0438\u044f": "BG",  # Болгария
    "\u0412\u0435\u043d\u0433\u0440\u0438\u044f": "HU",  # Венгрия
    "\u0420\u0443\u043c\u044b\u043d\u0438\u044f": "RO",  # Румыния
    "\u0413\u0440\u0435\u0446\u0438\u044f": "GR",  # Греция
    "\u0427\u0435\u0445\u0438\u044f": "CZ",  # Чехия
    "\u0421\u043b\u043e\u0432\u0430\u043a\u0438\u044f": "SK",  # Словакия
    "\u0421\u043b\u043e\u0432\u0435\u043d\u0438\u044f": "SI",  # Словения
    "\u0425\u043e\u0440\u0432\u0430\u0442\u0438\u044f": "HR",  # Хорватия
    "\u0421\u0435\u0440\u0431\u0438\u044f": "RS",  # Сербия
    # ── Chinese names ───────────────────────────────────────────────────
    "\u5fb7\u56fd": "DE",  # 德国
    "\u6cd5\u56fd": "FR",  # 法国
    "\u82f1\u56fd": "GB",  # 英国
    "\u7f8e\u56fd": "US",  # 美国
    "\u4e2d\u56fd": "CN",  # 中国
    "\u65e5\u672c": "JP",  # 日本
    "\u97e9\u56fd": "KR",  # 韩国
    "\u5370\u5ea6": "IN",  # 印度
    "\u5df4\u897f": "BR",  # 巴西
    "\u52a0\u62ff\u5927": "CA",  # 加拿大
    "\u6fb3\u5927\u5229\u4e9a": "AU",  # 澳大利亚
    "\u4fc4\u7f57\u65af": "RU",  # 俄罗斯
    "\u610f\u5927\u5229": "IT",  # 意大利
    "\u897f\u73ed\u7259": "ES",  # 西班牙
    "\u58a8\u897f\u54e5": "MX",  # 墨西哥
    "\u571f\u8033\u5176": "TR",  # 土耳其
    "\u57c3\u53ca": "EG",  # 埃及
    "\u5357\u975e": "ZA",  # 南非
    "\u6cf0\u56fd": "TH",  # 泰国
    "\u8d8a\u5357": "VN",  # 越南
    "\u9a6c\u6765\u897f\u4e9a": "MY",  # 马来西亚
    "\u5370\u5ea6\u5c3c\u897f\u4e9a": "ID",  # 印度尼西亚
    "\u83f2\u5f8b\u5bbe": "PH",  # 菲律宾
    # ── Arabic names ────────────────────────────────────────────────────
    "\u0623\u0644\u0645\u0627\u0646\u064a\u0627": "DE",  # ألمانيا
    "\u0641\u0631\u0646\u0633\u0627": "FR",  # فرنسا
    "\u0628\u0631\u064a\u0637\u0627\u0646\u064a\u0627": "GB",  # بريطانيا
    "\u0627\u0644\u0648\u0644\u0627\u064a\u0627\u062a \u0627\u0644\u0645\u062a\u062d\u062f\u0629": "US",  # الولايات المتحدة
    "\u0627\u0644\u0635\u064a\u0646": "CN",  # الصين
    "\u0627\u0644\u0647\u0646\u062f": "IN",  # الهند
    "\u0627\u0644\u0628\u0631\u0627\u0632\u064a\u0644": "BR",  # البرازيل
    "\u0645\u0635\u0631": "EG",  # مصر
    "\u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629": "SA",  # السعودية
    "\u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062a": "AE",  # الإمارات
    "\u0627\u0644\u0639\u0631\u0627\u0642": "IQ",  # العراق
    "\u0627\u0644\u0623\u0631\u062f\u0646": "JO",  # الأردن
    "\u0644\u0628\u0646\u0627\u0646": "LB",  # لبنان
    "\u0627\u0644\u0645\u063a\u0631\u0628": "MA",  # المغرب
    "\u062a\u0648\u0646\u0633": "TN",  # تونس
    "\u0627\u0644\u062c\u0632\u0627\u0626\u0631": "DZ",  # الجزائر
    "\u0646\u064a\u062c\u064a\u0631\u064a\u0627": "NG",  # نيجيريا
    "\u062a\u0631\u0643\u064a\u0627": "TR",  # تركيا
    # ── Portuguese names ────────────────────────────────────────────────
    "alemanha": "DE",
    "franca": "FR",
    "estados unidos": "US",
    "reino unido": "GB",
    "espanha": "ES",
    # ── French names ────────────────────────────────────────────────────
    "allemagne": "DE",
    "angleterre": "GB",
    "royaume-uni": "GB",
    "etats-unis": "US",
    "pays-bas": "NL",
    "suisse": "CH",
    "autriche": "AT",
    "espagne": "ES",
    "italie": "IT",
    "grece": "GR",
    "inde": "IN",
    "bresil": "BR",
    "chine": "CN",
    "japon": "JP",
    "coree du sud": "KR",
    "turquie": "TR",
    "egypte": "EG",
    "afrique du sud": "ZA",
    # ── Hindi (transliterated) ──────────────────────────────────────────
    "\u092d\u093e\u0930\u0924": "IN",  # भारत
    "\u091c\u0930\u094d\u092e\u0928\u0940": "DE",  # जर्मनी
    "\u0905\u092e\u0947\u0930\u093f\u0915\u093e": "US",  # अमेरिका
    "\u091a\u0940\u0928": "CN",  # चीन
    "\u091c\u093e\u092a\u093e\u0928": "JP",  # जापान
    "\u0930\u0942\u0938": "RU",  # रूस
    # ── Korean names ────────────────────────────────────────────────────
    "\ub3c5\uc77c": "DE",  # 독일
    "\ud504\ub791\uc2a4": "FR",  # 프랑스
    "\uc601\uad6d": "GB",  # 영국
    "\ubbf8\uad6d": "US",  # 미국
    "\uc911\uad6d": "CN",  # 중국
    "\uc77c\ubcf8": "JP",  # 일본
    "\ud55c\uad6d": "KR",  # 한국
    "\uc778\ub3c4": "IN",  # 인도
    "\ube0c\ub77c\uc9c8": "BR",  # 브라질
    "\uce90\ub098\ub2e4": "CA",  # 캐나다
    "\ud638\uc8fc": "AU",  # 호주
    "\ub7ec\uc2dc\uc544": "RU",  # 러시아
    # ── Japanese names ──────────────────────────────────────────────────
    "\u30c9\u30a4\u30c4": "DE",  # ドイツ
    "\u30d5\u30e9\u30f3\u30b9": "FR",  # フランス
    "\u30a4\u30ae\u30ea\u30b9": "GB",  # イギリス
    "\u30a2\u30e1\u30ea\u30ab": "US",  # アメリカ
    "\u30a4\u30bf\u30ea\u30a2": "IT",  # イタリア
    "\u30b9\u30da\u30a4\u30f3": "ES",  # スペイン
    "\u30ed\u30b7\u30a2": "RU",  # ロシア
    "\u30a4\u30f3\u30c9": "IN",  # インド
    "\u30d6\u30e9\u30b8\u30eb": "BR",  # ブラジル
    "\u30ab\u30ca\u30c0": "CA",  # カナダ
    "\u30aa\u30fc\u30b9\u30c8\u30e9\u30ea\u30a2": "AU",  # オーストラリア
    "\u30e1\u30ad\u30b7\u30b3": "MX",  # メキシコ
    "\u30c8\u30eb\u30b3": "TR",  # トルコ
    "\u30a8\u30b8\u30d7\u30c8": "EG",  # エジプト
}

# Lowercase all keys once at import time so the lookup is O(1) and
# case-insensitive for every script (Latin, Cyrillic, CJK, Arabic, etc.).
_LOOKUP: dict[str, str] = {k.lower(): v for k, v in _RAW_NAME_TO_CODE.items()}


def resolve_country_code(name: str) -> str | None:
    """Best-effort resolution of a free-text country name to ISO 3166-1 alpha-2.

    Case-insensitive exact match against a static mapping of English,
    German, French, Portuguese, Russian, Chinese, Arabic, Hindi, Korean
    and Japanese country names plus common abbreviations.

    Args:
        name: The country name as typed by the user, e.g. "Deutschland",
            "Germany", "USA", or a native-script name.

    Returns:
        Two-letter uppercase ISO 3166-1 alpha-2 code, or ``None`` when
        the name could not be resolved. Never raises.
    """
    if not name:
        return None
    key = name.strip().lower()
    if not key:
        return None
    return _LOOKUP.get(key)


def known_country_codes() -> frozenset[str]:
    """Every ISO 3166-1 alpha-2 code this resolver can produce."""
    return frozenset(_RAW_NAME_TO_CODE.values())
