// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The UI appearance in effect: the user's own choice layered over the
 * workspace default an admin set. See `shared/lib/appearance.ts` for the axes
 * and the boot script in index.html for the first paint.
 *
 * `user` is null when the user follows the workspace. Picking anything makes a
 * full personal override; "Use workspace default" clears it again.
 *
 * The menu look (`shared/lib/menuAppearance.ts`) layers the same way, kept
 * apart from the style so each card resets only its own part. Icon overrides
 * are personal only.
 */
import { create } from 'zustand';
import {
  type Appearance,
  type AppearanceAxis,
  USER_APPEARANCE_KEY,
  WORKSPACE_APPEARANCE_KEY,
  applyAppearance,
  readStoredAppearance,
  resolveAppearance,
  sanitizeAppearance,
  writeStoredAppearance,
} from '@/shared/lib/appearance';
import {
  type IconOverrides,
  type MenuAxis,
  type MenuLook,
  USER_MENU_KEY,
  WORKSPACE_MENU_KEY,
  MENU_ICON_OVERRIDES_KEY,
  applyMenu,
  readIconOverrides,
  readStoredMenu,
  resolveMenu,
  sanitizeIconOverrides,
  sanitizeMenu,
  writeIconOverrides,
  writeStoredMenu,
} from '@/shared/lib/menuAppearance';

interface AppearanceState {
  /** Personal override, or null to follow the workspace default. */
  user: Partial<Appearance> | null;
  /** Workspace default from the server (cached locally), or null. */
  workspace: Partial<Appearance> | null;
  /** What is applied right now. */
  effective: Appearance;
  /** Replace the personal choice with a whole style. */
  setAppearance: (value: Appearance) => void;
  /** Change one axis; the rest keep their current effective value. */
  setAxis: <K extends AppearanceAxis>(axis: K, value: Appearance[K]) => void;
  /** Drop the personal override and follow the workspace default again. */
  followWorkspace: () => void;
  /** Take the workspace default from the branding payload (unvalidated input). */
  setWorkspaceDefault: (raw: unknown) => void;

  /** Personal menu look, or null to follow the workspace default. */
  menuUser: Partial<MenuLook> | null;
  /** Workspace default menu look (cached locally), or null. */
  menuWorkspace: Partial<MenuLook> | null;
  /** Menu look applied right now. */
  menu: MenuLook;
  /** Replace the personal menu look with a whole one (a preset). */
  setMenu: (value: MenuLook) => void;
  /** Change one menu axis; the rest keep their current effective value. */
  setMenuAxis: <K extends MenuAxis>(axis: K, value: MenuLook[K]) => void;
  /** Drop the personal menu look and follow the workspace default again. */
  followWorkspaceMenu: () => void;
  /** Take the workspace default menu look (unvalidated input). */
  setWorkspaceMenu: (raw: unknown) => void;

  /** Per-item icon overrides: menu route -> catalogue icon name. */
  iconOverrides: IconOverrides;
  /** Set (name) or reset (null) the icon of one menu route. */
  setIconOverride: (route: string, name: string | null) => void;
  /** Reset every icon override. */
  resetIconOverrides: () => void;
}

function commit(user: Partial<Appearance> | null, workspace: Partial<Appearance> | null) {
  const effective = resolveAppearance(user, workspace);
  if (typeof document !== 'undefined') applyAppearance(effective);
  return { user, workspace, effective };
}

function commitMenu(menuUser: Partial<MenuLook> | null, menuWorkspace: Partial<MenuLook> | null) {
  const menu = resolveMenu(menuUser, menuWorkspace);
  if (typeof document !== 'undefined') applyMenu(menu);
  return { menuUser, menuWorkspace, menu };
}

export const useAppearanceStore = create<AppearanceState>((set, get) => {
  const user = readStoredAppearance(USER_APPEARANCE_KEY);
  const workspace = readStoredAppearance(WORKSPACE_APPEARANCE_KEY);
  const menuUser = readStoredMenu(USER_MENU_KEY);
  const menuWorkspace = readStoredMenu(WORKSPACE_MENU_KEY);

  if (typeof window !== 'undefined') {
    // Another tab changed the choice: follow it without a reload.
    window.addEventListener('storage', (e) => {
      if (e.key === USER_MENU_KEY || e.key === WORKSPACE_MENU_KEY) {
        set(commitMenu(readStoredMenu(USER_MENU_KEY), readStoredMenu(WORKSPACE_MENU_KEY)));
        return;
      }
      if (e.key === MENU_ICON_OVERRIDES_KEY) {
        set({ iconOverrides: readIconOverrides() });
        return;
      }
      if (e.key !== USER_APPEARANCE_KEY && e.key !== WORKSPACE_APPEARANCE_KEY) return;
      set(
        commit(readStoredAppearance(USER_APPEARANCE_KEY), readStoredAppearance(WORKSPACE_APPEARANCE_KEY)),
      );
    });
  }

  return {
    user,
    workspace,
    effective: resolveAppearance(user, workspace),

    setAppearance: (value) => {
      const next = sanitizeAppearance(value);
      writeStoredAppearance(USER_APPEARANCE_KEY, next);
      set(commit(next, get().workspace));
    },

    setAxis: (axis, value) => {
      get().setAppearance({ ...get().effective, [axis]: value });
    },

    followWorkspace: () => {
      writeStoredAppearance(USER_APPEARANCE_KEY, null);
      set(commit(null, get().workspace));
    },

    setWorkspaceDefault: (raw) => {
      const next = sanitizeAppearance(raw);
      writeStoredAppearance(WORKSPACE_APPEARANCE_KEY, next);
      set(commit(get().user, next));
    },

    menuUser,
    menuWorkspace,
    menu: resolveMenu(menuUser, menuWorkspace),

    setMenu: (value) => {
      const next = sanitizeMenu(value);
      writeStoredMenu(USER_MENU_KEY, next);
      set(commitMenu(next, get().menuWorkspace));
    },

    setMenuAxis: (axis, value) => {
      get().setMenu({ ...get().menu, [axis]: value });
    },

    followWorkspaceMenu: () => {
      writeStoredMenu(USER_MENU_KEY, null);
      set(commitMenu(null, get().menuWorkspace));
    },

    setWorkspaceMenu: (raw) => {
      const next = sanitizeMenu(raw);
      writeStoredMenu(WORKSPACE_MENU_KEY, next);
      set(commitMenu(get().menuUser, next));
    },

    iconOverrides: readIconOverrides(),

    setIconOverride: (route, name) => {
      const next = { ...get().iconOverrides };
      if (name) next[route] = name;
      else delete next[route];
      const clean = sanitizeIconOverrides(next);
      writeIconOverrides(clean);
      set({ iconOverrides: clean });
    },

    resetIconOverrides: () => {
      writeIconOverrides({});
      set({ iconOverrides: {} });
    },
  };
});
