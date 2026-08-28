import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import js from '@eslint/js';
import typescriptEslint from '@typescript-eslint/eslint-plugin';
import typescriptParser from '@typescript-eslint/parser';
import betterTailwindcss from 'eslint-plugin-better-tailwindcss';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import sonarjs from 'eslint-plugin-sonarjs';
import globals from 'globals';
import { defineConfig, globalIgnores } from 'eslint/config';

const configDirectory = dirname(fileURLToPath(import.meta.url));

const testGlobals = {
  afterAll: 'readonly',
  afterEach: 'readonly',
  beforeAll: 'readonly',
  beforeEach: 'readonly',
  describe: 'readonly',
  expect: 'readonly',
  it: 'readonly',
  test: 'readonly',
  vi: 'readonly',
};

export default defineConfig([
  /*
   * Generated files, dependency folders, and build output.
   */
  globalIgnores([
    '.vite-cache',
    'coverage',
    'dist',
    'lighthouse-reports',
    'node_modules',
  ]),

  /*
   * JavaScript configuration and tooling files.
   *
   * Examples:
   * - eslint.config.js
   * - tailwind.config.js
   */
  {
    files: ['**/*.{js,mjs,cjs}'],

    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',

      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },

    rules: {
      ...js.configs.recommended.rules,
    },
  },

  /*
   * Base TypeScript configuration.
   *
   * TypeScript Project Service provides type information for rules that need
   * to understand inferred and declared TypeScript types.
   */
  {
    files: ['**/*.{ts,tsx}'],

    languageOptions: {
      parser: typescriptParser,
      ecmaVersion: 'latest',
      sourceType: 'module',

      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
        /*
         * Source, test, and Playwright configuration files are resolved through
         * tsconfig.json.
         *
         * Root-level Vite and Vitest configuration files are not included in that
         * TypeScript project, so they use the default project.
         */
        projectService: {
          allowDefaultProject: ['vite.config.ts', 'vitest.config.ts'],
        },

        tsconfigRootDir: configDirectory,
      },

      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },

    plugins: {
      '@typescript-eslint': typescriptEslint,
      sonarjs,
    },

    rules: {
      ...js.configs.recommended.rules,
      ...typescriptEslint.configs.recommended.rules,
      ...sonarjs.configs.recommended.rules,

      /*
       * Require the configured @/ alias when an import traverses two or more
       * parent directories.
       *
       * Allowed:
       *   import value from '../value';
       *
       * Rejected:
       *   import value from '../../shared/value';
       */
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              regex: '^\\.\\./\\.\\./',
              message:
                'Use the @/ alias for imports that traverse two or more parent directories.',
            },
          ],
        },
      ],

      /*
       * Disable base rules that do not understand TypeScript syntax and types.
       * Their TypeScript-aware equivalents are enabled below.
       */
      'no-undef': 'off',
      'no-unused-vars': 'off',

      /*
       * Prevent explicit any values from bypassing type safety.
       */
      '@typescript-eslint/no-explicit-any': 'error',

      /*
       * Report unused variables while permitting intentionally unused names
       * prefixed with an underscore.
       */
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
        },
      ],

      /*
       * Detect union members already covered by a broader type.
       *
       * Example:
       *   'clear' | string
       *
       * The literal is redundant because string already includes it.
       */
      '@typescript-eslint/no-redundant-type-constituents': 'warn',

      /*
       * Keep functions understandable and discourage overly complicated
       * control flow.
       */
      'sonarjs/cognitive-complexity': ['warn', 15],

      /*
       * Detect expressions that repeat the same value on both sides.
       */
      'sonarjs/no-identical-expressions': 'warn',

      /*
       * Prefer readable control flow over nested ternary expressions.
       */
      'sonarjs/no-nested-conditional': 'warn',

      /*
       * Prevent mutation of React component props.
       */
      'sonarjs/prefer-read-only-props': 'warn',

      /*
       * Discourage selector parameters that make functions harder to follow
       * and test.
       */
      'sonarjs/no-selector-parameter': 'warn',

      /*
       * Prefer RegExp.exec() when retrieving regular-expression matches.
       */
      'sonarjs/prefer-regexp-exec': 'warn',

      /*
       * Prevent the void operator from silently discarding expression values.
       */
      'sonarjs/void-use': 'error',
    },
  },

  /*
   * React, React Hooks, accessibility, and Vite Fast Refresh.
   */
  {
    files: ['**/*.{ts,tsx}'],

    plugins: {
      react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'jsx-a11y': jsxA11y,
    },

    settings: {
      react: {
        version: 'detect',
      },
    },

    rules: {
      ...react.configs.flat.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      ...reactRefresh.configs.vite.rules,
      ...jsxA11y.flatConfigs.recommended.rules,

      /*
       * React 17+ uses the modern JSX transform and does not require React to
       * be imported into every TSX file.
       */
      'react/jsx-uses-react': 'off',
      'react/react-in-jsx-scope': 'off',

      /*
       * TypeScript interfaces and types provide component prop validation.
       */
      'react/prop-types': 'off',

      /*
       * Initial data-loading effects may invoke asynchronous functions whose
       * state updates happen after the first awaited response.
       */
      'react-hooks/set-state-in-effect': 'off',

      /*
       * Detect JSX where text may be rendered without the intended space.
       */
      'react/jsx-child-element-spacing': 'warn',

      /*
       * Prevent Context provider values from being reconstructed on every
       * render. Stable values should generally use useMemo or useCallback.
       */
      'react/jsx-no-constructed-context-values': 'warn',

      /*
       * Prefer destructuring useState into its value and setter.
       *
       * Example:
       *   const [value, setValue] = useState(initialValue);
       */
      'react/hook-use-state': 'warn',

      /*
       * Prefer native semantic elements when they accurately represent the
       * intended behavior.
       *
       * Examples:
       * - <button> instead of role="button"
       * - <progress> instead of role="progressbar"
       * - <output> instead of role="status"
       */
      'jsx-a11y/prefer-tag-over-role': 'warn',

      /*
       * Keep accessibility findings visible without blocking local builds.
       */
      'jsx-a11y/alt-text': 'warn',
      'jsx-a11y/aria-role': 'warn',
    },
  },

  /*
   * Tailwind CSS class validation.
   *
   * This configuration runs through ESLint, so it works from the terminal,
   * CI, and editors that support ESLint. It does not depend on VS Code or the
   * Tailwind CSS IntelliSense extension.
   */
  {
    files: ['src/**/*.{ts,tsx}'],

    plugins: {
      'better-tailwindcss': betterTailwindcss,
    },

    settings: {
      'better-tailwindcss': {
        /*
         * Tailwind CSS v4 entry point containing:
         *
         *   @import "tailwindcss";
         */
        entryPoint: 'src/index.css',

        /*
         * Used to resolve the @/ TypeScript path alias.
         */
        tsconfig: 'tsconfig.json',

        /*
         * Keep local and CI terminal messages concise.
         */
        messageStyle: 'compact',
      },
    },

    rules: {
      /*
       * Prefer Tailwind's canonical representation of equivalent classes.
       *
       * Example:
       *   text-[var(--text)]
       *
       * becomes:
       *   text-(--text)
       */
      'better-tailwindcss/enforce-canonical-classes': 'warn',
    },
  },

  /*
   * Vitest globals for test and specification files.
   */
  {
    files: ['tests/**/*.{ts,tsx}', '**/*.test.{ts,tsx}', '**/*.spec.{ts,tsx}'],

    languageOptions: {
      globals: testGlobals,
    },
  },
]);
