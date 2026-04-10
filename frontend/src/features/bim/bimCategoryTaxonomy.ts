/**
 * BIM category taxonomy — bucket raw Revit categories and IFC entities
 * into a small set of semantic groups that estimators actually care about.
 *
 * Why this exists: a freshly-loaded RVT model exposes ~50–80 distinct
 * Revit categories, half of which are annotation noise ("Weak Dims",
 * "Area Scheme Lines", "Detail Components") or model-analytical only
 * ("Analytical Nodes", "Analytical Members"). Showing all of those as
 * filter chips drowns the building elements that matter for cost
 * estimation. We bucket them into semantic groups, with the noise
 * groups collapsed and de-emphasised by default.
 */

export type BIMCategoryBucket =
  | 'structure'
  | 'envelope'
  | 'openings'
  | 'finishes'
  | 'mep'
  | 'fixtures'
  | 'furniture'
  | 'site'
  | 'spaces'
  | 'annotation'
  | 'analytical'
  | 'other';

export interface BucketMeta {
  id: BIMCategoryBucket;
  label: string;
  /** Lower number = shown first. */
  order: number;
  /** Noise buckets (annotation/analytical) — collapsed by default and
   *  excluded by the "buildings only" toggle. */
  noise: boolean;
  /** Tailwind text colour token (matches existing oe-* palette). */
  color: string;
}

export const BUCKETS: Record<BIMCategoryBucket, BucketMeta> = {
  structure: { id: 'structure', label: 'Structure', order: 10, noise: false, color: 'text-orange-600' },
  envelope: { id: 'envelope', label: 'Envelope', order: 20, noise: false, color: 'text-sky-600' },
  openings: { id: 'openings', label: 'Doors & Windows', order: 30, noise: false, color: 'text-amber-600' },
  finishes: { id: 'finishes', label: 'Finishes', order: 40, noise: false, color: 'text-rose-500' },
  mep: { id: 'mep', label: 'MEP', order: 50, noise: false, color: 'text-emerald-600' },
  fixtures: { id: 'fixtures', label: 'Fixtures', order: 60, noise: false, color: 'text-violet-500' },
  furniture: { id: 'furniture', label: 'Furniture', order: 70, noise: false, color: 'text-fuchsia-500' },
  spaces: { id: 'spaces', label: 'Spaces & Rooms', order: 80, noise: false, color: 'text-teal-500' },
  site: { id: 'site', label: 'Site', order: 90, noise: false, color: 'text-lime-600' },
  other: { id: 'other', label: 'Other', order: 100, noise: false, color: 'text-slate-500' },
  annotation: { id: 'annotation', label: 'Annotations', order: 200, noise: true, color: 'text-slate-400' },
  analytical: { id: 'analytical', label: 'Analytical model', order: 210, noise: true, color: 'text-slate-400' },
};

/* ── Mapping rules ───────────────────────────────────────────────────────
 *
 * Both Revit category names and IFC entity names are normalised
 * (lowercase, alphanumeric only) and matched against this table. The
 * first matching pattern wins.  Order matters — more specific patterns
 * must come before broader ones.
 */

interface Rule {
  /** Substring match against the normalised category. */
  match: string;
  bucket: BIMCategoryBucket;
}

const RULES: Rule[] = [
  // ── Annotations / drafting noise (most specific first) ─────────────
  { match: 'analyticalnode', bucket: 'analytical' },
  { match: 'analyticalmember', bucket: 'analytical' },
  { match: 'analytical', bucket: 'analytical' },
  { match: 'weakdim', bucket: 'annotation' },
  { match: 'dimension', bucket: 'annotation' },
  { match: 'areaschemeline', bucket: 'annotation' },
  { match: 'areascheme', bucket: 'annotation' },
  { match: 'arealine', bucket: 'annotation' },
  { match: 'detailcomponent', bucket: 'annotation' },
  { match: 'detailitem', bucket: 'annotation' },
  { match: 'genericannotation', bucket: 'annotation' },
  { match: 'annotation', bucket: 'annotation' },
  { match: 'tag', bucket: 'annotation' },
  { match: 'callout', bucket: 'annotation' },
  { match: 'sectionbox', bucket: 'annotation' },
  { match: 'sectionline', bucket: 'annotation' },
  { match: 'referenceplane', bucket: 'annotation' },
  { match: 'referenceline', bucket: 'annotation' },
  { match: 'gridhead', bucket: 'annotation' },
  { match: 'levelhead', bucket: 'annotation' },
  { match: 'cameras', bucket: 'annotation' },
  { match: 'viewport', bucket: 'annotation' },
  { match: 'sheet', bucket: 'annotation' },
  { match: 'matchline', bucket: 'annotation' },
  { match: 'titleblock', bucket: 'annotation' },
  { match: 'ifcannotation', bucket: 'annotation' },

  // ── Structure ─────────────────────────────────────────────────────
  { match: 'structuralcolumn', bucket: 'structure' },
  { match: 'structuralbeam', bucket: 'structure' },
  { match: 'structuralframing', bucket: 'structure' },
  { match: 'structuralfoundation', bucket: 'structure' },
  { match: 'structuralrebar', bucket: 'structure' },
  { match: 'structuraltruss', bucket: 'structure' },
  { match: 'structuralconnection', bucket: 'structure' },
  { match: 'structural', bucket: 'structure' },
  { match: 'foundation', bucket: 'structure' },
  { match: 'pile', bucket: 'structure' },
  { match: 'rebar', bucket: 'structure' },
  { match: 'ifccolumn', bucket: 'structure' },
  { match: 'ifcbeam', bucket: 'structure' },
  { match: 'ifcfooting', bucket: 'structure' },
  { match: 'ifcpile', bucket: 'structure' },
  { match: 'ifcmember', bucket: 'structure' },
  { match: 'ifcplate', bucket: 'structure' },
  { match: 'ifcreinforcingbar', bucket: 'structure' },
  { match: 'ifcreinforcingmesh', bucket: 'structure' },

  // ── Envelope (walls, slabs, roofs, curtain) ───────────────────────
  { match: 'curtainwall', bucket: 'envelope' },
  { match: 'curtaingrid', bucket: 'envelope' },
  { match: 'curtainpanel', bucket: 'envelope' },
  { match: 'curtainsystem', bucket: 'envelope' },
  { match: 'mullion', bucket: 'envelope' },
  { match: 'wall', bucket: 'envelope' },
  { match: 'floor', bucket: 'envelope' },
  { match: 'slab', bucket: 'envelope' },
  { match: 'roof', bucket: 'envelope' },
  { match: 'ceiling', bucket: 'envelope' },
  { match: 'stair', bucket: 'envelope' },
  { match: 'ramp', bucket: 'envelope' },
  { match: 'railing', bucket: 'envelope' },
  { match: 'ifcwall', bucket: 'envelope' },
  { match: 'ifcslab', bucket: 'envelope' },
  { match: 'ifcroof', bucket: 'envelope' },
  { match: 'ifccovering', bucket: 'finishes' },
  { match: 'ifcceiling', bucket: 'envelope' },
  { match: 'ifcstair', bucket: 'envelope' },
  { match: 'ifcramp', bucket: 'envelope' },
  { match: 'ifcrailing', bucket: 'envelope' },
  { match: 'ifccurtainwall', bucket: 'envelope' },
  { match: 'ifcplatecurtain', bucket: 'envelope' },

  // ── Openings (doors / windows / openings) ─────────────────────────
  { match: 'door', bucket: 'openings' },
  { match: 'window', bucket: 'openings' },
  { match: 'opening', bucket: 'openings' },
  { match: 'ifcdoor', bucket: 'openings' },
  { match: 'ifcwindow', bucket: 'openings' },
  { match: 'ifcopeningelement', bucket: 'openings' },

  // ── MEP (mechanical, electrical, plumbing) ────────────────────────
  { match: 'duct', bucket: 'mep' },
  { match: 'pipe', bucket: 'mep' },
  { match: 'cabletray', bucket: 'mep' },
  { match: 'conduit', bucket: 'mep' },
  { match: 'mechanicalequipment', bucket: 'mep' },
  { match: 'electricalequipment', bucket: 'mep' },
  { match: 'electricalfixture', bucket: 'mep' },
  { match: 'lightingfixture', bucket: 'mep' },
  { match: 'lightingdevice', bucket: 'mep' },
  { match: 'plumbingfixture', bucket: 'fixtures' },
  { match: 'plumbing', bucket: 'mep' },
  { match: 'sprinkler', bucket: 'mep' },
  { match: 'fireprotection', bucket: 'mep' },
  { match: 'firealarm', bucket: 'mep' },
  { match: 'datadevice', bucket: 'mep' },
  { match: 'communicationdevice', bucket: 'mep' },
  { match: 'securitydevice', bucket: 'mep' },
  { match: 'nursecalldevice', bucket: 'mep' },
  { match: 'telephonedevice', bucket: 'mep' },
  { match: 'mep', bucket: 'mep' },
  { match: 'mechanical', bucket: 'mep' },
  { match: 'electrical', bucket: 'mep' },
  { match: 'ifcductsegment', bucket: 'mep' },
  { match: 'ifcductfitting', bucket: 'mep' },
  { match: 'ifcpipesegment', bucket: 'mep' },
  { match: 'ifcpipefitting', bucket: 'mep' },
  { match: 'ifccabletray', bucket: 'mep' },
  { match: 'ifccableseg', bucket: 'mep' },
  { match: 'ifcsanitaryterminal', bucket: 'fixtures' },
  { match: 'ifcfiresuppression', bucket: 'mep' },
  { match: 'ifcairterminal', bucket: 'mep' },
  { match: 'ifcvalve', bucket: 'mep' },
  { match: 'ifcboiler', bucket: 'mep' },
  { match: 'ifcpump', bucket: 'mep' },
  { match: 'ifctank', bucket: 'mep' },
  { match: 'ifcunitaryequipment', bucket: 'mep' },
  { match: 'ifcflowterminal', bucket: 'mep' },
  { match: 'ifcflowfitting', bucket: 'mep' },
  { match: 'ifcflowsegment', bucket: 'mep' },
  { match: 'ifcdistributionelement', bucket: 'mep' },

  // ── Furniture & specialty equipment ───────────────────────────────
  { match: 'furniturepart', bucket: 'furniture' },
  { match: 'furniturefamily', bucket: 'furniture' },
  { match: 'furniture', bucket: 'furniture' },
  { match: 'specialtyequipment', bucket: 'fixtures' },
  { match: 'casework', bucket: 'furniture' },
  { match: 'planting', bucket: 'site' },
  { match: 'ifcfurnishingelement', bucket: 'furniture' },
  { match: 'ifcfurniture', bucket: 'furniture' },
  { match: 'ifcsystemfurniture', bucket: 'furniture' },

  // ── Spaces / rooms / zones ────────────────────────────────────────
  { match: 'room', bucket: 'spaces' },
  { match: 'space', bucket: 'spaces' },
  { match: 'area', bucket: 'spaces' },
  { match: 'zone', bucket: 'spaces' },
  { match: 'ifcspace', bucket: 'spaces' },
  { match: 'ifczone', bucket: 'spaces' },

  // ── Site ──────────────────────────────────────────────────────────
  { match: 'topography', bucket: 'site' },
  { match: 'parking', bucket: 'site' },
  { match: 'roads', bucket: 'site' },
  { match: 'ifcsite', bucket: 'site' },
  { match: 'ifcgeographicelement', bucket: 'site' },
];

/** Normalise a raw category string for rule matching. */
function normalise(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/** Resolve a raw category to its semantic bucket. */
export function bucketOf(rawCategory: string | undefined): BIMCategoryBucket {
  if (!rawCategory) return 'other';
  const norm = normalise(rawCategory);
  if (!norm) return 'other';
  for (const rule of RULES) {
    if (norm.includes(rule.match)) return rule.bucket;
  }
  return 'other';
}

/** True if the category falls into a noise bucket (annotation / analytical). */
export function isNoiseCategory(rawCategory: string | undefined): boolean {
  return BUCKETS[bucketOf(rawCategory)].noise;
}
