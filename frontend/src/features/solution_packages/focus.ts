// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure rules for the pack focus: group a pack's modules the way the module
 * wizard groups them, and derive a short guided start from what the pack
 * brings (demo projects, standard, rule sets, cost data, its own modules).
 */
import { ALL_MODULES, MODULE_GROUPS } from '@/features/onboarding/modules';
import type { FocusPreview } from './api';

export interface FocusModule {
  key: string;
  labelKey: string | null;
  descriptionKey: string | null;
}

export interface FocusGroup {
  id: string;
  labelKey: string;
  modules: FocusModule[];
}

const BY_KEY = new Map(ALL_MODULES.map((m) => [m.key, m]));

/** Modules in wizard group order; modules the wizard does not list go to `platform`. */
export function groupModules(keys: readonly string[]): FocusGroup[] {
  const buckets = new Map<string, FocusModule[]>();
  for (const key of keys) {
    const def = BY_KEY.get(key);
    const group = def?.group ?? 'platform';
    const list = buckets.get(group) ?? [];
    list.push({ key, labelKey: def?.labelKey ?? null, descriptionKey: def?.descriptionKey ?? null });
    buckets.set(group, list);
  }
  return MODULE_GROUPS.filter((g) => buckets.has(g.id)).map((g) => ({
    id: g.id,
    labelKey: g.labelKey,
    modules: buckets.get(g.id)!,
  }));
}

export type StepId = 'demo' | 'boq' | 'validation' | 'export_gaeb' | 'reports' | 'costs' | 'open_module';

export interface FirstStep {
  id: StepId;
  to: string;
  /** Module key for `open_module`, the standard or rule sets otherwise. */
  param?: string;
}

const GAEB = /gaeb/i;

/** Route of a module from the sidebar's route-to-module map (first route wins). */
export function routeForModule(
  module: string,
  routeMap: Record<string, string | readonly string[]>,
): string | null {
  const name = `oe_${module}`;
  for (const [route, owner] of Object.entries(routeMap)) {
    if (owner === name || (Array.isArray(owner) && owner.includes(name))) return route;
  }
  return null;
}

/** The project seeded from one of the pack's demo templates, newest first; null if none is installed. */
export function findDemoProjectId(
  projects: readonly { id: string; metadata?: Record<string, unknown> | null; created_at?: string }[],
  demoTemplateIds: readonly string[],
): string | null {
  const match = projects
    .filter((p) => demoTemplateIds.includes(String(p.metadata?.demo_id ?? '')))
    .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')));
  return match[0]?.id ?? null;
}

/** Three to five first steps that link to real routes the focus keeps visible. */
export function buildFirstSteps(
  preview: Pick<FocusPreview, 'modules' | 'demo_template_ids' | 'rule_sets' | 'standard' | 'cwicr_regions' | 'menu'>,
  routeMap: Record<string, string | readonly string[]>,
  demoProjectId?: string | null,
): FirstStep[] {
  const has = (m: string) => preview.modules.includes(m);
  const steps: FirstStep[] = [];
  if (preview.demo_template_ids.length) steps.push({ id: 'demo', to: demoProjectId ? `/projects/${demoProjectId}` : '/projects' });
  if (has('boq')) steps.push({ id: 'boq', to: '/boq', param: preview.standard ?? undefined });
  if (has('validation')) steps.push({ id: 'validation', to: '/validation', param: preview.rule_sets.join(',') || undefined });
  const gaeb = preview.rule_sets.some((r) => GAEB.test(r)) || GAEB.test(preview.standard ?? '');
  if (has('boq') && gaeb) steps.push({ id: 'export_gaeb', to: '/boq' });
  else if (has('reporting')) steps.push({ id: 'reports', to: '/reports' });
  if (preview.cwicr_regions.length) steps.push({ id: 'costs', to: '/costs' });

  const used = new Set(steps.map((s) => s.to));
  const candidates = [
    ...preview.menu.map((to) => {
      const owner = routeMap[to];
      return { to, module: typeof owner === 'string' ? owner.replace(/^oe_/, '') : undefined };
    }),
    ...preview.modules.map((m) => ({ to: routeForModule(m, routeMap), module: m })),
  ];
  for (const c of candidates) {
    if (steps.length >= 3) break;
    if (!c.to || used.has(c.to)) continue;
    used.add(c.to);
    steps.push({ id: 'open_module', to: c.to, param: c.module ?? c.to.replace(/^\//, '') });
  }
  return steps.slice(0, 5);
}
