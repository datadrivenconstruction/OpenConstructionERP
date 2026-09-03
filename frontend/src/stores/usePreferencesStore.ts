// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * User preferences store.
 *
 * Centralizes regional/formatting settings used across the app:
 * currency, measurement system, date format, number format.
 *
 * Persists to localStorage so preferences survive page reloads, and hydrates
 * from the user's ACCOUNT on the server on boot (issue #335) so a preference
 * set on one device (e.g. imperial units) is honoured after a fresh login on
 * another. localStorage remains the offline cache.
 */

import { create } from 'zustand';
import { apiGet } from '@/shared/lib/api';
import { getIntlLocale, useIntlLocale } from '@/shared/lib/intlLocale';
import { getMarketNumberLocale, useMarketNumberLocale } from '@/shared/lib/marketNumberLocale';

const STORAGE_KEY = 'oe_preferences';

/**
 * Bumped when a stored value has to be re-read rather than merged. Rides in the
 * same blob as the preferences so one localStorage entry still holds the whole
 * cache. See `LEGACY_NUMBER_LOCALE` for the migration this version guards.
 */
const SCHEMA_VERSION = 2;

export type MeasurementSystem = 'metric' | 'imperial';
/**
 * Date-format preference. `'auto'` means "follow the UI language" and is the
 * default: it renders exactly what the app rendered before the preference was
 * wired into the date surfaces, so an account that never picked a format sees
 * no change. See `formatDateWithPreference` in `@/shared/lib/formatters`.
 */
export type DateFormat = 'auto' | 'DD.MM.YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD';
/**
 * Number-format preference. `'auto'` means "follow the UI language" and is the
 * default, for the same reason `DateFormat` defaults that way: every other
 * number surface in the app resolves through `getIntlLocale()`, so a
 * preference that defaulted to one fixed locale put the money surfaces on a
 * different answer from the rest of the product. That is what wrote the same
 * amount as `$180,174.28` on the bill of quantities and `180.174,28 $` on the
 * finance register inside one English UI. Resolve it with
 * `resolveNumberLocale` or, in a component, `useNumberLocale`.
 */
export type NumberLocale =
  | 'auto'
  | 'de-DE'
  | 'en-US'
  | 'en-GB'
  | 'fr-FR'
  | 'ru-RU'
  | 'ar-SA'
  | 'ja-JP'
  | 'zh-CN'
  | 'es-MX'
  | 'en-IN';

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
  dateFormat: 'auto',
  numberLocale: 'auto',
  vatRate: 19,
  defaultRegion: 'DACH',
  defaultCurrency: 'EUR',
  defaultStandard: 'din276',
};

/**
 * The literal `numberLocale` carried as its hardcoded default before `'auto'`
 * existed.
 *
 * Changing the default alone would have fixed nothing for anybody: `persist`
 * writes the whole object on every change, so any browser that ever touched a
 * single preference has this value written down, and a stored value is
 * indistinguishable from a deliberate choice of German separators. We resolve
 * it in favour of `'auto'` exactly once, on the first read after the upgrade,
 * and record the schema version so a `'de-DE'` chosen from here on is kept.
 *
 * The only reader this can surprise is one running a non-German UI who
 * deliberately picked German numbers: on a German UI `'auto'` resolves to
 * `'de-DE'` and the migration is a no-op. That is the same trade
 * `adoptServerDateFormat` makes below, for the same reason.
 */
const LEGACY_NUMBER_LOCALE = 'de-DE';

function readPreferences(): Preferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    const { _v: version, ...stored } = JSON.parse(raw) as Partial<Preferences> & { _v?: number };
    const prefs: Preferences = { ...DEFAULTS, ...stored };
    if ((version ?? 1) < SCHEMA_VERSION && prefs.numberLocale === LEGACY_NUMBER_LOCALE) {
      prefs.numberLocale = 'auto';
    }
    return prefs;
  } catch {
    return DEFAULTS;
  }
}

function persist(prefs: Preferences) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...prefs, _v: SCHEMA_VERSION }));
  } catch { /* ignore */ }
}

/**
 * The locale to actually format a number with.
 *
 * This is the single resolver: a surface that renders a number reads the
 * preference through here, never straight off the store, so "which locale" has
 * one answer across the whole product rather than one answer per component.
 *
 * `'auto'` asks the market before it asks the UI language. Those are ordered
 * that way because digit grouping belongs to the document rather than to
 * whoever opened it: an Indian bill of quantities is grouped in lakh and crore
 * for a German reviewer exactly as it is for the estimator who wrote it, and
 * the alternative printed `476,579,722.78` on a document whose readers all
 * write `47,65,79,722.78`. An explicit preference still outranks both, so a
 * reader who went to regional settings and picked a format is never overruled
 * by the market they are working in.
 */
export function resolveNumberLocale(preference: NumberLocale): string {
  if (preference !== 'auto') return preference;
  return getMarketNumberLocale() ?? getIntlLocale();
}

/**
 * `resolveNumberLocale` for a caller that cannot hold a hook.
 *
 * A grid cell renderer is a plain function called by the grid, not a component
 * React owns, so it cannot subscribe to anything. This reads the preference at
 * the moment of the call. That makes it a snapshot, and a snapshot is only
 * correct because the surfaces that use it are repainted from above: the grid
 * rebuilds its context and its column definitions when the locale moves, and
 * the renderers run again. Keep those two halves in mind together. Dropping the
 * locale from a grid's dependencies would leave these cells reading a value
 * nobody asks them to read again.
 */
export function getNumberLocale(): string {
  return resolveNumberLocale(usePreferencesStore.getState().numberLocale);
}

/**
 * `resolveNumberLocale` bound to all three of the things it depends on.
 *
 * Reading the preference alone is not enough for a component: with `'auto'` the
 * answer also moves when the UI language moves, and the store has no idea that
 * happened. Subscribing to both is what makes a language switch reach the
 * numbers instead of leaving them in the previous language until an unrelated
 * prop re-renders them.
 *
 * The market is the third, and it needs the subscription for a reason the
 * other two do not have: the pack manifest arrives over the network after
 * first paint, so every amount on screen was formatted before the workspace
 * knew which market it serves. Without this, an Indian workspace would show
 * the Western grouping until something unrelated repainted it.
 */
export function useNumberLocale(): string {
  const preference = usePreferencesStore((s) => s.numberLocale);
  const intlLocale = useIntlLocale();
  const marketLocale = useMarketNumberLocale();
  if (preference !== 'auto') return preference;
  return marketLocale ?? intlLocale;
}

/* ── Server hydration (issue #335) ────────────────────────────────────── */

/** Shape of GET /v1/users/me/preferences/ (the account-level regional prefs). */
interface ServerPreferences {
  measurement_system?: string;
  date_format?: string;
  number_format?: string;
  currency_code?: string;
}

// Allow-lists so a server value is applied ONLY when it matches a value the
// store actually understands - a stray or future server value is skipped, never
// forced into the union.
const MEASUREMENT_SYSTEMS: readonly MeasurementSystem[] = ['metric', 'imperial'];
const DATE_FORMATS: readonly DateFormat[] = ['auto', 'DD.MM.YYYY', 'MM/DD/YYYY', 'YYYY-MM-DD'];

/**
 * The value the account column carries when nobody ever picked a date format:
 * `users.date_format` is NOT NULL and defaults to this, so on an account that
 * predates the "automatic" option the value is ambiguous between "never chose"
 * and "chose the day-first order".
 */
const LEGACY_ACCOUNT_DATE_FORMAT = 'DD.MM.YYYY';

/**
 * Decide what a server `date_format` means for this browser.
 *
 * Returns `undefined` for "leave the local value alone". We resolve the
 * ambiguous legacy default in favour of automatic unless this browser already
 * carries an explicit choice, which is what keeps every existing account
 * rendering exactly as it does today instead of switching to numeric dates on
 * the next sign-in. The two orders the column default can never produce, and
 * an explicit `auto`, are always adopted. A value outside the vocabulary (the
 * regional packs also ship `DD/MM/YYYY` and `YYYY/MM/DD`) is left alone rather
 * than forced, so it falls through to the `'auto'` default on a fresh browser.
 */
function adoptServerDateFormat(server: string, local: DateFormat): DateFormat | undefined {
  if (!(DATE_FORMATS as readonly string[]).includes(server)) return undefined;
  if (server === LEGACY_ACCOUNT_DATE_FORMAT && local === 'auto') return undefined;
  return server as DateFormat;
}
/**
 * The value the account column carries when nobody ever picked a number
 * format: `users.number_format` is NOT NULL and defaulted to this for every
 * account created anywhere in the world, so the stored string is ambiguous
 * between "never chose" and "chose German grouping". Same ambiguity as
 * `LEGACY_ACCOUNT_DATE_FORMAT` above, same resolution.
 */
const LEGACY_ACCOUNT_NUMBER_FORMAT = '1.234,56';

// The account stores the number format as a display PATTERN, not a BCP-47
// locale; map the known patterns onto the locale the store formats with.
const NUMBER_FORMAT_TO_LOCALE: Record<string, NumberLocale> = {
  '1.234,56': 'de-DE',
  '1,234.56': 'en-US',
  '1 234,56': 'fr-FR',
};

/**
 * The locale the seeded account pattern would be read as, derived rather than
 * written down so the two cannot drift apart.
 *
 * It is the only local value that AGREES with the seeded default, which is
 * what `adoptServerNumberFormat` needs to tell "chose German" apart from
 * "chose something, and the column still holds what the seed put there".
 */
const SEEDED_ACCOUNT_LOCALE: NumberLocale | undefined =
  NUMBER_FORMAT_TO_LOCALE[LEGACY_ACCOUNT_NUMBER_FORMAT];

/**
 * Every value `numberLocale` may hold, for validating what the server sends.
 *
 * Exported because the regional-settings picker builds its buttons from this
 * list rather than from a second one of its own. A value the type allows and
 * the picker has no button for is a setting the reader cannot reach: `en-IN`
 * was missing for exactly that reason, so Indian rupees were offered as a
 * currency while lakh and crore grouping was unreachable by any choice.
 */
export const NUMBER_LOCALES: readonly NumberLocale[] = [
  'auto', 'de-DE', 'en-US', 'en-GB', 'fr-FR', 'ru-RU', 'ar-SA', 'ja-JP', 'zh-CN', 'es-MX', 'en-IN',
];

/**
 * The number locale a country's documents are grouped in, or `null`.
 *
 * A country earns an entry here only when its tag actually changes the
 * grouping. India does: `en-IN` writes `47,65,79,722.78` where `en-US` writes
 * `476,579,722.78`, and that lakh/crore grouping is what every estimator,
 * contractor and auditor in that market reads. Germany and the United States
 * do not, because the UI language already resolves to their own tags, and
 * answering for them here would put a second opinion on top of a reader whose
 * separators were already right.
 *
 * Measured before it was written, and the measurement is why the table has one
 * row. Pakistan, Bangladesh, Sri Lanka and Nepal use the same lakh system in
 * life, but `en-PK`, `en-BD`, `en-LK` and `en-NP` all resolve to plain `en` and
 * group by threes, so there is no tag to map them onto and an entry would be a
 * promise the engine cannot keep. Their answer is a different piece of work,
 * not another line here.
 *
 * The return type is `NumberLocale`, so a tag that is not one of the values
 * the store understands cannot be added to this table without the compiler
 * saying so.
 *
 * @param country ISO 3166-1 alpha-2, any case; `null` when nothing says.
 */
export function numberLocaleForCountry(country: string | null | undefined): NumberLocale | null {
  const cc = (country || '').trim().toLowerCase();
  return cc === 'in' ? 'en-IN' : null;
}

/**
 * Read a server `number_format` in either of the two vocabularies the field
 * has been written in.
 *
 * The account column holds a display PATTERN - `i18n_data.py` seeds `1.234,56`
 * - but the regional-settings toggle has always PATCHed a BCP-47 tag into the
 * same free-form field. So a choice made in the UI came back as a value
 * `NUMBER_FORMAT_TO_LOCALE` has no key for and was dropped on every boot,
 * which meant the preference could not actually be overridden from the
 * account. Accepting both keeps the old pattern working and lets a saved
 * choice survive. An unknown value is skipped rather than forced in.
 *
 * The seeded pattern is refused unless this browser AGREES with it, in the
 * same spirit as `adoptServerDateFormat` refusing the seeded date order.
 * Without that, every account ever created read its numbers in German, because
 * the column defaulted to the German pattern for all of them and the
 * translator faithfully adopted it. `local` is what breaks the tie: the server
 * value alone cannot say whether German was chosen or seeded.
 *
 * The tie-break asks whether the local value agrees with the seeded pattern,
 * not merely whether one exists. That distinction is the whole correctness of
 * this function, and getting it wrong inverted it: the guard used to fire only
 * for `'auto'`, which read every other local value as proof that German had
 * been chosen when it was only proof that SOMETHING had been. Because the
 * column is NOT NULL and still holds the seed for every account nobody ever
 * PATCHed, the pattern arrives on every boot - so the old guard protected the
 * reader who never chose and silently overwrote every reader who did. A
 * browser holding `en-IN`, `en-US` or `fr-FR` was put back on German
 * separators on the next sign-in, with nothing on screen to say why.
 */
export function adoptServerNumberFormat(server: string, local: NumberLocale): NumberLocale | undefined {
  if (server === LEGACY_ACCOUNT_NUMBER_FORMAT && local !== SEEDED_ACCOUNT_LOCALE) return undefined;
  const mapped = NUMBER_FORMAT_TO_LOCALE[server];
  if (mapped) return mapped;
  return (NUMBER_LOCALES as readonly string[]).includes(server) ? (server as NumberLocale) : undefined;
}

interface PreferencesState extends Preferences {
  setPreference: <K extends keyof Preferences>(key: K, value: Preferences[K]) => void;
  setPreferences: (updates: Partial<Preferences>) => void;
  resetPreferences: () => void;
  /**
   * Load the account-level regional preferences from the server (issue #335)
   * and apply the ones this store understands, keeping localStorage as the
   * write-through offline cache. Safe to call once at boot; swallows any error
   * (offline / desktop without a reachable server) so the local cache stays
   * authoritative. A server value that does not match a known option is skipped
   * rather than forced in.
   */
  hydrateFromServer: () => Promise<void>;

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

  hydrateFromServer: async () => {
    try {
      const r = await apiGet<ServerPreferences>('/v1/users/me/preferences/');
      const updates: Partial<Preferences> = {};
      if (r.measurement_system && (MEASUREMENT_SYSTEMS as readonly string[]).includes(r.measurement_system)) {
        updates.measurementSystem = r.measurement_system as MeasurementSystem;
      }
      if (r.date_format) {
        const adopted = adoptServerDateFormat(r.date_format, get().dateFormat);
        if (adopted) updates.dateFormat = adopted;
      }
      const mappedLocale = r.number_format ? adoptServerNumberFormat(r.number_format, get().numberLocale) : undefined;
      if (mappedLocale) updates.numberLocale = mappedLocale;
      // An empty currency_code means "not chosen" on the account; only a real
      // ISO-4217 code overrides the local currency.
      if (r.currency_code && /^[A-Z]{3}$/.test(r.currency_code)) {
        updates.currency = r.currency_code;
        updates.defaultCurrency = r.currency_code;
      }
      if (Object.keys(updates).length === 0) return;
      // Write through to localStorage AND state, reusing the existing setter so
      // the persisted cache and the in-memory store stay in lockstep.
      get().setPreferences(updates);
    } catch {
      /* offline / desktop without a reachable server - keep the local cache */
    }
  },

  formatNumber: (value: number, decimals = 2) => {
    const { numberLocale } = get();
    try {
      return new Intl.NumberFormat(resolveNumberLocale(numberLocale), {
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals,
      }).format(value);
    } catch {
      return value.toFixed(decimals);
    }
  },
}));
