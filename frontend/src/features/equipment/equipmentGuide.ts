// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// equipmentGuide - "How it works" content for the Equipment & Fleet module.
// Consumed by <ModuleGuideButton content={equipmentGuide} /> on EquipmentPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const equipmentGuide: ModuleGuideContent = {
  titleKey: 'guide.equipment.title',
  titleDefault: 'Equipment & Fleet',
  introKey: 'guide.equipment.intro',
  introDefault:
    'Equipment & Fleet is the register for every owned, rented or leased machine on your sites. Use it to track utilisation, running cost, maintenance and certifications, and to keep unsafe or lapsed plant out of new assignments.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.equipment.assets.title',
      titleDefault: 'Register your assets',
      bodyKey: 'guide.equipment.assets.body',
      bodyDefault:
        'Each asset is one machine with a unique code, a type, an ownership (owned, rented or leased) and a status. New Asset opens a form for identity, lifecycle, financial value, telemetry and location. The Assets table lists code, name, type, status, location and running hours, and you can search or filter by status and ownership.',
    },
    {
      icon: 'Sparkles',
      titleKey: 'guide.equipment.fleet_intel.title',
      titleDefault: 'Fleet Intelligence',
      bodyKey: 'guide.equipment.fleet_intel.body',
      bodyDefault:
        'The panel at the top of the list reads your whole fleet against a target utilisation. It flags underutilised units worth redeploying, estimates the monthly idle-cost saving and proposes service bundles that group similar maintenance. Click any flagged unit to jump straight into its detail.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.equipment.utilization.title',
      titleDefault: 'Utilisation and telemetry',
      bodyKey: 'guide.equipment.utilization.body',
      bodyDefault:
        'Open an asset to see month-to-date utilisation, fuel cost, hour meter and odometer. Log meter reading records a new hour-meter, odometer, fuel level and engine status. Each reading rolls the asset state forward and can auto-fire a maintenance work order when a service is within fifty hours of due.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.equipment.maintenance.title',
      titleDefault: 'Maintenance and damage',
      bodyKey: 'guide.equipment.maintenance.body',
      bodyDefault:
        'The Maintenance tab tracks scheduled, in-progress and completed work orders, which you can add, edit, complete or delete. Filing a damage report on the Damage tab records severity and a repair estimate, and automatically opens a linked work order so the repair is tracked. Work order costs roll up into project Finance.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.equipment.certifications.title',
      titleDefault: 'Certifications keep plant safe',
      bodyKey: 'guide.equipment.certifications.body',
      bodyDefault:
        'Record statutory inspections, lift certificates and annual safety checks with their valid-until date and result. When the latest certificate lapses, or the asset is not active, the unit is automatically blocked from new resource assignments and a banner points you to Resources to review crew allocation.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.equipment.types.title',
      titleDefault: 'Classify with types',
      bodyKey: 'guide.equipment.types.body',
      bodyDefault:
        'The Types tab is the catalogue of categories you use to classify assets, such as excavator, crane or generator. Each asset references a type by code, and types drive default service intervals and inspection cadence. A type cannot be deleted while any asset still uses it.',
    },
  ],
  ctaKey: 'guide.equipment.cta',
  ctaDefault: 'Register your first asset',
};
