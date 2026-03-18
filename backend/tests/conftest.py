"""Shared test fixtures."""

import pytest


@pytest.fixture
def sample_boq_data():
    """Sample BOQ data for validation tests."""
    return {
        "positions": [
            {
                "id": "pos-001",
                "ordinal": "01.01.0010",
                "description": "Stahlbeton C30/37 für Fundamente",
                "unit": "m3",
                "quantity": 45.5,
                "unit_rate": 185.00,
                "classification": {"din276": "330", "masterformat": "03 30 00"},
            },
            {
                "id": "pos-002",
                "ordinal": "01.01.0020",
                "description": "Schalung für Fundamente",
                "unit": "m2",
                "quantity": 120.0,
                "unit_rate": 42.50,
                "classification": {"din276": "330"},
            },
            {
                "id": "pos-003",
                "ordinal": "01.02.0010",
                "description": "Betonstahl BSt 500 S",
                "unit": "kg",
                "quantity": 3200.0,
                "unit_rate": 1.85,
                "classification": {"din276": "330"},
            },
        ]
    }


@pytest.fixture
def sample_boq_data_with_issues():
    """BOQ data with validation issues."""
    return {
        "positions": [
            {
                "id": "pos-001",
                "ordinal": "01.01.0010",
                "description": "Good position",
                "unit": "m3",
                "quantity": 10.0,
                "unit_rate": 100.0,
                "classification": {"din276": "330"},
            },
            {
                "id": "pos-002",
                "ordinal": "01.01.0010",  # DUPLICATE ordinal
                "description": "",  # MISSING description
                "unit": "m2",
                "quantity": 0,  # ZERO quantity
                "unit_rate": 0,  # ZERO rate
                "classification": {},  # MISSING classification
            },
            {
                "id": "pos-003",
                "ordinal": "01.02.0010",
                "description": "Overpriced item",
                "unit": "pcs",
                "quantity": 5.0,
                "unit_rate": 999999.0,  # ANOMALY
                "classification": {"din276": "999"},  # INVALID code
            },
        ]
    }


@pytest.fixture
def sample_cad_elements():
    """Sample CAD canonical format elements."""
    return [
        {
            "id": "elem_001",
            "category": "wall",
            "classification": {"din276": "330"},
            "geometry": {
                "type": "extrusion",
                "length_m": 12.5,
                "height_m": 3.0,
                "thickness_m": 0.24,
                "area_m2": 37.5,
                "volume_m3": 9.0,
            },
            "properties": {"material": "concrete_c30_37"},
            "quantities": {"area": 37.5, "volume": 9.0},
        },
        {
            "id": "elem_002",
            "category": "floor",
            "classification": {"din276": "350"},
            "geometry": {
                "type": "slab",
                "area_m2": 85.0,
                "thickness_m": 0.20,
                "volume_m3": 17.0,
            },
            "properties": {"material": "concrete_c25_30"},
            "quantities": {"area": 85.0, "volume": 17.0},
        },
    ]
