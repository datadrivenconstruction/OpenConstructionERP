# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Worked examples for the project catalogue arithmetic.

One story runs through the file. An estimator copies "Reinforced concrete wall
C30/37" at 185.00 EUR from the regional database into the project, prices this
job at 172.50, and later the database moves to 190.00. Every status the screen
shows and every choice the estimator gets is one of the cases below.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.project_catalogue.catalogue_math import (
    ItemStatus,
    deviation_percent,
    item_status,
    resolve_sync,
)

D = Decimal


class TestItemStatus:
    def test_copied_rate_is_in_sync(self) -> None:
        status = item_status(
            source_type="cost_item",
            rate=D("185.00"),
            source_rate=D("185.00"),
            current_source_rate=D("185.00"),
            source_found=True,
        )
        assert status is ItemStatus.IN_SYNC

    def test_local_edit_is_an_override(self) -> None:
        status = item_status(
            source_type="cost_item",
            rate=D("172.50"),
            source_rate=D("185.00"),
            current_source_rate=D("185.00"),
            source_found=True,
        )
        assert status is ItemStatus.OVERRIDDEN

    def test_moved_source_is_reported_even_over_an_override(self) -> None:
        status = item_status(
            source_type="cost_item",
            rate=D("172.50"),
            source_rate=D("185.00"),
            current_source_rate=D("190.00"),
            source_found=True,
        )
        assert status is ItemStatus.SOURCE_CHANGED

    def test_trailing_zeros_are_not_a_change(self) -> None:
        status = item_status(
            source_type="catalog_resource",
            rate=D("185"),
            source_rate=D("185.0000"),
            current_source_rate=D("185.00"),
            source_found=True,
        )
        assert status is ItemStatus.IN_SYNC

    def test_deleted_source_is_missing(self) -> None:
        status = item_status(
            source_type="cost_item",
            rate=D("185.00"),
            source_rate=D("185.00"),
            current_source_rate=None,
            source_found=False,
        )
        assert status is ItemStatus.SOURCE_MISSING

    def test_own_rate_has_no_source(self) -> None:
        status = item_status(
            source_type="manual",
            rate=D("12.00"),
            source_rate=None,
            current_source_rate=None,
            source_found=False,
        )
        assert status is ItemStatus.MANUAL


class TestResolveSync:
    def test_take_source_replaces_the_local_rate(self) -> None:
        out = resolve_sync("take_source", rate=D("172.50"), current_source_rate=D("190.00"))
        assert out == (D("190.00"), D("190.00"))
        assert (
            item_status(
                source_type="cost_item",
                rate=out[0],
                source_rate=out[1],
                current_source_rate=D("190.00"),
                source_found=True,
            )
            is ItemStatus.IN_SYNC
        )

    def test_keep_local_acknowledges_the_new_source(self) -> None:
        out = resolve_sync("keep_local", rate=D("172.50"), current_source_rate=D("190.00"))
        assert out == (D("172.50"), D("190.00"))
        assert (
            item_status(
                source_type="cost_item",
                rate=out[0],
                source_rate=out[1],
                current_source_rate=D("190.00"),
                source_found=True,
            )
            is ItemStatus.OVERRIDDEN
        )

    def test_unknown_action_is_refused(self) -> None:
        with pytest.raises(ValueError, match="action"):
            resolve_sync("merge", rate=D("1"), current_source_rate=D("2"))


class TestDeviation:
    def test_ordinary_negotiation(self) -> None:
        assert deviation_percent(D("172.50"), D("185.00")) == D("-6.8")

    def test_slipped_decimal(self) -> None:
        assert deviation_percent(D("1725.00"), D("185.00")) == D("832.4")

    def test_no_base_no_percentage(self) -> None:
        assert deviation_percent(D("10"), D("0")) is None
        assert deviation_percent(D("10"), None) is None
