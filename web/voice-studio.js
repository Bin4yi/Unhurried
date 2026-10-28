// Voice Studio: record, review cuts, real-voice output, optional AI voice.
import { RATE, startMic } from "./mic.js";

const $ = (id) => document.getElementById(id);
let job = null, stopMic = null, chunks = [], recording = false, origBuf = null;

// ---------------------------------------------------------------- audio helpers
function wavBytes(int16) {
  const buf = new ArrayBuffer(44 + int16.length * 2), v = new DataView(buf);
  const str = (o, s) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF"); v.setUint32(4, 36 + int16.length * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, int16.length * 2, true);
  new Int16Array(buf, 44).set(int16);
  return new Blob([buf], { type: "audio/wav" });
}

function joinChunks(list) {
  const out = new Int16Array(list.reduce((n, c) => n + c.length, 0));
  let o = 0;
  for (const c of list) { out.set(c, o); o += c.length; }
  return out;
}

function css(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

function drawWave(canvas, samples, cuts = [], playhead = null) {
  const g = canvas.getContext("2d"), W = canvas.width, H = canvas.height;
  g.clearRect(0, 0, W, H);
  if (!samples || !samples.length) return;
  const dur = samples.length / RATE;
  for (const c of cuts) {
    const x0 = (c.start / dur) * W, x1 = (c.end / dur) * W;
    g.fillStyle = c.on ? css("--clay-soft") : "transparent";
    g.fillRect(x0, 0, x1 - x0, H);
    if (!c.on) { g.strokeStyle = css("--line"); g.strokeRect(x0, 1, x1 - x0, H - 2); }
  }
  const step = Math.max(1, Math.floor(samples.length / W));
  for (let x = 0; x < W; x++) {
    let peak = 0;
    for (let i = x * step; i < (x + 1) * step && i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i]));
    const t = (x / W) * dur;
    const inCut = cuts.some((c) => c.on && t >= c.start && t <= c.end);
    g.fillStyle = inCut ? css("--clay") : css("--ink-2");
    const h = Math.max(1, (peak / 32768) * H * 0.92);
    g.fillRect(x, (H - h) / 2, 1, h);
  }
  if (playhead != null) { g.fillStyle = css("--sage"); g.fillRect((playhead / dur) * W, 0, 2, H); }
}

// ---------------------------------------------------------------- step 1
async function toggleRecord() {
  if (recording) {
    recording = false;
    stopMic(); stopMic = null;
    $("rec").classList.remove("on");
    $("rec").setAttribute("aria-label", "Start recording");
    const pcm = joinChunks(chunks);
    if (pcm.length < RATE * 0.5) { $("rec-hint").textContent = "That was very short. Try again."; return; }
    origBuf = pcm;
    await process(wavBytes(pcm), "mic");
    return;
  }
  chunks = [];
  $("err").textContent = "";
  stopMic = await startMic((c) => {
    chunks.push(new Int16Array(c));
    if (chunks.length % 3 === 0) drawWave($("live-wave"), joinChunks(chunks.slice(-150)));
    if (chunks.length * 0.08 > 180) toggleRecord();
  });
  recording = true;
  $("rec").classList.add("on");
  $("rec").setAttribute("aria-label", "Stop recording");
  $("rec-hint").textContent = "Recording. Press again when you are done.";
}

async function process(blob, source) {
  const steps = [...$("progress").children];
  $("progress").hidden = false;
  steps.forEach((s) => (s.className = ""));
  let k = 0;
  const advance = () => { if (k > 0) steps[k - 1].className = "done"; if (k < steps.length) steps[k++].className = "on"; };
  advance();
  const timer = setInterval(() => { if (k < steps.length) advance(); }, 1800);
  const fd = new FormData();
  fd.append("audio", blob, "recording.wav");
  fd.append("source", source);
  fd.append("spark", $("use-spark").checked ? "true" : "false");
  try {
    const r = await fetch("/studio/process", { method: "POST", body: fd });
    const out = await r.json();
    if (!r.ok) throw new Error(out.detail || "could not process");
    job = out;
    steps.forEach((s) => (s.className = "done"));
    if (source !== "mic") origBuf = await decodeOriginal();
    showReview();
  } catch (e) {
    $("err").textContent = `Something went wrong: ${e.message}`;
  } finally {
    clearInterval(timer);
  }
}

async function decodeOriginal() {
  const buf = await (await fetch(`/studio/${job.id}/audio/original.wav`)).arrayBuffer();
  const v = new DataView(buf);
  for (let off = 12; off < buf.byteLength - 8;) {   // find the "data" chunk
    const id = String.fromCharCode(v.getUint8(off), v.getUint8(off + 1), v.getUint8(off + 2), v.getUint8(off + 3));
    const size = v.getUint32(off + 4, true);
    if (id === "data") return new Int16Array(buf.slice(off + 8, off + 8 + size - (size % 2)));
    off += 8 + size + (size % 2);
  }
  return new Int16Array(0);
}

// ---------------------------------------------------------------- step 2
const KIND = { sound: "sound", repeat: "repeat", filler: "filler", correction: "correction", block: "pause" };

function showReview() {
  $("review").hidden = $("outputs").hidden = $("danger").hidden = false;
  $("a-orig").src = `/studio/${job.id}/audio/original.wav`;
  $("clone-off").hidden = job.clone_available;
  $("clone-on").hidden = !job.clone_available;
  if (job.source !== "mic") $("get-sentence").disabled = true, $("get-sentence").title = "Record live in the Studio to use AI voice.";
  renderReview();
  $("review").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderReview() {
  const n = job.edits.filter((e) => e.on).length;
  const saved = job.edits.filter((e) => e.on).reduce((s, e) => s + (e.end - e.start), 0);
  $("summary").textContent = `${n} cuts · ${saved.toFixed(1)} s shorter`;
  drawWave($("wave"), origBuf, job.edits);

  const owner = {};
  for (const e of job.edits) if (e.words && !e.partial) for (let i = e.words[0]; i <= e.words[1]; i++) owner[i] = e;
  const blocksAfter = {};
  for (const e of job.edits) if (e.kind === "block") {
    const i = job.words.findIndex((w) => w.end >= e.start - 0.2);
    if (i >= 0) blocksAfter[i] = e;
  }
  const box = $("words");
  box.innerHTML = "";
  job.words.forEach((w, i) => {
    const sp = document.createElement("span");
    sp.textContent = w.text;
    const e = owner[i] || job.edits.find((x) => x.partial && x.words && x.words[0] === i);
    if (e) { sp.className = e.on ? "cut" : "kept"; sp.title = `${KIND[e.kind]}: tap to ${e.on ? "keep" : "cut"}`; sp.onclick = () => toggle(e); }
    box.append(sp, " ");
    if (blocksAfter[i]) {
      const b = blocksAfter[i], g = document.createElement("span");
      g.className = `gap ${b.on ? "" : "kept"}`;
      g.textContent = b.on ? `${b.text} → 0.3 s` : b.text;
      g.onclick = () => toggle(b);
      box.append(g, " ");
    }
  });

  const list = $("edits");
  list.innerHTML = "";
  for (const e of job.edits) {
    const li = document.createElement("li");
    li.className = e.on ? "" : "off";
    li.innerHTML = '<span class="kind"></span><span class="txt"></span><input type="checkbox" class="switch">';
    li.children[0].textContent = KIND[e.kind];
    li.children[0].classList.add(e.kind);
    li.children[1].textContent = `${e.text}  ·  ${e.start.toFixed(1)} s`;
    li.children[2].checked = e.on;
    li.children[2].setAttribute("aria-label", `Cut ${e.text}`);
    li.children[2].onchange = () => toggle(e);
    list.appendChild(li);
  }
  $("clean-text").textContent = job.clean_text;
}

async function toggle(e) {
  const r = await fetch(`/studio/${job.id}/edits`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: { [e.id]: !e.on } }),
  });
  job = { ...job, ...(await r.json()) };
  $("dl-clean").hidden = true;
  $("render-note").textContent = "Cuts changed. Make the clean version again.";
  renderReview();
}

$("wave").onclick = (ev) => {
  const r = ev.target.getBoundingClientRect();
  const t = ((ev.clientX - r.left) / r.width) * job.duration;
  $("a-orig").currentTime = t;
  $("a-orig").play();
};
$("a-orig").ontimeupdate = () => drawWave($("wave"), origBuf, job.edits, $("a-orig").currentTime);

// ---------------------------------------------------------------- step 3 and 4
$("render").onclick = async () => {
  $("render").disabled = true;
  $("render-note").textContent = "Cutting and joining…";
  const out = await (await fetch(`/studio/${job.id}/render`, { method: "POST" })).json();
  const url = `${out.url}?v=${Date.now()}`;
  $("a-clean").src = url;
  $("dl-clean").href = url;
  $("dl-clean").hidden = false;
  $("render-note").textContent = "Every sound in this file is from your recording.";
  $("render").disabled = false;
  $("a-clean").play();
};

$("get-sentence").onclick = async () => {
  const s = await (await fetch("/studio/verify/sentence")).json();
  $("sentence").textContent = s.sentence;
  $("verify-box").hidden = false;
};

let vStop = null, vChunks = [];
$("verify-rec").onclick = async () => {
  if (!vStop) {
    vChunks = [];
    vStop = await startMic((c) => vChunks.push(new Int16Array(c)));
    $("verify-rec").textContent = "Stop";
    $("verify-msg").textContent = "Reading…";
    return;
  }
  vStop(); vStop = null;
  $("verify-rec").textContent = "Record sentence";
  $("verify-msg").textContent = "Checking…";
  const fd = new FormData();
  fd.append("audio", wavBytes(joinChunks(vChunks)), "verify.wav");
  fd.append("sentence", $("sentence").textContent);
  const r = await fetch(`/studio/${job.id}/verify`, { method: "POST", body: fd });
  const out = await r.json();
  if (r.ok && out.verified) {
    $("verify-msg").innerHTML = '<span class="ok">Thanks, that was you.</span>';
    $("make-box").hidden = false;
  } else {
    $("verify-msg").textContent = r.ok ? `We heard "${out.heard}". Try once more, at your own pace.` : out.detail;
  }
};

$("make-clone").onclick = async () => {
  $("make-clone").disabled = true;
  $("clone-msg").textContent = "Making the AI-voice version. On this computer it can take a few minutes.";
  const r = await fetch(`/studio/${job.id}/clone`, { method: "POST" });
  if (!r.ok) { $("clone-msg").textContent = (await r.json()).detail; $("make-clone").disabled = false; return; }
  const poll = setInterval(async () => {
    const j = await (await fetch(`/studio/${job.id}`)).json();
    const st = j.clone && j.clone.status;
    if (st === "done") {
      clearInterval(poll);
      const url = `/studio/${job.id}/audio/clone.wav?v=${Date.now()}`;
      $("a-clone").src = url; $("dl-clone").href = url;
      $("clone-player").hidden = false;
      $("clone-msg").textContent = `Done in ${j.clone.seconds} s. AI voice, watermarked.`;
      $("make-clone").disabled = false;
    } else if (st === "failed") {
      clearInterval(poll);
      $("clone-msg").textContent = "The AI voice could not be made on this computer.";
      $("make-clone").disabled = false;
    }
  }, 3000);
};

$("copy").onclick = () => navigator.clipboard?.writeText(job.clean_text);
$("delete").onclick = async () => {
  if (!job || !confirm("Delete this recording and everything made from it?")) return;
  await fetch(`/studio/${job.id}`, { method: "DELETE" });
  location.reload();
};
// Open a saved recording: voice-studio.html?job=<id>
const saved = new URLSearchParams(location.search).get("job");
if (saved) {
  fetch(`/studio/${saved}/reanalyze`, { method: "POST" }).then((r) => r.json()).then(async (j) => {
    if (!j.id) return;
    job = j;
    origBuf = await decodeOriginal();
    showReview();
  });
}
$("rec").onclick = toggleRecord;
$("upload").onchange = (e) => e.target.files[0] && process(e.target.files[0], "upload");
