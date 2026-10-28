import { startMic } from "./mic.js";

const $ = (id) => document.getElementById(id);
let ws = null, stopMic = null;
const SPEECH_RATE = 0.9;

function setStatus(s) { $("status").textContent = s; }

function addMsg(who, text, raw) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  const main = document.createElement("div");
  main.textContent = text;
  div.appendChild(main);
  if (raw && raw !== text) {
    const btn = document.createElement("button");
    btn.className = "toggle";
    btn.textContent = "show what I said";
    btn.onclick = () => {
      div.classList.toggle("show-raw");
      btn.textContent = div.classList.contains("show-raw") ? "hide" : "show what I said";
    };
    const r = document.createElement("div");
    r.className = "raw";
    r.textContent = raw;
    div.append(btn, r);
  }
  $("chat").appendChild(div);
  div.scrollIntoView({ block: "nearest" });
}

function speak(text) {
  if (!("speechSynthesis" in window) || !text) return;
  const u = new SpeechSynthesisUtterance(text);
  u.rate = SPEECH_RATE;
  speechSynthesis.speak(u);
}

function captions() {
  return { live: $("captions").querySelector(".live"), done: $("captions").querySelector(".committed") };
}

function showCue(on) { $("cue").classList.toggle("on", on); }

function showConfirm(ev) {
  $("confirm-text").textContent = ev ? ev.text : "";
  $("confirm").classList.toggle("on", !!ev);
  $("confirm").dataset.action = ev ? ev.action_id : "";
}

function onEvent(ev) {
  const c = captions();
  switch (ev.type) {
    case "ready": setStatus(`Listening (${ev.mode})`); break;
    case "partial": c.live.textContent = ev.text; break;
    case "model_text": c.done.textContent = ev.text; c.live.textContent = ""; break;
    case "speech_start": break;
    case "hold": showCue(true); break;
    case "turn":
      showCue(false);
      c.done.textContent = ""; c.live.textContent = "";
      addMsg("you", ev.clean, ev.raw);
      break;
    case "bot": addMsg("bot", ev.text); speak(ev.text); break;
    case "confirm": showConfirm(ev); speak(ev.text); break;
    case "confirm_done": showConfirm(null); break;
    case "error": setStatus("Error: " + ev.message); break;
  }
}

function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

async function start() {
  $("start").disabled = true;
  setStatus("Connecting…");
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/listen`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  ws.onclose = () => { setStatus("Not listening"); cleanup(); };
  await new Promise((r) => (ws.onopen = r));
  send({ type: "start", mode: $("mode").value, ...(window.unhurriedSessionExtras?.() || {}) });
  // While the bot is speaking, send silence so the mic does not hear the bot.
  stopMic = await startMic((chunk) => ws && ws.readyState === 1 && ws.send(chunk),
    () => speechSynthesis.speaking);
  $("stop").disabled = false;
  $("mode").disabled = true;
}

function cleanup() {
  if (stopMic) stopMic();
  stopMic = null;
  showCue(false);
  showConfirm(null);
  $("start").disabled = false;
  $("stop").disabled = true;
  $("mode").disabled = false;
}

function stop() { send({ type: "stop" }); cleanup(); }

function sendTyped() {
  const text = $("typed").value.trim();
  if (!text) return;
  send({ type: "text", text });
  $("typed").value = "";
}

$("start").onclick = start;
$("stop").onclick = stop;
$("send-typed").onclick = sendTyped;
$("typed").addEventListener("keydown", (e) => { if (e.key === "Enter") sendTyped(); });
$("confirm-yes").onclick = () => send({ type: "confirm_answer", action_id: $("confirm").dataset.action, answer: "yes" });
$("confirm-change").onclick = () => send({ type: "confirm_answer", action_id: $("confirm").dataset.action, answer: "change" });

export { onEvent, send };
