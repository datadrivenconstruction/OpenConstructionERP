/**
 * Global store for cost database state.
 *
 * Tracks the active region so that cost search, BOQ autocomplete,
 * and other consumers all use the same filter.
 */

import { create } from 'zustand';

const ACTIVE_DB_KEY = 'oe_active_database';

const REGION_ALIASES: Record<string, string> = {
  TR_ISTANBUL: 'TR_NATIONAL',
  ZH_SHANGHAI: 'ZH_CHINA',
};

function readActiveRegion(): string {
  try {
    const saved = localStorage.getItem(ACTIVE_DB_KEY) ?? '';
    return REGION_ALIASES[saved] ?? saved;
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
  ZH_CHINA: { label: 'China (CNY)', name: 'China', flag: 'cn', currency: 'CNY' },
  HI_MUMBAI: { label: 'India (INR)', name: 'India / South Asia', flag: 'in', currency: 'INR' },
  // Added 2026-04-28 — DDC CWICR repo expanded from 11 to 30 regions.
  AU_SYDNEY: { label: 'Australia (AUD)', name: 'Australia', flag: 'au', currency: 'AUD' },
  BG_SOFIA: { label: 'Bulgaria (BGN)', name: 'Bulgaria', flag: 'bg', currency: 'BGN' },
  CS_PRAGUE: { label: 'Czechia (CZK)', name: 'Czech Republic', flag: 'cz', currency: 'CZK' },
  HR_ZAGREB: { label: 'Croatia (EUR)', name: 'Croatia', flag: 'hr', currency: 'EUR' },
  ID_JAKARTA: { label: 'Indonesia (IDR)', name: 'Indonesia', flag: 'id', currency: 'IDR' },
  IT_ROME: { label: 'Italy (EUR)', name: 'Italy', flag: 'it', currency: 'EUR' },
  JA_TOKYO: { label: 'Japan (JPY)', name: 'Japan', flag: 'jp', currency: 'JPY' },
  KO_SEOUL: { label: 'South Korea (KRW)', name: 'South Korea', flag: 'kr', currency: 'KRW' },
  MX_MEXICOCITY: { label: 'Mexico (MXN)', name: 'Mexico', flag: 'mx', currency: 'MXN' },
  NG_LAGOS: { label: 'Nigeria (NGN)', name: 'Nigeria', flag: 'ng', currency: 'NGN' },
  NL_AMSTERDAM: { label: 'Netherlands (EUR)', name: 'Netherlands', flag: 'nl', currency: 'EUR' },
  NZ_AUCKLAND: { label: 'New Zealand (NZD)', name: 'New Zealand', flag: 'nz', currency: 'NZD' },
  PL_WARSAW: { label: 'Poland (PLN)', name: 'Poland', flag: 'pl', currency: 'PLN' },
  RO_BUCHAREST: { label: 'Romania (RON)', name: 'Romania', flag: 'ro', currency: 'RON' },
  SV_STOCKHOLM: { label: 'Sweden (SEK)', name: 'Sweden', flag: 'se', currency: 'SEK' },
  TH_BANGKOK: { label: 'Thailand (THB)', name: 'Thailand', flag: 'th', currency: 'THB' },
  TR_NATIONAL: { label: 'Türkiye (TRY)', name: 'Türkiye', flag: 'tr', currency: 'TRY' },
  VI_HANOI: { label: 'Vietnam (VND)', name: 'Vietnam', flag: 'vn', currency: 'VND' },
  ZA_JOHANNESBURG: { label: 'South Africa (ZAR)', name: 'South Africa', flag: 'za', currency: 'ZAR' },
  // Authentic national / regional official bases (own local parquet).
  BR_NATIONAL: { label: 'Brazil (BRL)', name: 'Brazil (SINAPI)', flag: 'br', currency: 'BRL' },
  ES_ANDALUCIA: { label: 'Spain (EUR)', name: 'Spain (BCCA)', flag: 'es', currency: 'EUR' },
  IT_TOSCANA: { label: 'Italy (EUR)', name: 'Italy (Toscana)', flag: 'it', currency: 'EUR' },
  VN_NATIONAL: { label: 'Vietnam (VND)', name: 'Vietnam (Dinh Muc)', flag: 'vn', currency: 'VND' },
  ID_NATIONAL: { label: 'Indonesia (IDR)', name: 'Indonesia (AHSP)', flag: 'id', currency: 'IDR' },
  GR_NATIONAL: { label: 'Greece (EUR)', name: 'Greece (GGDE)', flag: 'gr', currency: 'EUR' },
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
    const canonical = REGION_ALIASES[region] ?? region;
    try {
      localStorage.setItem(ACTIVE_DB_KEY, canonical);
    } catch {
      // Storage unavailable — ignore.
    }
    set({ activeRegion: canonical });
  },
}));
