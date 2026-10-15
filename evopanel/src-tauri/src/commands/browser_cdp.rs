//! In-process CDP bridge for the embedded browser webview (Windows / WebView2).
//!
//! `Webview::with_webview` yields the raw `ICoreWebView2Controller`, and
//! `ICoreWebView2::CallDevToolsProtocolMethod` is the in-process equivalent of
//! Electron's `webContents.debugger.attach()` — no TCP port, no WS handshake, and
//! no debug port leaking onto the main webview.
//!
//! Playwright's `connect_over_cdp` insists on a real WebSocket endpoint, so
//! `browser_embed.rs` runs a loopback broker: Python connects exactly as it would
//! to Chrome's own debug port while every frame is serviced by the COM channel
//! instead.
//!
//! # Events are per-name receivers
//!
//! `ICoreWebView2::GetDevToolsProtocolEventReceiver(eventName)` hands back a
//! receiver for one specific protocol event, and its callback carries only that
//! event's `ParameterObjectAsJson`. So the bridge registers a receiver per event
//! name up front and never has to guess which event a payload belongs to.
//!
//! Threading: start `CallDevToolsProtocolMethod` inside `with_webview`, then
//! return so the app message pump can deliver the COM completion. Waiting for
//! the result with a nested `wait_for_async_operation` inside `with_webview`
//! deadlocks on child embed windows. Event receivers must still be created on
//! the webview UI thread via `with_webview`.

#![cfg(target_os = "windows")]

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, WebviewWindow};
use webview2_com::{
    CallDevToolsProtocolMethodCompletedHandler, CoTaskMemPWSTR, CompletedClosure,
    DevToolsProtocolEventReceivedEventHandler,
};
use webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2;
// The WebView2 COM bindings are generated against `windows-core`; the
// `Interface`/`Param` traits they need come from that crate rather than
// `windows`, even though both are version 0.61.
use windows_core::{PCWSTR, PWSTR};

/// Label derivation shared with `browser_embed`.
use crate::browser_embed::webview_label_for_thread;

/// Serialize all in-process CDP calls. Concurrent `with_webview` dispatches on
/// the same HWND race the COM completion callbacks and surface as timeouts.
fn cdp_global_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

/// COM pointer is !Send; we only invoke it on the UI/main thread.
struct SendableCoreWebView(ICoreWebView2);
// SAFETY: all ExecuteScript / store access happens on the Tauri main thread.
unsafe impl Send for SendableCoreWebView {}
unsafe impl Sync for SendableCoreWebView {}

/// Stashed `ICoreWebView2` captured once at create (with_webview + pump). Later
/// evaluate calls ExecuteScript on this pointer from the main thread — no
/// another with_webview hop (child embeds often never dispatch those).
fn core_webview_store() -> &'static Mutex<HashMap<String, SendableCoreWebView>> {
    static STORE: OnceLock<Mutex<HashMap<String, SendableCoreWebView>>> = OnceLock::new();
    STORE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Per-embed `--remote-debugging-port` so Runtime.evaluate can use real CDP WS
/// when with_webview / ExecuteScript never dispatch on the HWND.
fn embed_debug_ports() -> &'static Mutex<HashMap<String, u16>> {
    static PORTS: OnceLock<Mutex<HashMap<String, u16>>> = OnceLock::new();
    PORTS.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Bind an ephemeral local port, release it, and return the number for
/// `--remote-debugging-port=` (WebView2 will re-bind the same port).
pub fn allocate_embed_debug_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr().map(|a| a.port()))
        .unwrap_or(0)
}

pub fn register_embed_debug_port(label: &str, port: u16) {
    if port == 0 {
        return;
    }
    if let Ok(mut g) = embed_debug_ports().lock() {
        g.insert(label.to_string(), port);
    }
    crate::commands::browser_cdp_server::log_line(&format!(
        "[browser-cdp] embed debug port label={label} port={port}"
    ));
}

fn embed_debug_port(label: &str) -> Option<u16> {
    embed_debug_ports()
        .lock()
        .ok()
        .and_then(|g| g.get(label).copied())
}

/// Capture CoreWebView2 right after embed create. Must pump on the main thread.
pub fn capture_core_webview2(app: &AppHandle, window: &WebviewWindow, label: &str) {
    let (tx, rx) = std::sync::mpsc::sync_channel::<bool>(1);
    let win = window.clone();
    let label_owned = label.to_string();
    if app
        .run_on_main_thread(move || {
            let entered = Arc::new(AtomicBool::new(false));
            let flag = entered.clone();
            let label_cb = label_owned.clone();
            if let Err(e) = win.with_webview(move |platform| {
                flag.store(true, Ordering::SeqCst);
                match unsafe { platform.controller().CoreWebView2() } {
                    Ok(wv) => {
                        if let Ok(mut g) = core_webview_store().lock() {
                            g.insert(label_cb.clone(), SendableCoreWebView(wv));
                        }
                        crate::commands::browser_cdp_server::log_line(&format!(
                            "[browser-cdp] captured CoreWebView2 label={label_cb}"
                        ));
                    }
                    Err(e) => {
                        crate::commands::browser_cdp_server::log_line(&format!(
                            "[browser-cdp] CoreWebView2 capture failed label={label_cb}: {e}"
                        ));
                    }
                }
            }) {
                crate::commands::browser_cdp_server::log_line(&format!(
                    "[browser-cdp] capture with_webview enqueue failed: {e}"
                ));
                let _ = tx.send(false);
                return;
            }
            let deadline = std::time::Instant::now() + std::time::Duration::from_millis(1500);
            while std::time::Instant::now() < deadline {
                if entered.load(Ordering::SeqCst) {
                    let _ = tx.send(true);
                    return;
                }
                pump_win32_messages_once();
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
            let _ = tx.send(false);
        })
        .is_err()
    {
        return;
    }
    let ok = rx.recv_timeout(std::time::Duration::from_secs(3)).unwrap_or(false);
    if !ok {
        crate::commands::browser_cdp_server::log_line(&format!(
            "[browser-cdp] CoreWebView2 capture timed out label={label}"
        ));
    }
}

/// label -> sink for unsolicited protocol events.
type EventSink = Arc<dyn Fn(&str) + Send + Sync>;

/// Protocol events the panel forwards. WebView2 only delivers events for which a
/// receiver has been created, so this list is the bridge's event surface: it
/// covers the domains Playwright enables for `connect_over_cdp` plus the
/// screencast and lifecycle events the panel itself depends on.
const FORWARDED_EVENTS: &[&str] = &[
    // Page — navigation and lifecycle
    "Page.loadEventFired",
    "Page.domContentEventFired",
    "Page.frameNavigated",
    "Page.frameAttached",
    "Page.frameDetached",
    "Page.frameStartedLoading",
    "Page.frameStoppedLoading",
    "Page.frameStartedNavigating",
    "Page.navigatedWithinDocument",
    "Page.lifecycleEvent",
    "Page.javascriptDialogOpening",
    "Page.javascriptDialogClosed",
    "Page.windowOpen",
    "Page.fileChooserOpened",
    "Page.interstitialShown",
    "Page.interstitialHidden",
    "Page.downloadWillBegin",
    "Page.downloadProgress",
    // Page — screencast, used by the panel's own preview surface
    "Page.screencastFrame",
    "Page.screencastVisibilityChanged",
    // Runtime
    "Runtime.consoleAPICalled",
    "Runtime.exceptionThrown",
    "Runtime.exceptionRevoked",
    "Runtime.executionContextCreated",
    "Runtime.executionContextDestroyed",
    "Runtime.executionContextsCleared",
    "Runtime.bindingCalled",
    "Runtime.instrumentationScriptAdded",
    "Runtime.instrumentationScriptRemoved",
    // Network
    "Network.requestWillBeSent",
    "Network.requestWillBeSentExtraInfo",
    "Network.responseReceived",
    "Network.responseReceivedExtraInfo",
    "Network.loadingFinished",
    "Network.loadingFailed",
    "Network.requestServedFromCache",
    "Network.webSocketCreated",
    "Network.webSocketWillSendHandshakeRequest",
    "Network.webSocketHandshakeResponseReceived",
    "Network.webSocketFrameSent",
    "Network.webSocketFrameReceived",
    "Network.webSocketFrameError",
    "Network.webSocketClosed",
    "Network.eventSourceMessageReceived",
    "Network.resourceChangedPriority",
    "Network.signingRequested",
    "Network.trustTokenOperationDone",
    "Network.policyUpdated",
    // Log / DOM / Inspector
    "Log.entryAdded",
    "DOM.attributeModified",
    "DOM.attributeRemoved",
    "DOM.characterDataModified",
    "DOM.childNodeCountUpdated",
    "DOM.childNodeInserted",
    "DOM.childNodeRemoved",
    "DOM.distributedNodesUpdated",
    "DOM.documentUpdated",
    "DOM.setChildNodes",
    "DOM.shadowRootPopped",
    "DOM.shadowRootPushed",
    "DOM.topLayerElementsUpdated",
    "Inspector.targetCrashed",
    "Inspector.targetDestroyed",
    "Inspector.detached",
    "Inspector.targetInfoChanged",
];

#[derive(Default)]
pub struct CdpBrokerState {
    sinks: Mutex<HashMap<String, EventSink>>,
}

impl CdpBrokerState {
    pub fn set_sink(&self, label: &str, sink: EventSink) {
        if let Ok(mut map) = self.sinks.lock() {
            map.insert(label.to_string(), sink);
        }
    }

    pub fn clear(&self, label: &str) {
        if let Ok(mut map) = self.sinks.lock() {
            map.remove(label);
        }
    }

    /// Forward one already-named protocol event to the attached client.
    fn emit_event(&self, label: &str, method: &str, params_json: &str) {
        let sink = match self.sinks.lock() {
            Ok(map) => map.get(label).cloned(),
            Err(_) => None,
        };
        let Some(sink) = sink else {
            eprintln!("[browser-cdp] event {method} dropped: no sink for {label}");
            return;
        };
        let params: Value = serde_json::from_str(params_json).unwrap_or_else(|_| json!({}));
        eprintln!("[browser-cdp] event {method} -> sink");
        sink(&json!({ "method": method, "params": params }).to_string());
    }
}

/// Invoke one CDP method against the webview's COM channel and return the raw
/// JSON result string.
///
/// Hot path: `Page.navigate` / `Runtime.evaluate` use native WebView2 APIs
/// (`Navigate` / `ExecuteScript`) that already work in the embed host. The
/// generic `CallDevToolsProtocolMethod` path is kept for everything else.
pub fn call_cdp(
    app: &AppHandle,
    label: &str,
    method: &str,
    params_json: &str,
) -> Result<String, String> {
    let _lock = cdp_global_lock()
        .lock()
        .map_err(|_| "CDP global lock poisoned".to_string())?;
    call_cdp_locked(app, label, method, params_json)
}

/// Same as [`call_cdp`] but assumes the caller already holds [`cdp_global_lock`].
fn call_cdp_locked(
    app: &AppHandle,
    label: &str,
    method: &str,
    params_json: &str,
) -> Result<String, String> {
    let window: WebviewWindow = app
        .get_webview_window(label)
        .ok_or_else(|| format!("embedded webview '{label}' not found"))?;

    let trace_path = crate::commands::evoflow_dir().join("browser-cdp-trace.log");
    eprintln!("[browser-cdp] TRACE_FILE={}", trace_path.display());
    eprintln!("[browser-cdp] call {method} params={}", truncate(params_json, 400));

    // Native fast-paths — these are the browser-use bootstrap commands and must
    // not depend on CallDevToolsProtocolMethod (historically hung on child HWND).
    if method == "Page.navigate" {
        let url = serde_json::from_str::<Value>(params_json)
            .ok()
            .and_then(|v| v.get("url").and_then(|u| u.as_str()).map(str::to_string))
            .unwrap_or_else(|| "about:blank".to_string());
        let outcome = native_navigate(app, &window, label, &url);
        write_cdp_trace(&trace_path, label, method, &outcome);
        return outcome;
    }
    if method == "Runtime.evaluate" {
        let expression = serde_json::from_str::<Value>(params_json)
            .ok()
            .and_then(|v| v.get("expression").and_then(|u| u.as_str()).map(str::to_string))
            .unwrap_or_default();
        let outcome = native_evaluate(app, &window, label, &expression);
        write_cdp_trace(&trace_path, label, method, &outcome);
        return outcome;
    }

    // Generic CDP: same main-thread + PeekMessage pump as ExecuteScript.
    eprintln!("[browser-cdp] about to call with_webview for {method} on {label}...");
    let outcome = call_cdp_on_main_thread(app, &window, method, params_json);
    write_cdp_trace(&trace_path, label, method, &outcome);
    outcome
}

fn call_cdp_on_main_thread(
    app: &AppHandle,
    window: &WebviewWindow,
    method: &str,
    params_json: &str,
) -> Result<String, String> {
    let (tx, rx) = std::sync::mpsc::channel::<Result<String, String>>();
    let window = window.clone();
    let method_owned = method.to_string();
    let params_owned = params_json.to_string();
    app.run_on_main_thread(move || {
        let cell: Arc<Mutex<Option<Result<String, String>>>> = Arc::new(Mutex::new(None));
        let cell_inner = cell.clone();
        let entered = Arc::new(AtomicBool::new(false));
        let entered_flag = entered.clone();
        let method_for_closure = method_owned.clone();
        if let Err(e) = window.with_webview(move |platform| {
            entered_flag.store(true, Ordering::SeqCst);
            let webview = match core_webview2(&platform.controller()) {
                Ok(w) => w,
                Err(e) => {
                    eprintln!("[browser-cdp] core_webview2 failed: {e}");
                    if let Ok(mut guard) = cell_inner.lock() {
                        *guard = Some(Err(e));
                    }
                    return;
                }
            };
            let cell_cb = cell_inner.clone();
            let method_name_for_completed = method_for_closure.clone();
            let completed: CompletedClosure<windows_core::HRESULT, PCWSTR> =
                Box::new(move |error_code, raw_json| {
                    let outcome = match &error_code {
                        Ok(()) => Ok(raw_json),
                        Err(err) => Err(format!("{method_name_for_completed} failed: {err}")),
                    };
                    if let Ok(mut guard) = cell_cb.lock() {
                        *guard = Some(outcome);
                    }
                    error_code
                });
            let method_pw = CoTaskMemPWSTR::from(method_for_closure.as_str());
            let params_pw = CoTaskMemPWSTR::from(params_owned.as_str());
            let start = unsafe {
                webview.CallDevToolsProtocolMethod(
                    *method_pw.as_ref().as_pcwstr(),
                    *params_pw.as_ref().as_pcwstr(),
                    &CallDevToolsProtocolMethodCompletedHandler::create(completed),
                )
            };
            if let Err(err) = start {
                if let Ok(mut guard) = cell_inner.lock() {
                    *guard = Some(Err(format!(
                        "{method_for_closure} CallDevToolsProtocolMethod failed: {err}"
                    )));
                }
            }
        }) {
            let _ = tx.send(Err(format!("with_webview enqueue failed: {e}")));
            return;
        }

        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(25);
        loop {
            if let Some(outcome) = cell.lock().ok().and_then(|mut g| g.take()) {
                let _ = tx.send(outcome);
                return;
            }
            if std::time::Instant::now() >= deadline {
                let entered_ok = entered.load(Ordering::SeqCst);
                let detail = if entered_ok {
                    format!(
                        "{method_owned} timed out waiting for CDP callback \
                         (with_webview ran; COM completion never arrived)"
                    )
                } else {
                    format!(
                        "{method_owned} timed out waiting for the webview UI thread to dispatch the closure"
                    )
                };
                eprintln!("[browser-cdp] {detail}");
                let _ = tx.send(Err(detail));
                return;
            }
            pump_win32_messages_once();
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
    })
    .map_err(|e| format!("run_on_main_thread failed: {e}"))?;

    rx.recv_timeout(std::time::Duration::from_secs(30))
        .map_err(|e| format!("CDP main-thread wait failed: {e}"))?
}

fn write_cdp_trace(
    trace_path: &std::path::Path,
    label: &str,
    method: &str,
    outcome: &Result<String, String>,
) {
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(trace_path)
    {
        use std::io::Write as _;
        let secs = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(
            f,
            "ts:{secs} tid:{label} method:{method} DONE outcome={:?}",
            outcome
        );
        let _ = f.flush();
    }
}

/// Navigate via Tauri `WebviewWindow::navigate` — posts to the correct webview
/// thread without nesting `wait_with_pump` (which hangs on agent-created HWNDs).
fn native_navigate(
    app: &AppHandle,
    window: &WebviewWindow,
    label: &str,
    url: &str,
) -> Result<String, String> {
    let target = url.trim();
    if target.is_empty() {
        return Err("Page.navigate requires url".into());
    }
    eprintln!("[browser-cdp] native_navigate label={label} url={target}");
    let parsed = target
        .parse::<url::Url>()
        .or_else(|_| format!("https://{target}").parse::<url::Url>())
        .map_err(|e| format!("invalid navigate url {target:?}: {e}"))?;
    let href = parsed.to_string();
    window
        .navigate(parsed)
        .map_err(|e| format!("window.navigate failed: {e}"))?;
    if let Some(bridge) = app.try_state::<crate::commands::browser_embed_bridge::EmbedBridge>() {
        bridge.note_url(label, &href);
    }
    // CDP-shaped success payload so Python's browser_engine stays unchanged.
    Ok(json!({ "frameId": "evopanel", "loaderId": "evopanel" }).to_string())
}

/// Evaluate: cached URL → stashed CoreWebView2 ExecuteScript → HTTP guest poll.
fn native_evaluate(
    app: &AppHandle,
    window: &WebviewWindow,
    label: &str,
    expression: &str,
) -> Result<String, String> {
    eprintln!(
        "[browser-cdp] native_evaluate label={label} expr={}",
        truncate(expression, 120)
    );
    let expr = expression.trim();
    let bridge = app
        .try_state::<crate::commands::browser_embed_bridge::EmbedBridge>()
        .ok_or_else(|| "embed bridge state missing".to_string())?;

    // Fast path: never call window.url() — it hangs on child embeds.
    if matches!(
        expr,
        "location.href"
            | "window.location.href"
            | "document.location.href"
            | "location.href.toString()"
            | "String(location.href)"
    ) {
        if let Some(url) = bridge.cached_url(label) {
            crate::commands::browser_cdp_server::log_line(
                "[browser-cdp] native_evaluate via cached url ok",
            );
            return Ok(cdp_evaluate_result(Value::String(url)));
        }
    }

    // Primary: real Chromium CDP on the embed's remote-debugging-port.
    if let Some(port) = embed_debug_port(label) {
        match evaluate_via_remote_cdp(port, expr) {
            Ok(value) => {
                crate::commands::browser_cdp_server::log_line(
                    "[browser-cdp] native_evaluate via remote CDP ok",
                );
                return Ok(cdp_evaluate_result(value));
            }
            Err(e) => {
                crate::commands::browser_cdp_server::log_line(&format!(
                    "[browser-cdp] remote CDP miss ({e}); trying COM stash"
                ));
            }
        }
    }

    // Secondary: stashed CoreWebView2 ExecuteScript (works if capture succeeded).
    let has_stash = core_webview_store()
        .lock()
        .ok()
        .map(|g| g.contains_key(label))
        .unwrap_or(false);
    if !has_stash {
        capture_core_webview2(app, window, label);
    }
    match execute_script_on_stashed(app, label, expr) {
        Ok(value) => {
            crate::commands::browser_cdp_server::log_line(
                "[browser-cdp] native_evaluate via stashed CoreWebView2 ok",
            );
            return Ok(cdp_evaluate_result(value));
        }
        Err(e) => {
            crate::commands::browser_cdp_server::log_line(&format!(
                "[browser-cdp] stashed ExecuteScript miss ({e}); trying HTTP poll"
            ));
        }
    }

    match bridge.request_eval_http(label, expr) {
        Ok(value) => {
            crate::commands::browser_cdp_server::log_line(
                "[browser-cdp] native_evaluate via HTTP guest poll ok",
            );
            Ok(cdp_evaluate_result(value))
        }
        Err(e) => {
            crate::commands::browser_cdp_server::log_line(&format!(
                "[browser-cdp] HTTP guest poll miss ({e})"
            ));
            Err(e)
        }
    }
}

/// `Runtime.evaluate` over the embed WebView2 `--remote-debugging-port` WS.
fn evaluate_via_remote_cdp(port: u16, expression: &str) -> Result<Value, String> {
    use std::io::{Read as _, Write as _};
    use std::net::TcpStream;
    use std::time::Duration;

    let list_url = format!("http://127.0.0.1:{port}/json/list");
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    let mut ws_url = String::new();
    while std::time::Instant::now() < deadline {
        match ureq_get_json(&list_url) {
            Ok(list) => {
                if let Some(url) = list
                    .as_array()
                    .and_then(|arr| {
                        arr.iter().find_map(|t| {
                            t.get("webSocketDebuggerUrl")
                                .and_then(|u| u.as_str())
                                .map(str::to_string)
                        })
                    })
                {
                    ws_url = url;
                    break;
                }
            }
            Err(_) => {}
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    if ws_url.is_empty() {
        return Err(format!("no webSocketDebuggerUrl on debug port {port}"));
    }

    // ws://127.0.0.1:PORT/devtools/page/ID
    let httpish = ws_url.replacen("ws://", "http://", 1);
    let parsed = url::Url::parse(&httpish).map_err(|e| format!("bad ws url {ws_url}: {e}"))?;
    let ws_host = parsed.host_str().unwrap_or("127.0.0.1");
    let ws_port = parsed.port().unwrap_or(port);
    let ws_path = if parsed.query().is_some() {
        format!("{}?{}", parsed.path(), parsed.query().unwrap_or(""))
    } else {
        parsed.path().to_string()
    };
    let mut stream = TcpStream::connect(format!("{ws_host}:{ws_port}"))
        .map_err(|e| format!("cdp ws connect failed: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .ok();
    stream
        .set_write_timeout(Some(Duration::from_secs(5)))
        .ok();

    let key = {
        let mut b = [0u8; 16];
        getrandom_simple(&mut b);
        base64::Engine::encode(&base64::engine::general_purpose::STANDARD, b)
    };
    let req = format!(
        "GET {ws_path} HTTP/1.1\r\nHost: {ws_host}:{ws_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    );
    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("cdp ws handshake write: {e}"))?;
    let mut buf = [0u8; 4096];
    let n = stream
        .read(&mut buf)
        .map_err(|e| format!("cdp ws handshake read: {e}"))?;
    let resp = String::from_utf8_lossy(&buf[..n]);
    if !resp.contains("101") {
        return Err(format!("cdp ws handshake rejected: {}", truncate(&resp, 200)));
    }

    let id = 1u64;
    let payload = json!({
        "id": id,
        "method": "Runtime.evaluate",
        "params": { "expression": expression, "returnByValue": true }
    })
    .to_string();
    write_ws_text(&mut stream, &payload)?;

    let raw = read_ws_text(&mut stream)?;
    let msg: Value = serde_json::from_str(&raw).map_err(|e| format!("cdp ws json: {e}"))?;
    if let Some(err) = msg.get("error") {
        return Err(format!("cdp evaluate error: {err}"));
    }
    let result = msg
        .pointer("/result/result")
        .cloned()
        .ok_or_else(|| format!("cdp evaluate missing result: {}", truncate(&raw, 200)))?;
    // CDP shape: { type, value, ... } — unwrap value when present.
    if let Some(v) = result.get("value") {
        return Ok(v.clone());
    }
    if result.get("type").and_then(|t| t.as_str()) == Some("undefined") {
        return Ok(Value::Null);
    }
    Ok(result)
}

fn ureq_get_json(url: &str) -> Result<Value, String> {
    // Tiny blocking GET via std — avoid pulling another HTTP client into the hot path.
    use std::io::{Read as _, Write as _};
    let url = url::Url::parse(url).map_err(|e| e.to_string())?;
    let host = url.host_str().unwrap_or("127.0.0.1");
    let port = url.port_or_known_default().unwrap_or(80);
    let path = if url.query().is_some() {
        format!("{}?{}", url.path(), url.query().unwrap_or(""))
    } else {
        url.path().to_string()
    };
    let mut stream = std::net::TcpStream::connect(format!("{host}:{port}"))
        .map_err(|e| e.to_string())?;
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(2)))
        .ok();
    let req = format!("GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
    stream.write_all(req.as_bytes()).map_err(|e| e.to_string())?;
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).map_err(|e| e.to_string())?;
    let text = String::from_utf8_lossy(&buf);
    let body = text
        .split_once("\r\n\r\n")
        .or_else(|| text.split_once("\n\n"))
        .map(|(_, b)| b)
        .unwrap_or("");
    serde_json::from_str(body.trim()).map_err(|e| format!("json list parse: {e}"))
}

fn getrandom_simple(out: &mut [u8]) {
    use std::time::{SystemTime, UNIX_EPOCH};
    let mut x = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0x12345678);
    for b in out.iter_mut() {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        *b = (x & 0xff) as u8;
    }
}

fn write_ws_text(stream: &mut std::net::TcpStream, text: &str) -> Result<(), String> {
    use std::io::Write as _;
    let payload = text.as_bytes();
    let mut frame = Vec::with_capacity(2 + 4 + payload.len());
    frame.push(0x81); // FIN + text
    if payload.len() < 126 {
        frame.push(0x80 | (payload.len() as u8)); // masked
    } else if payload.len() <= 65535 {
        frame.push(0x80 | 126);
        frame.extend_from_slice(&(payload.len() as u16).to_be_bytes());
    } else {
        return Err("cdp ws payload too large".into());
    }
    let mask = [0x11u8, 0x22, 0x33, 0x44];
    frame.extend_from_slice(&mask);
    for (i, b) in payload.iter().enumerate() {
        frame.push(b ^ mask[i % 4]);
    }
    stream
        .write_all(&frame)
        .map_err(|e| format!("cdp ws write: {e}"))
}

fn read_ws_text(stream: &mut std::net::TcpStream) -> Result<String, String> {
    use std::io::Read as _;
    let mut hdr = [0u8; 2];
    stream
        .read_exact(&mut hdr)
        .map_err(|e| format!("cdp ws hdr: {e}"))?;
    let opcode = hdr[0] & 0x0f;
    let mut len = (hdr[1] & 0x7f) as usize;
    let masked = (hdr[1] & 0x80) != 0;
    if len == 126 {
        let mut ext = [0u8; 2];
        stream.read_exact(&mut ext).map_err(|e| e.to_string())?;
        len = u16::from_be_bytes(ext) as usize;
    } else if len == 127 {
        return Err("cdp ws 64-bit length unsupported".into());
    }
    let mut mask = [0u8; 4];
    if masked {
        stream.read_exact(&mut mask).map_err(|e| e.to_string())?;
    }
    let mut payload = vec![0u8; len];
    stream
        .read_exact(&mut payload)
        .map_err(|e| format!("cdp ws payload: {e}"))?;
    if masked {
        for (i, b) in payload.iter_mut().enumerate() {
            *b ^= mask[i % 4];
        }
    }
    if opcode != 0x1 {
        return Err(format!("cdp ws unexpected opcode {opcode}"));
    }
    String::from_utf8(payload).map_err(|e| e.to_string())
}

/// Look up stashed CoreWebView2 on the main thread and ExecuteScript with pump.
fn execute_script_on_stashed(
    app: &AppHandle,
    label: &str,
    expression: &str,
) -> Result<Value, String> {
    use webview2_com::ExecuteScriptCompletedHandler;

    let (tx, rx) = std::sync::mpsc::channel::<Result<String, String>>();
    let label_owned = label.to_string();
    let js = format!(
        "(function(){{try{{return ({expression});}}catch(e){{return {{__evoEvalError:String((e&&e.message)||e)}};}}}})()"
    );
    app.run_on_main_thread(move || {
        let wv = match core_webview_store()
            .lock()
            .ok()
            .and_then(|g| g.get(&label_owned).map(|s| s.0.clone()))
        {
            Some(w) => w,
            None => {
                let _ = tx.send(Err(format!("no stashed CoreWebView2 for {label_owned}")));
                return;
            }
        };
        let cell: Arc<Mutex<Option<Result<String, String>>>> = Arc::new(Mutex::new(None));
        let cell_cb = cell.clone();
        let handler = ExecuteScriptCompletedHandler::create(Box::new(move |error_code, result| {
            let out = match error_code {
                Ok(()) => Ok(result),
                Err(err) => Err(format!("ExecuteScript failed: {err}")),
            };
            if let Ok(mut g) = cell_cb.lock() {
                *g = Some(out);
            }
            Ok(())
        }));
        let hstr = windows::core::HSTRING::from(js.as_str());
        if let Err(e) = unsafe { wv.ExecuteScript(&hstr, &handler) } {
            let _ = tx.send(Err(format!("ExecuteScript COM error: {e}")));
            return;
        }
        std::mem::forget(handler);
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            if let Some(outcome) = cell.lock().ok().and_then(|mut g| g.take()) {
                let _ = tx.send(outcome);
                return;
            }
            if std::time::Instant::now() >= deadline {
                let _ = tx.send(Err("stashed ExecuteScript timed out".into()));
                return;
            }
            pump_win32_messages_once();
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
    })
    .map_err(|e| format!("run_on_main_thread failed: {e}"))?;

    let raw = rx
        .recv_timeout(std::time::Duration::from_secs(8))
        .map_err(|e| format!("stashed ExecuteScript wait failed: {e}"))??;
    let value: Value = serde_json::from_str(&raw).unwrap_or(Value::String(raw));
    if let Some(err) = value.get("__evoEvalError").and_then(|v| v.as_str()) {
        return Err(format!("evaluate threw: {err}"));
    }
    Ok(value)
}

fn cdp_evaluate_result(value: Value) -> String {
    let type_name = match &value {
        Value::Null => "undefined",
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) | Value::Object(_) => "object",
    };
    json!({ "result": { "type": type_name, "value": value } }).to_string()
}

fn native_execute_script_async_slot(window: &WebviewWindow, js: &str) -> Result<String, String> {
    use webview2_com::ExecuteScriptCompletedHandler;

    let slot: Arc<Mutex<Option<Result<String, String>>>> = Arc::new(Mutex::new(None));
    let slot_cb = slot.clone();
    let js_owned = js.to_string();
    window
        .with_webview(move |platform| {
            let controller = platform.controller();
            let webview = match unsafe { controller.CoreWebView2() } {
                Ok(w) => w,
                Err(e) => {
                    if let Ok(mut g) = slot_cb.lock() {
                        *g = Some(Err(format!("CoreWebView2 failed: {e}")));
                    }
                    return;
                }
            };
            let slot_done = slot_cb.clone();
            let handler = ExecuteScriptCompletedHandler::create(Box::new(move |error_code, result| {
                let out = match error_code {
                    Ok(()) => Ok(result),
                    Err(err) => Err(format!("ExecuteScript failed: {err}")),
                };
                if let Ok(mut g) = slot_done.lock() {
                    *g = Some(out);
                }
                Ok(())
            }));
            let hstr = windows::core::HSTRING::from(js_owned.as_str());
            if let Err(e) = unsafe { webview.ExecuteScript(&hstr, &handler) } {
                if let Ok(mut g) = slot_cb.lock() {
                    *g = Some(Err(format!("ExecuteScript COM error: {e}")));
                }
                return;
            }
            // Keep the completed-handler alive until COM invokes it — dropping
            // it when this closure returns cancels the callback (same pattern
            // as subscribe_events forgetting event receivers).
            std::mem::forget(handler);
        })
        .map_err(|e| format!("with_webview failed: {e}"))?;

    // Short budget: gateway polls evaluate every ~3s; a long hold on
    // cdp_global_lock starves Page.navigate.
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(3);
    while std::time::Instant::now() < deadline {
        if let Some(outcome) = slot.lock().ok().and_then(|mut g| g.take()) {
            crate::commands::browser_cdp_server::log_line(
                "[browser-cdp] native_evaluate via async ExecuteScript slot ok",
            );
            return outcome;
        }
        std::thread::sleep(std::time::Duration::from_millis(30));
    }
    Err("ExecuteScript async slot timed out".into())
}

/// Pump the Windows message queue so `with_webview` / COM completions can run
/// while we are blocked inside `run_on_main_thread` (tao's loop is paused).
///
/// Also used by `browser_embed::wait_webview2_ready` / `probe_webview_dispatch`
/// — readiness probes must share this pump or they report false timeouts while
/// CDP itself would succeed on the same HWND.
#[cfg(target_os = "windows")]
pub(crate) fn pump_win32_messages_once() {
    use windows::Win32::UI::WindowsAndMessaging::{
        DispatchMessageW, PeekMessageW, TranslateMessage, MSG, PM_REMOVE,
    };
    unsafe {
        let mut msg = std::mem::zeroed::<MSG>();
        while PeekMessageW(&mut msg, None, 0, 0, PM_REMOVE).as_bool() {
            let _ = TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}

/// Run `ExecuteScript` by hopping onto the Tauri main thread and pumping Win32
/// messages until the COM completion arrives.
///
/// Why this is required: `with_webview` posts to the webview HWND (main UI
/// thread). Waiting on a worker with `thread::sleep` only works when tao is
/// free to pump. Under load — or while another `run_on_main_thread` is in
/// flight — the PostMessage sits unhandled and we report
/// "UI thread did not dispatch with_webview". Running the wait *on* the main
/// thread with an explicit PeekMessage pump makes ExecuteScript reliable, the
/// same way Microsoft documents for WebView2 STA usage.
fn native_execute_script(
    app: &AppHandle,
    window: &WebviewWindow,
    js: &str,
) -> Result<String, String> {
    use webview2_com::ExecuteScriptCompletedHandler;

    let (tx, rx) = std::sync::mpsc::channel::<Result<String, String>>();
    let window = window.clone();
    let js_owned = js.to_string();
    app.run_on_main_thread(move || {
        let cell: Arc<Mutex<Option<Result<String, String>>>> = Arc::new(Mutex::new(None));
        let cell_inner = cell.clone();
        let entered = Arc::new(AtomicBool::new(false));
        let entered_flag = entered.clone();
        if let Err(e) = window.with_webview(move |platform| {
            entered_flag.store(true, Ordering::SeqCst);
            let controller = platform.controller();
            let webview = match unsafe { controller.CoreWebView2() } {
                Ok(w) => w,
                Err(e) => {
                    if let Ok(mut g) = cell_inner.lock() {
                        *g = Some(Err(format!("CoreWebView2 failed: {e}")));
                    }
                    return;
                }
            };
            let cell_cb = cell_inner.clone();
            let handler = ExecuteScriptCompletedHandler::create(Box::new(move |error_code, result| {
                let out = match error_code {
                    Ok(()) => Ok(result),
                    Err(err) => Err(format!("ExecuteScript failed: {err}")),
                };
                if let Ok(mut g) = cell_cb.lock() {
                    *g = Some(out);
                }
                Ok(())
            }));
            let hstr = windows::core::HSTRING::from(js_owned.as_str());
            if let Err(e) = unsafe { webview.ExecuteScript(&hstr, &handler) } {
                if let Ok(mut g) = cell_inner.lock() {
                    *g = Some(Err(format!("ExecuteScript COM error: {e}")));
                }
                return;
            }
            // Keep handler alive until COM invokes it (same as async_slot).
            std::mem::forget(handler);
        }) {
            let _ = tx.send(Err(format!("with_webview enqueue failed: {e}")));
            return;
        }

        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
        loop {
            if let Some(outcome) = cell.lock().ok().and_then(|mut g| g.take()) {
                let _ = tx.send(outcome);
                return;
            }
            if std::time::Instant::now() >= deadline {
                let entered_ok = entered.load(Ordering::SeqCst);
                let _ = tx.send(Err(if entered_ok {
                    "ExecuteScript timed out (callback never fired after with_webview ran)".into()
                } else {
                    "ExecuteScript timed out (webview UI thread did not dispatch with_webview)".into()
                }));
                return;
            }
            pump_win32_messages_once();
            std::thread::sleep(std::time::Duration::from_millis(2));
        }
    })
    .map_err(|e| format!("run_on_main_thread failed: {e}"))?;

    rx.recv_timeout(std::time::Duration::from_secs(25))
        .map_err(|e| format!("ExecuteScript main-thread wait failed: {e}"))?
}

/// Keep CDP logs readable: screenshot payloads and DOM snapshots run to
/// megabytes, and the tail is what identifies the call.
fn truncate(text: &str, limit: usize) -> String {
    if text.len() <= limit {
        return text.to_string();
    }
    let head: String = text.chars().take(limit).collect();
    format!("{head}…(+{} chars)", text.len() - limit)
}

fn core_webview2(
    controller: &webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2Controller,
) -> Result<ICoreWebView2, String> {
    unsafe { controller.CoreWebView2() }.map_err(|e| format!("CoreWebView2 failed: {e}"))
}

/// Register a receiver for every event in `FORWARDED_EVENTS`, routing payloads
/// into `state` under `label`. Must run on the webview's UI thread, which
/// `with_webview` guarantees.
pub fn subscribe_events(
    app: &AppHandle,
    label: &str,
    state: Arc<CdpBrokerState>,
) -> Result<(), String> {
    let window: WebviewWindow = app
        .get_webview_window(label)
        .ok_or_else(|| format!("embedded webview '{label}' not found"))?;
    let label_owned = label.to_string();

    let failure: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
    let failure_inner = failure.clone();

    window
        .with_webview(move |platform| {
            let webview = match core_webview2(&platform.controller()) {
                Ok(w) => w,
                Err(e) => {
                    if let Ok(mut guard) = failure_inner.lock() {
                        *guard = Some(e);
                    }
                    return;
                }
            };

            // Receivers must be kept alive: WebView2 unregisters the callback
            // when the receiver object is released.
            let mut receivers = Vec::with_capacity(FORWARDED_EVENTS.len());
            // Count outcomes instead of keeping only the first error. A few event
            // names are version-gated and legitimately absent on some WebView2
            // builds; treating any single miss as fatal made the whole panel
            // refuse to start over an event nothing depends on.
            let mut skipped: Vec<String> = Vec::new();
            let mut registered = 0usize;

            for event_name in FORWARDED_EVENTS {
                let receiver = match event_receiver(&webview, event_name) {
                    Ok(r) => r,
                    Err(e) => {
                        skipped.push(format!("{event_name} ({e})"));
                        continue;
                    }
                };
                let state = state.clone();
                let label = label_owned.clone();
                let name = event_name.to_string();
                let handler = DevToolsProtocolEventReceivedEventHandler::create(Box::new(
                    move |_sender, args| {
                        let Some(args) = args else {
                            eprintln!("[browser-cdp] event {name} had no args");
                            return Ok(());
                        };
                        let mut params = PWSTR::null();
                        if unsafe { args.ParameterObjectAsJson(&mut params) }.is_err() {
                            eprintln!("[browser-cdp] event {name} params unreadable");
                            return Ok(());
                        }
                        let params = CoTaskMemPWSTR::from(params).to_string();
                        if params.is_empty() {
                            eprintln!("[browser-cdp] event {name} had empty params");
                            return Ok(());
                        }
                        eprintln!("[browser-cdp] event {label}/{name} = {:.200}", params);
                        state.emit_event(&label, &name, &params);
                        Ok(())
                    },
                ));
                let mut token = 0i64;
                match unsafe { receiver.add_DevToolsProtocolEventReceived(&handler, &mut token) }
                {
                    Ok(()) => {
                        registered += 1;
                        receivers.push((receiver, token))
                    }
                    Err(e) => skipped.push(format!("{event_name} add ({e})")),
                }
            }

            // Leaking the receivers is deliberate: the COM callbacks stay valid
            // for the lifetime of the webview, and the panel closes with it.
            std::mem::forget(receivers);

            eprintln!(
                "[browser-cdp] subscribe {label_owned}: {registered}/{} events registered",
                FORWARDED_EVENTS.len()
            );
            for miss in &skipped {
                eprintln!("[browser-cdp]   skipped {miss}");
            }

            if registered == 0 {
                if let Ok(mut guard) = failure_inner.lock() {
                    *guard = Some(format!(
                        "no CDP events could be registered ({} attempted): {}",
                        FORWARDED_EVENTS.len(),
                        skipped.join("; ")
                    ));
                }
            }
        })
        .map_err(|e| format!("with_webview dispatch failed: {e}"))?;

    match failure.lock().ok().and_then(|mut guard| guard.take()) {
        Some(err) => Err(err),
        None => Ok(()),
    }
}

fn event_receiver(
    webview: &ICoreWebView2,
    event_name: &str,
) -> Result<
    webview2_com::Microsoft::Web::WebView2::Win32::ICoreWebView2DevToolsProtocolEventReceiver,
    String,
> {
    let name_pw = CoTaskMemPWSTR::from(event_name);
    unsafe { webview.GetDevToolsProtocolEventReceiver(*name_pw.as_ref().as_pcwstr()) }
        .map_err(|e| format!("GetDevToolsProtocolEventReceiver failed: {e}"))
}

// -- Public Tauri commands (used by Python backend over HTTP invoke) ------------

/// Call a single CDP method against the embedded browser's WebView2, returning
/// the JSON result.  This is the "direct" path that replaces the WS broker:
/// Python calls this over HTTP (browser_cdp_server) rather than over
/// `playwright.chromium.connect_over_cdp(ws://127.0.0.1:…/devtools/browser/…)`.
#[tauri::command]
pub fn browser_cdp_command(
    app: tauri::AppHandle,
    thread_id: String,
    method: String,
    params_json: String,
) -> Result<Value, String> {
    crate::commands::browser_cdp_server::log_line(&format!(
        "[browser-cdp] browser_cdp_command ENTER thread={thread_id} method={method}"
    ));
    let label = webview_label_for_thread(&thread_id);
    crate::commands::browser_cdp_server::log_line(&format!(
        "[browser-cdp] browser_cdp_command label={label}"
    ));

    // Ensure the WebView2 EXISTS *outside* the CDP global lock. Holding the
    // lock across a 10–60s panel-wait previously serialized every concurrent
    // Runtime.evaluate into "dispatch timeout" storms and starved the UI
    // thread that browser-panel-request needs to run upsert.
    //
    // Only Page.navigate / Page.reload may auto-create. Runtime.evaluate polls
    // from `_page_state` / panel sync used to each trigger ensure → 60s
    // create races that destroyed healthy HWNDs and blocked the HTTP bridge.
    #[cfg(target_os = "windows")]
    {
        use crate::commands::browser_embed::ensure_webview_for_cdp;
        // tauri-agent style: existence is enough for Page.navigate
        // (`WebviewWindow::navigate`). Do NOT probe with_webview here — that
        // COM path hangs on fresh/child HWNDs and used to destroy healthy
        // windows in a recreate storm.
        let window_ok = match app.get_webview_window(&label) {
            Some(win) => {
                let _ = win.show();
                true
            }
            None => false,
        };
        if !window_ok {
            let can_ensure = matches!(method.as_str(), "Page.navigate" | "Page.reload");
            if !can_ensure {
                crate::commands::browser_cdp_server::log_line(&format!(
                    "[browser-cdp] webview not ready for {method}; skip ensure (navigate first)"
                ));
                return Err(format!(
                    "embedded webview not ready for {method} (label={label}); Page.navigate first"
                ));
            }
            crate::commands::browser_cdp_server::log_line(&format!(
                "[browser-cdp] ensure needed; params_json={}",
                truncate(&params_json, 200)
            ));
            let boot_url = serde_json::from_str::<Value>(&params_json)
                .ok()
                .and_then(|v| v.get("url").and_then(|u| u.as_str()).map(str::to_string))
                .unwrap_or_else(|| "about:blank".to_string());
            if let Err(e) = ensure_webview_for_cdp(&app, &thread_id, &boot_url) {
                crate::commands::browser_cdp_server::log_line(&format!(
                    "[browser-cdp] ensure_webview_for_cdp failed: {e}"
                ));
                return Err(format!("auto-create embedded webview failed: {e}"));
            }
            crate::commands::browser_cdp_server::log_line(
                "[browser-cdp] ensure_webview_for_cdp ok",
            );
        }
    }

    // Page.navigate + Runtime.evaluate use dispatcher APIs (navigate /
    // eval_with_callback) — no with_webview, no CDP global lock. Holding the
    // lock across evaluate storms used to starve navigate and HTTP workers.
    let unlocked = matches!(
        method.as_str(),
        "Page.navigate" | "Page.reload" | "Runtime.evaluate"
    );
    crate::commands::browser_cdp_server::log_line("[browser-cdp] about to call_cdp");
    let body = if unlocked {
        call_cdp_locked(&app, &label, &method, &params_json)?
    } else {
        let _lock = cdp_global_lock()
            .lock()
            .map_err(|_| "CDP global lock poisoned".to_string())?;
        match call_cdp_locked(&app, &label, &method, &params_json) {
            Ok(body) => body,
            Err(e) if e.contains("not found") => {
                crate::commands::browser_cdp_server::log_line(&format!(
                    "[browser-cdp] call_cdp missing window ({e}); no ensure for {method}"
                ));
                return Err(e);
            }
            Err(e) => return Err(e),
        }
    };
    crate::commands::browser_cdp_server::log_line("[browser-cdp] call_cdp returned");
    serde_json::from_str(&body).map_err(|e| format!("CDP result parse failed: {e}"))
}

/// Return the HTTP port the CDP command server is listening on, starting it if
/// needed.  Python reads this once per session (or from the well-known file).
#[tauri::command]
pub fn browser_cdp_http_port(app: tauri::AppHandle) -> Result<u16, String> {
    use crate::commands::browser_cdp_server::ensure_http_server;
    tauri::async_runtime::block_on(async move { ensure_http_server(app).await })
}

/// Start the CDP event subscription for a thread's embedded browser.  Python's
/// gateway SSE endpoint calls this once per thread; Tauri streams each CDP event
/// as a JSON line until the `browser_cdp_unsubscribe` call arrives.
#[tauri::command]
pub fn browser_cdp_subscribe(
    app: tauri::AppHandle,
    thread_id: String,
) -> Result<String, String> {
    let label = webview_label_for_thread(&thread_id);
    // Trigger event registration synchronously (re-registration is idempotent).
    let cdp_state = app.state::<Arc<CdpBrokerState>>().inner().clone();
    subscribe_events(&app, &label, cdp_state)?;
    Ok(label)
}

/// Tear down the event subscription for a thread.  Called when the Python
/// SSE stream ends (browser tab closed / thread switched).
#[tauri::command]
pub fn browser_cdp_unsubscribe(
    app: tauri::AppHandle,
    thread_id: String,
) -> Result<(), String> {
    let label = webview_label_for_thread(&thread_id);
    let cdp_state = app.state::<Arc<CdpBrokerState>>().inner().clone();
    cdp_state.clear(&label);
    Ok(())
}

/// Check whether a thread has an active embedded browser and return its current
/// URL + page title.  Used by Python to detect "browser not open" without
/// sending a CDP command.
#[tauri::command]
pub fn browser_cdp_status(
    app: tauri::AppHandle,
    thread_id: String,
) -> Result<Value, String> {
    let label = webview_label_for_thread(&thread_id);

    // Existence only — never call window.url() (hangs on child embeds).
    if app.get_webview_window(&label).is_none() {
        return Err(format!("embedded webview '{label}' not found"));
    };
    let href = app
        .try_state::<crate::commands::browser_embed_bridge::EmbedBridge>()
        .and_then(|b| b.cached_url(&label))
        .unwrap_or_default();
    Ok(serde_json::json!({
        "url": href,
        "title": "",
        "readyState": if href.is_empty() { "none" } else { "unknown" },
        "label": label,
    }))
}

#[cfg(test)]
mod tests {
    use super::FORWARDED_EVENTS;
    use std::collections::HashSet;

    /// receivers for it, so the callback fires twice and Playwright sees
    /// duplicated lifecycle events. `DOM.documentUpdated` was listed twice.
    #[test]
    fn forwarded_events_have_no_duplicates() {
        let mut seen = HashSet::new();
        let dupes: Vec<&str> = FORWARDED_EVENTS
            .iter()
            .filter(|name| !seen.insert(**name))
            .copied()
            .collect();
        assert!(dupes.is_empty(), "duplicated CDP events: {dupes:?}");
    }

    /// A blank or malformed name would make `GetDevToolsProtocolEventReceiver`
    /// fail at runtime with no compile-time warning.
    #[test]
    fn forwarded_event_names_are_well_formed() {
        for name in FORWARDED_EVENTS {
            assert!(!name.is_empty(), "empty event name");
            assert!(!name.contains(' '), "event name has whitespace: {name:?}");
            assert!(
                name.split_once('.').is_some(),
                "event name is not Domain.method: {name:?}"
            );
        }
    }

    /// These are the events the panel itself depends on. Losing any of them
    /// silently breaks navigation tracking or the preview surface, so guard the
    /// subset that must never be dropped by a future edit.
    #[test]
    fn required_events_are_present() {
        for required in [
            "Page.loadEventFired",
            "Page.frameNavigated",
            "Page.screencastFrame",
            "Runtime.consoleAPICalled",
        ] {
            assert!(
                FORWARDED_EVENTS.contains(&required),
                "required event {required} was removed"
            );
        }
    }
}
