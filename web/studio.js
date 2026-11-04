// Unhurried Studio: talk to the booking assistant and see every turn decision.
import { startMic } from "./mic.js";
import { demoLabel } from "./demo-mode.js";
import { onResume, renderStats, resetInspector, sendLabel, showDecision, stats } from "./studio-inspector.js";

const $ = (id) => document.getElementById(id);
const ENGINES = {
  words_spark: { spark_check: true },
  words_sound_spark: { spark_check: true, sound: true },
  words: { spark_check: false },
};
let mode = "unhurried", main = null, shadow = null, stopMic = null, running = false;
let voiceOn = true, level = 0, mainOpen = false;

// ---------------------------------------------------------------- helpers
function setStatus(state, text) {
  $("status").dataset.state = state;
  $("status").lastElementChild.textContent = text;
}

function caption(done, live) {
  const el = $("caption");
  el.innerHTML = "";
  const a = document.createElement("span"); a.textContent = done;
  const b = document.createElement("span"); b.className = "live"; b.textContent = live ? ` ${live}` : "";
  el.append(a, b);
}

function held(on) {
  $("cue").classList.toggle("on", on && (!window.unhurriedPrefs || window.unhurriedPrefs.show_cue !== false));
  $("orb").classList.toggle("held", on);
  if (running) setStatus(on ? "held" : "live", on ? "Waiting for you" : "Listening");
}

function speak(text) {
  if (!voiceOn || !text || !("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 0.9;
  speechSynthesis.speak(u);
}

function addLine(list, who, text, extra = {}) {
  const box = $(list);
  box.querySelector(".empty, .muted")?.remove();
  const line = document.createElement("div");
  line.className = `line ${who}`;
  const label = document.createElement("div");
  label.className = "who";
  label.textContent = who === "you" ? "You" : "Bot";
  const body = document.createElement("div");
  const t = document.createElement("div");
  t.className = "text";
  t.textContent = text;
  body.appendChild(t);
  const meta = document.createElement("div");
  meta.className = "meta";
  for (const c of extra.changes || []) {
    const chip = document.createElement("span");
    chip.className = "chip fix";
    const from = document.createElement("s"); from.textContent = c.from;
    chip.append(from, document.createTextNode(c.to ? ` → ${c.to}` : " removed"));
    meta.appendChild(chip);
  }
  if (extra.reason) {
    const chip = document.createElement("span");
    chip.className = "chip sent";
    chip.textContent = `sent by ${sendLabel(extra.reason)}`;
    meta.appendChild(chip);
  }
  if (extra.cut) {
    const chip = document.createElement("span");
    chip.className = "chip warn";
    chip.textContent = "replied while you were mid-sentence";
    meta.appendChild(chip);
  }
  if (extra.raw && extra.raw !== text) {
    const btn = document.createElement("button");
    btn.className = "said-btn"; btn.type = "button"; btn.textContent = "show what I said";
    const said = document.createElement("div");
    said.className = "said"; said.textContent = extra.raw;
    btn.onclick = () => {
      line.classList.toggle("show-said");
      btn.textContent = line.classList.contains("show-said") ? "hide" : "show what I said";
    };
    meta.appendChild(btn);
    body.append(meta, said);
  } else if (meta.childElementCount) {
    body.appendChild(meta);
  }
  if (who === "you" && list === "lines") { label.style.color = "var(--clay)"; }
  line.append(label, body);
  box.appendChild(line);
  line.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ---------------------------------------------------------------- demo labels
function decisionLabel(d) {
  const last = (d.last_words || []).slice(-1)[0] || "";
  const sp = d.spark_check;
  if (d.decision === "hold") {
    const why = d.reason === "linking_word" ? `sentence ended on '${last}'`
      : d.reason === "voice_in_pause" ? "your voice is still active" : (d.reason || "").replace(/_/g, " ");
    return `Turn engine · holding: ${why} · words + voice`;
  }
  if (d.decision === "check") return "Completeness check · Muse Spark 1.3 · asking (at most 700 ms)";
  if (d.decision === "send" && d.reason === "words_sound") return "Turn engine · sent: words and voice agree · no model call";
  if (d.decision === "send" && sp && sp.ms) return `Completeness check · Muse Spark 1.3 · ${sp.ms} ms`;
  if (d.decision === "send" && d.reason === "spark_late") return "Turn engine · sent: Spark over 700 ms, decided by words + voice";
  if (d.decision === "send") return `Turn engine · sent (${(d.reason || "").replace(/_/g, " ")})`;
  return "Turn engine · listening";
}

// ---------------------------------------------------------------- sessions
function onMain(ev) {
  window.dispatchEvent(new CustomEvent("unhurried-event", { detail: ev }));
  switch (ev.type) {
    case "partial": mainOpen = true; caption(main.done, ev.text); break;
    case "model_text": main.done = ev.text; caption(ev.text, ""); break;
    case "hold": held(true); break;
    case "sending": held(false); break;
    case "resume":
      onResume(ev.t, ev.pause_ms);
      demoLabel("Turn engine · you went on: a normal bot would have cut in here");
      break;
    case "decision": showDecision(ev); demoLabel(decisionLabel(ev)); break;
    case "turn":
      mainOpen = false; main.done = "";
      caption("", "");
      stats.turns += 1;
      stats.fixes += (ev.changes || []).length;
      renderStats();
      addLine("lines", "you", ev.clean, { raw: ev.raw, changes: ev.changes, reason: mode === "baseline" ? null : ev.reason });
      if (mode !== "baseline") {
        const by = ev.spark && !ev.spark.error ? "Muse Spark 1.3 + code" : "code";
        demoLabel(`Meaning rebuild · ${by} · guard: ${ev.needs_confirm ? "asked you to confirm" : "passed"} · ${(ev.changes || []).length} repairs`);
      }
      break;
    case "bot": addLine("lines", "bot", ev.text); speak(ev.text); break;
    case "confirm":
      demoLabel("Confirm gate · nothing is booked until you say yes");
      $("confirm-text").textContent = ev.text;
      $("confirm").dataset.action = ev.action_id;
      $("confirm").classList.add("on");
      speak(ev.text);
      $("confirm-yes").focus();
      break;
    case "confirm_done": $("confirm").classList.remove("on"); break;
    case "error": setStatus("idle", ev.message); break;
  }
}

function onShadow(ev) {
  if (ev.type === "turn") addLine("compare-lines", "you", ev.raw, { cut: mainOpen });
  else if (ev.type === "bot") addLine("compare-lines", "bot", ev.text);
}

async function openSession(sessionMode, handler, extra = {}) {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/listen`);
  ws.binaryType = "arraybuffer";
  const s = { ws, done: "" };
  const ready = new Promise((resolve, reject) => {
    ws.onmessage = (m) => { const ev = JSON.parse(m.data); if (ev.type === "ready") resolve(); handler(ev); };
    ws.onerror = () => reject(new Error("could not connect"));
    ws.onclose = () => { if (running && s === main) end(); };
  });
  await new Promise((r, j) => { ws.onopen = r; ws.addEventListener("error", j, { once: true }); });
  ws.send(JSON.stringify({ type: "start", mode: sessionMode, bot: $("bot").value,
    engine: ENGINES[$("engine").value], ...extra }));
  await ready;
  return s;
}

function send(s, obj) { if (s && s.ws.readyState === 1) s.ws.send(JSON.stringify(obj)); }

async function begin() {
  $("begin").disabled = true;
  setStatus("idle", "Connecting…");
  resetInspector();
  $("lines").innerHTML = "";
  $("compare-lines").innerHTML = "";
  caption("", "");
  try {
    const extras = window.unhurriedSessionExtras?.() || {};
    const words = $("words").value.split(",").map((w) => w.trim()).filter(Boolean);
    const mainMode = mode === "baseline" ? "baseline" : "unhurried";
    [main, shadow] = await Promise.all([
      openSession(mainMode, onMain, { keywords: words, ...extras }),
      mode === "compare" ? openSession("baseline", onShadow, { keywords: words, auto_confirm: true }) : null,
    ]);
    stopMic = await startMic((chunk) => {
      const v = new Int16Array(chunk);
      let sum = 0;
      for (let i = 0; i < v.length; i += 4) sum += v[i] * v[i];
      level = Math.min(1, Math.sqrt(sum / (v.length / 4)) / 6000);
      for (const s of [main, shadow]) if (s && s.ws.readyState === 1) s.ws.send(chunk);
    }, () => speechSynthesis.speaking);
  } catch (e) {
    setStatus("idle", "Could not start. Is the server running?");
    $("begin").disabled = false;
    return;
  }
  running = true;
  $("orb").classList.remove("idle");
  setStatus("live", "Listening");
  $("begin").classList.add("on");
  $("begin").lastElementChild.textContent = "End";
  $("begin").disabled = false;
  for (const b of document.querySelectorAll(".seg button")) b.disabled = true;
}

function end() {
  running = false;
  if (stopMic) stopMic();
  stopMic = null;
  for (const s of [main, shadow]) send(s, { type: "stop" });
  shadow = null;
  held(false);
  level = 0;
  $("orb").classList.add("idle");
  $("confirm").classList.remove("on");
  setStatus("idle", "Not listening");
  $("begin").classList.remove("on");
  $("begin").lastElementChild.textContent = "Begin";
  for (const b of document.querySelectorAll(".seg button")) b.disabled = false;
}

// ---------------------------------------------------------------- wiring
$("begin").onclick = () => (running ? end() : begin());
$("confirm-yes").onclick = () => send(main, { type: "confirm_answer", action_id: $("confirm").dataset.action, answer: "yes" });
$("confirm-change").onclick = () => send(main, { type: "confirm_answer", action_id: $("confirm").dataset.action, answer: "change" });
$("type-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("typed").value.trim();
  if (!text || !running) return;
  send(main, { type: "text", text });
  $("typed").value = "";
};
for (const b of document.querySelectorAll(".seg button")) {
  b.onclick = () => {
    mode = b.dataset.mode;
    for (const x of document.querySelectorAll(".seg button")) x.setAttribute("aria-pressed", String(x === b));
    $("compare-panel").hidden = mode !== "compare";
    $("stage-title").textContent = mode === "baseline" ? "Your turn (normal bot)" : "Your turn";
  };
}
$("voice-toggle").onclick = () => {
  voiceOn = !voiceOn;
  $("voice-toggle").setAttribute("aria-pressed", String(voiceOn));
  $("voice-toggle").lastElementChild.textContent = voiceOn ? "Voice on" : "Voice off";
  if (!voiceOn) speechSynthesis.cancel();
};
$("open-settings").onclick = () => $("settings").showModal();
$("close-settings").onclick = () => $("settings").close();
$("settings").addEventListener("click", (e) => { if (e.target === $("settings")) $("settings").close(); });
try {
  $("words").value = localStorage.getItem("unhurried.words") || "";
  $("engine").value = localStorage.getItem("unhurried.engine") || "words_sound_spark";
  $("bot").value = localStorage.getItem("unhurried.bot") || "assistant";
} catch {}
$("words").addEventListener("change", () => { try { localStorage.setItem("unhurried.words", $("words").value); } catch {} });
$("bot").addEventListener("change", () => { try { localStorage.setItem("unhurried.bot", $("bot").value); } catch {} });
$("engine").addEventListener("change", () => { try { localStorage.setItem("unhurried.engine", $("engine").value); } catch {} });

// Orb follows the voice level, smoothed.
let shown = 0;
(function frame() {
  shown += (level - shown) * 0.25;
  $("orb").style.setProperty("--level", shown.toFixed(3));
  requestAnimationFrame(frame);
})();
