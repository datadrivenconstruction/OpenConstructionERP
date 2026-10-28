// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ProjectWeather — 15-day forecast card for a project's location.
 *
 * Uses Open-Meteo (https://open-meteo.com) — a free, keyless weather API
 * aligned with the project's "no vendor lock-in, no credentials required
 * to run the demo" stance.  We call /v1/forecast with daily aggregates
 * (min/max temp, precipitation sum, weather code) for 15 days and render
 * them as a 5-wide / 3-row grid.
 *
 * Caching: same `localStorage` strategy as the geocoder — 1-hour TTL on
 * weather so clicking around projects doesn't spam the API.  The hourly
 * TTL is intentional: daily aggregates don't shift significantly within
 * an hour and the average user session is shorter.
 *
 * When the network refuses — HTTP 429 from the shared public endpoint, no
 * route out of the site, an answer we cannot read — the widget renders
 * nothing at all.  A forecast is decoration: an empty card headed
 * "15-day forecast" and footed "refreshed hourly" is worse than no card,
 * because it names data it does not have.  The refusal is cached under a
 * far shorter TTL than a forecast so a dashboard of sites stops asking a
 * host that just said no, instead of repeating the burst on every load.
 *
 * Note for anyone auditing outbound traffic: this call is made by the
 * browser, directly, and no operator switch stops it.  `OE_GEOCODER_DISABLED`
 * gates the address geocoder, which is server-side (see
 * `backend/app/modules/geo_hub/geocoder.py`); it is read from `os.environ`
 * and never reaches this component.  The daily-diary module already calls
 * the same Open-Meteo host from the server
 * (`backend/app/modules/daily_diary/weather.py`), which is where this one
 * belongs too — same move `UpdateChecker` made when it stopped calling
 * api.github.com from the browser.
 */
import { useEffect, useState } from 'react';
import {
  CloudSun,
  Cloud,
  CloudRain,
  CloudSnow,
  Sun,
  Loader2,
  Droplets,
  Thermometer,
  CloudFog,
  CloudLightning,
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { fmtFixed } from '@/shared/lib/formatters';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

interface ProjectWeatherProps {
  lat: number | null | undefined;
  lng: number | null | undefined;
  /** Locale for day-of-week labels.  Falls back to browser default. */
  locale?: string;
  className?: string;
  /** Display variant.
   *  `full` — wide card with 15-day grid (detail page).
   *  `summary` — one-line two-stat chip with week + month averages
   *              (fits in a project list card). */
  variant?: 'full' | 'summary';
}

interface DailyForecast {
  date: string;
  weatherCode: number;
  tMin: number;
  tMax: number;
  precipMm: number;
}

interface ForecastCache {
  at: number;
  days: DailyForecast[];
  /** The last attempt for these coordinates was refused.  Held under
   *  `FAILURE_TTL_MS`, not `CACHE_TTL_MS`: it describes the network right
   *  now, not the weather. */
  refused?: boolean;
}

const CACHE_PREFIX = 'oe.weather.';
const CACHE_TTL_MS = 1000 * 60 * 60; // 1h
const FAILURE_TTL_MS = 1000 * 60 * 10; // 10min

function cacheKey(lat: number, lng: number, imperial?: boolean): string {
  // Round to 2 decimals — 1km precision is plenty for a building site and
  // dramatically increases cache hit rate across close projects.
  const suffix = imperial ? '_f' : '';
  return `${CACHE_PREFIX}${lat.toFixed(2)}_${lng.toFixed(2)}${suffix}`;
}

/** The days on a hit, `'refused'` when the last attempt for these
 *  coordinates was recently turned down, `null` when we know nothing. */
function readCache(lat: number, lng: number, imperial?: boolean): DailyForecast[] | 'refused' | null {
  try {
    const raw = localStorage.getItem(cacheKey(lat, lng, imperial));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ForecastCache;
    const age = Date.now() - parsed.at;
    if (parsed.refused) return age > FAILURE_TTL_MS ? null : 'refused';
    if (age > CACHE_TTL_MS) return null;
    return parsed.days;
  } catch {
    return null;
  }
}

function writeCache(lat: number, lng: number, days: DailyForecast[], imperial?: boolean) {
  try {
    const entry: ForecastCache = { at: Date.now(), days };
    localStorage.setItem(cacheKey(lat, lng, imperial), JSON.stringify(entry));
  } catch {
    /* quota full, ignore */
  }
}

/** Remember that this location was refused, so the next render doesn't ask
 *  again inside the back-off window.  Only ever overwrites a cache entry we
 *  already decided was too stale to use. */
function writeRefusal(lat: number, lng: number, imperial?: boolean) {
  try {
    const entry: ForecastCache = { at: Date.now(), days: [], refused: true };
    localStorage.setItem(cacheKey(lat, lng, imperial), JSON.stringify(entry));
  } catch {
    /* quota full, ignore */
  }
}

async function fetchForecast(
  lat: number,
  lng: number,
  signal?: AbortSignal,
  useImperial?: boolean,
): Promise<DailyForecast[] | null> {
  const cached = readCache(lat, lng, useImperial);
  if (cached === 'refused') return null;
  if (cached) return cached;

  // Open-Meteo's free /v1/forecast endpoint hard-caps forecast_days at 16
  // (we tried 18 in v2.9.30 and got HTTP 400). 15 is the largest value that
  // tiles cleanly into the grid as 3 rows × 5 cols, which is the layout
  // Artem picked over a ragged 16-cell grid.
  const params = new URLSearchParams({
    latitude: lat.toString(),
    longitude: lng.toString(),
    daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum',
    timezone: 'auto',
    forecast_days: '15',
    ...(useImperial ? { temperature_unit: 'fahrenheit' } : {}),
  });
  try {
    const res = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`, {
      signal,
    });
    if (!res.ok) {
      // 429 is the one that actually happens: the public endpoint is shared
      // and a dashboard asks once per site on every load.
      writeRefusal(lat, lng, useImperial);
      return null;
    }
    const body = (await res.json()) as {
      daily?: {
        time: string[];
        weather_code: number[];
        temperature_2m_min: number[];
        temperature_2m_max: number[];
        precipitation_sum: number[];
      };
    };
    const d = body.daily;
    if (!d || !d.time?.length) {
      writeRefusal(lat, lng, useImperial);
      return null;
    }
    const days: DailyForecast[] = d.time.map((date, i) => ({
      date,
      weatherCode: d.weather_code[i] ?? 0,
      tMin: d.temperature_2m_min[i] ?? 0,
      tMax: d.temperature_2m_max[i] ?? 0,
      precipMm: d.precipitation_sum[i] ?? 0,
    }));
    writeCache(lat, lng, days, useImperial);
    return days;
  } catch {
    // An abort is a navigation, not a refusal - caching it would blank the
    // widget for a location nothing is actually wrong with.
    if (!signal?.aborted) writeRefusal(lat, lng, useImperial);
    return null;
  }
}

/**
 * WMO weather code → icon.  Reference: https://open-meteo.com/en/docs
 * (search "WMO Weather interpretation codes").  The full table is
 * long; we cluster the codes into buckets that map cleanly onto
 * lucide-react icons most people recognize.
 */
function iconFor(code: number): typeof Sun {
  if (code === 0) return Sun;
  if (code >= 1 && code <= 2) return CloudSun;
  if (code === 3) return Cloud;
  if (code >= 45 && code <= 48) return CloudFog;
  if (code >= 51 && code <= 67) return CloudRain;
  if (code >= 71 && code <= 77) return CloudSnow;
  if (code >= 80 && code <= 82) return CloudRain;
  if (code >= 85 && code <= 86) return CloudSnow;
  if (code >= 95 && code <= 99) return CloudLightning;
  return Cloud;
}

function labelFor(code: number, t: ReturnType<typeof useTranslation>['t']): string {
  if (code === 0) return t('weather.clear', { defaultValue: 'Clear' });
  if (code >= 1 && code <= 2) return t('weather.partly_cloudy', { defaultValue: 'Partly cloudy' });
  if (code === 3) return t('weather.overcast', { defaultValue: 'Overcast' });
  if (code >= 45 && code <= 48) return t('weather.fog', { defaultValue: 'Fog' });
  if (code >= 51 && code <= 67) return t('weather.rain', { defaultValue: 'Rain' });
  if (code >= 71 && code <= 77) return t('weather.snow', { defaultValue: 'Snow' });
  if (code >= 80 && code <= 82) return t('weather.showers', { defaultValue: 'Showers' });
  if (code >= 85 && code <= 86) return t('weather.snow_showers', { defaultValue: 'Snow showers' });
  if (code >= 95 && code <= 99) return t('weather.thunderstorm', { defaultValue: 'Thunderstorm' });
  return t('weather.cloudy', { defaultValue: 'Cloudy' });
}

type WeatherSeverity = 'good' | 'rain' | 'severe';

function classifySeverity(day: { weatherCode: number; precipMm: number }): WeatherSeverity {
  const { weatherCode: code, precipMm } = day;
  if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) return 'severe';
  if (code >= 95 && code <= 99) return 'severe';
  if (precipMm > 5) return 'severe';
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return 'rain';
  if (precipMm > 1) return 'rain';
  return 'good';
}

export function ProjectWeather({
  lat, lng, locale, className, variant = 'full',
}: ProjectWeatherProps) {
  const { t, i18n } = useTranslation();
  const measurementSystem = usePreferencesStore((s) => s.measurementSystem);
  const isImperial = measurementSystem === 'imperial';
  const tempUnit = isImperial ? '°F' : '°C';
  const [days, setDays] = useState<DailyForecast[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [refused, setRefused] = useState(false);

  useEffect(() => {
    if (typeof lat !== 'number' || typeof lng !== 'number') {
      setDays(null);
      setRefused(false);
      return;
    }
    const controller = new AbortController();
    // Clear as each location starts, not only when one answers: otherwise a
    // widget refused for one project stays blank through the whole loading
    // window of the next, which reads as a widget that has given up.
    setRefused(false);
    setLoading(true);
    fetchForecast(lat, lng, controller.signal, isImperial)
      .then((d) => {
        // An aborted effect has been superseded; its answer says nothing
        // about the location now on screen.
        if (controller.signal.aborted) return;
        setDays(d);
        setRefused(d === null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [lat, lng, isImperial]);

  if (typeof lat !== 'number' || typeof lng !== 'number') return null;
  // Decoration that the network turned down renders as nothing, in either
  // variant. No error copy, no empty card - the page reads as if the widget
  // had never been asked for.
  if (refused) return null;

  const resolvedLocale = locale || i18n.language || 'en';
  // Weather dates are date-only (YYYY-MM-DD) and parse as UTC midnight, so
  // display them in UTC to prevent the weekday/label shifting by one day at
  // negative UTC offsets.
  const dayFmt = new Intl.DateTimeFormat(resolvedLocale, { weekday: 'short', timeZone: 'UTC' });
  const dateFmt = new Intl.DateTimeFormat(resolvedLocale, { day: 'numeric', month: 'short', timeZone: 'UTC' });

  /* ── Summary variant — one-line chip for project cards ─────────── */
  if (variant === 'summary') {
    if (!days) {
      return loading ? (
        <div className={clsx('flex items-center gap-1.5 text-[10px] text-content-quaternary', className)}>
          <Loader2 size={10} className="animate-spin" />
        </div>
      ) : null;
    }
    const week = days.slice(0, 7);
    const month = days;   // 15 days — practical horizon from Open-Meteo free tier
    const avg = (arr: DailyForecast[], pick: (d: DailyForecast) => number) =>
      arr.length > 0 ? arr.reduce((s, d) => s + pick(d), 0) / arr.length : 0;
    const weekMax = avg(week, (d) => d.tMax);
    const weekMin = avg(week, (d) => d.tMin);
    const weekRain = week.reduce((s, d) => s + d.precipMm, 0);
    const monthMax = avg(month, (d) => d.tMax);
    const monthMin = avg(month, (d) => d.tMin);
    // Pick the most frequent weather bucket to colour the lead icon
    const WeekIcon = iconFor(week[0]?.weatherCode ?? 0);
    return (
      <div
        className={clsx(
          'flex items-center gap-2 text-[10px] text-content-tertiary',
          className,
        )}
        title={t('weather.card_summary_hint', {
          defaultValue:
            'Rough forecast for this location - next 7 days and ~15 days avg',
        })}
      >
        <WeekIcon size={12} className="text-oe-blue shrink-0" />
        <span className="flex items-center gap-0.5">
          <span className="font-semibold text-content-primary">7d</span>
          <span className="tabular-nums">
            {Math.round(weekMin)}°/{Math.round(weekMax)}°
          </span>
          {weekRain > 0.5 && (
            <span className="flex items-center gap-0.5 text-blue-500">
              <Droplets size={9} />
              {fmtFixed(weekRain, weekRain < 10 ? 1 : 0)}mm
            </span>
          )}
        </span>
        <span className="text-content-quaternary">·</span>
        <span className="flex items-center gap-0.5">
          <span className="font-semibold text-content-primary">~1mo</span>
          <span className="tabular-nums">
            {Math.round(monthMin)}°/{Math.round(monthMax)}°
          </span>
        </span>
      </div>
    );
  }

  return (
    <div className={clsx('rounded-xl border border-border-light bg-surface-elevated p-4', className)}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CloudSun size={16} className="text-oe-blue" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('weather.title_18d', { defaultValue: '15-day forecast' })}
          </h3>
        </div>
        {days?.[0] && (
          <div className="flex items-center gap-3 text-xs text-content-tertiary">
            <span className="flex items-center gap-1">
              <Thermometer size={11} />
              {Math.round(days[0].tMin)}° / {Math.round(days[0].tMax)}{tempUnit}
            </span>
            <span className="flex items-center gap-1">
              <Droplets size={11} />
              {fmtFixed(days[0].precipMm, 1)} mm
            </span>
          </div>
        )}
      </div>

      {loading && !days && (
        <div className="flex items-center justify-center py-6 text-content-tertiary">
          <Loader2 size={14} className="animate-spin" />
          <span className="ml-2 text-xs">{t('common.loading', { defaultValue: 'Loading…' })}</span>
        </div>
      )}

      {days && (
        // 15-day layout — 5 columns at every breakpoint so the grid always
        // forms three tidy rows. Earlier 4/6-col responsive set produced
        // a stray cell on the last row (4 + 4 + 4 + 4 = 16 with a hole, or
        // 6 + 6 + 4) which Artem flagged as visually messy. Five-wide is
        // tight on phones but the cells are simple enough (icon + 2 nums)
        // to remain legible.
        <div className="grid grid-cols-5 gap-2">
          {days.map((d, i) => {
            const Icon = iconFor(d.weatherCode);
            const date = new Date(d.date);
            const tempRange = d.tMax - d.tMin;
            const severity = classifySeverity(d);
            return (
              <div
                key={d.date}
                className={clsx(
                  'flex flex-col items-center gap-1 rounded-lg px-1.5 py-2 border transition-colors',
                  i === 0 && 'ring-2 ring-oe-blue/30 ring-offset-1 ring-offset-surface-primary',
                  severity === 'severe'
                    ? 'border-rose-300/70 bg-rose-50/70 hover:border-rose-400 dark:border-rose-700/60 dark:bg-rose-900/20'
                    : severity === 'rain'
                      ? 'border-amber-300/70 bg-amber-50/70 hover:border-amber-400 dark:border-amber-700/60 dark:bg-amber-900/20'
                      : 'border-border-light/50 hover:border-border-light',
                )}
                title={`${labelFor(d.weatherCode, t)} · ${dateFmt.format(date)}`}
              >
                <span className="text-[10px] font-semibold text-content-tertiary uppercase tracking-wide">
                  {dayFmt.format(date)}
                </span>
                <Icon
                  size={18}
                  className={clsx(
                    d.weatherCode === 0
                      ? 'text-amber-500'
                      : d.weatherCode >= 51 && d.weatherCode <= 67
                        ? 'text-blue-500'
                        : d.weatherCode >= 71 && d.weatherCode <= 77
                          ? 'text-sky-400'
                          : d.weatherCode >= 95
                            ? 'text-violet-500'
                            : 'text-slate-500',
                  )}
                />
                <div className="flex flex-col items-center leading-tight">
                  <span className="text-[11px] font-bold text-content-primary tabular-nums">
                    {Math.round(d.tMax)}°
                  </span>
                  <span className="text-[10px] text-content-quaternary tabular-nums">
                    {Math.round(d.tMin)}°
                  </span>
                </div>
                {d.precipMm > 0.1 && (
                  <span className="text-[9px] text-blue-500 tabular-nums">
                    {fmtFixed(d.precipMm, d.precipMm < 1 ? 1 : 0)}mm
                  </span>
                )}
                {tempRange < 0 && <span aria-hidden />}
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-3 text-[10px] text-content-quaternary">
        {t('weather.attribution', { defaultValue: 'Weather data by Open-Meteo · refreshed hourly' })}
      </p>
    </div>
  );
}
