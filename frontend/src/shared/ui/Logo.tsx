import clsx from 'clsx';

interface LogoProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  animate?: boolean;
  className?: string;
}

const sizeMap = {
  sm: 'h-8 w-8',
  md: 'h-10 w-10',
  lg: 'h-14 w-14',
  xl: 'h-20 w-20',
};

const barScale = {
  sm: { rx: '1', bars: [{ x: 7, y: 18, w: 5, h: 8 }, { x: 13.5, y: 13, w: 5, h: 13 }, { x: 20, y: 8, w: 5, h: 18 }] },
  md: { rx: '1.5', bars: [{ x: 7, y: 18, w: 5, h: 8 }, { x: 13.5, y: 13, w: 5, h: 13 }, { x: 20, y: 8, w: 5, h: 18 }] },
  lg: { rx: '1.5', bars: [{ x: 7, y: 18, w: 5, h: 8 }, { x: 13.5, y: 13, w: 5, h: 13 }, { x: 20, y: 8, w: 5, h: 18 }] },
  xl: { rx: '2', bars: [{ x: 7, y: 18, w: 5, h: 8 }, { x: 13.5, y: 13, w: 5, h: 13 }, { x: 20, y: 8, w: 5, h: 18 }] },
};

export function Logo({ size = 'md', animate = false, className }: LogoProps) {
  return (
    <div
      className={clsx(
        sizeMap[size],
        'relative rounded-xl overflow-hidden',
        animate && 'animate-pulse-glow',
        className,
      )}
    >
      <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-full h-full">
        <defs>
          <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#0071e3" />
            <stop offset="100%" stopColor="#5856d6" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="7" fill="url(#logoGrad)" />
        {barScale[size].bars.map((bar, i) => (
          <rect
            key={i}
            x={bar.x}
            y={bar.y}
            width={bar.w}
            height={bar.h}
            rx={barScale[size].rx}
            fill="white"
            opacity={i === 1 ? 1 : 0.85}
            className={animate ? 'origin-bottom' : ''}
            style={
              animate
                ? {
                    animation: `scaleIn 500ms cubic-bezier(0.34, 1.56, 0.64, 1) both`,
                    animationDelay: `${i * 120}ms`,
                  }
                : undefined
            }
          />
        ))}
      </svg>
    </div>
  );
}

interface LogoWithTextProps extends LogoProps {
  showVersion?: boolean;
}

export function LogoWithText({ size = 'md', animate, showVersion = true, className }: LogoWithTextProps) {
  return (
    <div className={clsx('flex items-center gap-3', className)}>
      <Logo size={size} animate={animate} />
      <div className="min-w-0">
        <span className="text-sm font-semibold text-content-primary tracking-tight">
          Open<span className="text-oe-blue">Estimator</span>
        </span>
        {showVersion && (
          <span className="ml-1.5 text-2xs text-content-tertiary">.io</span>
        )}
      </div>
    </div>
  );
}
