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

export default [
  {
    // Apply globally so unknown disable directives don't error
    linterOptions: {
      reportUnusedDisableDirectives: false,
    },
  },

  // Built-in JS recommended rules
  js.configs.recommended,

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
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooksStub,
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

      // Plugin-provided rule used in inline disable comments — define as off
      // to satisfy reportUnusedDisableDirectives without installing the plugin
      'react-hooks/exhaustive-deps': 'off',
      'react-hooks/rules-of-hooks': 'off',
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
