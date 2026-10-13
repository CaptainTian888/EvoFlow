---
name: agent-browser
description: Interactive browser automation via the `agent-browser` CLI (single tool, multi-action — open/snapshot/click/fill/press/scroll/screenshot/back/close). Drives a real Chromium the user can see. The previous EvoPanel-embedded WebView2 ``browser`` tool was unregistered; use this skill instead.
---

# Agent Browser

Interactive browser control via the **`agent-browser`** CLI (a real Chromium driven over
CDP). The user runs the CLI on their own desktop, so they see the same browser window
the agent drives.

The legacy EvoPanel-embedded WebView2 ``browser`` tool was **unregistered** — the LLM
tool surface no longer exposes `browser`. Use this skill (the CLI) instead.

## Loading the tool (deferred, agent mode only)

1. Activate agent mode: `scenario(action='activate', scenario_key='agent')`
2. Reach the CLI through the **terminal** tool (or `evoflow` admin) — see "How the agent runs it" below.

## How the agent runs it

The agent does **not** call `agent-browser` directly. It uses the standard
**`terminal`** tool (or `bash`):

```
terminal(command='agent-browser open https://example.com', timeout_ms=35000)
terminal(command='agent-browser snapshot -c')
terminal(command='agent-browser click @e2')
```

`agent-browser --session <name>` keeps state per thread (one session per chat).
Always pass `--session` so multiple chats don't share a browser.

## Core workflow (snapshot + ref)

```
terminal(command='agent-browser --session <name> open https://example.com')
terminal(command='agent-browser --session <name> snapshot -c')   # refs e1, e2, …
terminal(command='agent-browser --session <name> click @e2')
terminal(command='agent-browser --session <name> fill @e3 "search text"')
terminal(command='agent-browser --session <name> press Enter')
terminal(command='agent-browser --session <name> snapshot -c')   # page changed → refs stale
terminal(command='agent-browser --session <name> screenshot /tmp/shot.png')  # optional pixels
terminal(command='agent-browser --session <name> close')
```

Actions: `open`, `snapshot`, `click`, `fill`, `press`, `scroll`, `screenshot`, `back`, `close`.

Add `--json` to any subcommand for structured output (easier to parse):

```
agent-browser --session <name> --json open https://example.com
```

## Session naming

Use one **agent-browser session per chat thread** so concurrent chats don't share a
browser. Pick a stable session name per thread (e.g. the chat UUID or
`evoflow-<thread-id>`).

## Discipline (do not skip)

1. **Always `snapshot` before choosing refs.** Refs (`e1`, `e2`, …) come from the
   latest snapshot and are invalidated by navigation and by clicks that change the page.
2. **Re-snapshot after navigation or state-changing clicks.** A stale ref returns
   `ref_not_found` — that is the signal to take a fresh snapshot, not to retry.
3. **Never guess CSS selectors, labels, or placeholders.** Build clicks and fills only
   from facts in the latest snapshot. If a locator target is ambiguous, take a fresh
   snapshot and narrow it instead of guessing.
4. **One state-changing action per observation.** After acting, judge success by the
   expected effect (URL, page state, next snapshot) — not by absence of errors.
5. **`snapshot` is how you read the page.** It returns URL, title, interactive elements
   with refs, and a compact content outline. Use `screenshot` only when pixels matter.

## When to screenshot

| Need | Use |
|------|-----|
| Click, fill, read structure | `snapshot` |
| CAPTCHA, dense layout, visual-only UI | `screenshot` (then read the file with `read_file` or `view_image`) |
| Deliver a picture to the user | `screenshot` and reference the saved PNG path in the chat reply |

## Prerequisites (one-time, on the user's machine)

Chromium must be installed locally. If `agent-browser open` returns an error like
"browser engine not installed", tell the user to run:

```
agent-browser install          # ~400MB, downloads to ~/.agent-browser/browsers
```

If `agent-browser` is not on PATH, use the bundled CLI:

```
tools/agent-browser/node_modules/.bin/agent-browser install
```

Do **not** invent alternate browsers or fall back to a generic Chromium.

## Login state (real desktop browser)

`agent-browser` drives the browser the user actually uses, so **logins persist
naturally** — whatever the user has signed into (content platforms, admin panels)
is already available to the agent. Before any scraping or account-bound task:

1. Verify login state from the snapshot: look for the user avatar / personal-center
   link. A visible「登录」/「Sign in」button means logged out.
2. If logged out, stop and tell the user to sign in first — do **not** scrape a
   logged-out page: sites serve truncated data and pop login modals mid-flow.
3. A login modal appearing mid-task (e.g.「扫码登录」) means the session expired or
   the site gated deeper pages. Stop, hand the modal to the user, resume after
   they sign in.

## Anti-bot etiquette (CAPTCHA & rate limits)

- CAPTCHA/slider overlay (e.g. `second_verify` masks): **the human solves it**.
  Screenshot it, tell the user, wait 1-2 minutes, re-snapshot. Never brute-retry —
  retrying escalates risk control.
- Frequency: for batch scraping keep it to a handful of sites/accounts per day,
  pause between rounds, and stop for the day once risk control appears.
- Account hygiene: run automation on a secondary account; risk control is tied to
  the logged-in account, keep the primary for manual use.

## When to write a script instead

`agent-browser` is for interactive and exploratory tasks. A flow that runs
unchanged every day (scheduled collection, monitoring) should be a **script**
driven by `terminal`/`process_start` (Playwright-core over CDP, or plain HTTP),
with the agent only calling it and interpreting results. Same browser, same
login, but no per-step model round-trips. Domain example: a
`douyin-blogger-analysis` style skill — profile → scroll → parse → POST to a
local store.

## Tips

- `fill` types through the keyboard path (focus + insertText), so React/Vue controlled
  inputs work as if the user typed.
- `press` accepts `Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, arrow keys,
  `Home`/`End`/`PageUp`/`PageDown`, single characters, and modifiers (e.g. `Ctrl+a`).
- `scroll` takes `direction` (`down`/`up`/`left`/`right`) and `amount` in CSS pixels.
- `back` walks the page history; `close` ends the session.
- The user can interact with the same browser window. Treat unexpected page changes
  as user actions: re-snapshot before continuing.
