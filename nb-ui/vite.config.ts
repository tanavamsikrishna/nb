// @ts-expect-error TS(2792): Cannot find module 'vite'. Did you mean to set the... Remove this comment to see the full error message
import { defineConfig } from "vite";
// @ts-expect-error TS(2792): Cannot find module '@sveltejs/vite-plugin-svelte'.... Remove this comment to see the full error message
import { svelte } from "@sveltejs/vite-plugin-svelte";
// @ts-expect-error TS(2792): Cannot find module 'path'. Did you mean to set the... Remove this comment to see the full error message
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  resolve: {
    alias: {
      $lib: path.resolve("./src/lib"),
    },
  },
  optimizeDeps: {
    exclude: ["@duckdb/duckdb-wasm"],
  },
  server: {
    proxy: {
      "/stream": "http://localhost:7777",
    },
  },
});
