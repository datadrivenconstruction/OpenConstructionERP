// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Solution packages: the client side of `/api/v1/solution-packages/`.
 *
 * A package is a ready bundle of modules (with its menu, dashboard widgets and
 * demo). The server owns the registry and the dependency closure; this file
 * only types it and offers the React Query hooks.
 */
import { useQuery } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

export interface SolutionPackage {
  id: string;
  icon: string;
  image: string;
  name_key: string;
  value_key: string;
  audience_key: string;
  required: string[];
  optional: string[];
  menu: string[];
  widgets: string[];
  demo_id: string | null;
  depends_on: string[];
}

export interface PackageState {
  installed: string[];
  optional: string[];
  modules: Record<string, boolean>;
  packaged: boolean;
  /** Pack slug (or `package:<id>`) the menu is focused on, or null. */
  focus_pack?: string | null;
}

/** What focusing on a pack turns on, and the facts its guided start uses. */
export interface FocusPreview {
  slug: string;
  name: string;
  name_key: string | null;
  type: string;
  source: 'manifest' | 'fallback';
  modules: string[];
  hidden: string[];
  demo_template_ids: string[];
  rule_sets: string[];
  standard: string | null;
  cwicr_regions: string[];
  currency: string | null;
  menu: string[];
}

export interface PackageListing {
  packages: SolutionPackage[];
  modules: { key: string; depends: string[] }[];
  state: PackageState;
}

export interface InstallResult extends PackageState {
  added: string[];
  enabled_modules: string[];
  demos: string[];
}

export const PACKAGES_QUERY_KEY = ['solution-packages'] as const;

export function fetchPackages(): Promise<PackageListing> {
  return apiGet<PackageListing>('/v1/solution-packages/');
}

export function installPackages(packageIds: string[], optional: string[] = []): Promise<InstallResult> {
  return apiPost<InstallResult>('/v1/solution-packages/install/', { package_ids: packageIds, optional });
}

export function setModuleEnabled(
  module: string,
  enabled: boolean,
  force = false,
): Promise<PackageState & { affected: string[] }> {
  return apiPut(`/v1/solution-packages/modules/${encodeURIComponent(module)}/`, { enabled, force });
}

export function removePackage(
  packageId: string,
  confirm: boolean,
): Promise<PackageState & { hidden: string[]; removed: boolean }> {
  return apiPost(`/v1/solution-packages/${encodeURIComponent(packageId)}/remove/`, { confirm });
}

export function seedPackageDemo(packageId: string): Promise<{ demo_id: string | null; project_id?: string }> {
  return apiPost(`/v1/solution-packages/${encodeURIComponent(packageId)}/demo/`);
}

export function fetchFocusPreview(slug: string): Promise<FocusPreview> {
  return apiGet<FocusPreview>(`/v1/solution-packages/focus/${encodeURIComponent(slug)}/preview/`);
}

export function focusOnPack(slug: string): Promise<PackageState & { preview: FocusPreview }> {
  return apiPost(`/v1/solution-packages/focus/${encodeURIComponent(slug)}/`);
}

export function showAllModules(): Promise<PackageState> {
  return apiPost('/v1/solution-packages/show-all/');
}

export function useFocusPreview(slug: string | null | undefined) {
  return useQuery({
    queryKey: ['solution-packages', 'focus-preview', slug],
    queryFn: () => fetchFocusPreview(slug as string),
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
  });
}

export function useSolutionPackages(enabled = true) {
  return useQuery({
    queryKey: PACKAGES_QUERY_KEY,
    queryFn: fetchPackages,
    enabled,
    staleTime: 30 * 1000,
  });
}
