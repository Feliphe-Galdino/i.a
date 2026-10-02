// Testes do detector de palmas com sinais sintéticos (node --test).
import assert from "node:assert/strict";
import { test } from "node:test";
import { ClapDetector } from "../../src/sexta/web/js/voice/clap-detector.js";

const RATE = 48000;
const BLOCK = 128;

// Gerador pseudoaleatório determinístico (testes reproduzíveis)
function rng(seed = 42) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296 * 2 - 1;
  };
}

function silence(seconds, noise = 0.004, rand = rng()) {
  return Float32Array.from({ length: Math.round(seconds * RATE) }, () => rand() * noise);
}

function clap(amplitude = 0.8, rand = rng(7)) {
  // ruído impulsivo com decaimento exponencial (~25 ms) — parecido com uma palma real
  const n = Math.round(0.06 * RATE);
  return Float32Array.from({ length: n }, (_, i) => rand() * amplitude * Math.exp(-i / (0.008 * RATE)));
}

function tone(seconds, amplitude = 0.4, freq = 220) {
  // som sustentado (voz/música)
  return Float32Array.from({ length: Math.round(seconds * RATE) }, (_, i) => amplitude * Math.sin((2 * Math.PI * freq * i) / RATE));
}

function concat(...parts) {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const p of parts) { out.set(p, offset); offset += p.length; }
  return out;
}

function run(signal, options = {}) {
  const detector = new ClapDetector({ sampleRate: RATE, ...options });
  const events = [];
  for (let i = 0; i + BLOCK <= signal.length; i += BLOCK) events.push(...detector.process(signal.subarray(i, i + BLOCK)));
  return {
    claps: events.filter((e) => e.type === "clap").length,
    doubles: events.filter((e) => e.type === "double").length,
    levels: events.filter((e) => e.type === "level").length,
  };
}

test("duas palmas com 0,4 s de intervalo ativam", () => {
  const r = run(concat(silence(1), clap(), silence(0.34), clap(), silence(1)));
  assert.equal(r.claps, 2);
  assert.equal(r.doubles, 1);
});

test("uma palma só não ativa", () => {
  const r = run(concat(silence(1), clap(), silence(2)));
  assert.equal(r.claps, 1);
  assert.equal(r.doubles, 0);
});

test("palmas muito espaçadas não ativam", () => {
  const r = run(concat(silence(1), clap(), silence(1.5), clap(), silence(1)));
  assert.equal(r.doubles, 0);
});

test("três palmas seguidas ativam apenas uma vez", () => {
  const r = run(concat(silence(1), clap(), silence(0.3), clap(), silence(0.3), clap(), silence(1)));
  assert.equal(r.doubles, 1);
});

test("som contínuo (voz/música) não é palma", () => {
  const r = run(concat(silence(1), tone(0.6, 0.5), silence(0.3), tone(0.6, 0.5), silence(1)));
  assert.equal(r.claps, 0);
  assert.equal(r.doubles, 0);
});

test("palmas fracas dependem da sensibilidade", () => {
  const weak = concat(silence(1), clap(0.15), silence(0.35), clap(0.15), silence(1));
  assert.equal(run(weak, { sensitivity: 0.1 }).doubles, 0);
  assert.equal(run(weak, { sensitivity: 0.9 }).doubles, 1);
});

test("emite nível de áudio periodicamente para o medidor", () => {
  const r = run(silence(1));
  assert.ok(r.levels >= 9 && r.levels <= 11, `levels=${r.levels}`);
});

test("picos curtos no meio da fala (consoantes explosivas) não ativam", () => {
  const speech = tone(2, 0.2, 180);
  const rand = rng(3);
  for (let start = 0.2; start < 1.9; start += 0.3) {
    const i0 = Math.round(start * RATE);
    for (let i = 0; i < 0.015 * RATE; i++) speech[i0 + i] += rand() * 0.6 * Math.exp(-i / (0.004 * RATE));
  }
  const r = run(concat(silence(1), speech, silence(1)));
  assert.equal(r.doubles, 0);
});
