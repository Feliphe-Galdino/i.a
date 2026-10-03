// Mensagem clara quando o servidor está fora do ar (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { api, ApiError, OFFLINE_MESSAGE } from "../../src/sexta/web/js/api.js";

test("falha de rede vira mensagem em português com o que fazer", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  try {
    await assert.rejects(api("/api/status"), (err) => err instanceof ApiError && err.status === 0 && err.message === OFFLINE_MESSAGE);
    assert.match(OFFLINE_MESSAGE, /sexta open/);
  } finally {
    globalThis.fetch = original;
  }
});
