import { create } from 'zustand';

type ThemeMode = 'light' | 'dark' | 'system';

interface ThemeState {
  /** User preference: light, dark, or system. */
  theme: ThemeMode;
  /** Resolved effective theme after evaluating system preference. */
  resolved: 'light' | 'dark';
  /** Set theme and persist to localStorage. */
  setTheme: (theme: ThemeMode) => void;
  /** Convenience: cycle light -> dark -> system -> light. */
  toggleTheme: () => void;
  /** Initialize from localStorage + system preference. Call once on mount. */
  init: () => void;
}

const STORAGE_KEY = 'oe_theme';

function getSystemPreference(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'system') return getSystemPreference();
  return mode;
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

  setTheme: (theme) => {
    const resolved = resolveTheme(theme);
    localStorage.setItem(STORAGE_KEY, theme);
    applyTheme(resolved);
    set({ theme, resolved });
  },

  toggleTheme: () => {
    const { theme } = get();
    const next: ThemeMode = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';
    get().setTheme(next);
  },

  init: () => {
    const stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
    const theme: ThemeMode = stored && ['light', 'dark', 'system'].includes(stored) ? stored : 'system';
    const resolved = resolveTheme(theme);

    // Apply immediately (no transition on initial load)
    if (resolved === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }

    set({ theme, resolved });

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
