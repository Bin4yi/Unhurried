// Voice Passport UI: unlock, save (IndexedDB + server, encrypted), export, import, delete.
import {
  addPauses, decryptProfile, encryptProfile, learnWords, newProfile, sessionSettings,
} from "./passport-crypto.js";

const $ = (id) => document.getElementById(id);
let profile = null, passphrase = "", learnNext = false;

// ---- storage ---------------------------------------------------------------
function profileId() {
  let id = null;
  try { id = localStorage.getItem("unhurried.passport.id"); } catch {}
  if (!id) {
    id = "p_" + Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");
    try { localStorage.setItem("unhurried.passport.id", id); } catch {}
  }
  return id;
}

function idb(mode, fn) {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open("unhurried", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("passport");
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const tx = open.result.transaction("passport", mode);
      const req = fn(tx.objectStore("passport"));
      tx.oncomplete = () => resolve(req && req.result);
      tx.onerror = () => reject(tx.error);
    };
  });
}

async function loadBlob() {
  try { const b = await idb("readonly", (s) => s.get("blob")); if (b) return b; } catch {}
  const r = await fetch(`/profile/${profileId()}`);
  return r.ok ? r.json() : null;
}

async function saveBlob(blob) {
  try { await idb("readwrite", (s) => s.put(blob, "blob")); } catch {}
  await fetch(`/profile/${profileId()}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(blob),
  });
}

async function persist() {
  if (profile && passphrase) await saveBlob(await encryptProfile(profile, passphrase));
  render();
}

// ---- UI --------------------------------------------------------------------
function render() {
  const on = !!profile;
  $("pp-status").textContent = on
    ? `Unlocked. Waits up to ${(profile.timing.max_wait_ms / 1000).toFixed(1)} s inside a sentence. ` +
      `${profile.words.added_by_me.length + profile.words.learned.length} words, ` +
      `${profile.switches.filter((s) => s.approved).length} word switches.`
    : "Locked. Unhurried uses default settings.";
  for (const id of ["pp-lock", "pp-export", "pp-save-words", "pp-show-cue"]) $(id).disabled = !on;
  $("pp-unlock").disabled = on;
  if (on) {
    $("pp-words").value = profile.words.added_by_me.join(", ");
    $("pp-show-cue").checked = profile.prefs.show_cue !== false;
  }
  window.unhurriedPrefs = on ? profile.prefs : null;
}

async function unlock() {
  const pass = $("pp-pass").value;
  if (pass.length < 8) { $("pp-msg").textContent = "Use a passphrase of at least 8 characters."; return; }
  $("pp-msg").textContent = "Unlocking…";
  try {
    const blob = await loadBlob();
    profile = blob ? await decryptProfile(blob, pass) : newProfile();
    passphrase = pass;
    $("pp-pass").value = "";
    $("pp-msg").textContent = blob ? "" : "New profile created.";
    await persist();
  } catch (e) {
    $("pp-msg").textContent = e.message;
  }
}

function lock() { profile = null; passphrase = ""; $("pp-msg").textContent = ""; render(); }

async function exportFile() {
  const blob = await encryptProfile(profile, passphrase);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(blob)], { type: "application/json" }));
  a.download = "unhurried-passport.json";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function importFile(file) {
  try {
    const blob = JSON.parse(await file.text());
    const pass = $("pp-pass").value || passphrase;
    profile = await decryptProfile(blob, pass);
    passphrase = pass;
    $("pp-pass").value = "";
    $("pp-msg").textContent = "Imported.";
    await persist();
  } catch (e) {
    $("pp-msg").textContent = "Import failed: " + e.message;
  }
}

async function deleteAll() {
  if (!confirm("Delete your Voice Passport from this browser and the server?")) return;
  try { await idb("readwrite", (s) => s.delete("blob")); } catch {}
  await fetch(`/profile/${profileId()}`, { method: "DELETE" });
  try { localStorage.removeItem("unhurried.passport.id"); } catch {}
  lock();
  $("pp-msg").textContent = "Deleted.";
}

// ---- session hooks ---------------------------------------------------------
window.unhurriedSessionExtras = () => {
  if (!profile) return {};
  const s = sessionSettings(profile);
  const extra = $("words").value.split(",").map((w) => w.trim()).filter(Boolean);
  return { ...s, keywords: [...new Set([...s.keywords, ...extra])] };
};

window.addEventListener("unhurried-event", async ({ detail: ev }) => {
  if (!profile) return;
  if (ev.type === "confirm_done" && ev.answer === "change") learnNext = true;
  else if (ev.type === "turn" && learnNext) { learnNext = false; learnWords(profile, ev.clean); await persist(); }
  else if (ev.type === "stopped" && ev.inner_pauses_ms?.length) { addPauses(profile, ev.inner_pauses_ms); await persist(); }
});

$("pp-unlock").onclick = unlock;
$("pp-lock").onclick = lock;
$("pp-export").onclick = exportFile;
$("pp-import").onchange = (e) => e.target.files[0] && importFile(e.target.files[0]);
$("pp-delete").onclick = deleteAll;
$("pp-save-words").onclick = async () => {
  profile.words.added_by_me = $("pp-words").value.split(",").map((w) => w.trim()).filter(Boolean);
  await persist();
};
$("pp-show-cue").onchange = async () => { profile.prefs.show_cue = $("pp-show-cue").checked; await persist(); };
render();
