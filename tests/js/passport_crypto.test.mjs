// Run: node tests/js/passport_crypto.test.mjs
import assert from "node:assert/strict";
import {
  addPauses, decryptProfile, encryptProfile, learnWords, maxWait, newProfile, sessionSettings,
} from "../../web/passport-crypto.js";

const FAST = 1000; // fewer rounds to keep the test quick; the app uses 600,000

const p = newProfile();
p.words.added_by_me = ["Binula", "Matara"];
const blob = await encryptProfile(p, "correct horse battery", FAST);
assert.deepEqual(Object.keys(blob).sort(), ["ct", "iv", "kdf", "rounds", "salt", "v"]);
assert.ok(!JSON.stringify(blob).includes("Binula"), "ciphertext must not contain plain text");
assert.deepEqual(await decryptProfile(blob, "correct horse battery"), p);
await assert.rejects(decryptProfile(blob, "wrong passphrase"), /wrong passphrase/);

const again = await encryptProfile(p, "correct horse battery", FAST);
assert.notEqual(again.salt, blob.salt);
assert.notEqual(again.iv, blob.iv);

const real = await encryptProfile(p, "x".repeat(8));
assert.equal(real.rounds, 600000);

assert.equal(maxWait([]), 6000);
assert.equal(maxWait([420, 1300, 2600, 900, 3100]), 3900);
addPauses(p, [0, 1500]);
assert.deepEqual(p.timing.inner_pauses_ms, [1500]);

learnWords(p, "the Weligama branch please");
learnWords(p, "Weligama");
assert.deepEqual(p.words.learned.find((w) => w.word === "weligama"), { word: "weligama", seen: 2 });
p.switches.push({ said: "the day after Monday", means: "Tuesday", approved: true },
                { said: "x", means: "y", approved: false });
const s = sessionSettings(p);
assert.deepEqual(Object.keys(s).sort(), ["keywords", "max_wait_ms", "prefs", "switches"]);
assert.ok(s.keywords.includes("weligama") && !s.keywords.includes("branch"));
assert.equal(s.switches.length, 1);
console.log("passport crypto tests passed");

import { applyProposal } from "../../web/passport-crypto.js";
const q = newProfile();
applyProposal(q, { tool: "adjust_max_wait", args: { new_ms: 9000 } });
assert.equal(sessionSettings(q).max_wait_ms, 6000);
applyProposal(q, { tool: "add_listen_word", args: { word: "Binula" } });
applyProposal(q, { tool: "set_pref", args: { name: "show_cue", value: false } });
assert.deepEqual(q.words.added_by_me, ["Binula"]);
assert.equal(q.prefs.show_cue, false);
addPauses(q, [3000]);
assert.equal(sessionSettings(q).max_wait_ms, 6000, "manual setting survives new pauses");
console.log("learner apply tests passed");
