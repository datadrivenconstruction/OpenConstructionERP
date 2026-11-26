// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Front-end facts about a backend module for the data path views: its route,
// its translated name (the sidebar's own label), its family (the sidebar
// section, with that section's tone). The project phase of a module comes
// from the API (MapModule.phase), never from here.

import { ROUTE_BACKEND_MODULE } from '@/app/layout/Sidebar';
import type { LucideIcon } from 'lucide-react';
import { navGroups } from '@/app/layout/navCatalog';
import { sectionTone } from '@/app/layout/menuIcons';
import { MODULE_REGISTRY } from '@/modules/_registry';

// Core modules are always installed, so the sidebar's optional-module map leaves
// them out; their pages still own data paths.
const CORE_ROUTE_MODULE: Record<string, string> = {
  '/boq': 'oe_boq',
  '/costs': 'oe_costs',
  '/assemblies': 'oe_assemblies',
  '/model-review': 'oe_bim_hub',
  '/progress': 'oe_progress',
  '/catalog': 'oe_catalog',
  '/project-catalogue': 'oe_project_catalogue',
  '/preliminaries': 'oe_preliminaries',
  '/timeline': 'oe_timeline',
  '/dashboards': 'oe_dashboards',
  '/dashboard': 'oe_dashboard',
  '/inbox': 'oe_dashboard',
  '/photos': 'oe_photos',
  '/files': 'oe_documents',
  '/files/trash': 'oe_file_trash',
  '/files/search': 'oe_file_search',
  '/files/transmittals': 'oe_file_transmittals',
  '/files/approvals': 'oe_file_approvals',
  '/sheets': 'oe_documents',
  '/deadlines': 'oe_deadlines',
  '/credentials': 'oe_credentials',
  '/users': 'oe_users',
  '/teams': 'oe_teams',
  '/admin/audit-log': 'oe_admin',
  '/admin/webhook-targets': 'oe_notifications',
  '/integrations': 'oe_integrations',
  '/jobs': 'oe_jobs',
  '/saved-views': 'oe_saved_views',
  '/tax-rates': 'oe_i18n_foundation',
  '/find': 'oe_retrieval',
  '/notifications': 'oe_notifications',
  '/project-intelligence': 'oe_project_intelligence',
  '/analytics': 'oe_projects',
  '/quality-concept': 'oe_quality_concept',
  '/hse-frame': 'oe_hse_frame',
  '/permits': 'oe_permits',
  '/staffing': 'oe_staffing',
  '/engineering-brief': 'oe_engineering_brief',
  '/handbook': 'oe_project_handbook',
  '/commitments': 'oe_commitment_release',
  '/economics': 'oe_economics',
  '/delivery': 'oe_delivery_model',
  '/plant-register': 'oe_plant_register',
  '/procurement-concept': 'oe_procurement_concept',
  '/stakeholders': 'oe_stakeholders',
  '/governance': 'oe_project_governance',
  '/design': 'oe_design_management',
  '/guarantees': 'oe_guarantees',
  '/wip': 'oe_wip_report',
  '/inbound': 'oe_inbound_capture',
  '/eac/blocks': 'oe_eac',
};

// Plugin modules (survey and the like) register their menu rows in their own
// manifest; the manifest id is the backend package name (dashes read as underscores).
function registryRoutes(): [string, string][] {
  return MODULE_REGISTRY.flatMap((m) => m.navItems.map((item): [string, string] => [item.to, `oe_${m.id.replace(/-/g, '_')}`]));
}

function routeOwners(): [string, string | readonly string[]][] {
  return [...Object.entries(CORE_ROUTE_MODULE), ...Object.entries(ROUTE_BACKEND_MODULE), ...registryRoutes()];
}

export interface ModuleMeta {
  module: string;
  route: string | null;
  labelKey: string | null;
  defaultLabel: string | null;
  familyId: string;
  familyLabelKey: string | null;
  familyDefaultLabel: string | null;
  /** `var(--oe-tone-N)` of the sidebar section; neutral when the module has no menu row. */
  tone: string;
  /** The module's menu icon; null when it has no menu row. */
  icon: LucideIcon | null;
}

interface RouteFacts {
  route: string;
  labelKey: string;
  defaultLabel: string | null;
  groupId: string;
  groupLabelKey: string;
  groupDefaultLabel: string | null;
  icon: LucideIcon | null;
}

let routeByModule: Map<string, RouteFacts> | null = null;

function routeIndex(): Map<string, RouteFacts> {
  if (routeByModule) return routeByModule;
  const navByRoute = new Map<string, RouteFacts>();
  for (const group of navGroups) {
    const dynamic = MODULE_REGISTRY.flatMap((m) => m.navItems.filter((i) => i.group === (group.dynamicGroupKey ?? group.id)));
    for (const item of [...group.items, ...dynamic]) {
      if (!navByRoute.has(item.to)) {
        navByRoute.set(item.to, {
          route: item.to,
          labelKey: item.labelKey,
          defaultLabel: ('defaultLabel' in item ? item.defaultLabel : undefined) ?? null,
          groupId: group.id,
          groupLabelKey: group.labelKey,
          groupDefaultLabel: group.defaultLabel ?? null,
          icon: item.icon ?? null,
        });
      }
    }
  }
  const out = new Map<string, RouteFacts>();
  for (const [route, owner] of routeOwners()) {
    const modules = typeof owner === 'string' ? [owner] : owner;
    const facts = navByRoute.get(route);
    for (const module of modules) {
      if (out.has(module)) continue;
      out.set(
        module,
        facts ?? { route, labelKey: '', defaultLabel: null, groupId: '', groupLabelKey: '', groupDefaultLabel: null, icon: null },
      );
    }
  }
  // Prefer a route that has a menu row over one that does not.
  for (const [route, owner] of routeOwners()) {
    const facts = navByRoute.get(route);
    if (!facts) continue;
    for (const module of typeof owner === 'string' ? [owner] : owner) {
      if (!out.get(module)?.labelKey) out.set(module, facts);
    }
  }
  routeByModule = out;
  return out;
}

const metaCache = new Map<string, ModuleMeta>();

export function moduleMeta(module: string): ModuleMeta {
  const hit = metaCache.get(module);
  if (hit) return hit;
  const facts = routeIndex().get(module);
  const toneIndex = facts?.route ? sectionTone(facts.route) : undefined;
  const meta: ModuleMeta = {
    module,
    route: facts?.route ?? null,
    labelKey: facts?.labelKey || null,
    defaultLabel: facts?.defaultLabel ?? null,
    familyId: facts?.groupId || 'platform',
    familyLabelKey: facts?.groupLabelKey || null,
    familyDefaultLabel: facts?.groupDefaultLabel ?? null,
    tone: toneIndex === undefined ? 'var(--oe-text-tertiary)' : `var(--oe-tone-${toneIndex})`,
    icon: facts?.icon ?? null,
  };
  metaCache.set(module, meta);
  return meta;
}

function ownerOfPath(pathname: string): string | null {
  let best: { route: string; module: string } | null = null;
  for (const [route, owner] of routeOwners()) {
    if (route === '/') continue;
    if (pathname === route || pathname.startsWith(`${route}/`)) {
      if (!best || route.length > best.route.length) {
        best = { route, module: typeof owner === 'string' ? owner : (owner[0] ?? '') };
      }
    }
  }
  return best?.module || null;
}

/** Module owning a front-end path: the longest route prefix in the sidebar map, segment-aligned.
 *  A project-scoped page (`/projects/<id>/<page>`) belongs to the module of `/<page>`. */
export function moduleForPath(pathname: string): string | null {
  const page = /^\/projects\/[^/]+(\/.+)$/.exec(pathname)?.[1];
  if (page) {
    const inner = ownerOfPath(page);
    if (inner) return inner;
  }
  return ownerOfPath(pathname);
}
