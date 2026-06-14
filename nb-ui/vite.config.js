import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  optimizeDeps: {
    exclude: ['@duckdb/duckdb-wasm']
  },
  server: {
    proxy: {
      '/stream': 'http://localhost:7777'
    }
  }
})
