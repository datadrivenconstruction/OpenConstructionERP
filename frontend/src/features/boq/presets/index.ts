// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BOQ custom-column presets — registry.
 *
 * Each preset is a curated set of columns that solves a single, real-world
 * BOQ workflow (procurement, quality, regional-standard compliance, etc).
 * Presets are organised into two regions:
 *
 *   - `universal` — applies anywhere (procurement, notes, schedule, ...)
 *   - country / standard codes — opt-in for specific markets
 *   - `integration` — cross-cutting integration columns (BIM, ERP, ...)
 *
 * Adding a preset to a BOQ creates its columns sequentially; existing
 * columns with the same `name` are skipped silently so re-applying a
 * preset is safe.
 *
 * Region values are the source of truth for the UI grouping in
 * `CustomColumnsDialog.tsx`. Keep regions stable — changing one shifts
 * a preset between the always-visible and collapsible sections.
 */
import {
  Package,
  FileText as NotesIcon,
  ShieldCheck,
  Leaf,
  Building2,
  FileCheck,
  Boxes,
  type LucideIcon,
  Flag,
  Gavel,
  Calendar as CalendarIcon,
  ClipboardList,
  Globe,
  Sparkles,
  Layers,
  Calculator,
} from 'lucide-react';
import type { CustomColumnDef } from '../api';

export type PresetRegion =
  | 'universal'
  | 'germany'
  | 'austria'
  | 'usa'
  | 'australia'
  | 'brazil'
  | 'uk'
  | 'china'
  | 'canada'
  | 'integration';

export interface ColumnPreset {
  id: string;
  region: PresetRegion;
  name: string;
  description: string;
  icon: LucideIcon;
  iconClass: string;
  columns: CustomColumnDef[];
}

/* ── Universal presets — apply anywhere ──────────────────────────────── */

const UNIVERSAL_PRESETS: ColumnPreset[] = [
  {
    id: 'procurement',
    region: 'universal',
    name: 'Procurement',
    description: 'Supplier, lead time, PO number, status - for purchasing tracking',
    icon: Package,
    iconClass: 'text-violet-600 bg-violet-500/10',
    columns: [
      { name: 'supplier', display_name: 'Supplier', column_type: 'text' },
      { name: 'lead_time_days', display_name: 'Lead Time (days)', column_type: 'number' },
      { name: 'po_number', display_name: 'PO Number', column_type: 'text' },
      {
        name: 'po_status',
        display_name: 'PO Status',
        column_type: 'select',
        options: ['Quoted', 'Ordered', 'In Transit', 'Delivered', 'Cancelled'],
      },
    ],
  },
  {
    id: 'notes',
    region: 'universal',
    name: 'Notes',
    description: 'Internal note + reference - quick context per position',
    icon: NotesIcon,
    iconClass: 'text-blue-600 bg-blue-500/10',
    columns: [
      { name: 'internal_note', display_name: 'Internal Note', column_type: 'text' },
      { name: 'reference', display_name: 'Reference', column_type: 'text' },
    ],
  },
  {
    id: 'quality',
    region: 'universal',
    name: 'Quality Control',
    description: 'Inspection status, inspector and date - for QA workflow',
    icon: ShieldCheck,
    iconClass: 'text-emerald-600 bg-emerald-500/10',
    columns: [
      {
        name: 'qc_status',
        display_name: 'QC Status',
        column_type: 'select',
        options: ['Pending', 'Passed', 'Failed', 'Rework', 'Waived'],
      },
      { name: 'inspector', display_name: 'Inspector', column_type: 'text' },
      { name: 'inspection_date', display_name: 'Inspection Date', column_type: 'date' },
    ],
  },
  {
    id: 'sustainability',
    region: 'universal',
    name: 'Sustainability',
    description: 'CO₂ footprint, EPD reference and material source',
    icon: Leaf,
    iconClass: 'text-green-600 bg-green-500/10',
    columns: [
      { name: 'co2_kg_per_unit', display_name: 'CO₂ kg/unit', column_type: 'number' },
      { name: 'epd_reference', display_name: 'EPD Reference', column_type: 'text' },
      { name: 'material_source', display_name: 'Material Source', column_type: 'text' },
    ],
  },
  {
    id: 'status_scope',
    region: 'universal',
    name: 'Status & Scope',
    description: 'Position status, scope flag, risk level and owner - for review workflows',
    icon: Flag,
    iconClass: 'text-amber-600 bg-amber-500/10',
    columns: [
      {
        name: 'position_status',
        display_name: 'Position Status',
        column_type: 'select',
        options: ['Draft', 'Confirmed', 'Awarded', 'In Progress', 'Done', 'On Hold'],
      },
      {
        name: 'scope_flag',
        display_name: 'Scope',
        column_type: 'select',
        options: ['In scope', 'Out of scope', 'Optional'],
      },
      {
        name: 'risk_level',
        display_name: 'Risk',
        column_type: 'select',
        options: ['Low', 'Medium', 'High'],
      },
      { name: 'owner', display_name: 'Owner', column_type: 'text' },
    ],
  },
  {
    id: 'tendering',
    region: 'universal',
    name: 'Tendering',
    description: 'Bidder, bid amount and award status - track tender packages per position',
    icon: Gavel,
    iconClass: 'text-indigo-600 bg-indigo-500/10',
    columns: [
      { name: 'tender_package', display_name: 'Tender Package', column_type: 'text' },
      { name: 'bidder', display_name: 'Bidder', column_type: 'text' },
      { name: 'bid_amount', display_name: 'Bid Amount', column_type: 'number' },
      { name: 'bid_date', display_name: 'Bid Date', column_type: 'date' },
      {
        name: 'award_status',
        display_name: 'Award Status',
        column_type: 'select',
        options: ['Pending', 'Accepted', 'Rejected', 'Tied'],
      },
    ],
  },
  {
    id: 'schedule',
    region: 'universal',
    name: 'Schedule',
    description: 'Start, end, duration and WBS code - link BOQ rows to the construction schedule',
    icon: CalendarIcon,
    iconClass: 'text-sky-600 bg-sky-500/10',
    columns: [
      { name: 'wbs_code', display_name: 'WBS Code', column_type: 'text' },
      { name: 'start_date', display_name: 'Start Date', column_type: 'date' },
      { name: 'end_date', display_name: 'End Date', column_type: 'date' },
      { name: 'duration_days', display_name: 'Duration (days)', column_type: 'number' },
      { name: 'predecessor', display_name: 'Predecessor', column_type: 'text' },
    ],
  },
];

/* ── Regional / standards-specific presets ──────────────────────────── */

const REGIONAL_PRESETS: ColumnPreset[] = [
  {
    id: 'gaeb_ava',
    region: 'germany',
    name: 'GAEB / AVA Style',
    description:
      'Splits unit rate into Lohn / Material / Geräte / Sonstiges + risk markup. Lohn/Material/Geräte auto-fill from position resources - no manual entry.',
    icon: FileCheck,
    iconClass: 'text-rose-600 bg-rose-500/10',
    columns: [
      { name: 'kg_bezug', display_name: 'KG-Bezug (DIN 276)', column_type: 'text' },
      // Lohn / Material / Geräte are derived from `metadata.resources[]`:
      // each one sums the per-unit subtotal of resources whose `type`
      // matches the role. ``Sonstiges`` is what's LEFT over (other +
      // operator + subcontractor) so the four EP columns add up to
      // ``unit_rate`` for any position that's been priced via resources.
      // ``Wagnis %`` stays a free-input number — it's a contractor
      // discretion knob and isn't carried on the position model.
      {
        name: 'lohn_ep',
        display_name: 'Lohn-EP',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'labor',
      },
      {
        name: 'material_ep',
        display_name: 'Material-EP',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'material',
      },
      {
        name: 'geraete_ep',
        display_name: 'Geräte-EP',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'equipment',
      },
      {
        name: 'sonstiges_ep',
        display_name: 'Sonstiges-EP',
        column_type: 'number',
        derived: 'resource_sum',
        // Catch-all bucket so Lohn + Material + Geräte + Sonstiges = unit_rate
        // even when the position carries operator / subcontractor resources.
        resource_role: ['other', 'operator', 'subcontractor'],
      },
      { name: 'wagnis_pct', display_name: 'Wagnis %', column_type: 'number' },
    ],
  },
  {
    id: 'oenorm_brz',
    region: 'austria',
    name: 'ÖNORM / BRZ Style',
    description:
      'LV position code, keyword, supplier + auto-computed labor share - matches Austrian ÖNORM B 2061 / A 2063 used in BRZ',
    icon: Building2,
    iconClass: 'text-orange-600 bg-orange-500/10',
    columns: [
      { name: 'lv_position', display_name: 'LV-Position', column_type: 'text' },
      { name: 'stichwort', display_name: 'Stichwort', column_type: 'text' },
      // Lohn-Anteil = labor share of the unit rate, expressed as a percent:
      // the labour resources over the position's stored ``unit_rate``, not
      // over the resource total. Auto-derived so the user can't enter a value
      // that disagrees with the position, and left free to exceed 100 so a
      // buildup worth more than its own rate is visible instead of rounded
      // into a plausible-looking share.
      {
        name: 'lohn_anteil_pct',
        display_name: 'Lohn-Anteil %',
        column_type: 'number',
        derived: 'percentage_of_unit_rate',
        resource_role: 'labor',
      },
      { name: 'aufschlag_pct', display_name: 'Aufschlag %', column_type: 'number' },
      { name: 'lieferant', display_name: 'Lieferant', column_type: 'text' },
    ],
  },
  {
    id: 'csi_masterformat',
    region: 'usa',
    name: 'USA - CSI MasterFormat',
    description:
      'Division / Section codes, crew, productivity and cost-data reference - matches CSI MasterFormat 2018',
    icon: ClipboardList,
    iconClass: 'text-blue-700 bg-blue-700/10',
    columns: [
      { name: 'csi_division', display_name: 'Division', column_type: 'text' },
      { name: 'csi_section', display_name: 'Section', column_type: 'text' },
      { name: 'crew_code', display_name: 'Crew Code', column_type: 'text' },
      { name: 'daily_output', display_name: 'Daily Output', column_type: 'number' },
      { name: 'cost_ref_code', display_name: 'Cost Ref Code', column_type: 'text' },
    ],
  },
  {
    id: 'aiqs_australia',
    region: 'australia',
    name: 'Australia - AIQS',
    description:
      'AIQS code, trade element, AS reference and floor area type - Australian QS measurement practice',
    icon: Globe,
    iconClass: 'text-yellow-600 bg-yellow-500/10',
    columns: [
      { name: 'aiqs_code', display_name: 'AIQS Code', column_type: 'text' },
      { name: 'trade_element', display_name: 'Trade Element', column_type: 'text' },
      { name: 'as_reference', display_name: 'Australian Standard', column_type: 'text' },
      { name: 'boma_group', display_name: 'BOMA Group', column_type: 'text' },
      {
        name: 'floor_area_type',
        display_name: 'Floor Area Type',
        column_type: 'select',
        options: ['GBA', 'NLA', 'Common'],
      },
    ],
  },
  {
    id: 'sinapi_brazil',
    region: 'brazil',
    name: 'Brazil - SINAPI',
    description:
      'SINAPI code, BDI, encargos and origin - matches Brazilian Caixa SINAPI cost-base format',
    icon: Sparkles,
    iconClass: 'text-lime-600 bg-lime-500/10',
    columns: [
      { name: 'sinapi_code', display_name: 'SINAPI Code', column_type: 'text' },
      {
        name: 'sinapi_tipo',
        display_name: 'Tipo',
        column_type: 'select',
        options: ['Insumo', 'Composição', 'Auxiliar'],
      },
      { name: 'bdi_pct', display_name: 'BDI %', column_type: 'number' },
      { name: 'encargos_pct', display_name: 'Encargos Sociais %', column_type: 'number' },
      { name: 'origem', display_name: 'Origem', column_type: 'text' },
    ],
  },
  {
    id: 'nrm2_uk',
    region: 'uk',
    name: 'UK - NRM2',
    description:
      'NRM2 code, element group / sub-element and cost-index reference - RICS New Rules of Measurement',
    icon: Building2,
    iconClass: 'text-purple-600 bg-purple-500/10',
    columns: [
      { name: 'nrm2_code', display_name: 'NRM2 Code', column_type: 'text' },
      { name: 'element_group', display_name: 'Element Group', column_type: 'text' },
      { name: 'sub_element', display_name: 'Sub-Element', column_type: 'text' },
      { name: 'measurement_unit', display_name: 'Measurement Unit', column_type: 'text' },
      { name: 'bcis_reference', display_name: 'Cost Index Reference', column_type: 'text' },
    ],
  },
  {
    id: 'gbt50500_china',
    region: 'china',
    // The label states GB 50500-2013 rather than the 2024 edition,
    // following the decision already recorded in tree: the shipped
    // Chinese item codes were authored against the 2013 text, it is the
    // only edition whose text is on hand, and conformance to the 2024
    // one is therefore not claimed. The prefix is the tell between them,
    // GB being the mandatory code and GB/T the recommended standard, so
    // the label cannot read GB/T while naming the older edition. The id
    // keeps ``gbt50500`` because that is the pack directory name and the
    // key the demo packs file their item codes under. It identifies the
    // pack, it does not claim an edition.
    name: 'China - GB 50500',
    description:
      'Item code, feature description and the labour / material / machinery split behind a comprehensive unit rate, plus management fee and profit - GB 50500-2013 bill-of-quantities valuation. The three cost-element columns auto-fill from position resources.',
    icon: Layers,
    iconClass: 'text-red-600 bg-red-500/10',
    columns: [
      // Display names are bilingual, matching how the rest of the Chinese
      // content in this codebase is written (the CN markup stack in
      // ``backend/app/modules/boq/markup_templates.py``, the Shanghai and
      // Shenzhen demo packs). A Latin-script reader can guess at
      // ``Lieferant`` or ``Origem``; they cannot guess at a CJK header.
      //
      // The item code is text, not a number: it is twelve digits, the first
      // nine fixed nationally by the appendix and the last three assigned
      // per project, and leading zeros are load-bearing (010101001001).
      { name: 'xiangmu_bianma', display_name: '项目编码 (Item code)', column_type: 'text' },
      // The feature description is the substantial one, and the single most
      // distinctive field on a Chinese bill: it is what an item is priced
      // against, so two rows carrying the same code price differently when
      // their feature text differs.
      {
        name: 'xiangmu_tezheng',
        display_name: '项目特征描述 (Feature description)',
        column_type: 'text',
      },
      // Labour / material / machinery are the cost elements a comprehensive
      // unit rate is built from, derived from ``metadata.resources[]``
      // exactly as the GAEB preset derives Lohn / Material / Geräte.
      {
        name: 'rengong_fei',
        display_name: '人工费 (Labour)',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'labor',
      },
      {
        name: 'cailiao_fei',
        display_name: '材料费 (Material)',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'material',
      },
      {
        name: 'jixie_fei',
        display_name: '机械费 (Machinery)',
        column_type: 'number',
        derived: 'resource_sum',
        // ``operator`` joins ``equipment`` here on purpose, and this is the
        // one place a country preset departs from the GAEB one, which
        // sweeps operator into Sonstiges instead. A machine-shift rate
        // (jixie taiban danjia) is conventionally quoted including the
        // wages of the crew on the machine, so a Chinese estimator reads
        // the operator inside the machinery element rather than beside it.
        //
        // There is deliberately no catch-all column here, unlike GAEB's
        // Sonstiges-EP. Specialist subcontracting is its own bill item
        // under the bill-of-quantities pricing method rather than part of a
        // comprehensive unit rate, so ``subcontractor`` and ``other``
        // resources stay outside all three columns on purpose.
        resource_role: ['equipment', 'operator'],
      },
      // Management fee and profit are free-input percentages and NOT derived
      // columns. ``percentage_of_unit_rate`` means "the share of the unit
      // rate contributed by resources of role X" - it divides one resource
      // sum by the position's stored ``unit_rate`` and renders read-only. No
      // resource role denotes a management fee, so a derived column here would
      // print some other role's share (or, with no role set, the whole buildup
      // against the rate) and then refuse the edit that would correct it. Same
      // reasoning as ``Wagnis %`` in the GAEB preset: a rate the contractor
      // decides is not carried on the position model.
      //
      // They belong on the position rather than beside the bill heads.
      // Under the bill-of-quantities pricing method the enterprise
      // management fee and the profit form part of the composition of a
      // comprehensive unit rate, which is exactly what a per-position column
      // is. ``markup_templates.py`` reached the same finding for the
      // bill-level markup stack and recorded that it has nowhere to say so;
      // this surface is the somewhere.
      // The label uses the full enterprise-management-fee name rather than
      // the bare short form, because every source in this repo that states
      // this charge as a structured name uses the full one: both Chinese
      // demo packs, the CN stack in ``markup_templates.py`` and the v2
      // seeder. Only flowing prose shortens it.
      // ``test_chinese_fee_categories_agree_across_sources`` keys its table
      // on the full name too, taking the leading run of Han characters, so a
      // fifth spelling here would be a name resolving to nothing if that
      // census ever reaches the frontend.
      {
        name: 'guanli_fei_pct',
        display_name: '企业管理费 % (Management fee)',
        column_type: 'number',
      },
      { name: 'lirun_pct', display_name: '利润 % (Profit)', column_type: 'number' },
      // The risk allowance completes the composition: a comprehensive unit
      // rate is the three cost elements plus management fee, profit and an
      // allowance for risk within an agreed range. Free input for the same
      // reason as the two above, and the direct counterpart of ``Wagnis %``
      // in the GAEB preset. Without it a Chinese estimator reads the
      // composition as one head short.
      { name: 'fengxian_pct', display_name: '风险 % (Risk allowance)', column_type: 'number' },
    ],
  },
  {
    id: 'unit_price_canada',
    region: 'canada',
    name: 'Canada - Unit Price Analysis',
    description:
      'Labour / material / equipment / subcontract buildup, overhead, profit and the provincial sales-tax regime. Canada classifies to MasterFormat, so the codes stay in the CSI preset and this one carries only what differs.',
    icon: Calculator,
    iconClass: 'text-teal-600 bg-teal-500/10',
    columns: [
      // No division / section columns here on purpose. Canadian estimates
      // classify to MasterFormat - both bundled Canadian packs seed
      // ``classification_standard="masterformat"`` - so the codes are the
      // ``csi_masterformat`` preset's job and duplicating them would put two
      // names on one fact. Applying both presets together is safe: a column
      // whose name already exists is skipped.
      {
        name: 'ca_labour',
        display_name: 'Labour',
        column_type: 'number',
        derived: 'resource_sum',
        // Operator sits on the labour line, the opposite of the Chinese
        // preset above: a North American crew rate prices the equipment
        // operator as labour hours and the machine as a separate equipment
        // line. ``other`` resources fall outside all four columns - there is
        // no catch-all because the buildup names four heads and inventing a
        // fifth would misstate it, so the four sum to the unit rate only for
        // a position priced entirely from these roles.
        resource_role: ['labor', 'operator'],
      },
      {
        name: 'ca_material',
        display_name: 'Material',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'material',
      },
      {
        name: 'ca_equipment',
        display_name: 'Equipment',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'equipment',
      },
      {
        name: 'ca_subcontract',
        display_name: 'Subcontract',
        column_type: 'number',
        derived: 'resource_sum',
        resource_role: 'subcontractor',
      },
      // Free-input for the same reason the Chinese management fee and profit
      // are: they are contractor decisions, not something summed out of the
      // position's resources.
      { name: 'ca_overhead_pct', display_name: 'Overhead %', column_type: 'number' },
      { name: 'ca_profit_pct', display_name: 'Profit %', column_type: 'number' },
      {
        name: 'ca_tax_regime',
        display_name: 'Sales Tax Regime',
        column_type: 'select',
        // Regime names carry no rates. The rates are provincial and they
        // move, and a rate baked into an option string is a number nobody
        // comes back to correct.
        //
        // What the column is actually for is recoverability, which is why it
        // sits on the position and not in a single project setting. GST, HST
        // and QST are recovered by a registrant through input tax credits and
        // do not belong inside a rate; provincial sales tax on materials in
        // British Columbia, Saskatchewan and Manitoba is not recoverable and
        // is embedded in the unit rate, the same way the US stack treats
        // sales tax on materials.
        options: ['GST', 'HST', 'GST + PST', 'GST + QST', 'Exempt'],
      },
    ],
  },
  {
    id: 'bim',
    region: 'integration',
    name: 'BIM Integration',
    description:
      'IFC GUID, element ID, storey and lifecycle phase - for linking BoQ rows to BIM models',
    icon: Boxes,
    iconClass: 'text-cyan-600 bg-cyan-500/10',
    columns: [
      { name: 'ifc_guid', display_name: 'IFC GUID', column_type: 'text' },
      { name: 'element_id', display_name: 'Element ID', column_type: 'text' },
      { name: 'storey', display_name: 'Storey/Level', column_type: 'text' },
      {
        name: 'phase',
        display_name: 'Phase',
        column_type: 'select',
        options: ['Existing', 'Demolition', 'New Construction', 'Temporary'],
      },
    ],
  },
];

export const PRESETS: ColumnPreset[] = [...UNIVERSAL_PRESETS, ...REGIONAL_PRESETS];

export const UNIVERSAL_PRESET_IDS: ReadonlySet<string> = new Set(
  UNIVERSAL_PRESETS.map((p) => p.id),
);

export function isUniversalPreset(preset: ColumnPreset): boolean {
  return preset.region === 'universal';
}

export function getUniversalPresets(): readonly ColumnPreset[] {
  return UNIVERSAL_PRESETS;
}

export function getRegionalPresets(): readonly ColumnPreset[] {
  return REGIONAL_PRESETS;
}
