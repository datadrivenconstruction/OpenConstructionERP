/**
 * Bundled seed packs for the Rule Library browser.
 *
 * The same 5 YAML files that the backend ships at `data/bim_rules/*.yaml`
 * are inlined here as raw strings so the library works offline (no backend
 * round-trip required to populate the catalogue). The user can preview the
 * raw YAML, edit it locally, and call `install-from-yaml` only when they
 * decide to install.
 *
 * Keep these strings byte-identical to the source files in `data/bim_rules/`
 * — they are the canonical artefact. If the backend rules change, update
 * this file in the same PR so the library does not drift.
 */

export type SeedPackCategory =
  | 'Accessibility'
  | 'Cost Classification'
  | 'Fire Safety'
  | 'MEP'
  | 'Naming';

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
    yaml: ROOM_NAMING_CONVENTION_YAML,
  },
];
