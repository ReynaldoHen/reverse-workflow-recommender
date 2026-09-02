const fs = require("fs")
const path = require("path")

const MAP_PATH = path.resolve(__dirname, "reverseActionMap.json")

let _data = { version: 0, apps: {}, heuristics: {} }
try {
  _data = JSON.parse(fs.readFileSync(MAP_PATH, "utf-8"))
} catch (err) {
  console.warn("[reverseMap] gagal memuat reverseActionMap.json:", err.message)
}

const APPS = _data.apps || {}
const HEUR = _data.heuristics || {}

function normalize(name) {
  return String(name || "").trim().toLowerCase().replace(/[\s-]+/g, "_")
}

function getAppConfig(appName) {
  if (!appName) return null
  if (APPS[appName]) return APPS[appName]
  const norm = normalize(appName)
  for (const key of Object.keys(APPS)) {
    if (normalize(key) === norm) return APPS[key]
  }
  return null
}

function startsWithAny(value, prefixes) {
  if (!Array.isArray(prefixes)) return false
  return prefixes.some(p => value.startsWith(normalize(p)))
}

function resolveReverse(actionName, appName = null) {
  const act = normalize(actionName)
  const llmActs = (HEUR.needs_llm_actions || ["custom_action"]).map(normalize)
  if (llmActs.includes(act)) {
    return { status: "needs_llm", reverse_action_name: "", reason: "custom_action: kebalikan disimpulkan dari konfigurasi (method/url/body)" }
  }
  const cfg = getAppConfig(appName)

  if (cfg) {
    for (const pair of (cfg.reversible || [])) {
      if (normalize(pair.action) === act) {
        return { status: "auto_mapped", reverse_action_name: normalize(pair.reverse_action), reason: "" }
      }
    }
    if ((cfg.requires_manual_review || []).some(a => normalize(a) === act)) {
      return { status: "requires_manual_review", reverse_action_name: "", reason: "app_listed" }
    }
    if ((cfg.no_reverse_needed || []).some(a => normalize(a) === act)) {
      return { status: "no_reverse_needed", reverse_action_name: "", reason: "app_listed" }
    }
    if ((cfg.needs_llm || []).some(a => normalize(a) === act)) {
      return { status: "needs_llm", reverse_action_name: "", reason: "app_listed" }
    }
    if (cfg.default_status) {
      return { status: cfg.default_status, reverse_action_name: "", reason: "app_default" }
    }
  }

  if (startsWithAny(act, HEUR.no_reverse_prefixes)) {
    return { status: "no_reverse_needed", reverse_action_name: "", reason: "heuristic_prefix" }
  }
  if (startsWithAny(act, HEUR.manual_review_prefixes)) {
    return { status: "requires_manual_review", reverse_action_name: "", reason: "heuristic_prefix" }
  }

  return { status: "needs_llm", reverse_action_name: "", reason: "unclassified" }
}

function lookupReverse(actionName, appName = null) {
  const r = resolveReverse(actionName, appName)
  return r.status === "auto_mapped" ? { reverseAction: r.reverse_action_name } : null
}
function isIrreversible(actionName, appName = null) {
  return resolveReverse(actionName, appName).status === "requires_manual_review"
}

module.exports = { resolveReverse, lookupReverse, isIrreversible, normalize }
