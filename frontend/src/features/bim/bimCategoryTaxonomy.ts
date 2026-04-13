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

/* ── Display prettifier ──────────────────────────────────────────────────
 *
 * Real-world Revit ingestion produces lowercase concatenated category
 * names like "Curtainwallmullions" or "Structuralcolumns" instead of
 * the natural "Curtain Wall Mullions" / "Structural Columns".  This
 * helper provides a *display-only* pretty form for the chips, while
 * the raw key stays unchanged for filter matching.
 *
 * Strategy: a curated lookup table of the well-known Revit categories
 * that show up everywhere in real models.  For anything NOT in the
 * table we return the raw value with the first letter capitalised —
 * never try to guess word boundaries algorithmically because the
 * wrong split ("Stair Srailingbaluster") is worse than an
 * ugly-but-correct concatenated word.
 */
const KNOWN_CATEGORIES: Record<string, string> = {
  none: 'Uncategorised',

  // Architectural
  walls: 'Walls',
  doors: 'Doors',
  windows: 'Windows',
  floors: 'Floors',
  ceilings: 'Ceilings',
  roofs: 'Roofs',
  stairs: 'Stairs',
  ramps: 'Ramps',
  columns: 'Columns',
  furniture: 'Furniture',
  casework: 'Casework',
  rooms: 'Rooms',
  areas: 'Areas',
  spaces: 'Spaces',
  curtainwall: 'Curtain Wall',
  curtainwallmullions: 'Curtain Wall Mullions',
  curtainwallpanels: 'Curtain Wall Panels',
  curtaingridswall: 'Curtain Wall Grids',
  curtaingridsroof: 'Curtain Roof Grids',
  curtainsystem: 'Curtain System',
  stairsrailing: 'Stair Railings',
  stairsrailingbaluster: 'Stair Balusters',
  stairsstringercarriage: 'Stair Stringers',
  stairspaths: 'Stair Paths',
  stairsruns: 'Stair Runs',
  stairstrisers: 'Stair Risers',
  stairscutmarks: 'Stair Cut Marks',
  stairslandings: 'Stair Landings',
  multistorystairs: 'Multistory Stairs',
  railinghandrail: 'Railing Handrails',
  railingtoprail: 'Railing Top Rails',
  stackedwalls: 'Stacked Walls',
  roofsoffit: 'Roof Soffit',
  fascia: 'Fascia',
  gutter: 'Gutter',
  reveals: 'Reveals',
  cornices: 'Cornices',
  edgeslab: 'Slab Edges',

  // Structural
  structuralcolumns: 'Structural Columns',
  structuralframing: 'Structural Framing',
  structuralframingsystem: 'Structural Framing System',
  structuralfoundation: 'Structural Foundation',
  structuraltruss: 'Structural Truss',
  structuralconnection: 'Structural Connections',
  structuralrebar: 'Structural Rebar',
  rebarbendingdetails: 'Rebar Bending Details',
  reinforcingbar: 'Reinforcing Bars',
  reinforcingmesh: 'Reinforcing Mesh',
  pile: 'Piles',
  piles: 'Piles',
  foundation: 'Foundation',
  beams: 'Beams',

  // MEP
  mechanicalequipment: 'Mechanical Equipment',
  electricalequipment: 'Electrical Equipment',
  electricalfixtures: 'Electrical Fixtures',
  lightingfixtures: 'Lighting Fixtures',
  lightingdevices: 'Lighting Devices',
  plumbingfixtures: 'Plumbing Fixtures',
  pipingsystem: 'Piping System',
  pipesegments: 'Pipe Segments',
  pipefittings: 'Pipe Fittings',
  pipecurves: 'Pipe Curves',
  pipeconnections: 'Pipe Connections',
  pipeschedules: 'Pipe Schedules',
  pipematerials: 'Pipe Materials',
  flexpipecurves: 'Flex Pipe Curves',
  ductsystem: 'Duct System',
  ductsegments: 'Duct Segments',
  ductfittings: 'Duct Fittings',
  ductcurves: 'Duct Curves',
  flexductcurves: 'Flex Duct Curves',
  airterminal: 'Air Terminals',
  cabletray: 'Cable Tray',
  conduit: 'Conduit',
  conduitstandards: 'Conduit Standards',
  wire: 'Wires',
  wireinsulations: 'Wire Insulations',
  wirematerials: 'Wire Materials',
  wiretemperatureratings: 'Wire Temperature Ratings',
  fluids: 'Fluids',
  electricalvoltage: 'Electrical Voltage',
  elecdistributionsys: 'Electrical Distribution',
  hvac: 'HVAC',
  'hvac load schedules': 'HVAC Load Schedules',
  'hvac zones': 'HVAC Zones',
  mepsystemzone: 'MEP System Zones',
  sprinklers: 'Sprinklers',
  fireprotection: 'Fire Protection',
  firealarmdevices: 'Fire Alarm Devices',
  securitydevices: 'Security Devices',
  communicationdevices: 'Communication Devices',
  datadevices: 'Data Devices',
  switchboardscheduletemplates: 'Switchboard Schedules',
  branchpanelscheduletemplates: 'Branch Panel Schedules',
  datapanelscheduletemplates: 'Data Panel Schedules',
  electricaldemandfactordefinitions: 'Electrical Demand Factor',
  electricalloadclassifications: 'Electrical Load Classifications',
  pipeinsulations: 'Pipe Insulations',
  ductinsulations: 'Duct Insulations',

  // Site
  topography: 'Topography',
  topographycontours: 'Topography Contours',
  toposolid: 'Topo Solid',
  buildingpad: 'Building Pad',
  parking: 'Parking',
  planting: 'Planting',
  entourage: 'Entourage',
  siteproperty: 'Site Property',
  sitepropertylinesegment: 'Site Property Lines',
  sitepropertylinesegmenttags: 'Site Property Tags',

  // Mass / massing
  mass: 'Mass',
  massform: 'Mass Form',
  massfloor: 'Mass Floor',
  massfloors: 'Mass Floors',
  massfloorsall: 'Mass Floors (All)',
  masswallsall: 'Mass Walls (All)',
  massroof: 'Mass Roof',
  massshade: 'Mass Shades',
  massglazingall: 'Mass Glazing (All)',
  massopening: 'Mass Openings',

  // Generic / model groups
  genericmodel: 'Generic Models',
  genericannotation: 'Generic Annotations',
  iosmodelgroups: 'Model Groups',
  iosdetailgroups: 'Detail Groups',
  iossketchgrid: 'Sketch Grids',
  iosgeolocations: 'Geo Locations',
  iosgeosite: 'Geo Site',
  iosarrays: 'Arrays',

  // Annotations / drafting / view-only
  detailcomponents: 'Detail Components',
  detailitems: 'Detail Items',
  sketchlines: 'Sketch Lines',
  weakdims: 'Weak Dimensions',
  dimensions: 'Dimensions',
  doortags: 'Door Tags',
  windowtags: 'Window Tags',
  roomtags: 'Room Tags',
  walltags: 'Wall Tags',
  areatags: 'Area Tags',
  keynotetags: 'Keynote Tags',
  materialtags: 'Material Tags',
  revisioncloudtags: 'Revision Cloud Tags',
  revisionclouds: 'Revision Clouds',
  revisions: 'Revisions',
  revisionnumberingsequences: 'Revision Sequences',
  areaschemes: 'Area Schemes',
  areaschemelines: 'Area Scheme Lines',
  roomseparationlines: 'Room Separation Lines',
  textnotes: 'Text Notes',
  schedules: 'Schedules',
  schedulegraphics: 'Schedule Graphics',
  rasterimages: 'Raster Images',
  colorfilllegends: 'Color Fill Legends',
  colorfillschema: 'Color Fill Schema',
  spotelevsymbols: 'Spot Elevation Symbols',
  elevationmarks: 'Elevation Marks',
  sectionheads: 'Section Heads',
  sectionbox: 'Section Box',
  callouthead: 'Callout Heads',
  calloutheads: 'Callout Heads',
  gridheads: 'Grid Heads',
  levelheads: 'Level Heads',
  matchline: 'Match Lines',
  viewportlabel: 'Viewport Labels',
  referenceviewersymbol: 'Reference Viewer',
  multireferenceannotations: 'Multi-Reference Annotations',
  profilefamilies: 'Profile Families',
  profileplane: 'Profile Planes',
  referenceplane: 'Reference Planes',
  referenceline: 'Reference Lines',
  constraints: 'Constraints',
  loadcases: 'Load Cases',
  tilepatterns: 'Tile Patterns',
  divisionrules: 'Division Rules',
  lines: 'Detail Lines',
  clines: 'Construction Lines',
  shaftopening: 'Shaft Openings',
  swallrectopening: 'Wall Rect Openings',

  // Analytical
  analyticalnodes: 'Analytical Nodes',
  analyticalmember: 'Analytical Members',
  analyticalpipeconnections: 'Analytical Pipe Connections',
  linksanalytical: 'Analytical Links',

  // Project / system
  projectinformation: 'Project Information',
  projectbasepoint: 'Project Base Point',
  sharedbasepoint: 'Shared Base Point',
  coordinatesystem: 'Coordinate System',
  eaconstructions: 'Energy Analysis Constructions',
  covertype: 'Cover Types',
  mechanicalequipmentset: 'Mechanical Equipment Set',
};

/**
 * Pretty-print a normalised Revit/IFC category name for display.
 *
 * - Lookups in the curated `KNOWN_CATEGORIES` table win first.
 * - "None" / empty → "Uncategorised".
 * - Already-spaced strings ("Hvac Load Schedules") and IFC entities
 *   ("IfcWall") pass through unchanged.
 * - Anything else gets first-letter capitalised but is otherwise
 *   un-touched — never algorithmically guessing word boundaries.
 *
 * Examples:
 *   prettifyCategoryName("Walls")               → "Walls"
 *   prettifyCategoryName("Curtainwallmullions") → "Curtain Wall Mullions"
 *   prettifyCategoryName("Structuralcolumns")   → "Structural Columns"
 *   prettifyCategoryName("Newcategory")         → "Newcategory"
 *   prettifyCategoryName("None")                → "Uncategorised"
 *   prettifyCategoryName("IfcWall")             → "IfcWall"
 */
export function prettifyCategoryName(raw: string | undefined | null): string {
  if (!raw) return '—';
  const trimmed = raw.trim();
  if (trimmed === '') return '—';
  const looked = KNOWN_CATEGORIES[trimmed.toLowerCase()];
  if (looked !== undefined) return looked;
  // Already has spaces → pass through
  if (/\s/.test(trimmed)) return trimmed;
  // IFC entity → pass through
  if (/^Ifc[A-Z]/.test(trimmed)) return trimmed;
  // Otherwise: just capitalise the first letter, leave the rest
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

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
  // ── Universal junk: the "None" Revit ingest bucket (no category at all).
  //    Treated as noise so the buildings-only view doesn't pollute the
  //    real category list with thousands of uncategorised rows.
  { match: 'none', bucket: 'annotation' },

  // ── Analytical model (structural physics) ───────────────────────────
  { match: 'analytical', bucket: 'analytical' },

  // ── Annotations / drafting / view-only categories ──────────────────
  //    Conservative — only patterns that are universally annotation-only
  //    across Revit + IFC + every other CAD source.
  { match: 'dimension', bucket: 'annotation' },
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
