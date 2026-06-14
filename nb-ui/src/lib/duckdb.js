/**
 * DuckDB-WASM initialization singleton.
 *
 * Provides a single, shared AsyncDuckDB instance for the browser session.
 * Call `getDb()` anywhere — it returns the same stable promise every time.
 *
 * Dependencies: @duckdb/duckdb-wasm
 * Exports: getDb()
 * Side-effects: Spawns a Web Worker on first call.
 * Constraints: Must be excluded from Vite pre-bundling (see vite.config.js).
 */
import * as duckdb from "@duckdb/duckdb-wasm";
import mvp_wasm from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import mvp_worker from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import eh_wasm from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import eh_worker from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";

const BUNDLES = {
  mvp: { mainModule: mvp_wasm, mainWorker: mvp_worker },
  eh: { mainModule: eh_wasm, mainWorker: eh_worker },
};

let _promise = null;

/**
 * Returns a promise that resolves to the shared AsyncDuckDB instance.
 * Safe and cheap to call multiple times.
 * @returns {Promise<duckdb.AsyncDuckDB>}
 */
export function getDb() {
  if (!_promise) _promise = _init();
  return _promise;
}

async function _init() {
  const bundle = await duckdb.selectBundle(BUNDLES);
  const worker = new Worker(bundle.mainWorker);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), worker);
  await db.instantiate(bundle.mainModule);
  return db;
}
