// ESLint v9 flat config for the OpenConstructionERP frontend.
//
// We intentionally keep this lightweight: type-checking is already
// covered by `tsc --noEmit` (and is enforced by `npm run typecheck`),
// and Prettier handles formatting. ESLint here only catches the small
// set of correctness issues that the TypeScript compiler can't see.
//
// Existing inline `// eslint-disable-next-line react-hooks/exhaustive-deps`
// comments throughout the codebase reference a plugin we don't ship —
// instead of installing the plugin (which would surface ~100 warnings),
// we tell ESLint to silently ignore disable directives for unknown rules.
//
// To run: `npm run lint`

import js from '@eslint/js';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import globals from 'globals';

// Stub plugin that satisfies inline `// eslint-disable-next-line
// react-hooks/exhaustive-deps` directives sprinkled throughout the
// codebase without requiring the real eslint-plugin-react-hooks
// dependency. The rules are no-ops — they always pass — so the
// disable directives work but don't add any new lint coverage.
const reactHooksStub = {
  rules: {
    'exhaustive-deps': { create: () => ({}) },
    'rules-of-hooks': { create: () => ({}) },
  },
};

// Stub plugin for the react plugin's `no-danger` rule. Some legacy
// components use `// eslint-disable-next-line react/no-danger` to
// document their intentional `dangerouslySetInnerHTML` usage. We
// don't ship eslint-plugin-react, so define a no-op rule here so
// those disable directives reference a known rule.
const reactStub = {
  rules: {
    'no-danger': { create: () => ({}) },
  },
};

export default [
  {
    // Apply globally so unknown disable directives don't error
    linterOptions: {
      reportUnusedDisableDirectives: false,
    },
  },

  // Built-in JS recommended rules
  js.configs.recommended,

  // Node-style audit/screenshot/build scripts at frontend root.
  // These are Puppeteer/Playwright drivers + utility scripts that run in
  // Node.js with both Node globals (process, __dirname, etc.) and DOM
  // globals available via page.evaluate() blocks. We declare both.
  {
    files: [
      '*.mjs',
      '*.cjs',
      '*.js',
      'e2e-match/**/*.{mjs,cjs,js}',
      'e2e/**/*.{mjs,cjs,js}',
      'scripts/**/*.{mjs,cjs,js}',
    ],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.node,
        ...globals.browser,
      },
    },
    rules: {
      // Audit/debug scripts often leave `e` or `_` parameters intentionally
      // unused for symmetry with Playwright API signatures. Allow the
      // underscore + single-letter exception markers.
      'no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_|^e$', varsIgnorePattern: '^_' },
      ],
      // Quick scripts sometimes use empty catch blocks for best-effort cleanup.
      'no-empty': ['error', { allowEmptyCatch: true }],
      // Regex spacing/escape style is intentional in shell-style scripts.
      'no-useless-escape': 'off',
      'no-regex-spaces': 'off',
    },
  },

  // TypeScript files
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooksStub,
      react: reactStub,
    },
    rules: {
      // TypeScript already enforces unused vars and undef via tsc --noEmit
      'no-unused-vars': 'off',
      'no-undef': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],

      // Allow `any` (we use it sparingly in error boundaries / dynamic data)
      '@typescript-eslint/no-explicit-any': 'off',

      // We use `// @ts-ignore` and `// @ts-expect-error` legitimately
      '@typescript-eslint/ban-ts-comment': 'off',

      // Allow empty catch blocks (silent failure is sometimes intentional)
      'no-empty': ['warn', { allowEmptyCatch: true }],

      // Regex literals are commonly written with redundant escapes for clarity
      'no-useless-escape': 'off',
      'no-regex-spaces': 'off',

      // Constant binary expressions show up in BIM/feature-flag guards
      // where one side is intentionally constant during a feature ramp.
      'no-constant-binary-expression': 'off',

      // Plugin-provided rule used in inline disable comments — define as off
      // to satisfy reportUnusedDisableDirectives without installing the plugin
      'react-hooks/exhaustive-deps': 'off',
      'react-hooks/rules-of-hooks': 'off',
      'react/no-danger': 'off',

      // Block zero-width and bidi-isolate Unicode characters that crash
      // React's reconciler when browser extensions (Google Translate,
      // ad blockers) mutate the DOM. See R6 / task #135.
      //
      // skipStrings/skipTemplates/skipComments: allow NBSP (U+00A0) and
      // other typographic whitespace inside strings, templates and
      // comments. German locale strings use NBSP between "z." and "B."
      // and engineering comments often use it for unit symbols (e.g.
      // "1.234,56 €"). NBSP does NOT trigger the React reconciler bug
      // (that's specific to U+200B-200F, U+2060-2064, U+2066-2069,
      // U+FEFF). The .github/workflows/ci.yml zero-width-guard job greps
      // for those specific codepoints across the full source tree
      // independently of ESLint, so coverage is preserved.
      'no-irregular-whitespace': [
        'error',
        {
          skipStrings: true,
          skipComments: true,
          skipRegExps: false,
          skipTemplates: true,
        },
      ],
    },
  },

  // Tests use vi/render globals from vitest — don't lint test files heavily
  {
    files: ['**/*.test.{ts,tsx}', '**/tests/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },

  // Ignore build output, dependencies, generated and config files
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'build/**',
      'coverage/**',
      'public/**',     // Static assets — not source code
      'e2e/**',        // Playwright specs use their own runner
      '*.config.js',
      '*.config.ts',
      '*.config.mjs',
      '**/*.d.ts',
      'src/app/i18n.ts', // Auto-generated translation file (huge)
    ],
  },
];
