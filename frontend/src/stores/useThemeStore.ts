// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { create } from 'zustand';
import {
  THEME_KEY,
  THEME_SCHEDULE_KEY,
  readStoredSchedule,
  readStoredThemeMode,
  resolveTheme as resolveThemeMode,
  type ThemeMode,
  type ThemeSchedule,
} from '@/shared/lib/theme';

export type { ThemeMode, ThemeSchedule };

interface ThemeState {
  /** User preference: light, dark, system, or dark by time of day. */
  theme: ThemeMode;
  /** Hours of the dark window used by the `schedule` mode. */
  schedule: ThemeSchedule;
  /** Change the dark window and persist it. */
  setSchedule: (schedule: ThemeSchedule) => void;
  /** Resolved effective theme after evaluating system preference. */
  resolved: 'light' | 'dark';
  /** Set theme and persist to localStorage. */
  setTheme: (theme: ThemeMode) => void;
  /** Convenience: cycle light -> dark -> system -> light. */
  toggleTheme: () => void;
  /** Initialize from localStorage + system preference. Call once on mount. */
  init: () => void;
}

const STORAGE_KEY = THEME_KEY;

function getSystemPreference(): 'light' | 'dark' {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveTheme(mode: ThemeMode, schedule: ThemeSchedule = readStoredSchedule()): 'light' | 'dark' {
  return resolveThemeMode(mode, {
    systemDark: getSystemPreference() === 'dark',
    hour: new Date().getHours(),
    schedule,
  });
}

function applyTheme(resolved: 'light' | 'dark'): void {
  const root = document.documentElement;

  // Add a transient class to enable smooth color transitions
  root.classList.add('theme-transition');

  if (resolved === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }

  // Remove transition class after animation completes to avoid interfering
  // with normal interactive transitions elsewhere
  window.setTimeout(() => {
    root.classList.remove('theme-transition');
  }, 350);
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: 'system',
  resolved: 'light',
  schedule: readStoredSchedule(),

  setTheme: (theme) => {
    const resolved = resolveTheme(theme, get().schedule);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* storage unavailable: applies for this session */
    }
    if (resolved !== get().resolved || theme !== get().theme) applyTheme(resolved);
    set({ theme, resolved });
  },

  setSchedule: (schedule) => {
    try {
      localStorage.setItem(THEME_SCHEDULE_KEY, JSON.stringify(schedule));
    } catch {
      /* storage unavailable: applies for this session */
    }
    set({ schedule });
    get().setTheme(get().theme);
  },

  toggleTheme: () => {
    const { theme } = get();
    const next: ThemeMode = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';
    get().setTheme(next);
  },

  init: () => {
    const theme = readStoredThemeMode();
    const schedule = readStoredSchedule();
    const resolved = resolveTheme(theme, schedule);

    // Apply immediately (no transition on initial load)
    if (resolved === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }

    set({ theme, resolved, schedule });

    // Time-of-day mode: re-check each minute so the switch lands on the hour.
    window.setInterval(() => {
      const current = get();
      if (current.theme !== 'schedule') return;
      const next = resolveTheme('schedule', current.schedule);
      if (next !== current.resolved) {
        applyTheme(next);
        set({ resolved: next });
      }
    }, 60_000);

    // Listen for OS-level preference changes when in "system" mode
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => {
      const current = get();
      if (current.theme === 'system') {
        const newResolved = getSystemPreference();
        applyTheme(newResolved);
        set({ resolved: newResolved });
      }
    };
    mql.addEventListener('change', handler);
  },
}));
