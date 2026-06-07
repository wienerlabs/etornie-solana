import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // The React 19 hooks ESLint plugin (shipped with Next 16) treats
  // `set-state-in-effect` as an error. It fires on the very common
  // "load data in an effect" pattern used across the dashboard's pages
  // (an async loader called from useEffect that flips loading/error/data
  // state). That pattern is intentional and safe here, so keep it a
  // warning rather than letting it fail the build.
  {
    rules: {
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
