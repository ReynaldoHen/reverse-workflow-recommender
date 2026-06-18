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

// The Python LLM service guards /generate/reverse with a JWT. We obtain one by
// logging in (default admin/admin — override via env) and cache it, refreshing
// automatically on a 401.
const LLM_AUTH_USER = process.env.LLM_AUTH_USER || "admin"
const LLM_AUTH_PASS = process.env.LLM_AUTH_PASS || "admin"

let _token = null

async function login() {
  try {
    const res = await axios.post(
      LOGIN_ENDPOINT,
      { username: LLM_AUTH_USER, password: LLM_AUTH_PASS },
      { timeout: 15000, headers: { "Content-Type": "application/json" } }
    )
    _token = res.data && res.data.access_token
    if (!_token) throw new Error("login returned no access_token")
    return _token
  } catch (err) {
    const detail = (err.response && err.response.data && err.response.data.detail) || err.message
    throw new Error(`[LLM] Login failed at ${LOGIN_ENDPOINT} — ${detail}`)
  }
}

async function getToken() {
  return _token || (await login())
}

// ─────────────────────────────────────────────
// CALL LLM
// The Python service queries Neo4j itself using workflow_id (the graph was saved
// in Step 4), does RAG retrieval, builds its own prompt, and returns raw_output.
// We therefore send identifiers + retry context, NOT a pre-built prompt.
// ─────────────────────────────────────────────
async function callLLM({ workflow_id, workflow_name, retryContext = null }) {
  const body = {
    workflow_id,
    workflow_name,
    retry_context: retryContext,
  }

  function post(token) {
    return axios.post(REVERSE_ENDPOINT, body, {
      timeout: 0,
      // timeout: 300000,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    })
  }

  try {
    let token = await getToken()
    let response
    try {
      response = await post(token)
      console.log(
        "[LLM] Response:",
        JSON.stringify(response.data, null, 2)
      )
    } catch (err) {
      // Token expired/invalid → re-login once and retry.
      if (err.response && err.response.status === 401) {
        token = await login()
        response = await post(token)
      } else {
        throw err
      }
    }

    const { raw_output, error } = response.data

    if (error) throw new Error(`[LLM] Service error: ${error}`)
    if (!raw_output) throw new Error("[LLM] Empty LLM output")

    return raw_output
  } catch (err) {
    const detail = (err.response && err.response.data && err.response.data.detail) || err.message
    throw new Error(`[LLM] Cannot reach service at ${REVERSE_ENDPOINT} — ${detail}`)
  }
}

// ─────────────────────────────────────────────
// PARSER
// ─────────────────────────────────────────────
function parseWorkflowJSON(raw) {
  if (typeof raw !== "string" || !raw.trim()) {
    throw new Error("LLM output invalid")
  }

  const cleaned = raw
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/, "")
    .replace(/```\s*$/, "")
    .trim()

  return JSON.parse(cleaned)
}

// ─────────────────────────────────────────────
// MAIN RETRY LOOP
// ─────────────────────────────────────────────
async function generateWithRetry({
  workflow_id,
  workflow_name,
  maxRetries = 3
}) {

  let lastValidation = null

  for (let attempt = 1; attempt <= maxRetries; attempt++) {

    console.log(`[LLM] Attempt ${attempt}/${maxRetries}`)

    // Shape the retry context to match the Python RetryContext schema.
    const retryContext = lastValidation
      ? {
          attempt,
          valid: lastValidation.valid === undefined ? false : lastValidation.valid,
          errors: (lastValidation.errors || []).map(e => ({
            code: e.code || "UNKNOWN",
            location: e.location || "root",
            message: e.message || "",
          })),
          correction_instructions: lastValidation.correction_instructions || null,
        }
      : null

    let raw

    try {
      raw = await callLLM({ workflow_id, workflow_name, retryContext })
    } catch (err) {
      console.warn("[LLM] Call failed:", err.message)
      lastValidation = {
        valid: false,
        errors: [{ code: "LLM_CALL_ERROR", location: "llm_service", message: err.message }],
      }
      continue
    }

    let workflow

    try {
      workflow = parseWorkflowJSON(raw)
    } catch (err) {
      console.warn("[LLM] JSON parse failed:", err.message)
      lastValidation = {
        valid: false,
        errors: [{ code: "INVALID_JSON", location: "root", message: err.message }],
      }
      continue
    }

    // VALIDATION
    const validation = await validateWorkflow(workflow)

    if (!validation.valid) {
      console.warn("[LLM] Validation failed:", validation.errors.length)
      lastValidation = validation
      continue
    }

    // IMPORT TO SHUFFLE
    try {
      const importResult = await importWorkflowToShuffle(workflow)
      console.log("[LLM] Import success:", importResult.id)
      return { workflow, importResult, attempts: attempt }
    } catch (err) {
      console.warn("[LLM] Import failed:", err.message)
      lastValidation = buildImportError(err.message)
    }
  }

  // FINAL ERROR
  const summary = (lastValidation && lastValidation.errors ? lastValidation.errors : [])
    .map(e => `[${e.code}] ${e.location}: ${e.message}`)
    .join("\n  ")

  throw new Error(
    `Failed to generate workflow after ${maxRetries} attempts\n` +
    (summary || "Unknown error")
  )
}

module.exports = {
  callLLM,
  generateWithRetry,
  login,
}
