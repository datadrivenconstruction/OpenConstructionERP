/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        oe: {
          blue: 'var(--oe-blue)',
          'blue-hover': 'var(--oe-blue-hover)',
          'blue-active': 'var(--oe-blue-active)',
          'blue-dark': 'var(--oe-blue-dark)',
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
          quaternary: 'var(--oe-text-quaternary)',
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
        '2xs': ['10px', { lineHeight: '1.4' }],
        xs: ['11px', { lineHeight: '1.36' }],
        sm: ['13px', { lineHeight: '1.46' }],
        base: ['15px', { lineHeight: '1.47' }],
        lg: ['16px', { lineHeight: '1.31' }],
        xl: ['19px', { lineHeight: '1.21' }],
        '2xl': ['22px', { lineHeight: '1.18' }],
        '3xl': ['30px', { lineHeight: '1.13' }],
        '4xl': ['37px', { lineHeight: '1.1' }],
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

        /* Auth page — floating gradient blobs */
        float: 'float 20s ease-in-out infinite alternate',
        'float-delayed': 'floatDelayed 24s ease-in-out infinite alternate',
        'float-slow': 'floatSlow 28s ease-in-out infinite alternate',

        /* Auth page — logo entrance glow */
        'logo-glow': 'logoGlow 2s cubic-bezier(0.22, 1, 0.36, 1) forwards',

        /* Auth page — staggered form fields */
        'stagger-in': 'staggerIn 500ms cubic-bezier(0.22, 1, 0.36, 1) both',

        /* Auth page — button hover shimmer */
        'btn-shimmer': 'btnShimmer 2.5s ease-in-out infinite',

        /* Auth page — form card entrance */
        'form-scale-in': 'formScaleIn 600ms cubic-bezier(0.22, 1, 0.36, 1) both',

        /* Dashboard — stat counter entrance */
        'count-up': 'countUp 600ms cubic-bezier(0.22, 1, 0.36, 1) both',

        /* Dashboard — gradient heading text */
        'gradient-text': 'gradientText 6s ease-in-out infinite',

        /* Dashboard — live pulse dot */
        'pulse-live': 'pulseLive 2s ease-in-out infinite',

        /* Dashboard — card entrance */
        'card-in': 'cardIn 500ms cubic-bezier(0.22, 1, 0.36, 1) both',

        /* Global — pulse glow for active/focus states */
        'pulse-glow': 'pulseGlow 2s ease infinite',

        /* Global — gradient background shift */
        gradient: 'gradientShift 6s ease infinite',

        /* Toast — slide in from right */
        'toast-in': 'toastIn 300ms cubic-bezier(0.22, 1, 0.36, 1) both',

        /* Drawer — slide in from right */
        'slide-in-right': 'slideInRight 250ms cubic-bezier(0.22, 1, 0.36, 1) both',

        /* Quantities — pulsing border for uninstalled converters */
        'pulse-border': 'pulseBorder 2s ease-in-out infinite',
      },
      keyframes: {
        slideInRight: {
          from: { opacity: '0', transform: 'translateX(100%)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
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

        /* Blob floating — organic, asymmetric paths */
        float: {
          '0%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(30px, -40px) scale(1.05)' },
          '66%': { transform: 'translate(-20px, 20px) scale(0.95)' },
          '100%': { transform: 'translate(15px, -25px) scale(1.02)' },
        },
        floatDelayed: {
          '0%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(-40px, 30px) scale(1.08)' },
          '66%': { transform: 'translate(25px, -35px) scale(0.96)' },
          '100%': { transform: 'translate(-15px, 20px) scale(1.04)' },
        },
        floatSlow: {
          '0%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(20px, 30px) scale(1.06)' },
          '66%': { transform: 'translate(-30px, -20px) scale(0.97)' },
          '100%': { transform: 'translate(10px, -15px) scale(1.03)' },
        },

        /* Logo entrance — scale + glow ring */
        logoGlow: {
          '0%': {
            boxShadow: '0 0 0 0 rgba(0, 113, 227, 0)',
            transform: 'scale(0.85)',
            opacity: '0',
          },
          '50%': {
            boxShadow: '0 0 28px 8px rgba(0, 113, 227, 0.3)',
            transform: 'scale(1.05)',
            opacity: '1',
          },
          '100%': {
            boxShadow: '0 8px 32px rgba(0, 113, 227, 0.15)',
            transform: 'scale(1)',
            opacity: '1',
          },
        },

        /* Form fields stagger */
        staggerIn: {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },

        /* Button shimmer sweep */
        btnShimmer: {
          '0%': { backgroundPosition: '-200% center' },
          '100%': { backgroundPosition: '200% center' },
        },

        /* Form card entrance — subtle scale + lift */
        formScaleIn: {
          from: { opacity: '0', transform: 'scale(0.96) translateY(10px)' },
          to: { opacity: '1', transform: 'scale(1) translateY(0)' },
        },

        /* Dashboard counter entrance */
        countUp: {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },

        /* Gradient text shimmer */
        gradientText: {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },

        /* Live status dot pulse */
        pulseLive: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.4', transform: 'scale(0.75)' },
        },

        /* Dashboard card entrance */
        cardIn: {
          from: { opacity: '0', transform: 'translateY(16px) scale(0.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },

        /* Global — pulse glow ring */
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(0, 113, 227, 0.2)' },
          '50%': { boxShadow: '0 0 0 8px rgba(0, 113, 227, 0)' },
        },

        /* Global — gradient background shift */
        gradientShift: {
          '0%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },

        /* Toast — slide in from right */
        toastIn: {
          from: { opacity: '0', transform: 'translateX(100%)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },

        /* Quantities — pulsing border ring for uninstalled converters */
        pulseBorder: {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(0, 113, 227, 0.15)' },
          '50%': { boxShadow: '0 0 0 4px rgba(0, 113, 227, 0.08)' },
        },
      },
    },
  },
  plugins: [],
};
