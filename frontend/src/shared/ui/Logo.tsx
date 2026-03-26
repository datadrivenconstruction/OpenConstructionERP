import clsx from 'clsx';

interface LogoProps {
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  animate?: boolean;
  className?: string;
}

const sizeMap = {
  xs: 'h-6 w-6',
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
        'relative',
        animate && 'animate-pulse-glow',
        className,
      )}
    >
      <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" className="w-full h-full">
        {/* Calculator body */}
        <rect
          x="1" y="5" width="22" height="25" rx="5"
          fill="#2563eb"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 400ms cubic-bezier(0.34,1.56,0.64,1) both' } : undefined}
        />

        {/* Screen */}
        <rect
          x="4.5" y="7.5" width="15.5" height="5.5" rx="2"
          fill="white" opacity="0.95"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 450ms cubic-bezier(0.34,1.56,0.64,1) both', animationDelay: '80ms' } : undefined}
        />
        <text x="18" y="11.8" textAnchor="end" fill="#2563eb" fontSize="4" fontWeight="700" fontFamily="system-ui">
          1.2M
        </text>

        {/* Button grid — 3x2 dots */}
        {[
          [7.5, 17], [12, 17], [16.5, 17],
          [7.5, 21], [12, 21], [16.5, 21],
        ].map(([cx, cy], i) => (
          <circle
            key={i}
            cx={cx} cy={cy} r="1.2"
            fill="white"
            opacity={0.3}
            className={animate ? 'origin-center' : ''}
            style={animate ? {
              animation: 'scaleIn 350ms cubic-bezier(0.34,1.56,0.64,1) both',
              animationDelay: `${150 + i * 40}ms`,
            } : undefined}
          />
        ))}

        {/* Gold equals bar */}
        <rect
          x="5" y="25" width="14.5" height="2" rx="1"
          fill="#f59e0b" opacity="0.9"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 350ms cubic-bezier(0.34,1.56,0.64,1) both', animationDelay: '420ms' } : undefined}
        />

        {/* Gold badge circle — fully visible, not clipped */}
        <circle
          cx="24.5" cy="7" r="6.5"
          fill="#f59e0b"
          className={animate ? 'origin-center' : ''}
          style={animate ? { animation: 'scaleIn 400ms cubic-bezier(0.34,1.56,0.64,1) both', animationDelay: '480ms' } : undefined}
        />

        {/* House — roof triangle */}
        <path
          d="M24.5 2.5 L29 6 L20 6 Z"
          fill="white" opacity="0.95"
        />
        {/* House — body */}
        <rect x="21.5" y="6" width="6" height="4.5" rx="0.6" fill="white" opacity="0.95"/>
        {/* House — door */}
        <rect x="23" y="7.5" width="3" height="3" rx="0.4" fill="#f59e0b" opacity="0.5"/>
      </svg>
    </div>
  );
}

interface LogoWithTextProps extends LogoProps {
  showVersion?: boolean;
}

const textSizeMap = {
  xs: 'text-sm',
  sm: 'text-[15px] leading-tight',
  md: 'text-base',
  lg: 'text-xl',
  xl: 'text-2xl',
};

const gapSizeMap = {
  xs: 'gap-2',
  sm: 'gap-2.5',
  md: 'gap-3',
  lg: 'gap-3',
  xl: 'gap-4',
};

export function LogoWithText({ size = 'md', animate, showVersion = true, className }: LogoWithTextProps) {
  return (
    <div className={clsx('flex items-center', gapSizeMap[size], className)}>
      <Logo size={size} animate={animate} />
      <span className={clsx(textSizeMap[size], 'font-bold text-content-primary tracking-tight whitespace-nowrap')}>
        Open<span className="text-oe-blue">Estimator</span>
        {showVersion && <span className="text-content-quaternary font-semibold">.io</span>}
      </span>
    </div>
  );
}
