// AudioWorklet: roda na thread de áudio, mesmo com a janela minimizada.
import { ClapDetector } from "./clap-detector.js";

class ClapProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    // `sampleRate` é global no escopo do AudioWorklet.
    this.detector = new ClapDetector({ sampleRate, sensitivity: options?.processorOptions?.sensitivity ?? 0.5 });
    this.port.onmessage = (event) => {
      if (event.data?.type === "sensitivity") this.detector.setSensitivity(event.data.value);
    };
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel) {
      for (const event of this.detector.process(channel)) this.port.postMessage(event);
    }
    return true;
  }
}

registerProcessor("clap-detector", ClapProcessor);
