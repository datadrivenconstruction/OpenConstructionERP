// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Layered dashboard backdrop. Rewritten 2026-05-11 to match styles-lab
// variant 03 "Dot Grid + Spotlight" — the design-system recommendation.
// Parametrized 2026-05-12 so other top-level pages can re-use the same
// structure with a different top-spotlight tint (BOQ uses amber, etc).

import { useEffect, useRef } from 'react';

interface Rgb {
  r: number;
  g: number;
  b: number;
}

export type BackdropVariant = 'dashboard' | 'estimation' | 'planning';

/**
 * Pick a backdrop variant from the current pathname. Mounted once in
 * AppLayout so per-page wrappers don't have to create their own stacking
 * context — and full-screen modals (z-50) keep covering the header
 * instead of being trapped beneath it.
 */
export function backdropVariantForPath(pathname: string): BackdropVariant {
  // Estimation/Kalkulation section + /files (user-requested grouping).
  // Pages: /boq, /match-elements, /costs, /assemblies, /catalog,
  // /bim/rules — and /files (Overview group but visually tied to
  // estimation per user direction on 2026-05-12).
  if (
    pathname === '/boq' ||
    pathname.startsWith('/boq/') ||
    pathname.startsWith('/match-elements') ||
    pathname.startsWith('/costs') ||
    pathname.startsWith('/assemblies') ||
    pathname.startsWith('/catalog') ||
    pathname.startsWith('/bim/rules') ||
    pathname === '/files' ||
    pathname.startsWith('/files/') ||
    /^\/projects\/[^/]+\/files/.test(pathname)
  ) {
    return 'estimation';
  }
  // Planning section
  if (
    pathname.startsWith('/schedule') ||
    pathname.startsWith('/tasks') ||
    pathname === '/5d' ||
    pathname.startsWith('/5d/') ||
    pathname.startsWith('/risks')
  ) {
    return 'planning';
  }
  // Everything else (dashboard, projects, …)
  return 'dashboard';
}


interface DashboardBackdropProps {
  /** Named preset. 'dashboard' = blue, 'estimation' = amber, 'planning' = red. */
  variant?: BackdropVariant;
  /** Override tint directly (takes precedence over `variant`). */
  tint?: Rgb;
  /** Alpha multiplier on the top spotlight (0..1). Lower = softer. */
  intensity?: number;
}

const APPLE_BLUE: Rgb = { r: 0, g: 113, b: 227 };
const ESTIMATION_AMBER: Rgb = { r: 217, g: 119, b: 6 };
const PLANNING_RED: Rgb = { r: 255, g: 59, b: 48 };

const VARIANT_PRESETS: Record<BackdropVariant, { tint: Rgb; intensity: number }> = {
  dashboard: { tint: APPLE_BLUE, intensity: 1 },
  estimation: { tint: ESTIMATION_AMBER, intensity: 0.7 },
  // 0.45 → top alpha ≈ 0.09 — softer than estimation so it doesn't feel
  // alarming. Apple system red, dialled way down.
  planning: { tint: PLANNING_RED, intensity: 0.45 },
};

export function DashboardBackdrop({
  variant = 'dashboard',
  tint,
  intensity,
}: DashboardBackdropProps = {}) {
  const preset = VARIANT_PRESETS[variant];
  const effTint = tint ?? preset.tint;
  const effIntensity = intensity ?? preset.intensity;
  // Pointer-tracked highlight — a soft accent halo follows the cursor.
  // Cheap: one CSS variable update on pointermove, no JS reflow.
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onMove = (e: PointerEvent) => {
      const rect = el.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      el.style.setProperty('--mx', `${x}%`);
      el.style.setProperty('--my', `${y}%`);
    };
    el.addEventListener('pointermove', onMove);
    return () => el.removeEventListener('pointermove', onMove);
  }, []);

  const rgb = `${effTint.r},${effTint.g},${effTint.b}`;
  const a1 = (0.2 * effIntensity).toFixed(3);
  const a2 = (0.06 * effIntensity).toFixed(3);
  const isDefaultTint =
    effTint.r === APPLE_BLUE.r && effTint.g === APPLE_BLUE.g && effTint.b === APPLE_BLUE.b;
  // The default tint follows the workspace accent (Settings > Style).
  const wash = (alpha: string) => (isDefaultTint ? `rgb(var(--oe-blue-ch) / ${alpha})` : `rgba(${rgb},${alpha})`);

  return (
    <div
      ref={ref}
      aria-hidden="true"
      className="dash-backdrop pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      style={{ '--mx': '50%', '--my': '40%' } as React.CSSProperties}
    >
      {/* Layer 1 — base surface wash. */}
      <div className="absolute inset-0 bg-surface-secondary" />

      {/* Layer 2 — top radial spotlight (tinted hero halo). */}
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(80% 55% at 50% -10%, ${wash(a1)} 0%, ${wash(a2)} 35%, ${wash('0')} 65%)`,
        }}
      />

      {/* Layer 3 — pointer-tracked highlight. Subtle, indigo. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(circle 380px at var(--mx) var(--my), rgba(99, 102, 241, 0.05), transparent 70%)',
          transition: 'background 0.2s ease',
        }}
      />

      {/* Layer 4 — subtle dot grid (rgba 16%, 0.9px, 24px step). */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'radial-gradient(circle, rgba(60,60,67,0.16) 0.9px, transparent 0.9px)',
          backgroundSize: '24px 24px',
          maskImage:
            'radial-gradient(ellipse 80% 75% at center, #000 25%, transparent 95%)',
          WebkitMaskImage:
            'radial-gradient(ellipse 80% 75% at center, #000 25%, transparent 95%)',
        }}
      />

      {/* Dark mode, keyed on the `dark` class of <html>. The halo override
          applies to the default tint only; custom tints keep their RGB and the
          intensity prop is the knob for brightness. */}
      <style>{`
        ${
          isDefaultTint
            ? `.dark .dash-backdrop > div:nth-child(2) {
            background: radial-gradient(80% 55% at 50% -10%, rgb(var(--oe-blue-ch) / 0.18) 0%, rgb(var(--oe-blue-ch) / 0.05) 35%, rgb(var(--oe-blue-ch) / 0) 65%);
          }`
            : ''
        }
        .dark .dash-backdrop > div:nth-child(4) {
          background-image: radial-gradient(circle, rgba(180,184,196,0.10) 0.9px, transparent 0.9px);
        }
      `}</style>
    </div>
  );
}
