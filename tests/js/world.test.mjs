// Testes das funções puras da tela Mundo e dos gráficos (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { niceTicks, stepDecimals } from "../../src/sexta/web/js/charts.js";
import { priceFormatter, safeUrl } from "../../src/sexta/web/js/views/world.js";

const clean = (s) => s.replace(/\s/g, " "); // Intl usa espaço não separável

test("preços: moeda, índice em pontos e valores grandes sem centavos", () => {
  assert.equal(clean(priceFormatter("moeda", "BRL")(5.4321)), "R$ 5,43");
  assert.equal(clean(priceFormatter("cripto", "BRL")(0.5)), "R$ 0,5000");
  assert.equal(clean(priceFormatter("indice", "BRL")(130512.4)), "130.512 pts");
  assert.equal(clean(priceFormatter("cripto", "BRL")(400245.77)), "R$ 400.246");
  assert.equal(clean(priceFormatter("cripto", "BRL", { compact: true })(400245.77)), "R$ 400,2 mil");
  assert.equal(priceFormatter("acao", "BRL")(null), "—");
  assert.equal(clean(priceFormatter("acao", "XYZ_INVALIDA")(10)), "10,00");
});

test("links de feeds: só http(s)", () => {
  assert.equal(safeUrl("https://g1.globo.com/a"), "https://g1.globo.com/a");
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("data:text/html,oi"), null);
  assert.equal(safeUrl("não é url"), null);
});

test("eixo Y com marcas redondas cobrindo os dados", () => {
  const { ticks, lo, hi, step } = niceTicks(149752, 173199, 4);
  assert.equal(step, 10000);
  assert.ok(lo <= 149752 && hi >= 173199);
  assert.deepEqual(ticks, [140000, 150000, 160000, 170000, 180000]);
  assert.equal(stepDecimals(0.05), 2);
  assert.equal(stepDecimals(10000), 0);
  const flat = niceTicks(5, 5);
  assert.ok(flat.lo < 5 && flat.hi > 5);
});
