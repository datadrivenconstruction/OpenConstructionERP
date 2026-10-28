// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bundled seed packs for the Rule Library browser.
 *
 * The YAML files that the backend ships at `data/bim_rules/*.yaml` are
 * inlined here as raw strings so the library works offline (no backend
 * round-trip required to populate the catalogue). The user can preview the
 * raw YAML, edit it locally, and call `install-from-yaml` only when they
 * decide to install.
 *
 * Each requirement template exists in two flavours that check the *same*
 * design intent against the two ways models arrive:
 *   - `ifc`   — selects by IFC entity class (IfcWall, IfcSpace, …) and
 *               asserts Pset-style property names (FireRating, ClearWidth).
 *   - `revit` — selects by Revit category (Walls, Rooms, …) and asserts
 *               Revit parameter names (Fire Rating, Width, DIN_276_Code),
 *               noting Type vs Instance vs Shared parameters in each rule.
 *
 * Keep these strings byte-identical to the source files in `data/bim_rules/`
 * - they are the canonical artefact. If the backend rules change, update
 * this file in the same PR so the library does not drift.
 */

export type SeedPackCategory =
  | 'Accessibility'
  | 'Cost Classification'
  | 'Fire Safety'
  | 'MEP'
  | 'Naming';

/** Which authoring format a template is written for. */
export type SeedPackFormat = 'ifc' | 'revit';

export interface SeedPack {
  id: string;
  name: string;
  description: string;
  source: string;
  version: string;
  regions: string[];
  classifications: string[];
  rule_count: number;
  category: SeedPackCategory;
  /** Authoring format the template targets (IFC entity class vs Revit category). */
  format: SeedPackFormat;
  yaml: string;
}

const DIN_276_KG_COMPLETENESS_YAML = `# DIN 276 cost-group completeness audit.
#
# Every IfcElement that contributes to the building substance must carry a
# DIN 276 cost-group code in its classification block. The check fails the
# element when the \`din276\` classifier is missing OR does not fall within
# the building-structure ranges 300 (Bauwerk - Baukonstruktion), 400
# (Bauwerk - Technische Anlagen) or 500 (Außenanlagen und Freiflächen),
# matching DIN 276:2018-12 §3.2.
#
# Why this matters: cost models built on top of an unclassified BIM model
# silently aggregate into "other", which is invisible in cost-group
# rollups and devastating for client reporting.
schema_version: "1.0"
pack:
  id: din_276_kg_completeness
  name: DIN 276 Cost-Group Completeness
  description: |
    Verifies that every building element carries a DIN 276 cost-group
    code in the 300, 400 or 500 ranges so cost-group rollups are
    well-defined.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276"]
    project_regions: ["DE", "AT", "CH", "LU"]

rules:
  - id: din276_code_present
    name: DIN 276 cost-group code present on every element
    severity: error
    rationale: |
      DIN 276:2018-12 §3.2 - every element of the building substance is
      assigned to a cost group. Missing codes cause silent leakage in
      cost-group rollups.
    selector:
      ifc_class: IfcElement
    assertion:
      property:
        key: din276
        op: exists
        value: true
    failure_message: "Element has no DIN 276 cost-group code."

  - id: din276_code_in_building_range
    name: DIN 276 code must be in the 300/400/500 series
    severity: warning
    rationale: |
      Cost groups 100/200/600/700 cover land, soft costs and FF&E and
      should not normally appear on building elements.
    selector:
      ifc_class: IfcElement
      properties:
        - { key: din276, op: exists, value: true }
    assertion:
      property:
        key: din276
        op: regex
        value: "^[345][0-9]{2}$"
    failure_message: "DIN 276 code '{{din276}}' is outside the building-structure ranges (300/400/500)."
`;

const CLEARANCE_CORRIDOR_DOOR_YAML = `# Accessibility clearance audit (DIN 18040-1 - barrier-free public buildings).
#
# - Corridors (IfcSpace where SpaceType=Corridor) must have a clear width
#   of at least 1.50 m per DIN 18040-1 §4.3.6.
# - Doors on barrier-free routes must have a clear opening width of at
#   least 0.90 m per DIN 18040-1 §4.3.3.2.
#
# Both checks are property-based: the model author is expected to expose
# \`Width\` (m) on IfcSpace and \`ClearWidth\` (m) on IfcDoor.
schema_version: "1.0"
pack:
  id: clearance_corridor_door
  name: DIN 18040-1 Corridor and Door Clearance
  description: |
    Validates barrier-free clearance dimensions for corridors and doors
    per DIN 18040-1 (public buildings, accessible routes).
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276", "DIN18040"]
    project_regions: ["DE", "AT", "CH"]

rules:
  - id: corridor_minimum_width
    name: Corridor minimum clear width 1.50 m
    severity: warning
    rationale: |
      DIN 18040-1 §4.3.6 - main corridors on accessible routes must allow
      two wheelchair users to pass; minimum clear width is 1.50 m.
    selector:
      ifc_class: IfcSpace
      properties:
        - { key: SpaceType, op: eq, value: Corridor }
    assertion:
      property:
        key: Width
        op: gte
        value: 1.5
        unit: m
    failure_message: "Corridor width {{Width}} m is below the 1.50 m DIN 18040-1 minimum."

  - id: door_clear_width
    name: Door clear opening width 0.90 m on accessible routes
    severity: error
    rationale: |
      DIN 18040-1 §4.3.3.2 - doors on accessible routes require a clear
      opening width of 0.90 m measured between the leaf at 90 ° and the
      stop on the opposite jamb.
    selector:
      ifc_class: IfcDoor
      properties:
        - { key: OnAccessibleRoute, op: eq, value: true }
    assertion:
      property:
        key: ClearWidth
        op: gte
        value: 0.9
        unit: m
    failure_message: "Door clear width {{ClearWidth}} m is below the 0.90 m DIN 18040-1 minimum."
`;

const FIRE_COMPARTMENT_PROPERTY_YAML = `# Internal-wall fire-rating completeness.
#
# Every interior wall (IfcWall with IsExternal=false) must declare a
# FireRating property. The set of acceptable values follows DIN 4102-2 /
# EN 13501-2 ("F30", "F60", "F90", "F120", "F180") plus the explicit
# "none" sentinel for walls intentionally outside any fire compartment
# (which still must be recorded - silent absence is the failure case).
schema_version: "1.0"
pack:
  id: fire_compartment_property
  name: Interior Wall Fire-Rating Completeness
  description: |
    Validates that every internal wall declares a FireRating value
    drawn from the DIN 4102-2 / EN 13501-2 vocabulary.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276", "DIN4102"]
    project_regions: ["DE", "AT", "CH"]

rules:
  - id: internal_wall_fire_rating_present
    name: FireRating present on every internal wall
    severity: error
    rationale: |
      Fire-compartment design fails silently when wall fire-ratings are
      missing; this rule guarantees the property is at least populated
      before any compartment-completeness audit runs downstream.
    selector:
      ifc_class: IfcWall
      properties:
        - { key: IsExternal, op: eq, value: false }
    assertion:
      property:
        key: FireRating
        op: exists
        value: true
    failure_message: "Internal wall has no FireRating property."

  - id: internal_wall_fire_rating_valid
    name: FireRating value drawn from DIN 4102 / EN 13501 vocabulary
    severity: warning
    rationale: |
      Ratings outside the standard vocabulary cannot be aggregated into
      compartment certificates and force manual review.
    selector:
      ifc_class: IfcWall
      properties:
        - { key: IsExternal, op: eq, value: false }
        - { key: FireRating, op: exists, value: true }
    assertion:
      property:
        key: FireRating
        op: in
        value: ["none", "F30", "F60", "F90", "F120", "F180"]
    failure_message: "FireRating '{{FireRating}}' is not in the DIN 4102 / EN 13501 vocabulary."
`;

const MEP_CLEARANCE_YAML = `# MEP-to-structure clearance.
#
# Pipe segments must keep at least 100 mm of clearance from structural
# beams to allow insulation, sleeves and tolerance during installation
# (cf. VDI 2055 §6.3 - Wärmedämmung an betriebstechnischen Anlagen).
#
# This is the canonical *set-vs-set* rule: it pairs every IfcPipeSegment
# (selector set) with every IfcBeam (other_selector set) and asserts a
# clearance property. The runtime knows how to handle the rule_type and
# the YAML carries the clearance metadata so a future geometric engine
# can swap in a true coordinate-based clearance check without changing
# the rule file.
schema_version: "1.0"
pack:
  id: mep_clearance
  name: MEP-to-Structure Clearance
  description: |
    Validates that pipe segments maintain a minimum 100 mm clearance
    from structural beams per VDI 2055.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276"]
    project_regions: ["DE", "AT", "CH"]

rules:
  - id: pipe_to_beam_clearance_100mm
    name: Pipe segment ≥ 100 mm from structural beam
    severity: error
    rule_type: set_vs_set
    rationale: |
      VDI 2055 §6.3 requires sufficient clearance around insulated pipe
      runs for insulation thickness, fastenings and maintenance access.
      The 100 mm threshold matches DN 80 insulated piping in
      uncongested service ceilings.
    selector:
      ifc_class: IfcPipeSegment
    assertion:
      set_vs_set:
        other_selector:
          ifc_class: IfcBeam
        metric: clearance
        property:
          key: ClearanceToStructure
          op: gte
          value: 0.1
          unit: m
    failure_message: "Pipe {{id}} clearance {{ClearanceToStructure}} m is below the 100 mm minimum to nearby beam."
`;

const ROOM_NAMING_CONVENTION_YAML = `# Room-code naming convention.
#
# IfcSpace.Name must match the canonical "<DEPT>.<LEVEL>.<ROOM>" pattern,
# e.g. "OR.02.001" for Operating Room, Level 02, Room 001. This is the
# typical Helsinki model-checking-tool-style room-coding scheme used to bridge
# architectural plans to FM systems and BIMQ exports.
schema_version: "1.0"
pack:
  id: room_naming_convention
  name: Room-Code Naming Convention
  description: |
    Enforces the canonical "<DEPT>.<LEVEL>.<ROOM>" room-code naming
    convention on IfcSpace.Name so downstream FM exports parse cleanly.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276", "COBie"]
    project_regions: []

rules:
  - id: space_name_matches_room_code_pattern
    name: IfcSpace.Name follows "<DEPT>.<LEVEL>.<ROOM>" pattern
    severity: warning
    rationale: |
      FM systems and COBie exports depend on the room-code structure to
      key rooms across disciplines. Non-conforming names break the join
      and force manual reconciliation.
    selector:
      ifc_class: IfcSpace
    assertion:
      property:
        key: Name
        op: regex
        value: "^[A-Z]{2}\\\\.[0-9]{2}\\\\.[0-9]{3}$"
    failure_message: "Space name '{{Name}}' does not match the <DEPT>.<LEVEL>.<ROOM> pattern (e.g. OR.02.001)."
`;

// ── Revit-flavoured twins ──────────────────────────────────────────────────
// Same design intent as the IFC packs above, re-expressed with Revit
// categories (selectors) and Revit parameter names (assertions). Each rule's
// rationale calls out whether a parameter is a Type, Instance or Shared
// parameter so the template doubles as a short Revit-authoring guide.

const REVIT_COST_CLASSIFICATION_YAML = `# Revit cost-classification completeness (DIN 276).
#
# Every enclosing and load-bearing element modelled in Revit must carry a
# DIN 276 cost-group code so cost-group rollups are well-defined. DIN 276
# is not a built-in Revit parameter, so the code lives in a shared
# parameter named "DIN_276_Code" (Text) that schedules, tags and exports
# cleanly. The built-in "Assembly Code" type parameter carries Uniformat,
# not DIN 276, so it cannot stand in for this.
#
# This is the Revit-flavoured twin of din_276_kg_completeness (IFC). In a
# real project the same pair of rules is replicated per model category
# (Walls, Floors, Roofs, Structural Columns, ...); Walls are the worked
# example here.
schema_version: "1.0"
pack:
  id: revit_cost_classification
  name: DIN 276 Cost-Group Completeness (Revit)
  description: |
    Verifies that every Revit® wall carries a DIN 276 cost-group code in the
    300, 400 or 500 ranges, stored in the DIN_276_Code shared parameter, so
    cost-group rollups are well-defined.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276"]
    project_regions: ["DE", "AT", "CH", "LU"]

rules:
  - id: revit_din276_code_present
    name: DIN_276_Code shared parameter present on every wall
    severity: error
    rationale: |
      DIN 276 is not a native Revit parameter. Add it as a shared
      parameter "DIN_276_Code" (Text) bound to the Walls category so it can
      be scheduled and exported. The built-in "Assembly Code" type
      parameter holds Uniformat, not DIN 276, and cannot substitute.
    selector:
      ifc_class: Walls
    assertion:
      property:
        key: DIN_276_Code
        op: exists
        value: true
    failure_message: "Wall {{id}} has no DIN_276_Code shared parameter."

  - id: revit_din276_code_in_building_range
    name: DIN_276_Code must be in the 300/400/500 series
    severity: warning
    rationale: |
      Cost groups 100/200/600/700 cover land, soft costs and FF and E and
      should not normally appear on building elements. DIN_276_Code is the
      shared parameter carrying the value.
    selector:
      ifc_class: Walls
      properties:
        - { key: DIN_276_Code, op: exists, value: true }
    assertion:
      property:
        key: DIN_276_Code
        op: regex
        value: "^[345][0-9]{2}$"
    failure_message: "DIN 276 code {{DIN_276_Code}} on wall {{id}} is outside the building-structure ranges (300/400/500)."
`;

const REVIT_CORRIDOR_DOOR_CLEARANCE_YAML = `# Accessibility clearance audit for Revit models (DIN 18040-1).
#
# - Corridors (Rooms whose built-in "Occupancy" instance parameter reads
#   "Corridor") must have a clear width of at least 1.50 m per
#   DIN 18040-1 4.3.6. Revit Rooms have no built-in clear-width, so the
#   value lives in a shared parameter "Clear Width" (m).
# - Doors on barrier-free routes must have a clear opening width of at
#   least 0.90 m per DIN 18040-1 4.3.3.2. Door "Width" is the built-in
#   type parameter; "Accessible Route" is a project/shared Yes/No flag.
#
# Revit-flavoured twin of clearance_corridor_door (IFC).
schema_version: "1.0"
pack:
  id: revit_corridor_door_clearance
  name: Corridor and Door Clearance (Revit)
  description: |
    Validates barrier-free clearance for Revit® Rooms tagged as corridors
    and for Doors on accessible routes, per DIN 18040-1 (public buildings).
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276", "DIN18040"]
    project_regions: ["DE", "AT", "CH"]

rules:
  - id: revit_corridor_minimum_width
    name: Corridor room minimum clear width 1.50 m
    severity: warning
    rationale: |
      DIN 18040-1 4.3.6 - main corridors on accessible routes must let two
      wheelchair users pass; minimum clear width is 1.50 m. "Occupancy" is
      a built-in Rooms instance parameter; "Clear Width" is a shared
      parameter (Revit has no built-in clear-width for Rooms); "Number" is
      the built-in Rooms instance parameter used as the room key.
    selector:
      ifc_class: Rooms
      properties:
        - { key: Occupancy, op: eq, value: Corridor }
    assertion:
      property:
        key: Clear Width
        op: gte
        value: 1.5
        unit: m
    failure_message: "Corridor room {{Number}} has a clear width below the 1.50 m DIN 18040-1 minimum."

  - id: revit_door_clear_width
    name: Door clear opening width 0.90 m on accessible routes
    severity: error
    rationale: |
      DIN 18040-1 4.3.3.2 - doors on accessible routes need a 0.90 m clear
      opening. "Width" is the built-in Doors type parameter (metres in a
      metric template); "Mark" is the built-in instance parameter; and
      "Accessible Route" is a project or shared Yes/No parameter that flags
      the barrier-free circulation path.
    selector:
      ifc_class: Doors
      properties:
        - { key: Accessible Route, op: eq, value: true }
    assertion:
      property:
        key: Width
        op: gte
        value: 0.9
        unit: m
    failure_message: "Door {{Mark}} width {{Width}} m is below the 0.90 m DIN 18040-1 minimum."
`;

const REVIT_FIRE_RATING_YAML = `# Interior-wall fire-rating completeness for Revit models.
#
# Every interior wall (Walls whose built-in "Function" type parameter reads
# "Interior") must declare a "Fire Rating" value. "Fire Rating" is the
# built-in Walls type parameter. Acceptable values follow DIN 4102-2
# ("F30", "F60", "F90", "F120", "F180") and the equivalent EN 13501-2
# classes ("REI 30" .. "REI 180"), plus the explicit "none" sentinel for
# walls intentionally outside any fire compartment (which still must be
# recorded; silent absence is the failure case).
#
# Revit-flavoured twin of fire_compartment_property (IFC). Revit "Function
# = Interior" corresponds to IFC "IsExternal = false".
schema_version: "1.0"
pack:
  id: revit_fire_rating
  name: Interior Wall Fire-Rating Completeness (Revit)
  description: |
    Validates that every interior Revit® wall declares a Fire Rating value
    drawn from the DIN 4102-2 / EN 13501-2 vocabulary.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276", "DIN4102"]
    project_regions: ["DE", "AT", "CH"]

rules:
  - id: revit_interior_wall_fire_rating_present
    name: Fire Rating present on every interior wall
    severity: error
    rationale: |
      Fire-compartment design fails silently when wall fire-ratings are
      missing. "Fire Rating" is the built-in Walls type parameter and
      "Function" is the built-in Walls type parameter whose "Interior"
      value corresponds to IFC IsExternal = false.
    selector:
      ifc_class: Walls
      properties:
        - { key: Function, op: eq, value: Interior }
    assertion:
      property:
        key: Fire Rating
        op: exists
        value: true
    failure_message: "Interior wall {{id}} has no Fire Rating type parameter."

  - id: revit_interior_wall_fire_rating_valid
    name: Fire Rating value drawn from DIN 4102 / EN 13501 vocabulary
    severity: warning
    rationale: |
      Ratings outside the standard vocabulary cannot be aggregated into
      compartment certificates and force manual review. Populate the
      built-in "Fire Rating" type parameter from the agreed value list
      (DIN 4102 F-classes or the equivalent EN 13501-2 REI classes).
    selector:
      ifc_class: Walls
      properties:
        - { key: Function, op: eq, value: Interior }
        - { key: Fire Rating, op: exists, value: true }
    assertion:
      property:
        key: Fire Rating
        op: in
        value: ["none", "F30", "F60", "F90", "F120", "F180", "REI 30", "REI 60", "REI 90", "REI 120", "REI 180"]
    failure_message: "Interior wall {{id}} has a Fire Rating outside the DIN 4102 / EN 13501 vocabulary."
`;

const REVIT_MEP_CLEARANCE_YAML = `# MEP-to-structure clearance for Revit models.
#
# Pipes must keep at least 100 mm of clearance from structural framing to
# allow insulation, sleeves and installation tolerance (cf. VDI 2055 6.3).
#
# This is the canonical set-vs-set rule: it pairs every element in the
# Pipes category (selector set) with every element in the Structural
# Framing category (other_selector set) and asserts a clearance property.
# "Clearance To Structure" is a shared parameter that carries the
# coordinated gap in metres; a future geometric engine can compute it from
# coordinates without changing this rule file.
#
# Revit-flavoured twin of mep_clearance (IFC).
schema_version: "1.0"
pack:
  id: revit_mep_clearance
  name: MEP-to-Structure Clearance (Revit)
  description: |
    Validates that Revit® pipes maintain a minimum 100 mm clearance from
    structural framing per VDI 2055.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276"]
    project_regions: ["DE", "AT", "CH"]

rules:
  - id: revit_pipe_to_framing_clearance_100mm
    name: Pipe at least 100 mm from structural framing
    severity: error
    rule_type: set_vs_set
    rationale: |
      VDI 2055 6.3 requires clearance around insulated pipe runs for
      insulation thickness, fastenings and maintenance access. Pipes and
      Structural Framing are Revit categories; "Clearance To Structure" is
      a shared parameter (metres) carrying the coordinated gap.
    selector:
      ifc_class: Pipes
    assertion:
      set_vs_set:
        other_selector:
          ifc_class: Structural Framing
        metric: clearance
        property:
          key: Clearance To Structure
          op: gte
          value: 0.1
          unit: m
    failure_message: "Pipe {{id}} is closer than the 100 mm minimum to nearby structural framing."
`;

const REVIT_ROOM_NAMING_YAML = `# Room-number naming convention for Revit models.
#
# The built-in Rooms instance parameter "Number" must match the canonical
# "<DEPT>.<LEVEL>.<ROOM>" pattern, e.g. "OR.02.001" for Operating Room,
# Level 02, Room 001. This is the typical healthcare room-coding scheme
# used to bridge architectural plans to FM systems and BIM data exports.
# IFC exposes the same value as IfcSpace.Name.
#
# Revit-flavoured twin of room_naming_convention (IFC).
schema_version: "1.0"
pack:
  id: revit_room_naming
  name: Room-Number Naming Convention (Revit)
  description: |
    Enforces the canonical "<DEPT>.<LEVEL>.<ROOM>" room-code pattern on the
    Revit® Rooms "Number" parameter so downstream FM exports parse cleanly.
  source: openconstructionerp
  version: "1.0.0"
  applies_to:
    classifications: ["DIN276", "COBie"]
    project_regions: []

rules:
  - id: revit_room_number_matches_code_pattern
    name: Room "Number" follows "<DEPT>.<LEVEL>.<ROOM>" pattern
    severity: warning
    rationale: |
      FM systems and COBie exports depend on the room-code structure to key
      rooms across disciplines. "Number" is the built-in Rooms instance
      parameter and the natural export key. Non-conforming numbers break
      the join and force manual reconciliation.
    selector:
      ifc_class: Rooms
    assertion:
      property:
        key: Number
        op: regex
        value: "^[A-Z]{2}\\\\.[0-9]{2}\\\\.[0-9]{3}$"
    failure_message: "Room number {{Number}} does not match the <DEPT>.<LEVEL>.<ROOM> pattern (e.g. OR.02.001)."
`;

export const SEED_PACKS: SeedPack[] = [
  {
    id: 'din_276_kg_completeness',
    name: 'DIN 276 Cost-Group Completeness',
    description:
      'Verifies that every building element carries a DIN 276 cost-group code in the 300, 400 or 500 ranges so cost-group rollups are well-defined.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH', 'LU'],
    classifications: ['DIN276'],
    rule_count: 2,
    category: 'Cost Classification',
    format: 'ifc',
    yaml: DIN_276_KG_COMPLETENESS_YAML,
  },
  {
    id: 'clearance_corridor_door',
    name: 'DIN 18040-1 Corridor and Door Clearance',
    description:
      'Validates barrier-free clearance dimensions for corridors and doors per DIN 18040-1 (public buildings, accessible routes).',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH'],
    classifications: ['DIN276', 'DIN18040'],
    rule_count: 2,
    category: 'Accessibility',
    format: 'ifc',
    yaml: CLEARANCE_CORRIDOR_DOOR_YAML,
  },
  {
    id: 'fire_compartment_property',
    name: 'Interior Wall Fire-Rating Completeness',
    description:
      'Validates that every internal wall declares a FireRating value drawn from the DIN 4102-2 / EN 13501-2 vocabulary.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH'],
    classifications: ['DIN276', 'DIN4102'],
    rule_count: 2,
    category: 'Fire Safety',
    format: 'ifc',
    yaml: FIRE_COMPARTMENT_PROPERTY_YAML,
  },
  {
    id: 'mep_clearance',
    name: 'MEP-to-Structure Clearance',
    description:
      'Validates that pipe segments maintain a minimum 100 mm clearance from structural beams per VDI 2055.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH'],
    classifications: ['DIN276'],
    rule_count: 1,
    category: 'MEP',
    format: 'ifc',
    yaml: MEP_CLEARANCE_YAML,
  },
  {
    id: 'room_naming_convention',
    name: 'Room-Code Naming Convention',
    description:
      'Enforces the canonical "<DEPT>.<LEVEL>.<ROOM>" room-code naming convention on IfcSpace.Name so downstream FM exports parse cleanly.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['INT'],
    classifications: ['DIN276', 'COBie'],
    rule_count: 1,
    category: 'Naming',
    format: 'ifc',
    yaml: ROOM_NAMING_CONVENTION_YAML,
  },
  {
    id: 'revit_cost_classification',
    name: 'DIN 276 Cost-Group Completeness (Revit)',
    description:
      'Verifies that every Revit® wall carries a DIN 276 cost-group code in the 300, 400 or 500 ranges, stored in the DIN_276_Code shared parameter, so cost-group rollups are well-defined.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH', 'LU'],
    classifications: ['DIN276'],
    rule_count: 2,
    category: 'Cost Classification',
    format: 'revit',
    yaml: REVIT_COST_CLASSIFICATION_YAML,
  },
  {
    id: 'revit_corridor_door_clearance',
    name: 'Corridor and Door Clearance (Revit)',
    description:
      'Validates barrier-free clearance for Revit® Rooms tagged as corridors and for Doors on accessible routes, per DIN 18040-1 (public buildings).',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH'],
    classifications: ['DIN276', 'DIN18040'],
    rule_count: 2,
    category: 'Accessibility',
    format: 'revit',
    yaml: REVIT_CORRIDOR_DOOR_CLEARANCE_YAML,
  },
  {
    id: 'revit_fire_rating',
    name: 'Interior Wall Fire-Rating Completeness (Revit)',
    description:
      'Validates that every interior Revit® wall declares a Fire Rating value drawn from the DIN 4102-2 / EN 13501-2 vocabulary.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH'],
    classifications: ['DIN276', 'DIN4102'],
    rule_count: 2,
    category: 'Fire Safety',
    format: 'revit',
    yaml: REVIT_FIRE_RATING_YAML,
  },
  {
    id: 'revit_mep_clearance',
    name: 'MEP-to-Structure Clearance (Revit)',
    description:
      'Validates that Revit® pipes maintain a minimum 100 mm clearance from structural framing per VDI 2055.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['DE', 'AT', 'CH'],
    classifications: ['DIN276'],
    rule_count: 1,
    category: 'MEP',
    format: 'revit',
    yaml: REVIT_MEP_CLEARANCE_YAML,
  },
  {
    id: 'revit_room_naming',
    name: 'Room-Number Naming Convention (Revit)',
    description:
      'Enforces the canonical "<DEPT>.<LEVEL>.<ROOM>" room-code pattern on the Revit® Rooms "Number" parameter so downstream FM exports parse cleanly.',
    source: 'openconstructionerp',
    version: '1.0.0',
    regions: ['INT'],
    classifications: ['DIN276', 'COBie'],
    rule_count: 1,
    category: 'Naming',
    format: 'revit',
    yaml: REVIT_ROOM_NAMING_YAML,
  },
];
