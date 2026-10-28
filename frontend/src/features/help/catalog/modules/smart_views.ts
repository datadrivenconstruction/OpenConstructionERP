// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How-it-works catalog - per-module gap-fill entry for Smart Views.
//
// Smart Views is a side-panel of the BIM viewer (BIMPage at /bim), so the
// card points at that host route: opening the module lands the user on the
// page that actually hosts the panel. See ../../types.ts for the shape and
// key convention, and ../coordination.ts for sibling coordination cards.

import type { ModuleExplanation } from '../../types';

export const smartViewsModules: ModuleExplanation[] = [
  {
    id: 'smart-views',
    route: '/bim',
    icon: 'Layers3',
    category: 'coordination',
    keywords:
      'smart views saved view rule rule-driven selector ifc class property colour color hide isolate transparent show preset legend folder share bim coordination discipline level status',
    titleKey: 'howto.smart-views.title',
    titleDefault: 'Smart Views',
    summaryKey: 'howto.smart-views.summary',
    summaryDefault:
      'Saved, rule-driven views that colour, hide or isolate BIM elements by their properties.',
    whatKey: 'howto.smart-views.what',
    whatDefault:
      'A Smart View is a saved set of rules, not a frozen snapshot. Each rule selects elements by IFC class or property and tells the BIM viewer to show, hide, isolate, colour or make them transparent. Because the rules re-evaluate every time a model loads, a view keeps doing its job after the geometry is revised. You can keep views private, share them with the project team, or install ready-made presets.',
    how: [
      {
        key: 'howto.smart-views.how.1',
        default:
          'Open a BIM model, then open the Smart Views panel from the viewer toolbar. With no model loaded you can still build views, but applying them needs a model.',
      },
      {
        key: 'howto.smart-views.how.2',
        default:
          'Switch between the My views and Project views tabs for your private and team views, or open the Presets tab to install a ready-made rule set in one click.',
      },
      {
        key: 'howto.smart-views.how.3',
        default:
          'Create a new view and add rules: each rule picks elements by IFC class or property with an operator such as equals, contains, greater than, between or exists, and applies an action - show, hide, isolate, colour or make transparent.',
      },
      {
        key: 'howto.smart-views.how.4',
        default:
          'Set the default action for elements no rule touches (show all or hide all), drag the rules into order since later rules override earlier ones, then save.',
      },
      {
        key: 'howto.smart-views.how.5',
        default:
          'Click a saved view to apply it to the loaded model; the rules re-evaluate against the current geometry, so the view keeps working after model revisions. Use Clear applied to drop it.',
      },
      {
        key: 'howto.smart-views.how.6',
        default:
          'Group views into folders, duplicate one as a starting point, or share a view by link so anyone with the link can open it read-only.',
      },
    ],
    tips: [
      {
        key: 'howto.smart-views.tip.1',
        default:
          'A Smart View stores rules, not a snapshot, so the same colour or isolate rule keeps applying as the model changes from one coordination round to the next.',
      },
      {
        key: 'howto.smart-views.tip.2',
        default:
          'Use the colour action with colour-by-property to bucket every match by a value, for example by level or fire rating, and get an automatic legend.',
      },
      {
        key: 'howto.smart-views.tip.3',
        default:
          'My views stay private to you while Project views are visible to the whole team; duplicate a personal view into the project scope once it is ready to share.',
      },
    ],
    whenKey: 'howto.smart-views.when',
    whenDefault:
      'Reach for it when you need to read a federated model by discipline, level or status: colour every element by fire rating, isolate one trade for a coordination review, or hide everything except the structure.',
  },
];
