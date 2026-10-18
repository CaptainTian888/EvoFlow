"use strict";

// Official node-repl-host sets process.title to "zcode-node-repl-mcp".
// That string is the Windows console caption. Keep claiming an EvoFlow title
// because the host assigns its own title after this preload runs.
const TITLE = "evoflow-node-repl";

function claimTitle() {
  try {
    if (process.title !== TITLE) process.title = TITLE;
  } catch {
    /* title is cosmetic */
  }
}

claimTitle();
const timer = setInterval(claimTitle, 200);
if (typeof timer.unref === "function") timer.unref();
