// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Global store for cost database state.
 *
 * Tracks the active region so that cost search, BOQ autocomplete,
 * and other consumers all use the same filter.
 */

import { create } from 'zustand';

const ACTIVE_DB_KEY = 'oe_active_database';

// There is deliberately no alias table here, and that is worth a sentence
// because one used to exist. It mapped TR_ISTANBUL to TR_NATIONAL and
// ZH_SHANGHAI to ZH_CHINA on both read and write, having been added by the
// commit that wired the national bases and treated those pairs as renames.
// They are not renames. ZH_SHANGHAI and TR_ISTANBUL are global-market
// catalogues; ZH_CHINA is the Chinese Dinge base and TR_NATIONAL the Turkish
// Birim Fiyat base, each its own norm system in its own folder, and all four
// load separately (see base_registry.py). Rewriting the id here meant the
// China and Turkiye country packs installed one base and then filtered on the
// other, so BOQ autocomplete matched zero rows with nothing shown to explain
// it. Keep both members of each pair in REGION_MAP below; an id that has no
// entry there is what made the alias look like a fix in the first place.
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
  TR_ISTANBUL: { label: 'Türkiye (TRY)', name: 'Türkiye', flag: 'tr', currency: 'TRY' },
  VI_HANOI: { label: 'Vietnam (VND)', name: 'Vietnam', flag: 'vn', currency: 'VND' },
  ZA_JOHANNESBURG: { label: 'South Africa (ZAR)', name: 'South Africa', flag: 'za', currency: 'ZAR' },
  // Authentic national / regional official bases (own local parquet). These
  // name their norm system, because each sits beside a global-market entry for
  // the same country and two cards both reading "China" is how the two got
  // conflated before.
  ZH_CHINA: { label: 'China (CNY)', name: 'China (Dinge)', flag: 'cn', currency: 'CNY' },
  TR_NATIONAL: { label: 'Türkiye (TRY)', name: 'Türkiye (Birim Fiyat)', flag: 'tr', currency: 'TRY' },
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
    try {
      localStorage.setItem(ACTIVE_DB_KEY, region);
    } catch {
      // Storage unavailable — ignore.
    }
    set({ activeRegion: region });
  },
}));
