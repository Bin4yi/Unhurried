// Split-screen demo: the same audio goes to a baseline session and an Unhurried session.
import { startMic, streamWav } from "./mic.js";

const $ = (id) => document.getElementById(id);
const sides = {};
let stopMic = null, stopped = true;

function side(mode) {
  const root = $(`side-${mode}`);
  const q = (sel) => root.querySelector(sel);
  return {
    mode, root, ws: null, turns: 0, cutoffs: 0,
    live: q(".live"), done: q(".committed"), chat: q(".chat"), stat: q(".stat"),
    cue: q(".cue"), confirm: q(".confirm"),
  };
}

function addMsg(s, who, text, raw) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  if (raw && raw !== text) {
    const r = document.createElement("div");
    r.className = "muted";
    r.textContent = `said: ${raw}`;
    div.appendChild(r);
  }
  s.chat.appendChild(div);
  div.scrollIntoView({ block: "nearest" });
}

function onEvent(s, ev) {
  switch (ev.type) {
    case "partial": s.live.textContent = ev.text; break;
    case "model_text": s.done.textContent = ev.text; s.live.textContent = ""; break;
    case "hold": if (s.cue) s.cue.classList.add("on"); break;
    case "sending": if (s.cue) s.cue.classList.remove("on"); break;
    case "turn":
      s.turns += 1;
      s.done.textContent = ""; s.live.textContent = "";
      addMsg(s, "you", ev.clean, ev.raw);
      s.stat.textContent = `${s.turns} turn(s) sent to the bot`;
      break;
    case "bot":
      addMsg(s, "bot", ev.text);
      if (s.mode === "unhurried" && $("speak").checked && "speechSynthesis" in window) {
        const u = new SpeechSynthesisUtterance(ev.text); u.rate = 0.9; speechSynthesis.speak(u);
      }
      break;
    case "confirm":
      if (s.confirm) {
        s.confirm.querySelector(".confirm-text").textContent = ev.text;
        s.confirm.dataset.action = ev.action_id;
        s.confirm.classList.add("on");
      }
      break;
    case "confirm_done": if (s.confirm) s.confirm.classList.remove("on"); break;
    case "error": $("status").textContent = ev.message; break;
  }
}

async function open(mode) {
  const s = side(mode);
  sides[mode] = s;
  s.chat.innerHTML = ""; s.stat.textContent = "";
  s.ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/listen`);
  s.ws.binaryType = "arraybuffer";
  const ready = new Promise((resolve) => {
    s.ws.onmessage = (m) => { const ev = JSON.parse(m.data); if (ev.type === "ready") resolve(); onEvent(s, ev); };
  });
  await new Promise((r) => (s.ws.onopen = r));
  // The baseline side has no confirm buttons, so its bookings are approved automatically.
  s.ws.send(JSON.stringify({ type: "start", mode, auto_confirm: mode === "baseline" }));
  await ready;
  if (s.confirm) {
    s.confirm.querySelector(".yes").onclick = () => answer(s, "yes");
    s.confirm.querySelector(".change").onclick = () => answer(s, "change");
  }
}

function answer(s, a) {
  s.ws.send(JSON.stringify({ type: "confirm_answer", action_id: s.confirm.dataset.action, answer: a }));
}

function sendBoth(chunk) {
  for (const s of Object.values(sides)) if (s.ws && s.ws.readyState === 1) s.ws.send(chunk);
}

async function begin() {
  stopped = false;
  $("mic").disabled = $("play").disabled = true;
  $("stop").disabled = false;
  $("status").textContent = "Connecting…";
  await Promise.all([open("baseline"), open("unhurried")]);
  $("status").textContent = "Listening";
}

async function useMic() {
  await begin();
  stopMic = await startMic(sendBoth, () => speechSynthesis.speaking);
}

async function playClip() {
  const file = $("clip").value;
  if (!file) return;
  await begin();
  const buf = await (await fetch(file)).arrayBuffer();
  const audio = new Audio(file);
  audio.play();
  await streamWav(buf, sendBoth, () => stopped);
  // keep the streams alive with silence so both sides can finish
  const silence = new ArrayBuffer(3840);
  for (let i = 0; i < 100 && !stopped; i++) { sendBoth(silence); await new Promise((r) => setTimeout(r, 80)); }
}

function stop() {
  stopped = true;
  if (stopMic) stopMic();
  stopMic = null;
  for (const s of Object.values(sides)) {
    if (s.ws && s.ws.readyState === 1) s.ws.send(JSON.stringify({ type: "stop" }));
    if (s.cue) s.cue.classList.remove("on");
  }
  $("mic").disabled = $("play").disabled = false;
  $("stop").disabled = true;
  $("status").textContent = "";
}

async function loadClips() {
  const clips = await (await fetch("/bench/clips")).json().catch(() => []);
  for (const c of clips.filter((c) => c.public_audio)) {
    const o = document.createElement("option");
    o.value = "/bench/audio/" + c.file.split("/").pop();
    o.textContent = `${c.id} (${c.kind}) ${c.script || ""}`.slice(0, 80);
    $("clip").appendChild(o);
  }
}

$("mic").onclick = useMic;
$("play").onclick = playClip;
$("stop").onclick = stop;
loadClips();
