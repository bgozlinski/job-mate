import js from '@eslint/js'
import { defineConfig } from 'eslint/config'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'
import tseslint from 'typescript-eslint'

// Type-aware linting, not just syntax. tsc already rejects what does not
// type-check; these rules catch what type-checks and is still wrong -- a
// promise nobody awaited, a condition that is always true because the value
// is an object rather than the boolean somebody meant.
//
// TypeScript rather than JavaScript so that this file is covered by
// tsconfig.node.json like any other source: a .js config belongs to no
// tsconfig, so the type-aware rules have no types for it and report the
// whole file as unresolvable. ESLint 10 loads a .ts config on its own.
//
// The generated API types are excluded: openapi-typescript writes them from
// openapi.json, and a lint fix there would be undone by the next generation.
export default defineConfig(
  { ignores: ['dist', 'src/api/schema.d.ts'] },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  tseslint.configs.stylisticTypeChecked,
  // configs.flat, not configs -- this plugin's top-level entries are still
  // the eslintrc shape, whose "plugins" is an array of names, and flat
  // config wants an object. Same rules, different packaging.
  reactHooks.configs.flat['recommended-latest'],
  {
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: ['**/*.test.ts', '**/*.test.tsx', 'src/test/**'],
    rules: {
      // A test asserts on what it just rendered; this rule fires on Testing
      // Library's own shapes rather than on anything the test controls.
      '@typescript-eslint/unbound-method': 'off',
    },
  },
)
