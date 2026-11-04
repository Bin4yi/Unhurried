// Mic capture at 24 kHz mono, 80 ms Int16 chunks.
// Keeps sending while on: silence is sent instead of mic audio when muted()
// returns true (the speech service closes the stream if audio stops for 10 s).
export const RATE = 24000;

export async function startMic(onChunk, muted = () => false) {
  const stream = await navigator.mediaDevices.getUserMedia({
    // A filmed take feeds a recording as the mic; browser processing would fill in its pauses.
    audio: new URLSearchParams(location.search).get("badge") === "recording"
      ? { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false }
      : { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const ctx = new AudioContext({ sampleRate: RATE });
  await ctx.audioWorklet.addModule(new URL("./capture-worklet.js", import.meta.url));
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "capture-processor");
  node.port.onmessage = (e) => {
    const chunk = muted() ? new ArrayBuffer(e.data.byteLength) : e.data;
    onChunk(chunk);
  };
  src.connect(node);
  return () => {
    node.port.onmessage = null;
    src.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    ctx.close();
  };
}

// Stream a 16-bit mono WAV (ArrayBuffer) at real time, in 80 ms chunks.
export async function streamWav(buf, onChunk, isStopped = () => false) {
  const view = new DataView(buf);
  let off = 12, dataOff = 44, dataLen = buf.byteLength - 44, rate = RATE;
  while (off < buf.byteLength - 8) {
    const id = String.fromCharCode(...new Uint8Array(buf, off, 4));
    const size = view.getUint32(off + 4, true);
    if (id === "fmt ") rate = view.getUint32(off + 12, true);
    if (id === "data") { dataOff = off + 8; dataLen = size; break; }
    off += 8 + size;
  }
  const step = Math.round(rate * 0.08) * 2;
  const start = performance.now();
  for (let i = 0, k = 0; i < dataLen && !isStopped(); i += step, k++) {
    onChunk(buf.slice(dataOff + i, dataOff + Math.min(i + step, dataLen)));
    const wait = start + (k + 1) * 80 - performance.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  }
  return rate;
}
