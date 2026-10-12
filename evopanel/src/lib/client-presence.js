/**
 * EvoPanel client instance registration — backend stops orphaned panel runs on gateway cold attach.
 *
 * Per-profile scoping: the instance id is prefixed with the active profile id
 * so two coexisting clients (installed = "default", dev = "dev") can never
 * collide on the same backend `client_presence` slot, and a Tauri dev window
 * and an installed client (when they happen to land on the same gateway) are
 * trivially distinguishable.
 */

const STORAGE_KEY = 'evopanel_client_instance_id'

function isTauriRuntime() {
  return typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__
}

function readProfileId() {
  if (typeof window === 'undefined') return ''
  const raw = window.__EVOFLOW_PROFILE_ID__
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  try {
    const fromLs = localStorage.getItem('evoflow_profile_id')
    if (fromLs) return fromLs
  } catch {
    /* ignore */
  }
  return ''
}

function readStoredClientInstanceId() {
  try {
    const fromLocal = localStorage.getItem(STORAGE_KEY)
    if (fromLocal) return fromLocal
  } catch {
    /* ignore */
  }
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStoredClientInstanceId(id) {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* ignore */
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, id)
  } catch {
    /* ignore */
  }
}

function createClientInstanceId() {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    /* ignore */
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export function getClientInstanceId() {
  let id = readStoredClientInstanceId()
  if (!id) {
    const profile = readProfileId() || 'unknown'
    const uuid = createClientInstanceId()
    id = `${profile}::${uuid}`
    writeStoredClientInstanceId(id)
  }
  if (isTauriRuntime() && typeof window !== 'undefined') {
    window.__evopanelClientInstanceId = id
  }
  return id
}

let attachInflight = null

/** Call once per page load before reading session execution state. */
export async function attachClientToGateway() {
  if (attachInflight) return attachInflight
  attachInflight = (async () => {
    const { gatewayJson } = await import('./gateway-json.js')
    return gatewayJson('POST', '/api/client/attach', {
      client_instance_id: getClientInstanceId(),
    })
  })()
  try {
    return await attachInflight
  } catch (e) {
    attachInflight = null
    throw e
  }
}
