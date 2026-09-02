const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const axios = require("axios")

const { validateWorkflow, buildImportError, getReviewRequiredFromGraph, getAutoMappedFromGraph, getAppImages } = require("../validators/validateWorkflow")
const { importWorkflowToShuffle } = require("../builders/buildShuffleWorkflow")
const paperLog = require("../utils/paperLog")
const { randomUUID } = require("crypto")
const { resolveReverse } = require("../config/reverseMap")

function normalizeWorkflowIds(workflow) {
  if (!workflow || !Array.isArray(workflow.actions)) return workflow

  if (typeof workflow.name === "string" && workflow.name.trim()) {
    if (!/\(reverse\)\s*$/i.test(workflow.name)) {
      workflow.name = workflow.name.trim() + " (reverse)"
    }
  }

  const idMap = {}
  let posIndex = 0
  for (const a of workflow.actions) {
    const oldId = a && a.id
    const newId = randomUUID()
    if (oldId) idMap[oldId] = newId
    a.id = newId
    if (typeof a.requires_manual_review !== "boolean") a.requires_manual_review = false
    if (typeof a.execution_delay !== "number") a.execution_delay = 0
    if (a.large_image === undefined) a.large_image = ""
    if (!a.position || typeof a.position !== "object" ||
        typeof a.position.x !== "number" || typeof a.position.y !== "number") {
      a.position = { x: 300, y: 150 + posIndex * 150 }
    }
    posIndex++
  }

  workflow.actions.forEach((a, i) => { a.is_start_node = (i === 0) })
  workflow.start = workflow.actions.length ? workflow.actions[0].id : ""

  workflow.branches = []
  for (let i = 0; i < workflow.actions.length - 1; i++) {
    workflow.branches.push({
      id: randomUUID(),
      source_id: workflow.actions[i].id,
      destination_id: workflow.actions[i + 1].id,
      condition: "",
    })
  }
  return workflow
}

function classifyAction(node) {
  const name  = String(node.action_name || "").toLowerCase()
  const app   = String(node.app_name || "").toLowerCase()
  const label = String(node.label || "").toLowerCase()

  if (app.includes("shuffle tools") || /execute_python|repeat_back_to_me|parse_|regex|set_variable|wait/.test(name))
    return "utility"
  if (/^(get_|list_|describe_|search_|fetch_|read_|lookup_|find_)/.test(name)) return "read"
  const method = (node.parameters || []).find(p => String(p.name || "").toLowerCase() === "method")
  if (method && String(method.value || "").trim().toUpperCase() === "GET") return "read"

  const auditApps = ["elasticsearch", "opensearch", "splunk", "sentinel", "datadog", "sumo", "graylog", "loki", "wazuh"]
  const writes = /create|index|document|post_|record|log|write|ingest|add_doc/.test(name)
  if (auditApps.some(a => app.includes(a)) && writes) return "audit_log"
  if (/record|audit|log|siem/.test(label) && writes) return "audit_log"

  const notifApps = ["email", "slack", "teams", "outlook", "smtp", "telegram", "discord", "pagerduty", "opsgenie", "jira", "servicenow", "mattermost", "webhook"]
  if (notifApps.some(a => app.includes(a))) return "notification"
  if (/send_|post_message|notify|create_ticket|create_issue|create_incident|create_alert/.test(name)) return "notification"

  return "containment"
}

function isReadOnlySource(node) {
  const name = String(node.action_name || "").toLowerCase()
  if (/^(get_|list_|describe_|search_|fetch_|read_|lookup_|find_)/.test(name)) return true
  const m = (node.parameters || []).find(p => String(p.name || "").toLowerCase() === "method")
  if (m && String(m.value || "").trim().toUpperCase() === "GET") return true
  return false
}

function buildActionNode(o) {
  return {
    id: randomUUID(),
    name: o.name,
    app_name: o.app_name || "",
    app_id: o.app_id || "",
    app_version: o.app_version || "",
    large_image: "",
    label: o.label || o.name,
    is_start_node: false,
    execution_delay: 0,
    requires_manual_review: !!o.requires_manual_review,
    parameters: Array.isArray(o.parameters) ? o.parameters : [],
    position: null,
  }
}

function buildCheckpoint(sourceNode, shuffleTools, reason) {
  const label = `CHECKPOINT (manual): tinjau '${sourceNode.action_name}' (${sourceNode.app_name}) — ${reason}`
  if (!shuffleTools) return null
  return buildActionNode({
    name: "repeat_back_to_me",
    app_name: shuffleTools.app_name, app_id: shuffleTools.app_id, app_version: shuffleTools.app_version,
    label, requires_manual_review: true,
    parameters: [{ name: "call", value: label }],
  })
}

function withRollbackContent(params, workflowName, summary) {
  const out = (params || []).map(p => ({ ...p }))
  const msg = `ROLLBACK: reverse workflow untuk '${workflowName}' dijalankan. ${summary}`
  const body = out.find(p => /^(body|message|data|text|content|description)$/i.test(String(p.name || "")))
  if (body) {
    try {
      const obj = JSON.parse(body.value)
      obj.event = "rollback"
      obj.rollback = true
      obj.message = msg
      obj.source_workflow = workflowName
      body.value = JSON.stringify(obj, null, 2)
    } catch (_) {
      body.value = msg
    }
  } else {
    out.push({ name: "body", value: msg })
  }
  return out
}

function buildObservabilityAction(node, ctx, kind) {
  return buildActionNode({
    name: node.action_name,
    app_name: node.app_name, app_id: node.app_id, app_version: node.app_version,
    parameters: withRollbackContent(node.parameters, ctx.workflowName, ctx.summary),
    label: (kind === "audit_log" ? "Audit rollback: " : "Notifikasi rollback: ") + (node.label || node.action_name),
  })
}

const TOGGLE_BOOL_KEYS = [
  "accountenabled", "account_enabled", "enabled", "disabled", "isenabled",
  "is_enabled", "active", "blocked", "is_blocked", "isblocked", "suspended",
]

function flipBoolValue(v) {
  if (typeof v === "boolean") return !v
  const s = String(v).trim().toLowerCase()
  if (s === "true") return false
  if (s === "false") return true
  return undefined
}

function buildToggleReverse(node) {
  const params = (node.parameters || []).map(p => ({ ...p }))
  let flipped = false

  const bodyP = params.find(p => /^body$/i.test(String(p.name || "")))
  if (bodyP && bodyP.value) {
    try {
      const obj = JSON.parse(bodyP.value)
      let changed = false
      for (const k of Object.keys(obj)) {
        if (TOGGLE_BOOL_KEYS.includes(k.toLowerCase())) {
          const nv = flipBoolValue(obj[k])
          if (nv !== undefined) { obj[k] = nv; changed = true }
        }
      }
      if (changed) { bodyP.value = JSON.stringify(obj, null, 2); flipped = true }
    } catch (_) { /* body bukan JSON → abaikan */ }
  }

  for (const p of params) {
    if (TOGGLE_BOOL_KEYS.includes(String(p.name || "").toLowerCase())) {
      const nv = flipBoolValue(p.value)
      if (nv !== undefined) { p.value = String(nv); flipped = true }
    }
  }

  if (!flipped) return null
  return buildActionNode({
    name: node.action_name,
    app_name: node.app_name, app_id: node.app_id, app_version: node.app_version,
    parameters: params,
    label: `Reverse: ${node.label || node.action_name}`,
  })
}

function assembleReverse(workflowName, sourceNodes, llmActions) {
  const sources = Array.isArray(sourceNodes) ? sourceNodes : []
  const shuffleTools = sources.find(n => /shuffle\s*tools/i.test(String(n.app_name || "")))
  const pool = Array.isArray(llmActions) ? llmActions.filter(a => a && a.name) : []
  const containment = []
  const observ = []
  const review_required = []
  const reverted = []

  for (const node of [...sources].reverse()) {
    const cat = classifyAction(node)
    if (cat === "utility" || cat === "read") continue
    if (cat === "audit_log" || cat === "notification") { observ.push({ node, cat }); continue }

    const toggle = buildToggleReverse(node)
    if (toggle) {
      containment.push(toggle)
      reverted.push(`${node.app_name}/${node.action_name} (toggle)`)
      continue
    }

    const rev = resolveReverse(node.action_name, node.app_name)
    const status = rev.status
    if (status === "no_reverse_needed") continue

    if (status === "auto_mapped") {
      containment.push(buildActionNode({
        name: rev.reverse_action_name,
        app_name: node.app_name, app_id: node.app_id, app_version: node.app_version,
        parameters: node.parameters, label: rev.reverse_action_name,
      }))
      reverted.push(`${node.app_name}/${rev.reverse_action_name}`)
      continue
    }

    if (status === "needs_llm") {
      if (isReadOnlySource(node)) continue
      const idx = pool.findIndex(a => String(a.app_name || "").toLowerCase() === String(node.app_name || "").toLowerCase())
      if (idx >= 0) {
        const a = pool.splice(idx, 1)[0]
        containment.push(buildActionNode({
          name: a.name || node.action_name,
          app_name: node.app_name, app_id: node.app_id, app_version: node.app_version,
          parameters: Array.isArray(a.parameters) && a.parameters.length ? a.parameters : node.parameters,
          label: a.label || a.name, requires_manual_review: true,
        }))
        reverted.push(`${node.app_name}/${a.name || node.action_name}`)
      } else {
        const cp = buildCheckpoint(node, shuffleTools, "LLM tak menghasilkan pembalik")
        if (cp) containment.push(cp)
        review_required.push({ source_action_name: node.action_name, app_name: node.app_name, status: "needs_llm", reason: "LLM tak menghasilkan pembalik" })
      }
      continue
    }

    const cp = buildCheckpoint(node, shuffleTools, rev.reason || "tidak ada pasangan pembalik")
    if (cp) containment.push(cp)
    review_required.push({ source_action_name: node.action_name, app_name: node.app_name, status: "requires_manual_review", reason: rev.reason || "tidak ada pasangan pembalik" })
  }

  const summary = reverted.length
    ? `Tindakan yang direvert: ${reverted.join(", ")}.`
    : "Tidak ada containment yang direvert otomatis."
  const ctx = { workflowName, summary }
  const tail = observ.map(({ node, cat }) => buildObservabilityAction(node, ctx, cat))

  return { actions: [...containment, ...tail], review_required }
}

function buildComment(label, x, y, w = 260, h = 150) {
  return {
    id: randomUUID(),
    label,
    type: "COMMENT",
    is_valid: true,
    decorator: true,
    width: w,
    height: h,
    position: { x, y },
    backgroundcolor: "#1f2023",
    color: "#ffffff",
    textHalign: "right",
    textValign: "bottom",
    textMarginX: `-${w - 10}px`,
    textMarginY: `-${h}px`,
    flowOrientation: "horizontal",
    errors: [],
  }
}

// ── Klasifikasi generik action hasil rakitan (berlaku semua workflow) ──
function classifyEmitted(a) {
  const lbl = String((a && a.label) || "")
  if (lbl.startsWith("CHECKPOINT")) return "checkpoint"
  if (lbl.startsWith("Audit rollback:") || lbl.startsWith("Notifikasi rollback:")) return "observability"
  if (a && a.requires_manual_review === true) return "llm_inferred"
  return "auto"
}

// Tingkat risiko generik dari jenis aplikasi (heuristik kategori, bukan nama workflow)
function deriveSeverity(appName) {
  const s = String(appName || "").toLowerCase()
  if (/(firewall|fortigate|palo|cisco|asa|edr|sophos|wazuh|crowdstrike|sentinel_?one|network)/.test(s)) return "TINGGI"
  if (/(entra|azure|okta|iam|identity|ldap|active_?directory|google_?workspace)/.test(s)) return "SEDANG"
  return "SEDANG"
}

// Ekstrak nama action & app sumber dari label checkpoint:
// "CHECKPOINT (manual): tinjau '<action>' (<app>) — <alasan>"
function parseCheckpointLabel(label) {
  const m = /tinjau '([^']+)' \(([^)]+)\)/.exec(String(label || ""))
  return { action: m ? m[1] : "", app: m ? m[2] : "" }
}

// Hitung ringkasan rollback dari actions hasil rakitan — deterministik & generik.
function buildRollbackSummary(actions) {
  const counts = { auto: 0, llm_inferred: 0, checkpoint: 0, observability: 0 }
  for (const a of actions || []) counts[classifyEmitted(a)]++
  const targets = counts.auto + counts.llm_inferred + counts.checkpoint
  const covered = counts.auto + counts.llm_inferred
  const coverage = targets === 0 ? 100 : Math.round((covered / targets) * 100)

  let status, statusNote
  if (counts.checkpoint > 0) {
    status = "PERLU INTERVENSI MANUAL"
    statusNote = `${counts.checkpoint} aksi tidak memiliki pembalik otomatis yang aman.`
  } else if (counts.llm_inferred > 0) {
    status = "SIAP — VERIFIKASI KONFIGURASI"
    statusNote = `${counts.llm_inferred} aksi hasil inferensi LLM perlu diverifikasi analis.`
  } else {
    status = "SIAP DIEKSEKUSI"
    statusNote = "Seluruh aksi containment dibalik otomatis."
  }
  return { counts, targets, covered, coverage, status, statusNote }
}

function buildComments(actions, workflowName) {
  const flagged = (actions || []).filter(a => a && a.requires_manual_review === true)
  const summary = buildRollbackSummary(actions)
  const comments = []

  // ── Komentar RINGKASAN ROLLBACK (selalu dibuat, semua workflow) ──
  const headerLines = [
    `RINGKASAN ROLLBACK — ${workflowName || "reverse workflow"}`,
    `STATUS: ${summary.status}`,
    `Cakupan otomatis: ${summary.covered}/${summary.targets} aksi containment (${summary.coverage}%).`,
    `${summary.counts.auto} otomatis | ${summary.counts.llm_inferred} inferensi LLM | ${summary.counts.checkpoint} checkpoint | ${summary.counts.observability} audit/notifikasi.`,
    summary.statusNote,
    flagged.length > 0
      ? "Tinjau seluruh node bertanda manual sebelum eksekusi."
      : "Tidak ada node yang menunggu tinjauan manual.",
  ]
  comments.push(buildComment(headerLines.join("\n"), 640, 90, 300, 190))

  // ── Komentar per node yang perlu perhatian analis ──
  const isCheckpoint = a => classifyEmitted(a) === "checkpoint"
  for (const a of flagged) {
    const pos = a.position && typeof a.position.x === "number"
      ? a.position
      : { x: 300, y: 150 }
    let note
    if (isCheckpoint(a)) {
      const src = parseCheckpointLabel(a.label)
      const sev = deriveSeverity(src.app)
      note = [
        `CHECKPOINT: '${src.action || "aksi sumber"}' (${src.app || "?"})`,
        `ALASAN: tidak ada pembalik otomatis yang aman — pembalikan butuh kondisi sebelum eksekusi (pre-state) yang tidak tersimpan.`,
        `DAMPAK bila dilewati: efek aksi sumber TETAP AKTIF. Risiko: ${sev}.`,
        `REKOMENDASI: pulihkan konfigurasi ${src.app || "aplikasi terkait"} secara manual ke kondisi sebelum eksekusi, lalu verifikasi hasilnya.`,
      ].join("\n")
    } else {
      note = [
        `VERIFIKASI (inferensi LLM)`,
        `${a.app_name || ""} / ${a.name || ""}`,
        `Konfigurasi pembalik disimpulkan oleh LLM — pastikan parameter benar sebelum eksekusi.`,
      ].join("\n")
    }
    comments.push(buildComment(note, pos.x + 320, pos.y - 18, 300, 175))
  }
  return { comments, summary }
}

const LLM_API_URL    = process.env.LLM_API_URL    || "http://localhost:8000"
const LLM_API_PREFIX = process.env.LLM_API_PREFIX || "/api/v1"

const REVERSE_ENDPOINT = `${LLM_API_URL}${LLM_API_PREFIX}/generate/reverse`
const LOGIN_ENDPOINT   = `${LLM_API_URL}${LLM_API_PREFIX}/auth/login`

const LLM_AUTH_USER = process.env.LLM_AUTH_USER || "admin"
const LLM_AUTH_PASS = process.env.LLM_AUTH_PASS || "admin"

const LLM_CALL_TIMEOUT_MS = parseInt(process.env.LLM_CALL_TIMEOUT_MS || "960000", 10)

let _token = null

async function login() {
  try {
    const res = await axios.post(
      LOGIN_ENDPOINT,
      { username: LLM_AUTH_USER, password: LLM_AUTH_PASS },
      { timeout: 15000 }
    )

    _token = res.data?.access_token

    if (!_token) {
      throw new Error("Login succeeded but no access_token returned")
    }

    console.log("[LLM] login success")
    return _token

  } catch (err) {
    const detail = err.response?.data || err.message
    console.error("[LLM] LOGIN ERROR:", detail)
    throw new Error(`[LLM] Login failed: ${JSON.stringify(detail)}`)
  }
}

async function getToken() {
  if (_token) return _token
  return await login()
}

async function callLLM({ workflow_id, workflow_name, retryContext = null }) {

  const body = {
    workflow_id,
    workflow_name,
    retry_context: retryContext,
  }

  const token = await getToken()

  try {
    console.log("[LLM] REQUEST →", REVERSE_ENDPOINT)

    const response = await axios.post(REVERSE_ENDPOINT, body, {
      timeout: LLM_CALL_TIMEOUT_MS,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    })

    console.log("[LLM] RESPONSE STATUS:", response.status)
    console.log("[LLM] RESPONSE SIZE:", JSON.stringify(response.data).length, "bytes")

    const data = response.data

    if (!data) {
      throw new Error("Empty response from LLM service")
    }

    if (data.error) {
      throw new Error(`LLM SERVICE ERROR: ${data.error}`)
    }

    const raw =
      data.raw_output ||
      data.workflow ||
      data.result ||
      data.output ||
      data

    return { raw, prompt: data.prompt || null }

  } catch (err) {

    const detail = err.response?.data || err.message

    console.error("[LLM] CALL FAILED FULL DETAIL:", detail)

    throw new Error(
      `[LLM] Reverse service failed → ${JSON.stringify(detail)}`
    )
  }
}

function parseWorkflowJSON(raw) {
  if (!raw) throw new Error("Empty LLM output")

  if (typeof raw === "object") return raw

  const cleaned = raw
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/, "")
    .replace(/```\s*$/, "")
    .trim()

  return JSON.parse(cleaned)
}

async function generateWithRetry({
  workflow_id,
  workflow_name,
  sourceNodes = [],
  maxRetries = 3
}) {

  let lastValidation = null

  for (let attempt = 1; attempt <= maxRetries; attempt++) {

    console.log(`[LLM] Attempt ${attempt}/${maxRetries}`)

    const retryContext = lastValidation
      ? {
          attempt,
          valid: false,
          errors: lastValidation.errors || [],
          correction_instructions: lastValidation.correction_instructions || null,
        }
      : null

    let raw
    let promptUsed = null

    try {
      const llmResp = await callLLM({ workflow_id, workflow_name, retryContext })
      raw = llmResp.raw
      promptUsed = llmResp.prompt
    } catch (err) {
      console.error("[LLM] CALL ERROR:", err.message)

      lastValidation = {
        valid: false,
        errors: [{
          code: "LLM_CALL_ERROR",
          location: "llm_service",
          message: err.message
        }],
      }

      continue
    }

    let workflow
    let assembledReview = []

    try {
      const llmWorkflow = parseWorkflowJSON(raw)
      const llmActions  = Array.isArray(llmWorkflow.actions) ? llmWorkflow.actions : []
      const assembled = assembleReverse(workflow_name, sourceNodes, llmActions)
      assembledReview = assembled.review_required
      workflow = {
        name: workflow_name || llmWorkflow.name || "Reverse Workflow",
        description: (typeof llmWorkflow.description === "string" && llmWorkflow.description)
          ? llmWorkflow.description
          : "Reverse (rollback) workflow sadar-konteks — draft, perlu peninjauan analis.",
        start: "",
        actions: assembled.actions,
        branches: [],
      }
      workflow = normalizeWorkflowIds(workflow)

      try {
        const appIds = [...new Set(workflow.actions.map(a => a.app_id).filter(Boolean))]
        const imageMap = await getAppImages(appIds)
        for (const a of workflow.actions) {
          if (a.app_id && imageMap[a.app_id] !== undefined) a.large_image = imageMap[a.app_id]
        }
      } catch (e) {
        console.warn("[LLM] inject large_image gagal:", e.message)
      }

      // COMMENT kanvas: RINGKASAN ROLLBACK (status + cakupan) + anotasi kaya
      // (ALASAN/DAMPAK/REKOMENDASI) per node checkpoint — generik semua workflow.
      const built = buildComments(workflow.actions, workflow_name)
      workflow.comments = built.comments
      // Headline status ke description (tampil di kartu workflow & editor Shuffle)
      const s = built.summary
      workflow.description =
        `[${s.status}] Cakupan otomatis ${s.covered}/${s.targets} (${s.coverage}%). ` +
        `${s.statusNote} Dibuat otomatis dari '${workflow_name}'.` +
        (workflow.description ? `\n${workflow.description}` : "")

      paperLog.logPromptAndOutput(promptUsed, workflow)
    } catch (err) {
      console.error("[LLM] PARSE ERROR:", err.message)

      lastValidation = {
        valid: false,
        errors: [{
          code: "INVALID_JSON",
          location: "root",
          message: err.message
        }],
      }

      continue
    }

    if (!Array.isArray(workflow.actions) || workflow.actions.length === 0) {
      console.log(`[LLM] NO AUTO-REVERSE: 0 action dibangun, ${assembledReview.length} perlu tinjauan manual`)
      return {
        workflow,
        importResult: null,
        attempts: attempt,
        review_required: assembledReview,
        note: "no_auto_reverse",
      }
    }

    const validation = await validateWorkflow(workflow, workflow_id)

    paperLog.logValidationStart(validation)

    if (!validation.valid) {
      paperLog.logImportResult(false, "dilewati — validasi gagal (lihat error di atas)")
      console.warn("[LLM] VALIDATION FAILED — ERRORS:", JSON.stringify(validation.errors, null, 2))
      lastValidation = validation
      continue
    }

    try {
      const importResult = await importWorkflowToShuffle(workflow)
      paperLog.logImportResult(true, importResult)
      console.log("[LLM] IMPORT SUCCESS:", importResult.id)

      return { workflow, importResult, attempts: attempt, review_required: assembledReview }

    } catch (err) {
      paperLog.logImportResult(false, err.message)
      console.error("[LLM] IMPORT FAILED:", err.message)

      lastValidation = buildImportError(err.message)
    }
  }

  throw new Error(
    `Failed after ${maxRetries} attempts → ` +
    JSON.stringify(lastValidation?.errors || [])
  )
}

module.exports = {
  callLLM,
  generateWithRetry,
  login,
}