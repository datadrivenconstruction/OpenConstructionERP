// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure rules for solution packages, kept apart from React so they are tested
 * directly: what a selection brings, which menu rows it puts first, which
 * sidebar routes it hides.
 */
import type { PackageState, SolutionPackage } from './api';

/** The selected ids plus the packages they build on, in registry order. */
export function withPackageDependencies(packages: SolutionPackage[], ids: string[]): string[] {
  const byId = new Map(packages.map((p) => [p.id, p]));
  const wanted = new Set<string>();
  const stack = [...ids];
  while (stack.length) {
    const id = stack.pop()!;
    const pkg = byId.get(id);
    if (!pkg || wanted.has(id)) continue;
    wanted.add(id);
    stack.push(...pkg.depends_on);
  }
  return packages.filter((p) => wanted.has(p.id)).map((p) => p.id);
}

/** Required modules of a selection (dependencies resolve on the server). */
export function selectionModules(packages: SolutionPackage[], ids: string[]): string[] {
  const all = withPackageDependencies(packages, ids);
  const out: string[] = [];
  for (const pkg of packages) {
    if (!all.includes(pkg.id)) continue;
    for (const mod of pkg.required) if (!out.includes(mod)) out.push(mod);
  }
  return out;
}

/** Menu rows of the selection, in package order, without repeats. */
export function mergedMenu(packages: SolutionPackage[], ids: string[]): string[] {
  const out: string[] = [];
  for (const pkg of packages) {
    if (!ids.includes(pkg.id)) continue;
    for (const route of pkg.menu) if (!out.includes(route)) out.push(route);
  }
  return out;
}

/** Dashboard widgets of the selection, in package order, without repeats. */
export function mergedWidgets(packages: SolutionPackage[], ids: string[]): string[] {
  const out: string[] = [];
  for (const pkg of packages) {
    if (!ids.includes(pkg.id)) continue;
    for (const w of pkg.widgets) if (!out.includes(w)) out.push(w);
  }
  return out;
}

/**
 * Whether the tenant's packages hide a sidebar route.
 *
 * `owner` is the route's backend module (`oe_<dir>`) or several of them; the
 * route stays while any owner is on. No packages, or a module the packages say
 * nothing about, hides nothing.
 */
export function isRouteHiddenByPackages(
  owner: string | readonly string[] | undefined,
  state: PackageState | undefined,
): boolean {
  if (!owner || !state?.packaged) return false;
  const off = (name: string) => state.modules[name.replace(/^oe_/, '')] === false;
  return typeof owner === 'string' ? off(owner) : owner.length > 0 && owner.every(off);
}

/** Modules switched on in `state`, for the dependency warning. */
export function enabledModules(state: PackageState | undefined): Set<string> {
  return new Set(Object.entries(state?.modules ?? {}).filter(([, on]) => on).map(([k]) => k));
}

/** Enabled modules that list `module` among their dependencies. */
export function directDependents(
  module: string,
  graph: { key: string; depends: string[] }[],
  enabled: Set<string>,
): string[] {
  return graph.filter((m) => enabled.has(m.key) && m.depends.includes(module)).map((m) => m.key);
}
