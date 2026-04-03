/**
 * User preferences store.
 *
 * Centralizes regional/formatting settings used across the app:
 * currency, measurement system, date format, number format.
 *
 * Persists to localStorage so preferences survive page reloads.
 */

import { create } from 'zustand';

const STORAGE_KEY = 'oe_preferences';

export type MeasurementSystem = 'metric' | 'imperial';
export type DateFormat = 'DD.MM.YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD';
export type NumberLocale = 'de-DE' | 'en-US' | 'en-GB' | 'fr-FR' | 'ru-RU' | 'ar-SA' | 'ja-JP' | 'zh-CN';

interface Preferences {
  currency: string;
  measurementSystem: MeasurementSystem;
  dateFormat: DateFormat;
  numberLocale: NumberLocale;
  vatRate: number;
  defaultRegion: string;
  defaultCurrency: string;
  defaultStandard: string;
}

const DEFAULTS: Preferences = {
  currency: 'EUR',
  measurementSystem: 'metric',
  dateFormat: 'DD.MM.YYYY',
  numberLocale: 'de-DE',
  vatRate: 19,
  defaultRegion: 'DACH',
  defaultCurrency: 'EUR',
  defaultStandard: 'din276',
};

function readPreferences(): Preferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

function persist(prefs: Preferences) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch { /* ignore */ }
}

interface PreferencesState extends Preferences {
  setPreference: <K extends keyof Preferences>(key: K, value: Preferences[K]) => void;
  setPreferences: (updates: Partial<Preferences>) => void;
  resetPreferences: () => void;

  /** Format a number as currency using current settings */
  formatCurrency: (amount: number) => string;
  /** Format a number using current locale */
  formatNumber: (value: number, decimals?: number) => string;
}

export const usePreferencesStore = create<PreferencesState>((set, get) => ({
  ...readPreferences(),

  setPreference: (key, value) => {
    const next = { ...readPreferences(), [key]: value };
    persist(next);
    set({ [key]: value });
  },

  setPreferences: (updates) => {
    const current = get();
    const next = { ...current, ...updates };
    persist(next);
    set(updates);
  },

  resetPreferences: () => {
    persist(DEFAULTS);
    set(DEFAULTS);
  },

  formatCurrency: (amount: number) => {
    const { currency, numberLocale } = get();
    const safe = /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
    try {
      return new Intl.NumberFormat(numberLocale, {
        style: 'currency',
        currency: safe,
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      return `${amount.toFixed(2)} ${safe}`;
    }
  },

  formatNumber: (value: number, decimals = 2) => {
    const { numberLocale } = get();
    try {
      return new Intl.NumberFormat(numberLocale, {
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals,
      }).format(value);
    } catch {
      return value.toFixed(decimals);
    }
  },
}));
