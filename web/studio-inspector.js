// Inspector: explains each turn decision in plain words and keeps session stats.
const $ = (id) => document.getElementById(id);

const HOLD_WHY = {
  linking_word: (w) => `Your sentence ended on "${w}", so more was coming.`,
  cut_word: () => "The last word was cut off.",
  repeat: () => "A word was repeating.",
  filler: () => "You were still thinking.",
  no_words: () => "No words yet.",
  check_no: () => "Spark said the request was not complete yet.",
  sound: () => "Your voice did not sound finished.",
  voice_in_pause: () => "Your voice was still active in the pause.",
  check_timeout_sound: () => "Spark was slow and your voice did not sound finished.",
};
const SEND_WHY = {
  rules: "A complete sentence. Sent after a short beat.",
  words_sound: "Your words and your voice both sounded finished.",
  check_yes: "Spark agreed the request was complete.",
  check_timeout: "Your words looked complete. Spark was slow, so you were not kept waiting.",
  check_failed: "Your words looked complete.",
  max_wait: "A long quiet after your last word, so it was sent.",
  max_wait_empty: "A long quiet with no words, so it was sent.",
  typed: "You typed to finish the sentence.",
};
const LABEL = {
  rules: "words", words_sound: "words + voice", check_yes: "Spark", check_timeout: "words",
  check_failed: "words", max_wait: "max wait", max_wait_empty: "max wait", typed: "typed",
  model_end: "end of speech",
};

export const stats = { saved: 0, longest: 0, turns: 0, fixes: 0, pauseStart: null };

export function resetInspector() {
  Object.assign(stats, { saved: 0, longest: 0, turns: 0, fixes: 0, pauseStart: null });
  $("timeline").innerHTML = '<li class="muted" style="display:block">No pauses yet.</li>';
  $("verdict").textContent = "Listening";
  $("verdict").className = "verdict";
  $("why").textContent = "Each time you pause, Unhurried decides: wait, or send.";
  for (const id of ["sig-words", "sig-sound", "sig-spark"]) $(id).textContent = "–";
  $("sig-sound-bar").style.width = "0";
  renderStats();
}

export function renderStats() {
  $("s-saved").textContent = stats.saved;
  $("s-longest").textContent = `${stats.longest.toFixed(1)}s`;
  $("s-turns").textContent = stats.turns;
  $("s-fixes").textContent = stats.fixes;
}

export function sendLabel(reason) { return LABEL[reason] || reason; }

function wordsText(d) {
  const s = d.signals || {};
  const w = (d.last_words || []).slice(-1)[0] || "";
  if (s.cut_word) return "cut word";
  if (s.repeat) return "repeating";
  if (s.filler) return "filler";
  if (s.linking_word) return `ends on "${w}"`;
  return (d.last_words || []).length ? "looks complete" : "no words";
}

function addTimeline(kind, text, t) {
  const list = $("timeline");
  if (list.querySelector(".muted")) list.innerHTML = "";
  const li = document.createElement("li");
  li.className = kind;
  li.innerHTML = '<span class="dot"></span><span></span><span class="t"></span>';
  li.children[1].textContent = text;
  li.children[2].textContent = `${t.toFixed(1)}s`;
  list.prepend(li);
}

// One decision row from the server (same shape as decisions.jsonl).
export function showDecision(d) {
  const v = $("verdict");
  $("sig-words").textContent = wordsText(d);
  if (d.sound) {
    $("sig-sound-bar").style.width = `${Math.round(d.sound.score * 100)}%`;
    const pitch = d.sound.pitch_falling === true ? "pitch falls" : d.sound.pitch_falling === false ? "pitch level" : "";
    $("sig-sound").textContent = d.sound.voiced_in_pause ? "still voicing" : [pitch, `fade ${Math.round(d.sound.fade * 100)}%`].filter(Boolean).join(", ");
  } else {
    $("sig-sound-bar").style.width = "0";
    $("sig-sound").textContent = "off";
  }
  const sp = d.spark_check;
  $("sig-spark").textContent = !sp ? (d.decision === "check" ? "asking…" : "not needed")
    : sp.answer === "timeout" ? "too slow, skipped" : `${sp.answer}${sp.ms ? `, ${(sp.ms / 1000).toFixed(1)}s` : ""}${sp.cached ? " (early)" : ""}`;

  const last = (d.last_words || []).slice(-1)[0] || "";
  if (d.decision === "hold") {
    v.textContent = "Held"; v.className = "verdict held";
    $("why").textContent = (HOLD_WHY[d.reason] || (() => "Waiting for you."))(last);
    if (stats.pauseStart === null) stats.pauseStart = d.t - d.pause_ms / 1000;
    addTimeline("hold", `Held: ${wordsText(d)}`, d.t);
  } else if (d.decision === "send") {
    v.textContent = "Sent"; v.className = "verdict sent";
    $("why").textContent = SEND_WHY[d.reason] || "Sent.";
    stats.pauseStart = null;
    addTimeline("send", `Sent (${sendLabel(d.reason)}) after ${(d.pause_ms / 1000).toFixed(1)}s`, d.t);
  } else if (d.decision === "check") {
    v.textContent = "Checking"; v.className = "verdict";
    $("why").textContent = "Your words look complete. Asking Spark to be sure.";
  } else if (d.decision === "send_soon") {
    v.textContent = "Almost"; v.className = "verdict";
    $("why").textContent = "Your words look complete. Sending in a moment unless you go on.";
  }
}

// Speech started again inside a held turn: a normal bot would have replied here.
export function onResume(t, pauseMs) {
  stats.saved += 1;
  const gap = pauseMs != null ? pauseMs / 1000 : stats.pauseStart !== null ? t - stats.pauseStart : 0;
  stats.longest = Math.max(stats.longest, gap);
  stats.pauseStart = null;
  addTimeline("hold", "You went on. A normal bot would have cut in here.", t);
  renderStats();
}
