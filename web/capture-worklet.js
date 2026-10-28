// Collects mic samples and posts 80 ms blocks of 16-bit PCM to the main thread.
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = Math.round(sampleRate * 0.08);
    this.buf = new Int16Array(this.block);
    this.n = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === this.block) {
        this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
        this.buf = new Int16Array(this.block);
        this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("capture-processor", CaptureProcessor);
