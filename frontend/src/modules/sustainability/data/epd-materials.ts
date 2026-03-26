/**
 * Embedded EPD (Environmental Product Declaration) material database.
 *
 * Data sourced from:
 * - Okobaudat (Germany) — https://www.oekobaudat.de
 * - ICE Database v3.0 (UK) — University of Bath
 * - EU Level(s) framework reference values
 *
 * GWP values in kg CO2e per declared unit.
 * All values are representative averages — actual EPDs vary by manufacturer.
 */

export interface EPDMaterial {
  id: string;
  name: string;
  category: EPDCategory;
  /** kg CO2e per declared unit */
  gwp: number;
  /** Declared unit (e.g. 'kg', 'm3', 'm2') */
  unit: string;
  /** Density in kg/m3 (for volume ↔ mass conversion) */
  density?: number;
  /** Data source */
  source: 'okobaudat' | 'ice_v3' | 'eu_levels';
  /** EPD lifecycle stages included (A1-A3 = cradle to gate) */
  stages: string;
  /** Additional notes */
  notes?: string;
}

export type EPDCategory =
  | 'concrete'
  | 'steel'
  | 'timber'
  | 'masonry'
  | 'insulation'
  | 'glass'
  | 'plastics'
  | 'finishes'
  | 'roofing'
  | 'foundations'
  | 'mep';

export const EPD_CATEGORIES: { id: EPDCategory; label: string }[] = [
  { id: 'concrete', label: 'Concrete & Cement' },
  { id: 'steel', label: 'Steel & Metals' },
  { id: 'timber', label: 'Timber & Wood' },
  { id: 'masonry', label: 'Masonry & Brick' },
  { id: 'insulation', label: 'Insulation' },
  { id: 'glass', label: 'Glass' },
  { id: 'plastics', label: 'Plastics & Membranes' },
  { id: 'finishes', label: 'Finishes & Coatings' },
  { id: 'roofing', label: 'Roofing' },
  { id: 'foundations', label: 'Foundations & Earthworks' },
  { id: 'mep', label: 'MEP Systems' },
];

export const EPD_MATERIALS: EPDMaterial[] = [
  // ── Concrete & Cement ──────────────────────────────────────────────
  { id: 'c20-25', name: 'Concrete C20/25', category: 'concrete', gwp: 214, unit: 'm3', density: 2400, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'c25-30', name: 'Concrete C25/30', category: 'concrete', gwp: 236, unit: 'm3', density: 2400, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'c30-37', name: 'Concrete C30/37', category: 'concrete', gwp: 264, unit: 'm3', density: 2400, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'c35-45', name: 'Concrete C35/45', category: 'concrete', gwp: 298, unit: 'm3', density: 2400, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'c40-50', name: 'Concrete C40/50', category: 'concrete', gwp: 328, unit: 'm3', density: 2400, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'c50-60', name: 'Concrete C50/60', category: 'concrete', gwp: 375, unit: 'm3', density: 2400, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'concrete-lc', name: 'Lightweight Concrete', category: 'concrete', gwp: 180, unit: 'm3', density: 1800, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'concrete-ggbs', name: 'Concrete with GGBS (50%)', category: 'concrete', gwp: 155, unit: 'm3', density: 2400, source: 'ice_v3', stages: 'A1-A3', notes: '50% GGBS cement replacement' },
  { id: 'concrete-pfa', name: 'Concrete with PFA (30%)', category: 'concrete', gwp: 190, unit: 'm3', density: 2400, source: 'ice_v3', stages: 'A1-A3', notes: '30% PFA cement replacement' },
  { id: 'cement-cem1', name: 'Portland Cement CEM I', category: 'concrete', gwp: 0.912, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'cement-cem2', name: 'Portland Composite CEM II', category: 'concrete', gwp: 0.76, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'rebar-steel', name: 'Reinforcing Steel (rebar)', category: 'concrete', gwp: 1.99, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'precast-hollow', name: 'Precast Hollowcore Slab', category: 'concrete', gwp: 285, unit: 'm3', density: 1500, source: 'okobaudat', stages: 'A1-A3' },
  { id: 'screed', name: 'Cement Screed', category: 'concrete', gwp: 195, unit: 'm3', density: 2100, source: 'okobaudat', stages: 'A1-A3' },

  // ── Steel & Metals ─────────────────────────────────────────────────
  { id: 'steel-structural', name: 'Structural Steel (sections)', category: 'steel', gwp: 1.53, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'steel-plate', name: 'Steel Plate', category: 'steel', gwp: 2.45, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'steel-stainless', name: 'Stainless Steel', category: 'steel', gwp: 6.15, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'steel-galvanized', name: 'Galvanized Steel Sheet', category: 'steel', gwp: 2.76, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'aluminium-primary', name: 'Aluminium (primary)', category: 'steel', gwp: 8.24, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'aluminium-recycled', name: 'Aluminium (recycled)', category: 'steel', gwp: 1.81, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'copper-pipe', name: 'Copper Pipe', category: 'steel', gwp: 3.83, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'zinc-sheet', name: 'Zinc Sheet', category: 'steel', gwp: 3.09, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },

  // ── Timber & Wood ──────────────────────────────────────────────────
  { id: 'timber-softwood', name: 'Softwood Timber (sawn)', category: 'timber', gwp: -1.63, unit: 'kg', source: 'okobaudat', stages: 'A1-A3', notes: 'Biogenic carbon stored' },
  { id: 'timber-hardwood', name: 'Hardwood Timber (sawn)', category: 'timber', gwp: -1.55, unit: 'kg', source: 'okobaudat', stages: 'A1-A3', notes: 'Biogenic carbon stored' },
  { id: 'timber-glulam', name: 'Glulam (GL24h)', category: 'timber', gwp: -1.38, unit: 'kg', source: 'okobaudat', stages: 'A1-A3', notes: 'Biogenic carbon stored' },
  { id: 'timber-clt', name: 'Cross-Laminated Timber (CLT)', category: 'timber', gwp: -1.42, unit: 'kg', source: 'okobaudat', stages: 'A1-A3', notes: 'Biogenic carbon stored' },
  { id: 'timber-osb', name: 'OSB Board', category: 'timber', gwp: -1.05, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'timber-plywood', name: 'Plywood', category: 'timber', gwp: -0.98, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'timber-mdf', name: 'MDF Board', category: 'timber', gwp: -0.59, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'timber-particle', name: 'Particleboard', category: 'timber', gwp: -0.68, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },

  // ── Masonry & Brick ────────────────────────────────────────────────
  { id: 'brick-clay', name: 'Clay Brick', category: 'masonry', gwp: 0.24, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'brick-calcium', name: 'Calcium Silicate Brick', category: 'masonry', gwp: 0.16, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'block-aac', name: 'AAC Block (Autoclaved Aerated Concrete)', category: 'masonry', gwp: 0.34, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'block-concrete', name: 'Concrete Block', category: 'masonry', gwp: 0.073, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'mortar-cement', name: 'Cement Mortar', category: 'masonry', gwp: 0.208, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'mortar-lime', name: 'Lime Mortar', category: 'masonry', gwp: 0.15, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'natural-stone', name: 'Natural Stone (limestone)', category: 'masonry', gwp: 0.062, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },

  // ── Insulation ─────────────────────────────────────────────────────
  { id: 'insul-eps', name: 'EPS (Expanded Polystyrene)', category: 'insulation', gwp: 3.29, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'insul-xps', name: 'XPS (Extruded Polystyrene)', category: 'insulation', gwp: 4.42, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'insul-mineral', name: 'Mineral Wool', category: 'insulation', gwp: 1.28, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'insul-glass', name: 'Glass Wool', category: 'insulation', gwp: 1.35, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'insul-pur', name: 'PUR/PIR Rigid Foam', category: 'insulation', gwp: 4.26, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'insul-cellulose', name: 'Cellulose Insulation', category: 'insulation', gwp: 0.17, unit: 'kg', source: 'okobaudat', stages: 'A1-A3', notes: 'Recycled newspaper based' },
  { id: 'insul-woodfibre', name: 'Wood Fibre Insulation', category: 'insulation', gwp: -1.16, unit: 'kg', source: 'okobaudat', stages: 'A1-A3', notes: 'Biogenic carbon stored' },
  { id: 'insul-cork', name: 'Cork Insulation', category: 'insulation', gwp: -0.72, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'insul-hempcrete', name: 'Hempcrete', category: 'insulation', gwp: -0.35, unit: 'kg', source: 'ice_v3', stages: 'A1-A3', notes: 'Bio-based composite' },

  // ── Glass ───────────────────────────────────────────────────────────
  { id: 'glass-float', name: 'Float Glass (4mm)', category: 'glass', gwp: 1.44, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'glass-double', name: 'Double Glazing Unit', category: 'glass', gwp: 34.2, unit: 'm2', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'glass-triple', name: 'Triple Glazing Unit', category: 'glass', gwp: 48.6, unit: 'm2', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'glass-tempered', name: 'Tempered Safety Glass', category: 'glass', gwp: 1.67, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },

  // ── Plastics & Membranes ───────────────────────────────────────────
  { id: 'pvc-pipe', name: 'PVC Pipe', category: 'plastics', gwp: 2.41, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'pe-membrane', name: 'PE Vapour Barrier', category: 'plastics', gwp: 2.54, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'epdm-membrane', name: 'EPDM Roofing Membrane', category: 'plastics', gwp: 3.18, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'bitumen-membrane', name: 'Bitumen Waterproofing', category: 'plastics', gwp: 0.86, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'sealant-silicone', name: 'Silicone Sealant', category: 'plastics', gwp: 4.26, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },

  // ── Finishes & Coatings ────────────────────────────────────────────
  { id: 'plaster-gypsum', name: 'Gypsum Plaster', category: 'finishes', gwp: 0.12, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'plasterboard', name: 'Plasterboard (12.5mm)', category: 'finishes', gwp: 0.39, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'paint-emulsion', name: 'Emulsion Paint', category: 'finishes', gwp: 2.12, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'tile-ceramic', name: 'Ceramic Floor Tile', category: 'finishes', gwp: 0.78, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'tile-porcelain', name: 'Porcelain Tile', category: 'finishes', gwp: 0.95, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'carpet-synthetic', name: 'Carpet (synthetic)', category: 'finishes', gwp: 5.53, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'laminate-floor', name: 'Laminate Flooring', category: 'finishes', gwp: 1.05, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'vinyl-floor', name: 'Vinyl Flooring (PVC)', category: 'finishes', gwp: 2.82, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },

  // ── Roofing ────────────────────────────────────────────────────────
  { id: 'roof-clay-tile', name: 'Clay Roof Tile', category: 'roofing', gwp: 0.45, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'roof-concrete-tile', name: 'Concrete Roof Tile', category: 'roofing', gwp: 0.22, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'roof-slate', name: 'Natural Slate', category: 'roofing', gwp: 0.058, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'roof-metal-standing', name: 'Standing Seam Metal Roof', category: 'roofing', gwp: 3.8, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'roof-green', name: 'Green Roof (extensive)', category: 'roofing', gwp: 18.5, unit: 'm2', source: 'okobaudat', stages: 'A1-A3', notes: 'Includes substrate, drainage, membrane' },

  // ── Foundations & Earthworks ────────────────────────────────────────
  { id: 'gravel-aggregate', name: 'Gravel / Aggregate', category: 'foundations', gwp: 0.0048, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'sand', name: 'Sand', category: 'foundations', gwp: 0.0051, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'geotextile', name: 'Geotextile Membrane', category: 'foundations', gwp: 2.54, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'dpm-pe', name: 'DPM (PE sheeting)', category: 'foundations', gwp: 2.54, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },

  // ── MEP Systems ────────────────────────────────────────────────────
  { id: 'cable-copper', name: 'Copper Electric Cable', category: 'mep', gwp: 4.45, unit: 'kg', source: 'ice_v3', stages: 'A1-A3' },
  { id: 'duct-galvanized', name: 'Galvanized Air Duct', category: 'mep', gwp: 2.76, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'pipe-copper', name: 'Copper Water Pipe', category: 'mep', gwp: 3.83, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'pipe-pe', name: 'PE-HD Water Pipe', category: 'mep', gwp: 1.93, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
  { id: 'radiator-steel', name: 'Steel Panel Radiator', category: 'mep', gwp: 2.12, unit: 'kg', source: 'okobaudat', stages: 'A1-A3' },
];

/** EU CPR 2024/3110 benchmark thresholds for GWP (kg CO2e / m2 GFA / year, 50yr RSP) */
export const EU_CPR_BENCHMARKS = {
  /** Below this = excellent */
  excellent: 8.0,
  /** Below this = good compliance */
  good: 12.0,
  /** Below this = acceptable */
  acceptable: 16.0,
  /** Above this = non-compliant */
  limit: 20.0,
};
