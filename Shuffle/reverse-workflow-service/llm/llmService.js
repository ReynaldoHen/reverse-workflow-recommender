const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const axios = require("axios")
const { validateWorkflow }                          = require("../validators/validateWorkflow")
const { importWorkflowToShuffle, buildImportError } = require("../builders/buildShuffleWorkflow")

// ─────────────────────────────────────────────────────────────────────────────
// CONFIG
// Set LLM_API_URL=http://llm-service:8000 in .env when running in Docker,
// or http://localhost:8000 when running locally.
// ─────────────────────────────────────────────────────────────────────────────
const LLM_API_URL = process.env.LLM_API_URL || "http://localhost:8000"

// ─────────────────────────────────────────────────────────────────────────────
// HTTP CALL TO PYTHON LLM SERVICE
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Call the Python LLM service to generate a reverse workflow.
 *
 * The Python service handles internally:
 *   1. Query Neo4j for the workflow graph (using workflow_id)
 *   2. Retrieve similar playbooks via RAG (BGE-M3 + reranker)
 *   3. Build the full prompt with graph + RAG context
 *   4. Call Ollama to generate the Shuffle workflow JSON
 *
 * @param {string}      workflow_id   - Source workflow ID (already in Neo4j from Step 4)
 * @param {string}      workflow_name - Source workflow name
 * @param {object|null} retryContext  - Validation errors from last attempt, or null on first call
 * @returns {Promise<string>}           Raw output string from Ollama (may contain code fences)
 */
async function callLLM(workflow_id, workflow_name, retryContext = null) {
  let response
  try {
    response = await axios.post(
      `${LLM_API_URL}/generate/reverse`,
      { workflow_id, workflow_name, retry_context: retryContext },
      { timeout: 120_000, headers: { "Content-Type": "application/json" } }
    )
  } catch (err) {
    const detail = err.response?.data?.detail || err.message
    throw new Error(`[LLM] Cannot reach Python LLM service at ${LLM_API_URL} — ${detail}`)
  }

  const { raw_output, error } = response.data

  if (error)      throw new Error(`[LLM] Service returned error: ${error}`)
  if (!raw_output) throw new Error("[LLM] Service returned empty raw_output")

  return raw_output
}

// ─────────────────────────────────────────────────────────────────────────────
// JSON PARSER
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parse raw LLM output into a JavaScript object.
 * Handles cases where the LLM wraps JSON inside a markdown code block.
 */
function parseWorkflowJSON(raw) {
  if (typeof raw !== "string" || !raw.trim()) {
    throw new Error("LLM output is empty or not a string")
  }
  const cleaned = raw
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/,      "")
    .replace(/```\s*$/,      "")
    .trim()
  return JSON.parse(cleaned)
}

// ─────────────────────────────────────────────────────────────────────────────
// RETRY LOOP
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Generate a Shuffle Workflow JSON with automatic retry.
 *
 * Pipeline per attempt:
 *   1. Call Python LLM service → raw JSON string
 *   2. Parse JSON
 *   3. Level A + B validation (structural + semantic/Neo4j)
 *   4. Level C: import to Shuffle
 *      → Success : return result — done
 *      → Failure : forward errors to next attempt via retryContext
 *
 * @param {string} workflow_id    - Source workflow ID
 * @param {string} workflow_name  - Source workflow name
 * @param {number} maxRetries     - Max attempts (default: 3)
 */
async function generateWithRetry(workflow_id, workflow_name, maxRetries = 3) {
  let lastValidation = null

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    console.log(`[LLM] Attempt ${attempt}/${maxRetries} — calling Python LLM service...`)

    // ── Step 1: Call LLM ─────────────────────────────────────────────
    let raw
    try {
      raw = await callLLM(workflow_id, workflow_name, lastValidation)
    } catch (callError) {
      console.warn(`[LLM] Call failed (attempt ${attempt}):`, callError.message)
      lastValidation = {
        errors: [{ code: "LLM_CALL_ERROR", location: "llm_service", message: callError.message }],
        attempt,
      }
      if (attempt === maxRetries) break
      continue
    }

    // ── Step 2: Parse JSON ────────────────────────────────────────────
    let workflow
    try {
      workflow = parseWorkflowJSON(raw)
    } catch (parseError) {
      console.warn(`[LLM] JSON parse failed (attempt ${attempt}):`, parseError.message)
      lastValidation = {
        errors: [{ code: "INVALID_JSON", location: "root", message: parseError.message }],
        attempt,
      }
      if (attempt === maxRetries) break
      continue
    }

    // ── Step 3: Validate Level A + B ─────────────────────────────────
    const validation = await validateWorkflow(workflow)
    if (!validation.valid) {
      console.warn(
        `[LLM] Validation failed — ${validation.errors.length} error(s):`,
        validation.errors.map(e => `[${e.code}] ${e.location}`).join(", ")
      )
      lastValidation = { ...validation, attempt }
      if (attempt === maxRetries) break
      continue
    }

    // ── Step 4: Level C — Import to Shuffle ──────────────────────────
    console.log("[LLM] Validation passed — attempting Shuffle import...")
    try {
      const importResult = await importWorkflowToShuffle(workflow)
      console.log(`[LLM] ✅ Import successful — ID: ${importResult.id} (attempt ${attempt})`)
      return { workflow, importResult, attempts: attempt }
    } catch (importError) {
      console.warn("[LLM] Import failed:", importError.message)
      lastValidation = { ...buildImportError(importError.message), attempt }
      if (attempt === maxRetries) break
      continue
    }
  }

  // ── All attempts exhausted ────────────────────────────────────────
  const summary = (lastValidation?.errors ?? [])
    .map(e => `[${e.code}] ${e.location}: ${e.message}`)
    .join("\n  ")

  throw new Error(
    `Failed to generate valid workflow after ${maxRetries} attempt(s).\n` +
    `Last errors:\n  ${summary || "Unknown"}`
  )
}

module.exports = { callLLM, generateWithRetry }