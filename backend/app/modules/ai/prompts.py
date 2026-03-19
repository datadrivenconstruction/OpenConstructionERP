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

SYSTEM_PROMPT = """\
You are an expert construction cost estimator integrated into the OpenEstimate \
platform. You generate accurate, detailed Bills of Quantities with realistic \
market-rate pricing. Always return valid JSON arrays. Never include explanatory \
text outside the JSON structure.\
"""
