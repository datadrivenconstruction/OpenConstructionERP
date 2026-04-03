import { describe, it, expect, beforeEach } from 'vitest';
import { usePreferencesStore } from './usePreferencesStore';

describe('usePreferencesStore', () => {
  beforeEach(() => {
    localStorage.clear();
    usePreferencesStore.getState().resetPreferences();
  });

  it('should have correct default values', () => {
    const state = usePreferencesStore.getState();
    expect(state.currency).toBe('EUR');
    expect(state.measurementSystem).toBe('metric');
    expect(state.dateFormat).toBe('DD.MM.YYYY');
    expect(state.numberLocale).toBe('de-DE');
    expect(state.vatRate).toBe(19);
  });

  it('should update currency via setPreference', () => {
    usePreferencesStore.getState().setPreference('currency', 'GBP');
    expect(usePreferencesStore.getState().currency).toBe('GBP');
  });

  it('should update measurement system via setPreference', () => {
    usePreferencesStore.getState().setPreference('measurementSystem', 'imperial');
    expect(usePreferencesStore.getState().measurementSystem).toBe('imperial');
  });

  it('should update date format via setPreference', () => {
    usePreferencesStore.getState().setPreference('dateFormat', 'MM/DD/YYYY');
    expect(usePreferencesStore.getState().dateFormat).toBe('MM/DD/YYYY');
  });

  it('should update number locale via setPreference', () => {
    usePreferencesStore.getState().setPreference('numberLocale', 'en-US');
    expect(usePreferencesStore.getState().numberLocale).toBe('en-US');
  });

  it('should update VAT rate via setPreference', () => {
    usePreferencesStore.getState().setPreference('vatRate', 20);
    expect(usePreferencesStore.getState().vatRate).toBe(20);
  });

  it('should update multiple preferences at once', () => {
    usePreferencesStore.getState().setPreferences({ currency: 'USD', vatRate: 0 });
    const state = usePreferencesStore.getState();
    expect(state.currency).toBe('USD');
    expect(state.vatRate).toBe(0);
  });

  it('should reset to defaults', () => {
    usePreferencesStore.getState().setPreference('currency', 'CHF');
    usePreferencesStore.getState().resetPreferences();
    expect(usePreferencesStore.getState().currency).toBe('EUR');
  });

  it('should format currency correctly', () => {
    const { formatCurrency } = usePreferencesStore.getState();
    const result = formatCurrency(1234.56);
    expect(result).toContain('1');
    expect(result).toContain('234');
  });

  it('should format numbers correctly', () => {
    const { formatNumber } = usePreferencesStore.getState();
    const result = formatNumber(1234.567, 2);
    expect(result).toContain('1');
    expect(result).toContain('234');
  });

  it('should persist to localStorage', () => {
    usePreferencesStore.getState().setPreference('currency', 'JPY');
    const stored = JSON.parse(localStorage.getItem('oe_preferences') || '{}');
    expect(stored.currency).toBe('JPY');
  });
});
