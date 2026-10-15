//! Guest bridge for the embedded browser WebView2 (tauri-agent pattern).
//!
//! External pages cannot run our React shell, so we inject a small init script
//! that listens for `browser-embed://cdp` and answers via
//! `browser_embed_bridge_response`. Rust waits on an mpsc channel — same shape
//! as `tauri-agent-plugin`'s `AgentBridge`, without pulling that crate in.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, EventTarget, Runtime};

pub const EMBED_CDP_EVENT: &str = "browser-embed://cdp";
const DEFAULT_TIMEOUT: Duration = Duration::from_secs(8);

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EmbedBridgeResponse {
    pub id: String,
    pub result: Option<Value>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EmbedBridgeRequest {
    id: String,
    method: String,
    params: Value,
}

#[derive(Default)]
pub struct EmbedBridge {
    pending: Mutex<HashMap<String, Sender<Result<Value, String>>>>,
    next_id: AtomicU64,
}

impl EmbedBridge {
    pub fn request_eval<R: Runtime>(
        &self,
        app: &AppHandle<R>,
        webview_label: &str,
        expression: &str,
    ) -> Result<Value, String> {
        let id = format!(
            "embed-{}-{}",
            self.next_id.fetch_add(1, Ordering::SeqCst),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0)
        );
        let rx = self.insert_pending(id.clone());
        let payload = EmbedBridgeRequest {
            id: id.clone(),
            method: "Runtime.evaluate".into(),
            params: serde_json::json!({ "expression": expression, "returnByValue": true }),
        };
        // Target the embed webview by label (tauri-agent uses emit_to).
        if let Err(e) = app.emit_to(
            EventTarget::webview_window(webview_label),
            EMBED_CDP_EVENT,
            payload,
        ) {
            self.remove_pending(&id);
            return Err(format!("embed bridge emit failed: {e}"));
        }
        match rx.recv_timeout(DEFAULT_TIMEOUT) {
            Ok(Ok(v)) => Ok(v),
            Ok(Err(e)) => Err(e),
            Err(_) => {
                self.remove_pending(&id);
                Err("embed bridge timed out waiting for guest response".into())
            }
        }
    }

    fn insert_pending(&self, id: String) -> Receiver<Result<Value, String>> {
        let (tx, rx) = channel();
        self.pending
            .lock()
            .expect("embed bridge mutex")
            .insert(id, tx);
        rx
    }

    fn remove_pending(&self, id: &str) {
        let _ = self.pending.lock().expect("embed bridge mutex").remove(id);
    }

    pub fn complete(&self, response: EmbedBridgeResponse) -> bool {
        let Some(tx) = self
            .pending
            .lock()
            .expect("embed bridge mutex")
            .remove(&response.id)
        else {
            return false;
        };
        let result = match response.error {
            Some(msg) => Err(msg),
            None => Ok(response.result.unwrap_or(Value::Null)),
        };
        tx.send(result).is_ok()
    }
}

/// Init script injected into every document of the embed WebView2.
pub fn embed_guest_init_script() -> &'static str {
    r#"(function(){
  if (window.__evoEmbedBridgeInstalled) return;
  window.__evoEmbedBridgeInstalled = true;
  var EVENT = 'browser-embed://cdp';
  function attach() {
    var t = window.__TAURI__;
    if (!t || !t.event || !t.core) { setTimeout(attach, 40); return; }
    t.event.listen(EVENT, function(ev) {
      var p = (ev && ev.payload) || {};
      var result = null;
      var error = null;
      try {
        if (p.method === 'Runtime.evaluate') {
          var expr = (p.params && p.params.expression) || 'undefined';
          result = (0, eval)(String(expr));
          if (typeof result === 'undefined') result = null;
          try { result = JSON.parse(JSON.stringify(result)); }
          catch (_e) { result = String(result); }
        } else {
          error = 'unsupported method: ' + String(p.method || '');
        }
      } catch (e) {
        error = String((e && e.message) || e);
      }
      t.core.invoke('browser_embed_bridge_response', {
        response: { id: p.id, result: result, error: error }
      }).catch(function(err) {
        console.warn('[evo-embed-bridge] response failed', err);
      });
    });
  }
  attach();
})();"#
}

#[tauri::command]
pub fn browser_embed_bridge_response(
    bridge: tauri::State<'_, EmbedBridge>,
    response: EmbedBridgeResponse,
) -> bool {
    bridge.complete(response)
}
