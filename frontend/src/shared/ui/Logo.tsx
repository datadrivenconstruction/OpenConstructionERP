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
        {/* Background */}
        <rect width="32" height="32" rx="7" fill="url(#logoGrad)" />

        {/* Calculator body */}
        <rect
          x="7" y="5" width="18" height="22" rx="2.5"
          fill="white" opacity="0.95"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 400ms cubic-bezier(0.34,1.56,0.64,1) both' } : undefined}
        />

        {/* Screen */}
        <rect
          x="9" y="7" width="14" height="5" rx="1.2"
          fill="url(#logoGrad)" opacity="0.85"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 450ms cubic-bezier(0.34,1.56,0.64,1) both', animationDelay: '80ms' } : undefined}
        />

        {/* Number on screen */}
        <text x="20.5" y="11" textAnchor="end" fill="white" fontSize="4" fontWeight="700" fontFamily="system-ui">
          1.2M
        </text>

        {/* Button grid 4x3 */}
        {[
          [9, 14], [13.5, 14], [18, 14],
          [9, 17.5], [13.5, 17.5], [18, 17.5],
          [9, 21], [13.5, 21], [18, 21],
        ].map(([cx, cy], i) => (
          <rect
            key={i}
            x={cx} y={cy}
            width={3.5} height={2.5} rx="0.6"
            fill={i === 8 ? '#0071e3' : '#e8e8ed'}
            opacity={i === 8 ? 0.9 : 0.7}
            className={animate ? 'origin-center' : ''}
            style={animate ? {
              animation: 'scaleIn 350ms cubic-bezier(0.34,1.56,0.64,1) both',
              animationDelay: `${150 + i * 40}ms`,
            } : undefined}
          />
        ))}

        {/* Equals button (wider, bottom) */}
        <rect
          x="9" y="24" width="12.5" height="2.5" rx="0.6"
          fill="#0071e3" opacity="0.8"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 350ms cubic-bezier(0.34,1.56,0.64,1) both', animationDelay: '520ms' } : undefined}
        />
        <text x="15.25" y="26" textAnchor="middle" fill="white" fontSize="2" fontWeight="700" fontFamily="system-ui">
          =
        </text>
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
