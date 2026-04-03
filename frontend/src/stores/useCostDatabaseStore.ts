/**
 * Global store for cost database state.
 *
 * Tracks the active region so that cost search, BOQ autocomplete,
 * and other consumers all use the same filter.
 */

import { create } from 'zustand';

const ACTIVE_DB_KEY = 'oe_active_database';

function readActiveRegion(): string {
  try {
    return localStorage.getItem(ACTIVE_DB_KEY) ?? '';
  } catch {
    return '';
  }
}

interface RegionInfo {
  label: string;
  name: string;
  flag: string;
  currency: string;
}

export const REGION_MAP: Record<string, RegionInfo> = {
  USA_USD: { label: 'USA (USD)', name: 'United States', flag: 'us', currency: 'USD' },
  UK_GBP: { label: 'UK (GBP)', name: 'United Kingdom', flag: 'gb', currency: 'GBP' },
  DE_BERLIN: { label: 'Germany (EUR)', name: 'Germany / DACH', flag: 'de', currency: 'EUR' },
  ENG_TORONTO: { label: 'Canada (CAD)', name: 'Canada / International', flag: 'ca', currency: 'CAD' },
  FR_PARIS: { label: 'France (EUR)', name: 'France', flag: 'fr', currency: 'EUR' },
  SP_BARCELONA: { label: 'Spain (EUR)', name: 'Spain / Latin America', flag: 'es', currency: 'EUR' },
  PT_SAOPAULO: { label: 'Brazil (BRL)', name: 'Brazil / Portugal', flag: 'br', currency: 'BRL' },
  RU_STPETERSBURG: { label: 'Russia (RUB)', name: 'Russia / CIS', flag: 'ru', currency: 'RUB' },
  AR_DUBAI: { label: 'Middle East (AED)', name: 'Middle East / Gulf', flag: 'ae', currency: 'AED' },
  ZH_SHANGHAI: { label: 'China (CNY)', name: 'China', flag: 'cn', currency: 'CNY' },
  HI_MUMBAI: { label: 'India (INR)', name: 'India / South Asia', flag: 'in', currency: 'INR' },
  CUSTOM: { label: 'My Database', name: 'My Database', flag: 'custom', currency: '' },
};

interface CostDatabaseStore {
  /** Currently active region ID (empty string = all regions). */
  activeRegion: string;
  /** Set the active region and persist to localStorage. */
  setActiveRegion: (region: string) => void;
}

export const useCostDatabaseStore = create<CostDatabaseStore>((set) => ({
  activeRegion: readActiveRegion(),

  setActiveRegion: (region: string) => {
    try {
      localStorage.setItem(ACTIVE_DB_KEY, region);
    } catch {
      // Storage unavailable — ignore.
    }
    set({ activeRegion: region });
  },
}));
