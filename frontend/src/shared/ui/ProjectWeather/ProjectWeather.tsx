/**
 * ProjectWeather — 16-day forecast card for a project's location.
 *
 * Uses Open-Meteo (https://open-meteo.com) — a free, keyless weather API
 * aligned with the project's "no vendor lock-in, no credentials required
 * to run the demo" stance.  We call /v1/forecast with daily aggregates
 * (min/max temp, precipitation sum, weather code) for 16 days and render
 * a compact horizontal strip.
 *
 * Caching: same `localStorage` strategy as the geocoder — 1-hour TTL on
 * weather so clicking around projects doesn't spam the API.  The hourly
 * TTL is intentional: daily aggregates don't shift significantly within
 * an hour and the average user session is shorter.
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

interface ProjectWeatherProps {
  lat: number | null | undefined;
  lng: number | null | undefined;
  /** Locale for day-of-week labels.  Falls back to browser default. */
  locale?: string;
  className?: string;
  /** Display variant.
   *  `full` — wide card with 16-day grid (detail page).
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
}

const CACHE_PREFIX = 'oe.weather.';
const CACHE_TTL_MS = 1000 * 60 * 60; // 1h

function cacheKey(lat: number, lng: number): string {
  // Round to 2 decimals — 1km precision is plenty for a building site and
  // dramatically increases cache hit rate across close projects.
  return `${CACHE_PREFIX}${lat.toFixed(2)}_${lng.toFixed(2)}`;
}

function readCache(lat: number, lng: number): DailyForecast[] | null {
  try {
    const raw = localStorage.getItem(cacheKey(lat, lng));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ForecastCache;
    if (Date.now() - parsed.at > CACHE_TTL_MS) return null;
    return parsed.days;
  } catch {
    return null;
  }
}

function writeCache(lat: number, lng: number, days: DailyForecast[]) {
  try {
    const entry: ForecastCache = { at: Date.now(), days };
    localStorage.setItem(cacheKey(lat, lng), JSON.stringify(entry));
  } catch {
    /* quota full, ignore */
  }
}

async function fetchForecast(
  lat: number,
  lng: number,
  signal?: AbortSignal,
): Promise<DailyForecast[] | null> {
  const cached = readCache(lat, lng);
  if (cached) return cached;

  const params = new URLSearchParams({
    latitude: lat.toString(),
    longitude: lng.toString(),
    daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum',
    timezone: 'auto',
    forecast_days: '16',
  });
  try {
    const res = await fetch(`https://api.open-meteo.com/v1/forecast?${params}`, {
      signal,
    });
    if (!res.ok) return null;
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
    if (!d || !d.time?.length) return null;
    const days: DailyForecast[] = d.time.map((date, i) => ({
      date,
      weatherCode: d.weather_code[i] ?? 0,
      tMin: d.temperature_2m_min[i] ?? 0,
      tMax: d.temperature_2m_max[i] ?? 0,
      precipMm: d.precipitation_sum[i] ?? 0,
    }));
    writeCache(lat, lng, days);
    return days;
  } catch {
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
  const [days, setDays] = useState<DailyForecast[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof lat !== 'number' || typeof lng !== 'number') {
      setDays(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    fetchForecast(lat, lng, controller.signal)
      .then((d) => {
        if (!controller.signal.aborted) setDays(d);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [lat, lng]);

  if (typeof lat !== 'number' || typeof lng !== 'number') return null;

  const resolvedLocale = locale || i18n.language || 'en';
  const dayFmt = new Intl.DateTimeFormat(resolvedLocale, { weekday: 'short' });
  const dateFmt = new Intl.DateTimeFormat(resolvedLocale, { day: 'numeric', month: 'short' });

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
    const month = days;   // up to 16 days — best we get from Open-Meteo free tier
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
            'Rough forecast for this location — next 7 days and ~16 days avg',
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
              {weekRain.toFixed(weekRain < 10 ? 1 : 0)}mm
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
            {t('weather.title_16d', { defaultValue: '16-day forecast' })}
          </h3>
        </div>
        {days?.[0] && (
          <div className="flex items-center gap-3 text-xs text-content-tertiary">
            <span className="flex items-center gap-1">
              <Thermometer size={11} />
              {Math.round(days[0].tMin)}° / {Math.round(days[0].tMax)}°C
            </span>
            <span className="flex items-center gap-1">
              <Droplets size={11} />
              {days[0].precipMm.toFixed(1)} mm
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
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
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
                    {d.precipMm.toFixed(d.precipMm < 1 ? 1 : 0)}mm
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
