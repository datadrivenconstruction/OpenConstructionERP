"""Built-in BOQ templates for common building types.

Each template is a complete BOQ structure with sections and positions.
Positions use a ``qty_factor`` that is multiplied by the user-provided gross
floor area (GFA, in m2) to derive the actual quantity.

Templates cover the most common building types worldwide:
    - residential — Multi-family residential (apartments), 3-5 floors
    - office — Commercial office, 4-8 floors, steel or RC frame
    - warehouse — Logistics warehouse, single-story, steel portal frame
    - school — Primary or secondary school, 2-3 floors
    - hospital — General hospital or clinic, highly serviced
    - hotel — 3-5 star hotel with restaurant and conference
    - retail — Retail space or shopping mall, 1-3 floors
    - infrastructure — Road bridge, overpass, or elevated highway section
"""

from typing import Any

TemplateSection = dict[str, Any]
TemplateData = dict[str, Any]

TEMPLATES: dict[str, TemplateData] = {
    "residential": {
        "name": "Residential Building",
        "description": "Multi-family residential (apartments), 3-5 floors",
        "icon": "Home",
        "sections": [
            {
                "ordinal": "01",
                "description": "Earthwork & Foundations",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Site clearing and grubbing",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 8.50,
                    },
                    {
                        "ordinal": "01.01.0020",
                        "description": "Excavation to formation level",
                        "unit": "m3",
                        "qty_factor": 0.8,
                        "rate": 12.50,
                    },
                    {
                        "ordinal": "01.01.0030",
                        "description": "Backfill and compaction",
                        "unit": "m3",
                        "qty_factor": 0.3,
                        "rate": 15.00,
                    },
                    {
                        "ordinal": "01.02.0010",
                        "description": "Reinforced concrete strip foundations",
                        "unit": "m3",
                        "qty_factor": 0.15,
                        "rate": 285.00,
                    },
                    {
                        "ordinal": "01.02.0020",
                        "description": "Ground floor slab, RC C30/37, d=250mm",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 95.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Structural Frame",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "RC columns 300x300mm",
                        "unit": "m3",
                        "qty_factor": 0.03,
                        "rate": 420.00,
                    },
                    {
                        "ordinal": "02.01.0020",
                        "description": "RC beams",
                        "unit": "m3",
                        "qty_factor": 0.05,
                        "rate": 380.00,
                    },
                    {
                        "ordinal": "02.02.0010",
                        "description": "RC floor slabs, d=220mm",
                        "unit": "m2",
                        "qty_factor": 3.0,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "02.02.0020",
                        "description": "Reinforcement steel BSt 500",
                        "unit": "kg",
                        "qty_factor": 15.0,
                        "rate": 1.85,
                    },
                    {
                        "ordinal": "02.03.0010",
                        "description": "Precast concrete stairs",
                        "unit": "pcs",
                        "qty_factor": 0.012,
                        "rate": 2800.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "External Walls & Facade",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "External masonry walls, d=240mm",
                        "unit": "m2",
                        "qty_factor": 1.8,
                        "rate": 62.00,
                    },
                    {
                        "ordinal": "03.01.0020",
                        "description": "Thermal insulation ETICS, 160mm",
                        "unit": "m2",
                        "qty_factor": 1.8,
                        "rate": 48.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "External render/plaster",
                        "unit": "m2",
                        "qty_factor": 1.8,
                        "rate": 32.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "Internal Walls & Partitions",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "Internal masonry walls, d=175mm",
                        "unit": "m2",
                        "qty_factor": 2.5,
                        "rate": 48.00,
                    },
                    {
                        "ordinal": "04.01.0020",
                        "description": "Internal plaster, 15mm",
                        "unit": "m2",
                        "qty_factor": 5.0,
                        "rate": 18.50,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Drywalls/partitions, double-sided",
                        "unit": "m2",
                        "qty_factor": 0.8,
                        "rate": 42.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "Roof",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Flat roof waterproofing membrane",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 65.00,
                    },
                    {
                        "ordinal": "05.01.0020",
                        "description": "Roof insulation, 200mm",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 35.00,
                    },
                    {
                        "ordinal": "05.01.0030",
                        "description": "Roof drainage system",
                        "unit": "m",
                        "qty_factor": 0.15,
                        "rate": 45.00,
                    },
                ],
            },
            {
                "ordinal": "06",
                "description": "Windows & Doors",
                "positions": [
                    {
                        "ordinal": "06.01.0010",
                        "description": "PVC windows, double-glazed",
                        "unit": "m2",
                        "qty_factor": 0.25,
                        "rate": 280.00,
                    },
                    {
                        "ordinal": "06.02.0010",
                        "description": "Internal doors, wooden",
                        "unit": "pcs",
                        "qty_factor": 0.02,
                        "rate": 450.00,
                    },
                    {
                        "ordinal": "06.02.0020",
                        "description": "Entrance doors, security rated",
                        "unit": "pcs",
                        "qty_factor": 0.003,
                        "rate": 1200.00,
                    },
                ],
            },
            {
                "ordinal": "07",
                "description": "MEP (Mechanical, Electrical, Plumbing)",
                "positions": [
                    {
                        "ordinal": "07.01.0010",
                        "description": "Electrical installation (rough-in + finish)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "07.02.0010",
                        "description": "Plumbing installation",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 65.00,
                    },
                    {
                        "ordinal": "07.03.0010",
                        "description": "HVAC system",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 75.00,
                    },
                    {
                        "ordinal": "07.04.0010",
                        "description": "Fire protection (sprinkler + alarm)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 35.00,
                    },
                ],
            },
            {
                "ordinal": "08",
                "description": "Interior Finishes",
                "positions": [
                    {
                        "ordinal": "08.01.0010",
                        "description": "Floor screed, 65mm",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 22.00,
                    },
                    {
                        "ordinal": "08.01.0020",
                        "description": "Floor tiling (bathroom/kitchen)",
                        "unit": "m2",
                        "qty_factor": 0.3,
                        "rate": 55.00,
                    },
                    {
                        "ordinal": "08.01.0030",
                        "description": "Laminate flooring (living areas)",
                        "unit": "m2",
                        "qty_factor": 0.7,
                        "rate": 38.00,
                    },
                    {
                        "ordinal": "08.02.0010",
                        "description": "Wall painting, 2 coats",
                        "unit": "m2",
                        "qty_factor": 5.0,
                        "rate": 12.00,
                    },
                    {
                        "ordinal": "08.03.0010",
                        "description": "Bathroom fittings (per apartment)",
                        "unit": "pcs",
                        "qty_factor": 0.01,
                        "rate": 3500.00,
                    },
                    {
                        "ordinal": "08.03.0020",
                        "description": "Kitchen fittings (per apartment)",
                        "unit": "pcs",
                        "qty_factor": 0.01,
                        "rate": 4500.00,
                    },
                ],
            },
            {
                "ordinal": "09",
                "description": "External Works",
                "positions": [
                    {
                        "ordinal": "09.01.0010",
                        "description": "Landscaping and planting",
                        "unit": "m2",
                        "qty_factor": 0.3,
                        "rate": 25.00,
                    },
                    {
                        "ordinal": "09.01.0020",
                        "description": "Paving and paths",
                        "unit": "m2",
                        "qty_factor": 0.2,
                        "rate": 45.00,
                    },
                    {
                        "ordinal": "09.02.0010",
                        "description": "External utilities connections",
                        "unit": "lsum",
                        "qty_factor": 0.001,
                        "rate": 25000.00,
                    },
                ],
            },
        ],
    },
    "office": {
        "name": "Office Building",
        "description": "Commercial office, 4-8 floors, steel or RC frame",
        "icon": "Building2",
        "sections": [
            {
                "ordinal": "01",
                "description": "Substructure",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Piled foundations",
                        "unit": "m",
                        "qty_factor": 0.6,
                        "rate": 65.00,
                    },
                    {
                        "ordinal": "01.01.0020",
                        "description": "Pile caps and ground beams",
                        "unit": "m3",
                        "qty_factor": 0.1,
                        "rate": 320.00,
                    },
                    {
                        "ordinal": "01.02.0010",
                        "description": "Ground floor slab",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 95.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Frame & Upper Floors",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "Steel frame (columns + beams)",
                        "unit": "t",
                        "qty_factor": 0.06,
                        "rate": 3200.00,
                    },
                    {
                        "ordinal": "02.02.0010",
                        "description": "Composite metal deck + concrete slab",
                        "unit": "m2",
                        "qty_factor": 5.0,
                        "rate": 72.00,
                    },
                    {
                        "ordinal": "02.03.0010",
                        "description": "Precast stairs",
                        "unit": "pcs",
                        "qty_factor": 0.01,
                        "rate": 4200.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Envelope",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "Curtain wall glazing system",
                        "unit": "m2",
                        "qty_factor": 2.5,
                        "rate": 485.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Flat roof, single-ply membrane + insulation",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 145.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "MEP Systems",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "HVAC (full system incl. AHU)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 120.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Electrical (incl. data/comms)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 95.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Plumbing + fire protection",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 55.00,
                    },
                    {
                        "ordinal": "04.04.0010",
                        "description": "Lifts/elevators, 2 No.",
                        "unit": "pcs",
                        "qty_factor": 0.002,
                        "rate": 85000.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "Finishes",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Raised access flooring",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 65.00,
                    },
                    {
                        "ordinal": "05.02.0010",
                        "description": "Suspended ceiling tiles",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 42.00,
                    },
                    {
                        "ordinal": "05.03.0010",
                        "description": "Internal partitions (glass/drywall)",
                        "unit": "m2",
                        "qty_factor": 0.8,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "05.04.0010",
                        "description": "Painting and decoration",
                        "unit": "m2",
                        "qty_factor": 3.0,
                        "rate": 14.00,
                    },
                    {
                        "ordinal": "05.05.0010",
                        "description": "Washroom fit-out",
                        "unit": "pcs",
                        "qty_factor": 0.005,
                        "rate": 8000.00,
                    },
                ],
            },
        ],
    },
    "warehouse": {
        "name": "Warehouse / Industrial",
        "description": "Logistics warehouse, single-story, steel portal frame",
        "icon": "Warehouse",
        "sections": [
            {
                "ordinal": "01",
                "description": "Site & Foundations",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Site preparation and leveling",
                        "unit": "m2",
                        "qty_factor": 1.2,
                        "rate": 6.00,
                    },
                    {
                        "ordinal": "01.02.0010",
                        "description": "Pad foundations",
                        "unit": "m3",
                        "qty_factor": 0.05,
                        "rate": 250.00,
                    },
                    {
                        "ordinal": "01.03.0010",
                        "description": "Ground-bearing slab, 200mm, fiber-reinforced",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 55.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Steel Structure",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "Steel portal frame",
                        "unit": "t",
                        "qty_factor": 0.03,
                        "rate": 2800.00,
                    },
                    {
                        "ordinal": "02.02.0010",
                        "description": "Purlins and girts",
                        "unit": "t",
                        "qty_factor": 0.01,
                        "rate": 2500.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Cladding & Roof",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "Insulated metal wall cladding",
                        "unit": "m2",
                        "qty_factor": 0.8,
                        "rate": 65.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Insulated metal roof sheeting",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 55.00,
                    },
                    {
                        "ordinal": "03.03.0010",
                        "description": "Roller shutter doors",
                        "unit": "pcs",
                        "qty_factor": 0.002,
                        "rate": 8000.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "Services",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "Electrical installation (warehouse)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 35.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Fire sprinkler system",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 28.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Office fit-out area (10% of GFA)",
                        "unit": "m2",
                        "qty_factor": 0.1,
                        "rate": 450.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "External Works",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Hardstanding / truck yard",
                        "unit": "m2",
                        "qty_factor": 0.5,
                        "rate": 45.00,
                    },
                    {
                        "ordinal": "05.02.0010",
                        "description": "Perimeter fencing",
                        "unit": "m",
                        "qty_factor": 0.15,
                        "rate": 85.00,
                    },
                ],
            },
        ],
    },
    "school": {
        "name": "School / Educational",
        "description": "Primary or secondary school, 2-3 floors",
        "icon": "GraduationCap",
        "sections": [
            {
                "ordinal": "01",
                "description": "Substructure",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Strip foundations",
                        "unit": "m3",
                        "qty_factor": 0.12,
                        "rate": 285.00,
                    },
                    {
                        "ordinal": "01.02.0010",
                        "description": "Ground floor slab",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 85.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Structure",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "RC frame (columns, beams, slabs)",
                        "unit": "m2",
                        "qty_factor": 2.0,
                        "rate": 165.00,
                    },
                    {
                        "ordinal": "02.02.0010",
                        "description": "Stairs and landings",
                        "unit": "pcs",
                        "qty_factor": 0.008,
                        "rate": 3500.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Envelope",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "External walls (masonry + insulation)",
                        "unit": "m2",
                        "qty_factor": 1.5,
                        "rate": 110.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Windows (high-performance glazing)",
                        "unit": "m2",
                        "qty_factor": 0.3,
                        "rate": 350.00,
                    },
                    {
                        "ordinal": "03.03.0010",
                        "description": "Roof (flat, insulated)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 120.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "MEP",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "HVAC with heat recovery",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 95.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Electrical + IT infrastructure",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 80.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Plumbing + sanitary",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 45.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "Finishes & FF&E",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Floor finishes (vinyl/tile mix)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 42.00,
                    },
                    {
                        "ordinal": "05.02.0010",
                        "description": "Wall finishes and painting",
                        "unit": "m2",
                        "qty_factor": 4.0,
                        "rate": 15.00,
                    },
                    {
                        "ordinal": "05.03.0010",
                        "description": "Classroom furniture and equipment",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 65.00,
                    },
                ],
            },
            {
                "ordinal": "06",
                "description": "External & Sports",
                "positions": [
                    {
                        "ordinal": "06.01.0010",
                        "description": "Sports field / playground",
                        "unit": "m2",
                        "qty_factor": 0.5,
                        "rate": 55.00,
                    },
                    {
                        "ordinal": "06.02.0010",
                        "description": "Parking and access roads",
                        "unit": "m2",
                        "qty_factor": 0.2,
                        "rate": 45.00,
                    },
                ],
            },
        ],
    },
    "hospital": {
        "name": "Hospital / Healthcare",
        "description": "General hospital or clinic, highly serviced",
        "icon": "Hospital",
        "sections": [
            {
                "ordinal": "01",
                "description": "Substructure",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Piled foundations (heavy loads)",
                        "unit": "m",
                        "qty_factor": 0.8,
                        "rate": 75.00,
                    },
                    {
                        "ordinal": "01.02.0010",
                        "description": "Basement / ground slab",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 120.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Superstructure",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "RC frame (columns, walls, slabs)",
                        "unit": "m2",
                        "qty_factor": 4.0,
                        "rate": 185.00,
                    },
                    {
                        "ordinal": "02.02.0010",
                        "description": "Stairs and lift shafts",
                        "unit": "pcs",
                        "qty_factor": 0.01,
                        "rate": 5000.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Envelope",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "External walls (high-performance)",
                        "unit": "m2",
                        "qty_factor": 2.0,
                        "rate": 150.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Windows and curtain wall",
                        "unit": "m2",
                        "qty_factor": 0.4,
                        "rate": 420.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "MEP (Hospital-grade)",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "HVAC with clean room / OR air handling",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 220.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Medical gas systems",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 45.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Electrical + UPS + generator",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 150.00,
                    },
                    {
                        "ordinal": "04.04.0010",
                        "description": "Plumbing + fire protection",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "04.05.0010",
                        "description": "Lifts/elevators (incl. bed lifts)",
                        "unit": "pcs",
                        "qty_factor": 0.003,
                        "rate": 120000.00,
                    },
                    {
                        "ordinal": "04.06.0010",
                        "description": "BMS / Building Management System",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 35.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "Finishes (Clinical-grade)",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Floor finishes (anti-bacterial vinyl)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 65.00,
                    },
                    {
                        "ordinal": "05.02.0010",
                        "description": "Wall finishes (hygienic cladding)",
                        "unit": "m2",
                        "qty_factor": 4.0,
                        "rate": 35.00,
                    },
                    {
                        "ordinal": "05.03.0010",
                        "description": "Suspended ceilings",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 48.00,
                    },
                ],
            },
            {
                "ordinal": "06",
                "description": "Medical Equipment (allowance)",
                "positions": [
                    {
                        "ordinal": "06.01.0010",
                        "description": "Medical equipment provisional sum",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 350.00,
                    },
                ],
            },
        ],
    },
    "hotel": {
        "name": "Hotel",
        "description": "3-5 star hotel with restaurant and conference facilities",
        "icon": "Hotel",
        "sections": [
            {
                "ordinal": "01",
                "description": "Substructure",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Foundations and ground slab",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 145.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Structure",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "RC frame (6-8 floors)",
                        "unit": "m2",
                        "qty_factor": 6.0,
                        "rate": 165.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Envelope",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "Facade system (stone/glass)",
                        "unit": "m2",
                        "qty_factor": 2.5,
                        "rate": 380.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Roof",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 130.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "MEP",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "HVAC (individual room control)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 135.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Electrical + low voltage",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 110.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Plumbing (en-suite bathrooms)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "04.04.0010",
                        "description": "Lifts",
                        "unit": "pcs",
                        "qty_factor": 0.003,
                        "rate": 95000.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "Finishes & FF&E",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Room fit-out (per key)",
                        "unit": "pcs",
                        "qty_factor": 0.04,
                        "rate": 18000.00,
                    },
                    {
                        "ordinal": "05.02.0010",
                        "description": "Public area finishes",
                        "unit": "m2",
                        "qty_factor": 0.3,
                        "rate": 250.00,
                    },
                    {
                        "ordinal": "05.03.0010",
                        "description": "Restaurant/kitchen fit-out",
                        "unit": "m2",
                        "qty_factor": 0.1,
                        "rate": 650.00,
                    },
                ],
            },
        ],
    },
    "retail": {
        "name": "Retail / Shopping Center",
        "description": "Retail space or shopping mall, 1-3 floors",
        "icon": "ShoppingBag",
        "sections": [
            {
                "ordinal": "01",
                "description": "Substructure",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Foundations and ground slab",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 110.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Structure",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "Steel/RC frame (large spans)",
                        "unit": "m2",
                        "qty_factor": 2.0,
                        "rate": 155.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Envelope",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "Glazed storefront facade",
                        "unit": "m2",
                        "qty_factor": 1.5,
                        "rate": 420.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Roof (flat, insulated)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 95.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "MEP",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "HVAC (large volume)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 110.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Electrical + emergency systems",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Plumbing + fire sprinklers",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 55.00,
                    },
                    {
                        "ordinal": "04.04.0010",
                        "description": "Escalators and lifts",
                        "unit": "pcs",
                        "qty_factor": 0.004,
                        "rate": 65000.00,
                    },
                ],
            },
            {
                "ordinal": "05",
                "description": "Shell & Core Finish",
                "positions": [
                    {
                        "ordinal": "05.01.0010",
                        "description": "Common area finishes",
                        "unit": "m2",
                        "qty_factor": 0.4,
                        "rate": 180.00,
                    },
                    {
                        "ordinal": "05.02.0010",
                        "description": "Tenant shell (base build)",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 85.00,
                    },
                    {
                        "ordinal": "05.03.0010",
                        "description": "Parking structure",
                        "unit": "m2",
                        "qty_factor": 0.8,
                        "rate": 450.00,
                    },
                ],
            },
        ],
    },
    "infrastructure": {
        "name": "Infrastructure / Bridge",
        "description": "Road bridge, overpass, or elevated highway section",
        "icon": "Route",
        "sections": [
            {
                "ordinal": "01",
                "description": "Preliminaries & Site Setup",
                "positions": [
                    {
                        "ordinal": "01.01.0010",
                        "description": "Mobilization, site establishment",
                        "unit": "lsum",
                        "qty_factor": 0.001,
                        "rate": 500000.00,
                    },
                    {
                        "ordinal": "01.01.0020",
                        "description": "Traffic management",
                        "unit": "lsum",
                        "qty_factor": 0.001,
                        "rate": 200000.00,
                    },
                ],
            },
            {
                "ordinal": "02",
                "description": "Substructure",
                "positions": [
                    {
                        "ordinal": "02.01.0010",
                        "description": "Bored piles, 1200mm dia",
                        "unit": "m",
                        "qty_factor": 2.0,
                        "rate": 650.00,
                    },
                    {
                        "ordinal": "02.02.0010",
                        "description": "Pile caps",
                        "unit": "m3",
                        "qty_factor": 0.3,
                        "rate": 420.00,
                    },
                    {
                        "ordinal": "02.03.0010",
                        "description": "Abutments",
                        "unit": "m3",
                        "qty_factor": 0.5,
                        "rate": 380.00,
                    },
                    {
                        "ordinal": "02.04.0010",
                        "description": "Piers",
                        "unit": "m3",
                        "qty_factor": 0.8,
                        "rate": 450.00,
                    },
                ],
            },
            {
                "ordinal": "03",
                "description": "Superstructure",
                "positions": [
                    {
                        "ordinal": "03.01.0010",
                        "description": "Post-tensioned bridge deck",
                        "unit": "m3",
                        "qty_factor": 3.0,
                        "rate": 520.00,
                    },
                    {
                        "ordinal": "03.02.0010",
                        "description": "Post-tensioning tendons",
                        "unit": "t",
                        "qty_factor": 0.1,
                        "rate": 8500.00,
                    },
                    {
                        "ordinal": "03.03.0010",
                        "description": "Reinforcement steel",
                        "unit": "t",
                        "qty_factor": 1.5,
                        "rate": 1450.00,
                    },
                ],
            },
            {
                "ordinal": "04",
                "description": "Finishing & Safety",
                "positions": [
                    {
                        "ordinal": "04.01.0010",
                        "description": "Bridge bearings",
                        "unit": "pcs",
                        "qty_factor": 0.01,
                        "rate": 35000.00,
                    },
                    {
                        "ordinal": "04.02.0010",
                        "description": "Expansion joints",
                        "unit": "m",
                        "qty_factor": 0.02,
                        "rate": 3200.00,
                    },
                    {
                        "ordinal": "04.03.0010",
                        "description": "Safety barriers",
                        "unit": "m",
                        "qty_factor": 0.3,
                        "rate": 280.00,
                    },
                    {
                        "ordinal": "04.04.0010",
                        "description": "Waterproofing + surfacing",
                        "unit": "m2",
                        "qty_factor": 1.0,
                        "rate": 75.00,
                    },
                    {
                        "ordinal": "04.05.0010",
                        "description": "Lighting",
                        "unit": "pcs",
                        "qty_factor": 0.01,
                        "rate": 8500.00,
                    },
                ],
            },
        ],
    },
}
