/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        oe: {
          blue: 'var(--oe-blue)',
          'blue-hover': 'var(--oe-blue-hover)',
          'blue-active': 'var(--oe-blue-active)',
          'blue-subtle': 'var(--oe-blue-subtle)',
        },
        surface: {
          primary: 'var(--oe-bg)',
          secondary: 'var(--oe-bg-secondary)',
          tertiary: 'var(--oe-bg-tertiary)',
          elevated: 'var(--oe-bg-elevated)',
        },
        border: {
          DEFAULT: 'var(--oe-border)',
          light: 'var(--oe-border-light)',
          focus: 'var(--oe-border-focus)',
        },
        content: {
          primary: 'var(--oe-text-primary)',
          secondary: 'var(--oe-text-secondary)',
          tertiary: 'var(--oe-text-tertiary)',
          inverse: 'var(--oe-text-inverse)',
        },
        semantic: {
          success: 'var(--oe-success)',
          'success-bg': 'var(--oe-success-bg)',
          warning: 'var(--oe-warning)',
          'warning-bg': 'var(--oe-warning-bg)',
          error: 'var(--oe-error)',
          'error-bg': 'var(--oe-error-bg)',
          info: 'var(--oe-info)',
          'info-bg': 'var(--oe-info-bg)',
        },
      },
      fontFamily: {
        sans: ['var(--oe-font-sans)'],
        mono: ['var(--oe-font-mono)'],
      },
      fontSize: {
        '2xs': ['11px', { lineHeight: '1.36' }],
        xs: ['12px', { lineHeight: '1.33' }],
        sm: ['14px', { lineHeight: '1.43' }],
        base: ['16px', { lineHeight: '1.47' }],
        lg: ['17px', { lineHeight: '1.29' }],
        xl: ['20px', { lineHeight: '1.2' }],
        '2xl': ['24px', { lineHeight: '1.17' }],
        '3xl': ['32px', { lineHeight: '1.125' }],
        '4xl': ['40px', { lineHeight: '1.1' }],
      },
      borderRadius: {
        xs: 'var(--oe-radius-xs)',
        sm: 'var(--oe-radius-sm)',
        md: 'var(--oe-radius-md)',
        lg: 'var(--oe-radius-lg)',
        xl: 'var(--oe-radius-xl)',
      },
      boxShadow: {
        xs: 'var(--oe-shadow-xs)',
        sm: 'var(--oe-shadow-sm)',
        md: 'var(--oe-shadow-md)',
        lg: 'var(--oe-shadow-lg)',
        xl: 'var(--oe-shadow-xl)',
      },
      transitionTimingFunction: {
        oe: 'cubic-bezier(0.25, 0.1, 0.25, 1)',
      },
      transitionDuration: {
        fast: '120ms',
        normal: '200ms',
        slow: '350ms',
      },
      spacing: {
        sidebar: 'var(--oe-sidebar-width)',
        header: 'var(--oe-header-height)',
      },
      maxWidth: {
        content: 'var(--oe-content-max-width)',
      },
      animation: {
        'fade-in': 'fadeIn 200ms cubic-bezier(0.25, 0.1, 0.25, 1)',
        'slide-up': 'slideUp 250ms cubic-bezier(0.25, 0.1, 0.25, 1)',
        'slide-down': 'slideDown 250ms cubic-bezier(0.25, 0.1, 0.25, 1)',
        'scale-in': 'scaleIn 200ms cubic-bezier(0.25, 0.1, 0.25, 1)',
        shimmer: 'shimmer 2s infinite linear',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          from: { opacity: '0', transform: 'translateY(-8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        scaleIn: {
          from: { opacity: '0', transform: 'scale(0.97)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
};
