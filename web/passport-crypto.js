// Voice Passport encryption. Runs in the browser (and in Node for tests).
// AES-256-GCM, key from a passphrase with PBKDF2-SHA-256 (600,000 rounds, random salt).
// The stored blob holds only salt + iv + ciphertext; the server cannot read it.
export const ROUNDS = 600000;
const enc = new TextEncoder();
const dec = new TextDecoder();

const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function deriveKey(passphrase, salt, rounds) {
  const base = await crypto.subtle.importKey("raw", enc.encode(passphrase), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: rounds },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
}

export async function encryptProfile(profile, passphrase, rounds = ROUNDS) {
  if (!passphrase) throw new Error("passphrase required");
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(passphrase, salt, rounds);
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, enc.encode(JSON.stringify(profile)));
  return { v: 1, kdf: "PBKDF2-SHA256", rounds, salt: b64(salt), iv: b64(iv), ct: b64(ct) };
}

export async function decryptProfile(blob, passphrase) {
  const key = await deriveKey(passphrase, unb64(blob.salt), blob.rounds || ROUNDS);
  let plain;
  try {
    plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(blob.iv) }, key, unb64(blob.ct));
  } catch {
    throw new Error("wrong passphrase or damaged profile");
  }
  return JSON.parse(dec.decode(plain));
}

export function newProfile() {
  return {
    version: 1,
    timing: { inner_pauses_ms: [], max_wait_ms: 6000 },
    words: { added_by_me: [], learned: [] },
    switches: [],
    prefs: { show_cue: true, confirm: "important_only", word_chips: false, bot_pace: "calm" },
    updated: new Date().toISOString(),
  };
}

// Same rule as server/timing_profile.py: p90 of inner pauses + 1 s, in [2 s, 6 s].
export function maxWait(pauses) {
  if (!pauses.length) return 6000;
  const xs = [...pauses].sort((a, b) => a - b);
  const k = (xs.length - 1) * 0.9, lo = Math.floor(k), hi = Math.min(lo + 1, xs.length - 1);
  const p90 = xs[lo] + (xs[hi] - xs[lo]) * (k - lo);
  return Math.round(Math.max(2000, Math.min(6000, p90 + 1000)));
}

export function addPauses(profile, pauses) {
  const all = [...profile.timing.inner_pauses_ms, ...pauses.filter((p) => p > 0)].slice(-200);
  profile.timing = { inner_pauses_ms: all, max_wait_ms: maxWait(all) };
  profile.updated = new Date().toISOString();
  return profile;
}

const STOP = new Set(["the", "and", "for", "with", "that", "this", "please", "want", "would",
  "like", "table", "book", "booking", "have", "about", "from", "your", "what", "when"]);

export function learnWords(profile, text) {
  for (const raw of (text.match(/[A-Za-z][A-Za-z']{3,}/g) || [])) {
    const word = raw.toLowerCase();
    if (STOP.has(word)) continue;
    const hit = profile.words.learned.find((w) => w.word === word);
    if (hit) hit.seen += 1; else profile.words.learned.push({ word, seen: 1 });
  }
  profile.updated = new Date().toISOString();
  return profile;
}

// What a session needs from the profile. Nothing else leaves the browser.
export function sessionSettings(profile) {
  const learned = profile.words.learned.filter((w) => w.seen >= 2).map((w) => w.word);
  return {
    max_wait_ms: profile.timing.max_wait_ms,
    keywords: [...new Set([...profile.words.added_by_me, ...learned])].slice(0, 80),
    switches: profile.switches.filter((s) => s.approved),
    prefs: profile.prefs,
  };
}
