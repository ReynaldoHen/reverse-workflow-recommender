const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const axios = require("axios")

const { validateWorkflow, buildImportError } = require("../validators/validateWorkflow")
const { importWorkflowToShuffle } = require("../builders/buildShuffleWorkflow")

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────
const LLM_API_URL    = process.env.LLM_API_URL    || "http://localhost:8000"
const LLM_API_PREFIX = process.env.LLM_API_PREFIX || "/api/v1"

const REVERSE_ENDPOINT = `${LLM_API_URL}${LLM_API_PREFIX}/generate/reverse`
const LOGIN_ENDPOINT   = `${LLM_API_URL}${LLM_API_PREFIX}/auth/login`

const LLM_AUTH_USER = process.env.LLM_AUTH_USER || "admin"
const LLM_AUTH_PASS = process.env.LLM_AUTH_PASS || "admin"

// Worst case on the Python side: embedder/reranker model load (cold) +
// Qdrant search + Ollama generation (up to 900s by default for CPU inference,
// see config.py OLLAMA_READ_TIMEOUT). Add ~60s overhead for the Python layer.
// Configurable so it can be tuned per-environment without another code change.
const LLM_CALL_TIMEOUT_MS = parseInt(process.env.LLM_CALL_TIMEOUT_MS || "960000", 10) // 960 detik atau 16 menit

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

// ─────────────────────────────────────────────
// CALL LLM
// ─────────────────────────────────────────────
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
    console.log("[LLM] RESPONSE DATA:", JSON.stringify(response.data, null, 2))

    // ── SAFE PARSING ─────────────────────
    const data = response.data

    if (!data) {
      throw new Error("Empty response from LLM service")
    }

    if (data.error) {
      throw new Error(`LLM SERVICE ERROR: ${data.error}`)
    }

    // fleksibel parsing
    const raw =
      data.raw_output ||
      data.workflow ||
      data.result ||
      data.output ||
      data

    return raw

  } catch (err) {

    // IMPORTANT: jangan hide error asli
    const detail = err.response?.data || err.message

    console.error("[LLM] CALL FAILED FULL DETAIL:", detail)

    throw new Error(
      `[LLM] Reverse service failed → ${JSON.stringify(detail)}`
    )
  }
}

// ─────────────────────────────────────────────
// PARSER
// ─────────────────────────────────────────────
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

// ─────────────────────────────────────────────
// RETRY LOOP
// ─────────────────────────────────────────────
async function generateWithRetry({
  workflow_id,
  workflow_name,
  maxRetries = 1 // 3x kesempatan untuk LLM menghasilkan output yang valid, setelah itu dianggap gagal
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

    try {
      raw = await callLLM({ workflow_id, workflow_name, retryContext })
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

    try {
      workflow = parseWorkflowJSON(raw)
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

    const validation = await validateWorkflow(workflow)
    if (!validation.valid) {
      console.warn("[LLM] VALIDATION FAILED — ERRORS:", JSON.stringify(validation.errors, null, 2))
      lastValidation = validation
      continue
    }

    try {
      const importResult = await importWorkflowToShuffle(workflow)
      console.log("[LLM] IMPORT SUCCESS:", importResult.id)

      return { workflow, importResult, attempts: attempt }

    } catch (err) {
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