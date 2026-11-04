// Voice-over player: one switch between your original and the clean version, kept in sync.
import { demoLabel } from "./demo-mode.js";
const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
if (params.get("demo") === "1") document.body.classList.add("demo");

let job = null, editing = true, playing = false, wordEls = [], cleanEls = [];
const orig = $("a-orig"), clean = $("a-clean");
const active = () => (editing ? clean : orig);

// ---- time mapping (same rules as server/studio/voiceover.py) ----------------
function toClean(t, map) {
  for (const s of map) {
    const [a, b] = s.src;
    if (t < a) return s.dst;
    if (t <= b) return s.dst + (t - a);
  }
  const l = map[map.length - 1];
  return l ? l.dst + (l.src[1] - l.src[0]) : 0;
}
function toOriginal(t, map) {
  for (const s of map) {
    const [a, b] = s.src;
    if (t <= s.dst + (b - a)) return a + Math.max(0, t - s.dst);
  }
  return map.length ? map[map.length - 1].src[1] : 0;
}
const originalNow = () => (editing ? toOriginal(clean.currentTime, job.output_map) : orig.currentTime);
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

// ---- loading --------------------------------------------------------------
async function loadList() {
  const list = await (await fetch("/studio/list/recent")).json();
  $("pick").innerHTML = "";
  for (const r of list) {
    const o = document.createElement("option");
    o.value = r.id;
    o.textContent = `${new Date(r.created * 1000).toLocaleString()} · ${r.duration.toFixed(0)} s · ${r.cuts} cuts · "${r.preview}…"`;
    $("pick").appendChild(o);
  }
  const want = params.get("job") || (list[0] && list[0].id);
  if (!want) { $("pick-note").textContent = "No recordings yet. Record your voice-over in Voice Studio first."; return; }
  $("pick").value = want;
  await load(want);
}

async function load(id) {
  job = await (await fetch(`/studio/${id}`)).json();
  if (!job.id) return;
  await fetch(`/studio/${id}/render`, { method: "POST" });     // clean version with the current cuts
  const v = Date.now();
  orig.src = `/studio/${id}/audio/original.wav`;
  clean.src = `/studio/${id}/audio/clean.wav?v=${v}`;
  $("dl-clean").href = clean.src;
  updateAb();
  renderTexts();
  renderCuts();
  $("ai").hidden = !(job.clone && job.clone.status === "done");
  if (!$("ai").hidden) $("a-ai").src = `/studio/${id}/audio/clone.wav?v=${v}`;
  history.replaceState(null, "", `?job=${id}${params.get("demo") === "1" ? "&demo=1" : ""}`);
}

function cutOwner() {
  const owner = {};
  for (const e of job.edits) if (e.on && e.words && !e.partial) for (let i = e.words[0]; i <= e.words[1]; i++) owner[i] = e;
  return owner;
}

function renderTexts() {
  const owner = cutOwner();
  $("said").innerHTML = ""; $("cleaned").innerHTML = "";
  wordEls = []; cleanEls = [];
  job.words.forEach((w, i) => {
    const s = document.createElement("span");
    s.textContent = w.text;
    const fragment = w.text.endsWith("-") && w.text.replace(/[^a-z0-9']/gi, "").length <= 3;
    if (owner[i] || fragment) s.className = "cut";
    $("said").append(s, " ");
    wordEls.push({ el: s, w });
    if (!s.className) {
      const c = document.createElement("span");
      c.textContent = w.text;
      $("cleaned").append(c, " ");
      cleanEls.push({ el: c, w });
    }
  });
}

function evidence(e) {
  if (e.kind === "block") return "pause shortened to 0.3 s";
  if (e.kind === "manual") return "my own cut";
  if (e.by === "rules") return "found by rules";
  const p = ["Spark heard it"];
  if (e.agreed) p.push("heard again on a second listen");
  if (e.confirmed) p.push("wav2vec 2.0 heard it too");
  if (e.transcript) p.push("Voice Transcribe wrote it twice");
  return p.join(" · ");
}

function renderCuts() {
  const list = $("edits");
  list.innerHTML = "";
  for (const e of job.edits.filter((x) => x.on)) {
    const li = document.createElement("li");
    li.innerHTML = '<span class="kind"></span><span class="txt"></span><span class="muted"></span>';
    li.children[0].textContent = e.kind === "block" ? "pause" : e.kind;
    li.children[0].classList.add(e.kind);
    li.children[1].textContent = e.text;
    const s = document.createElement("small"); s.className = "why-cut"; s.textContent = evidence(e);
    li.children[1].append(document.createElement("br"), s);
    li.children[2].textContent = `${e.start.toFixed(1)} s`;
    list.appendChild(li);
  }
  const rej = (job.harness && job.harness.rejected) || [];
  $("rejected").innerHTML = rej.length ? "" : '<li class="muted">None.</li>';
  for (const r of rej) {
    const li = document.createElement("li");
    li.textContent = `"${r.text}" at ${r.start.toFixed(1)} s: ${r.reason}`;
    $("rejected").appendChild(li);
  }
}

// ---- playback ---------------------------------------------------------------
function setEditing(on) {
  if (!job || on === editing) return;
  demoLabel(on ? "Voice editing ON · my real voice, stammers cut (only cuts, nothing added)"
               : "Voice editing OFF · exactly what I said");
  const t = originalNow();
  const wasPlaying = playing;
  active().pause();
  editing = on;
  active().currentTime = editing ? toClean(t, job.output_map) : t;
  if (wasPlaying) active().play();
  $("on").setAttribute("aria-pressed", String(on));
  $("off").setAttribute("aria-pressed", String(!on));
  $("badge").textContent = on ? "Real voice · only cuts" : "Real voice · as spoken";
  $("said-card").classList.toggle("panel-dim", on);
  $("clean-card").classList.toggle("panel-dim", !on);
}

function togglePlay() {
  if (!job) return;
  if (playing) { active().pause(); playing = false; }
  else { active().play(); playing = true; }
  $("play").innerHTML = playing
    ? '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
}

function tick() {
  if (job) {
    const a = active();
    const dur = a.duration || 0;
    $("time").textContent = `${fmt(a.currentTime)} / ${fmt(dur)}`;
    if (dur && document.activeElement !== $("seek")) $("seek").value = (100 * a.currentTime) / dur;
    const t = originalNow();
    for (const { el, w } of wordEls) el.classList.toggle("now", t >= w.start && t <= w.end);
    for (const { el, w } of cleanEls) el.classList.toggle("now", t >= w.start && t <= w.end);
  }
  requestAnimationFrame(tick);
}

function updateAb() {
  if (!job) return;
  $("dl-ab").href = `/studio/${job.id}/ab.wav?start=${Number($("ab-start").value) || 0}&seconds=${Number($("ab-len").value) || 10}`;
}

for (const a of [orig, clean]) a.onended = () => { if (a === active()) { playing = true; togglePlay(); } };
$("on").onclick = () => setEditing(true);
$("off").onclick = () => setEditing(false);
$("play").onclick = togglePlay;
$("seek").oninput = () => { const a = active(); if (a.duration) a.currentTime = (Number($("seek").value) / 100) * a.duration; };
$("pick").onchange = () => load($("pick").value);
$("ab-start").oninput = updateAb;
$("ab-len").oninput = updateAb;
document.addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT"].includes(e.target.tagName)) return;
  if (e.code === "Space") { e.preventDefault(); togglePlay(); }
  if (e.key === "e" || e.key === "E") setEditing(!editing);
});
$("said-card").classList.add("panel-dim");
requestAnimationFrame(tick);
loadList();
