// Demo mode (?demo=1): a feature label bar for the video, bigger text, no debug details.
// Pages call window.demoLabel("Feature · Meta model · detail") as things happen.
const on = new URLSearchParams(location.search).get("demo") === "1";

export function demoLabel(text) {
  if (!on) return;
  const el = document.getElementById("demo-label");
  if (el && text) el.textContent = text;
}
window.demoLabel = demoLabel;

if (on) {
  document.body.classList.add("demo");
  const style = document.createElement("style");
  style.textContent = `
    body.demo { font-size: 19px; padding-top: 58px; }
    body.demo .foot, body.demo .debug, body.demo #pp-msg { display: none !important; }
    .demo-bar { position: fixed; top: 0; left: 0; right: 0; z-index: 50; display: flex; align-items: center;
      gap: 14px; padding: 12px 24px; background: var(--ink, #1e1b16); color: var(--paper, #f4efe6);
      font: 600 19px/1.3 var(--sans, system-ui); box-shadow: 0 6px 20px -12px rgba(0,0,0,.6); }
    .demo-bar #demo-label { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .demo-live { font: 700 12px/1 var(--sans, system-ui); letter-spacing: .14em; text-transform: uppercase;
      background: var(--clay, #b8532c); color: #fff; padding: 7px 10px; border-radius: 999px; }
    .demo-live.recorded { background: var(--sage, #4f6e4b); }`;
  document.head.appendChild(style);
  const bar = document.createElement("div");
  bar.className = "demo-bar";
  bar.setAttribute("role", "status");
  const live = document.body.dataset.demoBadge || "Live, not edited";
  bar.innerHTML = `<span id="demo-label"></span><span class="demo-live"></span>`;
  bar.querySelector(".demo-live").textContent = live;
  if (live !== "Live, not edited") bar.querySelector(".demo-live").classList.add("recorded");
  bar.querySelector("#demo-label").textContent = document.body.dataset.demoStart || "Unhurried";
  document.body.prepend(bar);
  // keep links inside the demo
  for (const a of document.querySelectorAll("a[href^='/web/'], a[href^='voice'], a[href^='studio']")) {
    const u = new URL(a.href, location.href);
    u.searchParams.set("demo", "1");
    a.href = u.pathname + u.search;
  }
}
