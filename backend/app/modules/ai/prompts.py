"""AI prompt templates for construction cost estimation.

Contains carefully crafted prompts for text-based and photo-based estimation.
Prompts instruct the AI to return structured JSON arrays of work items
with realistic quantities, units, and market-rate prices.
"""

TEXT_ESTIMATE_PROMPT = """\
You are a professional construction cost estimator with 20+ years of experience.
Based on the following project description, generate a detailed Bill of Quantities.

Project: {description}
{extra_context}

Return a JSON array of work items:
[
  {{
    "ordinal": "01.01.0010",
    "description": "Site clearing and grubbing",
    "unit": "m2",
    "quantity": 500.0,
    "unit_rate": 8.50,
    "classification": {{"din276": "312"}},
    "category": "Earthworks"
  }},
  ...
]

Rules:
- Include ALL trades: earthwork, foundation, structure, walls, roof, MEP, finishes
- Use realistic quantities based on the described area/scope
- Use market-rate unit prices for the specified location
- Include 15-30 line items for a typical project
- Calculate total = quantity * unit_rate for each item
- Currency: {currency}
- Classification standard: {standard}
- Be specific: don't write "concrete work", write "Reinforced concrete C30/37 \
for foundation slab, d=30cm"
- Assign ordinals in format NN.NN.NNNN grouped by trade
- Each item must have a category from: Earthworks, Foundations, Concrete, Steel, \
Masonry, Roofing, Facades, Partitions, Floors, Windows & Doors, MEP, HVAC, \
Plumbing, Electrical, Fire Protection, Finishing, Landscaping, General
- Return ONLY the JSON array, no other text
"""

PHOTO_ESTIMATE_PROMPT = """\
You are a construction cost estimator analyzing a building photo.
Look at this photo and estimate the construction costs.

Identify:
1. Building type and approximate dimensions (use visible scale references like \
doors ~0.9m x 2.1m, windows ~1.2m x 1.5m, floor height ~3m, cars ~4.5m)
2. Structural system (concrete frame, steel, masonry, timber)
3. Number of floors
4. Facade type and materials
5. Roof type

Then generate a BOQ with realistic quantities and prices.

Return a JSON array of work items:
[
  {{
    "ordinal": "01.01.0010",
    "description": "Excavation for foundations",
    "unit": "m3",
    "quantity": 150.0,
    "unit_rate": 12.00,
    "classification": {{}},
    "category": "Earthworks"
  }},
  ...
]

Rules:
- Generate 10-25 work items covering all visible and implied trades
- Use dimension-based quantity estimation from the photo
- Include ONLY works that are DIRECTLY VISIBLE or clearly implied
- Do NOT guess interior finishes from an exterior photo
- Be CONSERVATIVE with quantities — measure carefully from the photo
- Calculate total = quantity * unit_rate
- Location: {location}
- Currency: {currency}
- Classification standard: {standard}
- Return ONLY the JSON array, no other text
"""

SMART_IMPORT_PROMPT = """\
You are a construction cost estimation expert.
Analyze this document and extract ALL construction work items / BOQ positions.

Document: {filename}
Content:
{text}

Extract every line item you can find and return as a JSON array:
[
  {{
    "ordinal": "01.01.0010",
    "description": "Description of the work item",
    "unit": "m2",
    "quantity": 100.0,
    "unit_rate": 45.00,
    "classification": {{"din276": "330"}}
  }}
]

Rules:
- Extract ALL items, even if quantities or rates are missing (use 0)
- Preserve original descriptions as closely as possible
- Detect the unit from context (m2, m3, kg, pcs, lsum, m, t, h)
- If rates are present, include them. If not, set to 0.
- Auto-number ordinals sequentially if not present in the document
- Include classification codes if visible (DIN 276, NRM, MasterFormat)
- Handle multi-language documents (German, English, Russian, etc.)
- Skip header/footer/summary rows
- Be thorough — it is better to include too many items than too few
- Return ONLY the JSON array, no other text
"""

SMART_IMPORT_VISION_PROMPT = """\
You are a construction cost estimation expert.
Analyze this photo/scan of a construction document and extract ALL work items / \
BOQ positions visible in the image.

Document: {filename}

Extract every line item you can find and return as a JSON array:
[
  {{
    "ordinal": "01.01.0010",
    "description": "Description of the work item",
    "unit": "m2",
    "quantity": 100.0,
    "unit_rate": 45.00,
    "classification": {{"din276": "330"}}
  }}
]

Rules:
- Read ALL text in the image carefully — OCR every row
- Extract ALL items, even if quantities or rates are missing (use 0)
- Preserve original descriptions as closely as possible
- Detect the unit from context (m2, m3, kg, pcs, lsum, m, t, h)
- If rates are present, include them. If not, set to 0.
- Auto-number ordinals sequentially if not present in the document
- Include classification codes if visible (DIN 276, NRM, MasterFormat)
- Handle multi-language documents (German, English, Russian, etc.)
- Skip header/footer/summary rows
- Be thorough — it is better to include too many items than too few
- Return ONLY the JSON array, no other text
"""

CAD_IMPORT_PROMPT = """\
You are a professional construction cost estimator with 20+ years of experience.
A BIM/CAD model has been converted to element data.
Analyze the elements and create a complete BOQ (Bill of Quantities).

CAD Data:
{text}

Generate BOQ positions that map each element type to construction work items.
Group by trade/section. Include realistic unit rates.

Return a JSON array:
[
  {{
    "ordinal": "01.01.0010",
    "description": "Reinforced concrete wall C30/37, d=24cm",
    "unit": "m3",
    "quantity": 45.0,
    "unit_rate": 280.00,
    "classification": {{"din276": "330"}},
    "category": "Concrete"
  }},
  ...
]

Rules:
- Map element categories to proper work descriptions
- Sum quantities by element type (don't create one position per element)
- Include related work (formwork for concrete, rebar for RC elements, etc.)
- Add finishes and services proportionally if not in the model
- Use realistic market-rate unit prices
- Generate 15-40 line items covering all trades present in the model
- Assign ordinals in format NN.NN.NNNN grouped by trade
- Each item must have a category from: Earthworks, Foundations, Concrete, Steel, \
Masonry, Roofing, Facades, Partitions, Floors, Windows & Doors, MEP, HVAC, \
Plumbing, Electrical, Fire Protection, Finishing, Landscaping, General
- Currency: {currency}
- Return ONLY the JSON array, no other text
"""

SYSTEM_PROMPT = """\
You are an expert construction cost estimator integrated into the OpenEstimate \
platform. You generate accurate, detailed Bills of Quantities with realistic \
market-rate pricing. Always return valid JSON arrays. Never include explanatory \
text outside the JSON structure.\
"""
