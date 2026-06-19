/**
 * DuckDB-WASM singleton: one shared AsyncDuckDB instance per browser session.
 * `getDb()` returns the same stable promise every call (and spawns the worker
 * on first call). Must be excluded from Vite pre-bundling (see vite.config.js).
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
