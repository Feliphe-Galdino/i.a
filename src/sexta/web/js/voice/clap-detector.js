// Detector de palmas — processamento 100% local (o áudio não sai do computador).
//
// Uma palma é um som IMPULSIVO: sobe de repente, bem acima do ruído ambiente, e some em
// poucos milissegundos. Fala e música também têm picos, mas são sustentadas ou vêm no meio
// de outros sons — por isso exigimos (1) pico alto, (2) energia muito acima da média recente
// e (3) duração curta. Duas palmas com intervalo entre 0,12 s e 0,9 s = ativação.
//
// Usado dentro de um AudioWorklet (blocos de 128 amostras), mas é uma classe pura,
// testável no Node (tests/js/clap-detector.test.mjs).

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export class ClapDetector {
  constructor({ sampleRate = 48000, sensitivity = 0.5, levelEveryMs = 100 } = {}) {
    this.sampleRate = sampleRate;
    this.setSensitivity(sensitivity);
    this.t = 0;
    this.floor = 0.003;        // ruído de fundo (média lenta)
    this.recent = 0.003;       // energia recente (média curta)
    this.state = "idle";
    this.onsetT = 0;
    this.maxRms = 0;
    this.sustained = false;
    this.lastClapT = -Infinity;
    this.lockUntil = 0;
    this.refractoryUntil = 0;
    this.levelEvery = levelEveryMs / 1000;
    this.nextLevelT = 0;
    this.levelPeak = 0;
    this.levelRms = 0;
    this.minGap = 0.12;          // intervalo mínimo entre as duas palmas (s)
    this.maxGap = 0.9;           // intervalo máximo (s)
    this.maxClapDuration = 0.15; // uma palma decai antes disso (s)
  }

  /** 0 = pouco sensível (palmas fortes) · 1 = muito sensível (palmas leves). */
  setSensitivity(value) {
    const s = clamp(Number(value) || 0, 0, 1);
    this.sensitivity = s;
    this.peakThreshold = 0.45 - 0.37 * s; // 0,45 → 0,08
    this.ratio = 14 - 9 * s;               // energia 14× → 5× acima da referência
  }

  /** Processa um bloco de amostras e devolve eventos: level, clap, double. */
  process(samples) {
    const n = samples.length;
    if (!n) return [];
    let peak = 0;
    let sum = 0;
    for (let i = 0; i < n; i++) {
      const v = samples[i];
      const a = v < 0 ? -v : v;
      if (a > peak) peak = a;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / n);
    const t = this.t;
    this.t += n / this.sampleRate;
    const events = [];

    this.levelPeak = Math.max(this.levelPeak, peak);
    this.levelRms = Math.max(this.levelRms, rms);
    if (t >= this.nextLevelT) {
      events.push({ type: "level", peak: this.levelPeak, rms: this.levelRms, floor: this.floor, threshold: this.peakThreshold });
      this.levelPeak = 0;
      this.levelRms = 0;
      this.nextLevelT = t + this.levelEvery;
    }

    if (this.state === "idle") {
      const reference = Math.max(this.floor, this.recent);
      if (t >= this.refractoryUntil && peak >= this.peakThreshold && rms >= reference * this.ratio) {
        this.state = "event";
        this.onsetT = t;
        this.maxRms = rms;
        this.sustained = false;
      } else if (rms < this.floor * 3) {
        this.floor = Math.max(0.0015, this.floor * 0.98 + rms * 0.02);
      }
    } else {
      if (rms > this.maxRms) this.maxRms = rms;
      const duration = t - this.onsetT;
      if (rms < this.maxRms * 0.2 || rms < this.floor * 2) {
        this.state = "idle";
        this.refractoryUntil = t + 0.06;
        if (!this.sustained && duration <= this.maxClapDuration) events.push(...this.registerClap(this.onsetT));
      } else if (duration > this.maxClapDuration) {
        this.sustained = true; // som contínuo (voz, música): não é palma
      }
    }
    this.recent = this.recent * 0.97 + rms * 0.03;
    return events;
  }

  registerClap(at) {
    if (at < this.lockUntil) return [];
    const out = [{ type: "clap", t: at }];
    const gap = at - this.lastClapT;
    if (gap >= this.minGap && gap <= this.maxGap) {
      out.push({ type: "double", t: at });
      this.lastClapT = -Infinity;
      this.lockUntil = at + 1.2; // evita que uma 3ª palma dispare de novo
    } else {
      this.lastClapT = at;
    }
    return out;
  }
}
