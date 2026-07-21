import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _literal_assignment(relative_path: str, name: str):
    source_path = REPO_ROOT / relative_path
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)

    raise AssertionError(f"{name} assignment not found in {relative_path}")


def test_local_cwicr_regions_are_registered_without_importing_app():
    marketplace_source = (REPO_ROOT / "backend/app/core/marketplace.py").read_text(encoding="utf-8")
    v3_catalogue_source = (REPO_ROOT / "backend/app/modules/costs/cwicr_v3_catalogue.py").read_text(
        encoding="utf-8"
    )
    yaml_source = (REPO_ROOT / "data/match/region_language.yaml").read_text(encoding="utf-8")

    catalog_region_map = _literal_assignment(
        "backend/app/modules/catalog/router.py",
        "REGION_MAP",
    )
    marketplace_catalog_map = _literal_assignment(
        "backend/app/core/marketplace.py",
        "_CATALOG_ID_TO_REGION",
    )
    marketplace_module_aliases = _literal_assignment(
        "backend/app/core/marketplace.py",
        "_MODULE_ID_ALIASES",
    )
    v3_region_aliases = _literal_assignment(
        "backend/app/modules/costs/cwicr_v3_catalogue.py",
        "_REGION_ALIASES",
    )
    github_cwicr_files = _literal_assignment(
        "backend/app/modules/costs/router.py",
        "_GITHUB_CWICR_FILES",
    )
    github_snapshot_files = _literal_assignment(
        "backend/app/modules/costs/router.py",
        "_GITHUB_SNAPSHOT_FILES",
    )
    qdrant_head_aliases = _literal_assignment(
        "backend/app/modules/costs/qdrant_adapter.py",
        "_REGION_HEAD_ALIASES",
    )
    legacy_currency_map = _literal_assignment(
        "backend/app/modules/costs/router.py",
        "_REGION_CURRENCY_LEGACY",
    )
    region_language_map = _literal_assignment(
        "backend/app/core/match_service/region_language.py",
        "REGION_LANGUAGE",
    )

    assert "TR_NATIONAL" in catalog_region_map
    assert "ZH_CHINA" in catalog_region_map
    assert 'id="cwicr-zh-china"' in marketplace_source
    assert 'id="catalog-zh-china"' in marketplace_source
    assert 'id="vector-zh-china"' in marketplace_source
    assert 'region="ZH_CHINA"' in v3_catalogue_source
    assert 'region="TR_NATIONAL"' in v3_catalogue_source
    assert "ZH_CHINA: zh" in yaml_source
    assert "TR_NATIONAL: tr" in yaml_source
    assert marketplace_catalog_map["catalog-zh-shanghai"] == "ZH_CHINA"
    assert marketplace_catalog_map["catalog-zh-china"] == "ZH_CHINA"
    assert marketplace_module_aliases["catalog-zh-shanghai"] == "catalog-zh-china"
    assert marketplace_module_aliases["cwicr-zh-shanghai"] == "cwicr-zh-china"
    assert marketplace_module_aliases["vector-zh-shanghai"] == "vector-zh-china"
    assert v3_region_aliases["CN_SHANGHAI"] == "ZH_CHINA"
    assert v3_region_aliases["ZH_SHANGHAI"] == "ZH_CHINA"
    assert v3_region_aliases["TR_ISTANBUL"] == "TR_NATIONAL"

    assert "TR_NATIONAL" in github_cwicr_files
    assert "ZH_CHINA" in github_cwicr_files
    assert "TR_NATIONAL" in github_cwicr_files["TR_NATIONAL"]
    assert "ZH_CHINA" in github_cwicr_files["ZH_CHINA"]
    assert "ZH_CHINA" in github_snapshot_files
    assert "ZH_SHANGHAI" in github_snapshot_files["ZH_CHINA"]
    assert qdrant_head_aliases["ZH"] == "CN"

    assert legacy_currency_map["TR_NATIONAL"] == "TRY"
    assert legacy_currency_map["ZH_CHINA"] == "CNY"

    assert region_language_map["TR_NATIONAL"] == "tr"
    assert region_language_map["ZH_CHINA"] == "zh"
    assert "TR_ISTANBUL" not in region_language_map
    assert "CN_SHANGHAI" not in region_language_map
