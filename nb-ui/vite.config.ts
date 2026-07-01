import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import path from "path";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    svelte({
      compilerOptions: { preserveWhitespace: true },
    }),
  ],
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
      "/notebooks": "http://localhost:7777",
      "/experiments": "http://localhost:7777",
      "/experiment": "http://localhost:7777",
      "/artifact": "http://localhost:7777",
    },
  },
});
