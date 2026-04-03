"""Marketplace registry — static catalog of installable OpenEstimate modules.

Provides a browsable catalog of add-ons: cost databases, vector indices,
language packs, CAD converters, analytics, and integrations. Each entry
carries metadata for the frontend marketplace UI.

The ``installed`` field is computed at runtime by checking which modules
the :class:`~app.core.module_loader.ModuleLoader` has already loaded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.module_loader import module_loader

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketplaceModule:
    """Metadata for a single marketplace entry."""

    id: str  # e.g. "cwicr-de-berlin"
    name: str  # "CWICR Germany (Berlin)"
    description: str  # Detailed blurb
    category: str  # cost_database | vector_index | language | converter | analytics | integration
    icon: str  # lucide-react icon name
    version: str  # SemVer
    size_mb: float  # Estimated download size
    author: str  # Publisher
    tags: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)  # Module dependencies
    price: str = "Free"  # "Free" | "Pro" | "$9.99/mo"

    def to_dict(self, *, installed: bool, coming_soon: bool = False) -> dict:
        """Serialize to a JSON-friendly dict with runtime ``installed`` flag."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "version": self.version,
            "size_mb": self.size_mb,
            "author": self.author,
            "tags": list(self.tags),
            "requires": list(self.requires),
            "installed": installed,
            "price": self.price,
            "coming_soon": coming_soon,
        }


# ---------------------------------------------------------------------------
# Registry — all available marketplace modules
# ---------------------------------------------------------------------------

_DDC = "Data Driven Construction"
_OE = "OpenEstimate Core Team"

MARKETPLACE_MODULES: list[MarketplaceModule] = [
    # ── Cost Databases (11) ──────────────────────────────────────────────
    MarketplaceModule(
        id="cwicr-usa-usd",
        name="CWICR United States (USD)",
        description="55,719 construction cost items covering all CSI MasterFormat divisions. US national average rates in USD with regional adjustment factors.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=87.5,
        author=_DDC,
        tags=["North America", "USD", "MasterFormat", "CSI"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-uk-gbp",
        name="CWICR United Kingdom (GBP)",
        description="55,719 construction cost items aligned with NRM 1/2 measurement rules. UK national rates in GBP with BCIS regional indices.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=85.2,
        author=_DDC,
        tags=["UK", "GBP", "NRM", "BCIS"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-de-berlin",
        name="CWICR Germany (Berlin)",
        description="55,719 construction cost items with DIN 276 classification. Berlin regional rates in EUR with BKI benchmark data.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=92.3,
        author=_DDC,
        tags=["DACH", "EUR", "DIN 276", "BKI"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-eng-toronto",
        name="CWICR Canada (Toronto, CAD)",
        description="55,719 construction cost items for the Canadian market. Toronto regional rates in CAD with CSC UniFormat alignment.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=83.7,
        author=_DDC,
        tags=["North America", "CAD", "CSC", "UniFormat"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-fr-paris",
        name="CWICR France (Paris, EUR)",
        description="55,719 construction cost items for the French market. Paris regional rates in EUR with Batiprix classification mapping.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=88.1,
        author=_DDC,
        tags=["Europe", "EUR", "Batiprix", "France"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-sp-barcelona",
        name="CWICR Spain (Barcelona, EUR)",
        description="55,719 construction cost items for the Spanish market. Barcelona regional rates in EUR with ITEC classification.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=86.4,
        author=_DDC,
        tags=["Europe", "EUR", "ITEC", "Spain"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-pt-saopaulo",
        name="CWICR Brazil (Sao Paulo, BRL)",
        description="55,719 construction cost items for the Brazilian market. Sao Paulo rates in BRL with SINAPI classification.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=79.8,
        author=_DDC,
        tags=["South America", "BRL", "SINAPI", "Brazil"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-ru-stpetersburg",
        name="CWICR Russia (St. Petersburg, RUB)",
        description="55,719 construction cost items for the Russian market. St. Petersburg rates in RUB with GESN/FER classification.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=91.0,
        author=_DDC,
        tags=["CIS", "RUB", "GESN", "Russia"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-ar-dubai",
        name="CWICR UAE (Dubai, AED)",
        description="55,719 construction cost items for the UAE market. Dubai rates in AED with local classification standards.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=76.5,
        author=_DDC,
        tags=["Middle East", "AED", "UAE", "Dubai"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-zh-shanghai",
        name="CWICR China (Shanghai, CNY)",
        description="55,719 construction cost items for the Chinese market. Shanghai rates in CNY with GB/T classification system.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=94.2,
        author=_DDC,
        tags=["Asia Pacific", "CNY", "GB/T", "China"],
        requires=["oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="cwicr-hi-mumbai",
        name="CWICR India (Mumbai, INR)",
        description="55,719 construction cost items for the Indian market. Mumbai rates in INR with IS/CPWD schedule alignment.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=81.3,
        author=_DDC,
        tags=["Asia Pacific", "INR", "CPWD", "India"],
        requires=["oe_costs"],
        price="Free",
    ),
    # ── Resource Catalogs (11) ────────────────────────────────────────────
    MarketplaceModule(
        id="catalog-ar-dubai",
        name="Resource Catalog: Arabic (Dubai, AED)",
        description="Curated resource catalog for the UAE market. Materials, equipment, labor, and operators with Dubai regional pricing in AED. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["Middle East", "AED", "Dubai", "Arabic"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-de-berlin",
        name="Resource Catalog: German (Berlin, EUR)",
        description="Curated resource catalog for the German market. Materials, equipment, labor, and operators with Berlin regional pricing in EUR. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["DACH", "EUR", "Berlin", "German"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-en-toronto",
        name="Resource Catalog: English (Toronto, CAD)",
        description="Curated resource catalog for the Canadian market. Materials, equipment, labor, and operators with Toronto regional pricing in CAD. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["North America", "CAD", "Toronto", "English"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-sp-barcelona",
        name="Resource Catalog: Spanish (Barcelona, EUR)",
        description="Curated resource catalog for the Spanish market. Materials, equipment, labor, and operators with Barcelona regional pricing in EUR. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["Europe", "EUR", "Barcelona", "Spanish"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-fr-paris",
        name="Resource Catalog: French (Paris, EUR)",
        description="Curated resource catalog for the French market. Materials, equipment, labor, and operators with Paris regional pricing in EUR. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["Europe", "EUR", "Paris", "French"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-hi-mumbai",
        name="Resource Catalog: Hindi (Mumbai, INR)",
        description="Curated resource catalog for the Indian market. Materials, equipment, labor, and operators with Mumbai regional pricing in INR. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["Asia Pacific", "INR", "Mumbai", "Hindi"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-pt-saopaulo",
        name="Resource Catalog: Portuguese (Sao Paulo, BRL)",
        description="Curated resource catalog for the Brazilian market. Materials, equipment, labor, and operators with Sao Paulo regional pricing in BRL. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["South America", "BRL", "Sao Paulo", "Portuguese"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-ru-stpetersburg",
        name="Resource Catalog: Russian (St. Petersburg, RUB)",
        description="Curated resource catalog for the Russian market. Materials, equipment, labor, and operators with St. Petersburg regional pricing in RUB. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["CIS", "RUB", "St. Petersburg", "Russian"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-uk-gbp",
        name="Resource Catalog: UK (London, GBP)",
        description="Curated resource catalog for the UK market. Materials, equipment, labor, and operators with UK national pricing in GBP. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["UK", "GBP", "London", "English"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-usa-usd",
        name="Resource Catalog: USA (USD)",
        description="Curated resource catalog for the US market. Materials, equipment, labor, and operators with US national average pricing in USD. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["North America", "USD", "USA", "English"],
        requires=["oe_catalog"],
        price="Free",
    ),
    MarketplaceModule(
        id="catalog-zh-shanghai",
        name="Resource Catalog: Chinese (Shanghai, CNY)",
        description="Curated resource catalog for the Chinese market. Materials, equipment, labor, and operators with Shanghai regional pricing in CNY. Downloadable from DDC CWICR GitHub repository.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["Asia Pacific", "CNY", "Shanghai", "Chinese"],
        requires=["oe_catalog"],
        price="Free",
    ),
    # ── Vector Indices (11) ──────────────────────────────────────────────
    # These require `pip install sentence-transformers` to enable semantic
    # vector search across 55,000+ cost items. Without this, text-based
    # search is used as fallback. DDC-CWICR-OE-2026.
    MarketplaceModule(
        id="vector-usa-usd",
        name="Vector Index: USA (USD)",
        description="Semantic vector index for 55K+ CWICR US cost items. Enables AI-powered fuzzy search by description — find 'reinforced concrete slab' even if the DB entry says 'cast-in-place structural concrete'. Requires: pip install sentence-transformers.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=22.4,
        author=_DDC,
        tags=["AI", "Semantic Search", "USA"],
        requires=["oe_costs", "cwicr-usa-usd"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-uk-gbp",
        name="Vector Index: UK (GBP)",
        description="Semantic vector index for 55K+ CWICR UK cost items (NRM 1/2). Smart fuzzy search — match AI estimates to real BCIS-aligned rates. Requires: pip install sentence-transformers.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=21.8,
        author=_DDC,
        tags=["AI", "Semantic Search", "UK"],
        requires=["oe_costs", "cwicr-uk-gbp"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-de-berlin",
        name="Vector Index: Germany (Berlin)",
        description="Semantic vector index for 55K+ CWICR DACH cost items (DIN 276). Smart fuzzy search — match AI estimates to real BKI-aligned market rates. Requires: pip install sentence-transformers.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=23.1,
        author=_DDC,
        tags=["AI", "Semantic Search", "DACH"],
        requires=["oe_costs", "cwicr-de-berlin"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-eng-toronto",
        name="Vector Index: Canada (Toronto)",
        description="Pre-built semantic vector index for CWICR Canada database. Enables AI-powered cost item search and automatic UniFormat classification.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=20.9,
        author=_DDC,
        tags=["AI", "Semantic Search", "Canada"],
        requires=["oe_costs", "cwicr-eng-toronto"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-fr-paris",
        name="Vector Index: France (Paris)",
        description="Pre-built semantic vector index for CWICR France database. Enables AI-powered cost item search and Batiprix classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=22.0,
        author=_DDC,
        tags=["AI", "Semantic Search", "France"],
        requires=["oe_costs", "cwicr-fr-paris"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-sp-barcelona",
        name="Vector Index: Spain (Barcelona)",
        description="Pre-built semantic vector index for CWICR Spain database. Enables AI-powered cost item search and ITEC classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=21.5,
        author=_DDC,
        tags=["AI", "Semantic Search", "Spain"],
        requires=["oe_costs", "cwicr-sp-barcelona"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-pt-saopaulo",
        name="Vector Index: Brazil (Sao Paulo)",
        description="Pre-built semantic vector index for CWICR Brazil database. Enables AI-powered cost item search and SINAPI classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=19.8,
        author=_DDC,
        tags=["AI", "Semantic Search", "Brazil"],
        requires=["oe_costs", "cwicr-pt-saopaulo"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-ru-stpetersburg",
        name="Vector Index: Russia (St. Petersburg)",
        description="Pre-built semantic vector index for CWICR Russia database. Enables AI-powered cost item search and GESN classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=23.5,
        author=_DDC,
        tags=["AI", "Semantic Search", "Russia"],
        requires=["oe_costs", "cwicr-ru-stpetersburg"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-ar-dubai",
        name="Vector Index: UAE (Dubai)",
        description="Pre-built semantic vector index for CWICR UAE database. Enables AI-powered cost item search and local classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=18.7,
        author=_DDC,
        tags=["AI", "Semantic Search", "UAE"],
        requires=["oe_costs", "cwicr-ar-dubai"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-zh-shanghai",
        name="Vector Index: China (Shanghai)",
        description="Pre-built semantic vector index for CWICR China database. Enables AI-powered cost item search and GB/T classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=24.1,
        author=_DDC,
        tags=["AI", "Semantic Search", "China"],
        requires=["oe_costs", "cwicr-zh-shanghai"],
        price="Free",
    ),
    MarketplaceModule(
        id="vector-hi-mumbai",
        name="Vector Index: India (Mumbai)",
        description="Pre-built semantic vector index for CWICR India database. Enables AI-powered cost item search and CPWD classification matching.",
        category="vector_index",
        icon="Sparkles",
        version="1.2.0",
        size_mb=20.3,
        author=_DDC,
        tags=["AI", "Semantic Search", "India"],
        requires=["oe_costs", "cwicr-hi-mumbai"],
        price="Free",
    ),
    # ── Language Packs (20) ──────────────────────────────────────────────
    MarketplaceModule(
        id="lang-en",
        name="English",
        description="English language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["English", "Default"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-de",
        name="Deutsch (German)",
        description="German language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["German", "DACH"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-fr",
        name="Francais (French)",
        description="French language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["French", "Europe"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-es",
        name="Espanol (Spanish)",
        description="Spanish language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["Spanish", "Latin America"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-pt",
        name="Portugues (Portuguese)",
        description="Portuguese language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["Portuguese", "Brazil"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-ru",
        name="Russkij (Russian)",
        description="Russian language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.14,
        author=_OE,
        tags=["Russian", "CIS"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-ar",
        name="Arabic",
        description="Arabic language pack with RTL support — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.14,
        author=_OE,
        tags=["Arabic", "RTL", "Middle East"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-zh",
        name="Chinese (Simplified)",
        description="Simplified Chinese language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.15,
        author=_OE,
        tags=["Chinese", "Asia Pacific"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-ja",
        name="Japanese",
        description="Japanese language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.15,
        author=_OE,
        tags=["Japanese", "Asia Pacific"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-ko",
        name="Korean",
        description="Korean language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.14,
        author=_OE,
        tags=["Korean", "Asia Pacific"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-hi",
        name="Hindi",
        description="Hindi language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.14,
        author=_OE,
        tags=["Hindi", "India"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-sv",
        name="Svenska (Swedish)",
        description="Swedish language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["Swedish", "Nordics"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-no",
        name="Norsk (Norwegian)",
        description="Norwegian language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["Norwegian", "Nordics"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-da",
        name="Dansk (Danish)",
        description="Danish language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["Danish", "Nordics"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-fi",
        name="Suomi (Finnish)",
        description="Finnish language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["Finnish", "Nordics"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-nl",
        name="Nederlands (Dutch)",
        description="Dutch language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["Dutch", "Benelux"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-pl",
        name="Polski (Polish)",
        description="Polish language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["Polish", "Central Europe"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-cs",
        name="Cestina (Czech)",
        description="Czech language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["Czech", "Central Europe"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-tr",
        name="Turkce (Turkish)",
        description="Turkish language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["Turkish", "Middle East"],
        price="Free",
    ),
    MarketplaceModule(
        id="lang-it",
        name="Italiano (Italian)",
        description="Italian language pack — UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.13,
        author=_OE,
        tags=["Italian", "Europe"],
        price="Free",
    ),
    # ── Converters (4) ───────────────────────────────────────────────────
    MarketplaceModule(
        id="converter-dwg",
        name="DWG/DXF Converter",
        description="Import AutoCAD DWG and DXF files. Extracts geometry, layers, blocks, and properties into structured element tables for cost estimation.",
        category="converter",
        icon="FileInput",
        version="1.0.0",
        size_mb=245.0,
        author=_DDC,
        tags=["CAD", "DWG", "DXF", "AutoCAD"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-rvt",
        name="Revit (RVT) Parser",
        description="Native Revit file parser. No Autodesk license required. Extracts families, parameters, quantities, and spatial structure.",
        category="converter",
        icon="FileInput",
        version="0.5.0",
        size_mb=128.0,
        author=_DDC,
        tags=["BIM", "RVT", "Revit"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-ifc",
        name="IFC Import",
        description="Import IFC 2x3 and IFC4 files. Maps IFC entities to structured element tables with full property set extraction and spatial decomposition.",
        category="converter",
        icon="FileInput",
        version="1.0.0",
        size_mb=195.0,
        author=_DDC,
        tags=["BIM", "IFC", "buildingSMART"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-dgn",
        name="DGN Converter",
        description="Import MicroStation DGN files. Extracts elements, levels, properties, and 3D geometry into structured tables.",
        category="converter",
        icon="FileInput",
        version="1.0.0",
        size_mb=180.0,
        author=_DDC,
        tags=["CAD", "DGN", "MicroStation"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-pdf-ocr",
        name="PDF Takeoff Engine",
        description="AI-powered PDF takeoff with symbol detection, dimension extraction, and area measurement. Recognizes construction drawings and extracts quantities automatically.",
        category="converter",
        icon="FileInput",
        version="0.8.0",
        size_mb=512.0,
        author=_DDC,
        tags=["AI", "PDF", "OCR", "Takeoff"],
        requires=["oe_projects"],
        price="Free",
    ),
    # ── Analytics (3) ────────────────────────────────────────────────────
    MarketplaceModule(
        id="analytics-co2",
        name="Carbon Calculator (CO2)",
        description="Calculate embodied carbon (CO2e) for BOQ positions using EPD databases. Supports EN 15978 lifecycle stages A1-A5, B, C, D. Generate sustainability reports.",
        category="analytics",
        icon="BarChart3",
        version="1.0.0",
        size_mb=15.8,
        author=_OE,
        tags=["Sustainability", "CO2", "EPD", "EN 15978"],
        requires=["oe_boq", "oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="analytics-benchmarks",
        name="Cost Benchmarks (BKI/BCIS)",
        description="Compare your estimates against regional benchmarks. BKI (Germany), BCIS (UK), RSMeans (US) cost-per-m2 data with building type normalization.",
        category="analytics",
        icon="BarChart3",
        version="1.0.0",
        size_mb=42.5,
        author=_DDC,
        tags=["Benchmarks", "BKI", "BCIS", "RSMeans"],
        requires=["oe_boq", "oe_costs"],
        price="Free",
    ),
    # Risk Analysis and GAEB Exchange are now real frontend plugins
    # (installable via Modules page → Installable Plugins section).
    # ── Integrations ─────────────────────────────────────────────────
    MarketplaceModule(
        id="integration-procore",
        name="Procore Connector",
        description="Bi-directional sync with Procore. Push estimates to Procore budgets, pull change orders, sync cost items and project data via Procore REST API.",
        category="integration",
        icon="Plug",
        version="1.0.0",
        size_mb=3.4,
        author=_OE,
        tags=["Procore", "Sync", "REST API", "Cloud"],
        requires=["oe_projects", "oe_boq"],
        price="Free",
    ),
    MarketplaceModule(
        id="integration-msproject",
        name="Microsoft Project Sync",
        description="Import/export Microsoft Project (.mpp) schedules. Link BOQ positions to schedule activities for 4D/5D planning and cash flow forecasting.",
        category="integration",
        icon="Plug",
        version="1.0.0",
        size_mb=12.7,
        author=_OE,
        tags=["Microsoft Project", "MPP", "Schedule", "4D/5D"],
        requires=["oe_projects", "oe_boq"],
        price="Free",
    ),
]

# ── Demo Projects ──────────────────────────────────────────────────────────

MARKETPLACE_MODULES += [
    MarketplaceModule(
        id="demo-residential-berlin",
        name="Demo: Residential Complex Berlin",
        description="48-unit residential complex, 6 floors, DIN 276 classification. Full BOQ with 12 sections, 44 positions, 4D schedule (18 months), 5D budget with EVM, and tendering with 3 bids. Total: ~6.5M EUR.",
        category="demo_project",
        icon="Building2",
        version="1.0.0",
        size_mb=0.1,
        author=_DDC,
        tags=["DACH", "EUR", "DIN 276", "Residential", "48 units"],
        requires=[],
        price="Free",
    ),
    MarketplaceModule(
        id="demo-office-london",
        name="Demo: Office Tower London",
        description="8-storey steel frame office, NRM 1 classification, Canary Wharf. Full BOQ with 10 sections, 41 positions, 4D schedule (24 months), 5D budget, and 3 UK contractor bids. Total: ~35M GBP.",
        category="demo_project",
        icon="Building2",
        version="1.0.0",
        size_mb=0.1,
        author=_DDC,
        tags=["UK", "GBP", "NRM", "Commercial", "Steel frame"],
        requires=[],
        price="Free",
    ),
    MarketplaceModule(
        id="demo-medical-us",
        name="Demo: Downtown Medical Center",
        description="200-bed hospital with ED, surgical suites, diagnostic imaging. 5-story steel frame. MasterFormat, 12 sections, 38 positions, 22-month schedule. Full MEP systems. Total: ~$25M.",
        category="demo_project",
        icon="Building2",
        version="1.0.0",
        size_mb=0.1,
        author=_DDC,
        tags=["US", "USD", "MasterFormat", "Healthcare", "Hospital"],
        requires=[],
        price="Free",
    ),
    MarketplaceModule(
        id="demo-warehouse-dubai",
        name="Demo: Logistics Warehouse Dubai",
        description="Large logistics warehouse with high-bay racking, loading docks, fire suppression. 6 sections, 25 positions, 12-month fast-track schedule. Total: ~15M AED.",
        category="demo_project",
        icon="Building2",
        version="1.0.0",
        size_mb=0.1,
        author=_DDC,
        tags=["Gulf", "AED", "Logistics", "Steel", "Warehouse"],
        requires=[],
        price="Free",
    ),
    MarketplaceModule(
        id="demo-school-paris",
        name="Demo: Primary School Paris",
        description="Primary school with 16 classrooms, gymnasium, canteen, playground. French standards, 7 sections, 30 positions, 14-month schedule. Total: ~8M EUR.",
        category="demo_project",
        icon="Building2",
        version="1.0.0",
        size_mb=0.1,
        author=_DDC,
        tags=["France", "EUR", "Education", "Public", "School"],
        requires=[],
        price="Free",
    ),
]

# Index by id for fast lookup
_MODULES_BY_ID: dict[str, MarketplaceModule] = {m.id: m for m in MARKETPLACE_MODULES}


def get_marketplace_catalog(
    loaded_catalog_regions: set[str] | None = None,
) -> list[dict]:
    """Return the full marketplace catalog with runtime ``installed`` status.

    Installed status is determined by:
    - Languages: all 20 bundled, always installed
    - Converters: built-in, always installed
    - Analytics: built-in, always installed
    - Integrations: not yet implemented, marked ``coming_soon=True``
    - Cost databases: checked on frontend via /costs/regions
    - Resource catalogs: checked against loaded catalog regions
    - Vector indices: checked on frontend
    - Demo projects: always available to install

    Args:
        loaded_catalog_regions: Set of catalog region keys that have been imported
            (e.g. {"AR_DUBAI", "DE_BERLIN"}). When provided, the corresponding
            ``resource_catalog`` marketplace entries are marked as installed.
    """
    loaded_names = {name for name in module_loader.loaded_modules}

    # Map catalog module IDs to their corresponding region keys
    _CATALOG_ID_TO_REGION: dict[str, str] = {
        "catalog-ar-dubai": "AR_DUBAI",
        "catalog-de-berlin": "DE_BERLIN",
        "catalog-en-toronto": "ENG_TORONTO",
        "catalog-sp-barcelona": "SP_BARCELONA",
        "catalog-fr-paris": "FR_PARIS",
        "catalog-hi-mumbai": "HI_MUMBAI",
        "catalog-pt-saopaulo": "PT_SAOPAULO",
        "catalog-ru-stpetersburg": "RU_STPETERSBURG",
        "catalog-uk-gbp": "UK_GBP",
        "catalog-usa-usd": "USA_USD",
        "catalog-zh-shanghai": "ZH_SHANGHAI",
    }

    _loaded_regions = loaded_catalog_regions or set()

    result: list[dict] = []
    for mod in MARKETPLACE_MODULES:
        installed = False
        coming_soon = False

        if mod.category == "language":
            # All 20 languages are bundled with the app
            installed = True
        elif mod.category == "converter":
            # All converters are built-in
            installed = True
        elif mod.category == "analytics":
            # All analytics modules are built-in
            installed = True
        elif mod.category == "integration":
            # Integrations are not yet implemented
            installed = False
            coming_soon = True
        elif mod.category == "demo_project":
            installed = False  # Always installable
        elif mod.category == "cost_database":
            # Will be checked on frontend via /costs/regions
            installed = False
        elif mod.category == "resource_catalog":
            region_key = _CATALOG_ID_TO_REGION.get(mod.id, "")
            installed = region_key in _loaded_regions
        elif mod.category == "vector_index":
            installed = False  # Checked on frontend
        else:
            installed = mod.id in loaded_names

        result.append(mod.to_dict(installed=installed, coming_soon=coming_soon))

    return result


def get_marketplace_module(module_id: str) -> MarketplaceModule | None:
    """Look up a single marketplace module by id."""
    return _MODULES_BY_ID.get(module_id)
