"""Shared ISO constants for internationalization.

Reference data for measurement systems, paper sizes, date/number formats,
region groupings, and per-country defaults.  Used throughout the backend
(project settings, report generation, export formatting) and exposed to the
frontend via the ``/api/v1/i18n/`` endpoints.

All dictionaries are plain Python literals — no database dependency, no I/O.
Import freely from any module.
"""

__all__ = [
    "COUNTRY_DEFAULTS",
    "DATE_FORMATS",
    "MEASUREMENT_SYSTEMS",
    "NUMBER_FORMATS",
    "PAPER_SIZES",
    "REGION_GROUPS",
]

# ---------------------------------------------------------------------------
# Measurement systems
# ---------------------------------------------------------------------------

MEASUREMENT_SYSTEMS: dict[str, dict[str, str]] = {
    "metric": {
        "name": "Metric",
        "length": "m",
        "area": "m\u00b2",
        "volume": "m\u00b3",
        "weight": "kg",
    },
    "imperial": {
        "name": "Imperial",
        "length": "ft",
        "area": "sq ft",
        "volume": "cu ft",
        "weight": "lb",
    },
}

# ---------------------------------------------------------------------------
# Standard paper sizes (ISO 216 + North American)
# ---------------------------------------------------------------------------

PAPER_SIZES: dict[str, dict[str, str | int]] = {
    "A0": {"width_mm": 841, "height_mm": 1189, "name": "A0"},
    "A1": {"width_mm": 594, "height_mm": 841, "name": "A1"},
    "A2": {"width_mm": 420, "height_mm": 594, "name": "A2"},
    "A3": {"width_mm": 297, "height_mm": 420, "name": "A3"},
    "A4": {"width_mm": 210, "height_mm": 297, "name": "A4"},
    "Letter": {"width_mm": 216, "height_mm": 279, "name": "US Letter"},
    "Legal": {"width_mm": 216, "height_mm": 356, "name": "US Legal"},
    "Tabloid": {"width_mm": 279, "height_mm": 432, "name": "US Tabloid"},
}

# ---------------------------------------------------------------------------
# Date format patterns
# ---------------------------------------------------------------------------

DATE_FORMATS: dict[str, dict[str, str | list[str]]] = {
    "DD.MM.YYYY": {"example": "07.04.2026", "regions": ["DACH", "RU"]},
    "MM/DD/YYYY": {"example": "04/07/2026", "regions": ["US"]},
    "DD/MM/YYYY": {"example": "07/04/2026", "regions": ["UK", "EU", "LATAM"]},
    "YYYY-MM-DD": {"example": "2026-04-07", "regions": ["ISO"]},
    "YYYY/MM/DD": {"example": "2026/04/07", "regions": ["JP", "KR", "CN"]},
}

# ---------------------------------------------------------------------------
# Number format patterns
# ---------------------------------------------------------------------------

NUMBER_FORMATS: dict[str, dict[str, str | list[str]]] = {
    "1,234.56": {
        "decimal": ".",
        "thousands": ",",
        "regions": ["US", "UK", "JP", "KR", "CN"],
    },
    "1.234,56": {
        "decimal": ",",
        "thousands": ".",
        "regions": ["DACH", "EU", "LATAM"],
    },
    "1 234,56": {
        "decimal": ",",
        "thousands": " ",
        "regions": ["RU", "FR"],
    },
}

# ---------------------------------------------------------------------------
# Region groups — map marketing regions to ISO 3166-1 alpha-2 country codes
# ---------------------------------------------------------------------------

REGION_GROUPS: dict[str, list[str]] = {
    "DACH": ["DE", "AT", "CH"],
    "EU": [
        "FR", "ES", "IT", "NL", "BE", "PT", "GR", "PL", "CZ", "RO",
        "HU", "SE", "DK", "FI", "NO", "IE", "BG", "HR", "SK", "SI",
        "LT", "LV", "EE",
    ],
    "UK": ["GB"],
    "NA": ["US", "CA"],
    "LATAM": ["MX", "BR", "AR", "CL", "CO", "PE"],
    "MENA": ["SA", "AE", "QA", "KW", "EG", "IL", "TR"],
    "APAC": ["AU", "JP", "NZ", "KR", "CN", "SG", "IN", "MY", "TH"],
    "RU": ["RU"],
}

# ---------------------------------------------------------------------------
# Per-country defaults (30 most relevant countries for construction ERP)
# ---------------------------------------------------------------------------

COUNTRY_DEFAULTS: dict[str, dict[str, str]] = {
    # DACH ----------------------------------------------------------------
    "DE": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "de",
    },
    "AT": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "de",
    },
    "CH": {
        "currency": "CHF",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "de",
    },
    # UK / Ireland --------------------------------------------------------
    "GB": {
        "currency": "GBP",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "en",
    },
    "IE": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "en",
    },
    # North America -------------------------------------------------------
    "US": {
        "currency": "USD",
        "measurement": "imperial",
        "paper": "Letter",
        "date_format": "MM/DD/YYYY",
        "number_format": "1,234.56",
        "locale": "en",
    },
    "CA": {
        "currency": "CAD",
        "measurement": "metric",
        "paper": "Letter",
        "date_format": "YYYY-MM-DD",
        "number_format": "1,234.56",
        "locale": "en",
    },
    # Western Europe ------------------------------------------------------
    "FR": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1 234,56",
        "locale": "fr",
    },
    "ES": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1.234,56",
        "locale": "es",
    },
    "IT": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1.234,56",
        "locale": "it",
    },
    "NL": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD-MM-YYYY",
        "number_format": "1.234,56",
        "locale": "nl",
    },
    "BE": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1.234,56",
        "locale": "nl",
    },
    "PT": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1.234,56",
        "locale": "pt",
    },
    # Nordics -------------------------------------------------------------
    "SE": {
        "currency": "SEK",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "YYYY-MM-DD",
        "number_format": "1.234,56",
        "locale": "sv",
    },
    "NO": {
        "currency": "NOK",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "no",
    },
    "DK": {
        "currency": "DKK",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "da",
    },
    "FI": {
        "currency": "EUR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "fi",
    },
    # Central / Eastern Europe --------------------------------------------
    "PL": {
        "currency": "PLN",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "pl",
    },
    "CZ": {
        "currency": "CZK",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "cs",
    },
    "RU": {
        "currency": "RUB",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1 234,56",
        "locale": "ru",
    },
    # Middle East / Turkey ------------------------------------------------
    "TR": {
        "currency": "TRY",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD.MM.YYYY",
        "number_format": "1.234,56",
        "locale": "tr",
    },
    "AE": {
        "currency": "AED",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "ar",
    },
    "SA": {
        "currency": "SAR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "ar",
    },
    "QA": {
        "currency": "QAR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "ar",
    },
    # Asia-Pacific --------------------------------------------------------
    "AU": {
        "currency": "AUD",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "en",
    },
    "NZ": {
        "currency": "NZD",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "en",
    },
    "JP": {
        "currency": "JPY",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "YYYY/MM/DD",
        "number_format": "1,234.56",
        "locale": "ja",
    },
    "KR": {
        "currency": "KRW",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "YYYY/MM/DD",
        "number_format": "1,234.56",
        "locale": "ko",
    },
    "CN": {
        "currency": "CNY",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "YYYY/MM/DD",
        "number_format": "1,234.56",
        "locale": "zh",
    },
    "IN": {
        "currency": "INR",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "hi",
    },
    # Latin America -------------------------------------------------------
    "BR": {
        "currency": "BRL",
        "measurement": "metric",
        "paper": "A4",
        "date_format": "DD/MM/YYYY",
        "number_format": "1.234,56",
        "locale": "pt",
    },
    "MX": {
        "currency": "MXN",
        "measurement": "metric",
        "paper": "Letter",
        "date_format": "DD/MM/YYYY",
        "number_format": "1,234.56",
        "locale": "es",
    },
}
