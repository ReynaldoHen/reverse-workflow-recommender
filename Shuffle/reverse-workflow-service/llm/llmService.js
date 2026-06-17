const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const axios = require("axios")

const { validateWorkflow } = require("../validators/validateWorkflow")
const {
  importWorkflowToShuffle,
  buildImportError
} = require("../builders/buildShuffleWorkflow")

const { buildReverseWorkflowPrompt } = require("../prompt/buildReverseWorkflowPrompt")
// const { saveDebugJSON } = require("../utils/saveDebugJSON")

// ─────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────
const LLM_API_URL = process.env.LLM_API_URL || "http://localhost:8000"
const LLM_API_PREFIX = process.env.LLM_API_PREFIX || "/api/v1"
const REVERSE_ENDPOINT = `${LLM_API_URL}${LLM_API_PREFIX}/generate/reverse`

// ─────────────────────────────────────────────
// CALL LLM
// ─────────────────────────────────────────────
async function callLLM(prompt, retryContext = null) {
  try {
    const response = await axios.post(
      REVERSE_ENDPOINT,
      {
        prompt,
        retry_context: retryContext
      },
      {
        timeout: 120_000,
        headers: { "Content-Type": "application/json" }
      }
    )

    const { raw_output, error } = response.data

    if (error) throw new Error(`[LLM] Service error: ${error}`)
    if (!raw_output) throw new Error("[LLM] Empty LLM output")

    return raw_output

  } catch (err) {
    const detail = err.response?.data?.detail || err.message
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
  graphContext,
  maxRetries = 3
}) {

  let lastValidation = null

  // ─────────────────────────────────────────────
  // BUILD PROMPT ONCE
  // ─────────────────────────────────────────────
  const promptObject = buildReverseWorkflowPrompt({
    workflow_id,
    workflow_name,
    graphContext
  })

  const prompt = JSON.stringify(promptObject, null, 2)

  // // ─────────────────────────────────────────────
  // // DEBUG: SAVE PROMPT
  // // ─────────────────────────────────────────────
  // saveDebugJSON(
  //   `prompt-${workflow_id}-${Date.now()}.json`,
  //   {
  //     workflow_id,
  //     workflow_name,
  //     graphContext,
  //     prompt: promptObject
  //   }
  // )

  // ─────────────────────────────────────────────
  // RETRY LOOP
  // ─────────────────────────────────────────────
  for (let attempt = 1; attempt <= maxRetries; attempt++) {

    console.log(`[LLM] Attempt ${attempt}/${maxRetries}`)

    let raw

    try {
      raw = await callLLM(prompt, lastValidation)
    } catch (err) {

      console.warn("[LLM] Call failed:", err.message)

      lastValidation = {
        errors: [{
          code: "LLM_CALL_ERROR",
          location: "llm_service",
          message: err.message
        }],
        attempt
      }

      continue
    }

    let workflow

    try {
      workflow = parseWorkflowJSON(raw)
    } catch (err) {

      console.warn("[LLM] JSON parse failed:", err.message)

      lastValidation = {
        errors: [{
          code: "INVALID_JSON",
          location: "root",
          message: err.message
        }],
        attempt
      }

      continue
    }

    // ─────────────────────────────────────────────
    // VALIDATION
    // ─────────────────────────────────────────────
    const validation = await validateWorkflow(workflow)

    if (!validation.valid) {
      console.warn("[LLM] Validation failed:", validation.errors.length)

      lastValidation = { ...validation, attempt }
      continue
    }

    // ─────────────────────────────────────────────
    // IMPORT TO SHUFFLE
    // ─────────────────────────────────────────────
    try {
      const importResult = await importWorkflowToShuffle(workflow)

      console.log("[LLM] Import success:", importResult.id)

      return {
        workflow,
        importResult,
        attempts: attempt
      }

    } catch (err) {

      console.warn("[LLM] Import failed:", err.message)

      lastValidation = {
        ...buildImportError(err.message),
        attempt
      }
    }
  }

  // ─────────────────────────────────────────────
  // FINAL ERROR
  // ─────────────────────────────────────────────
  const summary = (lastValidation?.errors || [])
    .map(e => `[${e.code}] ${e.location}: ${e.message}`)
    .join("\n  ")

  throw new Error(
    `Failed to generate workflow after ${maxRetries} attempts\n` +
    (summary || "Unknown error")
  )
}

module.exports = {
  callLLM,
  generateWithRetry
}