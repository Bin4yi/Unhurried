import { startMic } from "./mic.js";

const $ = (id) => document.getElementById(id);
let ws = null, stopMic = null;

function setStatus(s) { $("status").textContent = s; }

function onEvent(ev) {
  const live = $("captions").querySelector(".live");
  const done = $("captions").querySelector(".committed");
  if (ev.type === "ready") setStatus("Listening");
  else if (ev.type === "partial") live.textContent = ev.text;
  else if (ev.type === "speech_end") { done.textContent = (done.textContent + " " + live.textContent).trim(); live.textContent = ""; }
  else if (ev.type === "error") setStatus("Error: " + ev.message);
}

async function start() {
  $("start").disabled = true;
  setStatus("Connecting…");
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/listen`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  ws.onclose = () => { setStatus("Not listening"); cleanup(); };
  await new Promise((r) => (ws.onopen = r));
  ws.send(JSON.stringify({ type: "start", mode: "baseline" }));
  stopMic = await startMic((chunk) => ws && ws.readyState === 1 && ws.send(chunk));
  $("stop").disabled = false;
}

function cleanup() {
  if (stopMic) stopMic();
  stopMic = null;
  $("start").disabled = false;
  $("stop").disabled = true;
}

function stop() {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "stop" }));
  cleanup();
}

$("start").onclick = start;
$("stop").onclick = stop;
