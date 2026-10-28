"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Whether the two CWICR work-name columns are joined depends on the base type.

The classic CIS parquets split one sentence across ``rate_original_name`` and
``rate_final_name``, so those must be concatenated. The national bases carry two
parallel full descriptions of the same item, so joining them prints it twice.
Both diverge in ~100% of rows, so only the base type can tell them apart - these
tests pin both sides of that decision.
"""

import pandas as pd

from app.modules.costs import base_registry

# Classic CIS shape: a parent description plus the variant that distinguishes it.
_CLASSIC_PARENT = "Soil excavation using single-bucket electric dragline excavators with a capacity of:"
_CLASSIC_VARIANT = "15 m3, soil group 1"

# National shape: two independent renderings of the same item in the same language.
_NATIONAL_A = "Demolition of the Catalan vault, including manual loading"
_NATIONAL_B = "Demolition of the vault to the flat arch, including manual loading"


def _series(*values: str) -> pd.Series:
    return pd.Series(list(values), dtype="object")


def _join(orig: list[str], final: list[str], *, join: bool) -> list[str]:
    from app.modules.costs.router import _join_work_name_columns

    return list(_join_work_name_columns(_series(*orig), _series(*final), join=join))


def test_classic_base_still_joins_the_two_halves_of_one_sentence() -> None:
    """Dropping the join here would strand every variant without its context."""
    (result,) = _join([_CLASSIC_PARENT], [_CLASSIC_VARIANT], join=True)
    assert result == f"{_CLASSIC_PARENT} {_CLASSIC_VARIANT}"


def test_national_base_keeps_a_single_copy() -> None:
    """Joining here printed the same item twice in the user's own language."""
    (result,) = _join([_NATIONAL_A], [_NATIONAL_B], join=False)
    assert result == _NATIONAL_B
    assert _NATIONAL_A not in result


def test_national_base_falls_back_when_the_final_column_is_empty() -> None:
    """No row may end up blank just because one column was not populated."""
    assert _join([_NATIONAL_A], [""], join=False) == [_NATIONAL_A]
    assert _join([""], [_NATIONAL_B], join=False) == [_NATIONAL_B]


def test_equal_columns_never_double_on_either_side() -> None:
    """The China and Turkiye parquets hold the same string in both columns."""
    assert _join([_NATIONAL_A], [_NATIONAL_A], join=True) == [_NATIONAL_A]
    assert _join([_NATIONAL_A], [_NATIONAL_A], join=False) == [_NATIONAL_A]


def test_restored_verbatim_source_text_is_not_shown_to_other_languages() -> None:
    """The shape the China base takes once its verbatim source text is restored.

    Today China's two columns agree, so it renders cleanly by accident. The
    pending repair puts the real Chinese back into ``rate_original_name`` while
    ``rate_final_name`` keeps the translation, which is the doubling shape. A
    German reader must still get only German.
    """
    chinese, german = "现场平整", "Baustellenebene"
    assert _join([chinese], [german], join=False) == [german]
    # And the classic base, whose columns are two halves of one sentence, is
    # unaffected by that repair because it is not a national base.
    assert _join([_CLASSIC_PARENT], [_CLASSIC_VARIANT], join=True) == [f"{_CLASSIC_PARENT} {_CLASSIC_VARIANT}"]


def test_a_blank_row_stays_blank_rather_than_leaking_source_text() -> None:
    """Both columns empty is the only empty case the published parquets have.

    Measured on origin/main: every row with an empty ``rate_final_name`` also has
    an empty ``rate_original_name``, so the fallback never fires on real data and
    the source text cannot reach a reader of another language through it.
    """
    assert _join([""], [""], join=False) == [""]


def test_national_regions_are_recognised_in_all_three_forms() -> None:
    """Home, per-language and staging ids all transform work-item text."""
    assert base_registry.is_national_region("ZH_CHINA")
    assert base_registry.is_national_region("ZH_CHINA_de")
    assert base_registry.is_national_region("__xlate_ZH_CHINA_de")
    assert base_registry.is_national_region("IT_TOSCANA_it")


def test_the_classic_base_and_its_markets_are_not_national() -> None:
    """The global base must keep joining, so it must not match the predicate."""
    assert not base_registry.is_national_region("RU_MOSCOW_ru")
    assert not base_registry.is_national_region("ENG_TORONTO")
    assert not base_registry.is_national_region("")
    assert not base_registry.is_national_region("nonexistent_xx")


def test_every_national_base_resolves_to_no_join() -> None:
    """The flag the callers compute must be False for all eight bases."""
    for family in base_registry._NATIONAL_FAMILIES:
        region = family.variants[0].region
        assert base_registry.is_national_region(region), region
        assert base_registry.is_national_region(f"__xlate_{region}_de"), region


def test_the_real_loader_ids_are_national_not_just_the_file_tokens() -> None:
    """A base's parquet file token is NOT its region id, and only the id is passed.

    Turkiye ships ``TR_..._workitems...parquet`` but loads as ``TR_NATIONAL``, so a
    predicate built from file tokens would answer False for four of the eight
    bases and silently leave them doubling. Pin the ids the callers really use.
    """
    checked = 0
    for family in base_registry._NATIONAL_FAMILIES:
        base_region = family.variants[0].region
        for lang in ("de", "ru", base_registry.home_language_code(base_region) or "de"):
            db_id = base_registry.national_language_region(base_region, lang)
            if db_id is None:
                continue
            assert base_registry.is_national_region(db_id), db_id
            assert base_registry.is_national_region(f"__xlate_{db_id}"), db_id
            checked += 1
    assert checked >= 16, f"expected to cover every base, only checked {checked}"
