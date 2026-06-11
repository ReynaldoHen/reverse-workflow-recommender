const { validateWorkflow, buildImportError } = require("../validators/validateWorkflow")
const { importWorkflowToShuffle }           = require("../builders/buildShuffleWorkflow")

// ─────────────────────────────────────────────
// LLM CALLER  (development placeholder)
// ─────────────────────────────────────────────

/**
 * Send messages to the LLM and receive a JSON string output.
 *
 * ⚠️  DEVELOPMENT PLACEHOLDER
 * Replace the body of this function with your actual LLM implementation.
 *
 * Contract:
 *   Input  : messages[] → [{ role: "system"|"user"|"assistant", content: string }]
 *   Output : string     → JSON string (Shuffle Workflow)
 *
 * ── OpenAI ──────────────────────────────────────────────────────────
 * const { OpenAI } = require("openai")
 * const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY })
 *
 * const res = await openai.chat.completions.create({
 *   model: "gpt-4o",
 *   messages,
 *   response_format: { type: "json_object" },
 * })
 * return res.choices[0].message.content
 *
 * ── Anthropic Claude ────────────────────────────────────────────────
 * const Anthropic = require("@anthropic-ai/sdk")
 * const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY })
 *
 * const system  = messages.find(m => m.role === "system")?.content || ""
 * const history = messages.filter(m => m.role !== "system")
 *
 * const res = await client.messages.create({
 *   model:      "claude-opus-4-6",
 *   max_tokens: 8096,
 *   system,
 *   messages:   history,
 * })
 * return res.content[0].text
 *
 * ── Ollama (local) ───────────────────────────────────────────────────
 * const axios = require("axios")
 * const res = await axios.post("http://localhost:11434/api/chat", {
 *   model:   process.env.OLLAMA_MODEL || "llama3",
 *   messages,
 *   stream:  false,
 *   format:  "json",
 * })
 * return res.data.message.content
 */
async function callLLM(messages) {
  throw new Error(
    "[LLM] callLLM() is not yet implemented. " +
    "Open llmService.js and uncomment one of the example implementations " +
    "that matches the LLM provider you are using."
  )
}

// ─────────────────────────────────────────────
// JSON PARSER
// ─────────────────────────────────────────────

/**
 * Parse raw LLM output into a JavaScript object.
 * Handles cases where the LLM wraps JSON inside a markdown code block.
 */
function parseWorkflowJSON(raw) {
  if (typeof raw !== "string" || !raw.trim()) {
    throw new Error("LLM output is empty or not a string")
  }

  // strip ```json ... ``` or ``` ... ```
  const cleaned = raw
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/,      "")
    .replace(/```\s*$/,      "")
    .trim()

  return JSON.parse(cleaned)
}

// ─────────────────────────────────────────────
// RETRY LOOP
// ─────────────────────────────────────────────

/**
 * Generate a Shuffle Workflow JSON with an automatic retry loop.
 *
 * Flow per attempt:
 *   1. Call callLLM() with messages that include errors from the
 *      previous attempt (if any).
 *   2. Parse the JSON output.
 *   3. Level A + B validation (structural + semantic/Neo4j).
 *   4. Level C: attempt to import into Shuffle.
 *      → Success : return result — done.
 *      → Failure : send error back to LLM and retry.
 *
 * @param {Function} buildMessages
 *   fn(lastValidationResult, attempt) → messages[]
 *   Called before every attempt. On the first attempt,
 *   lastValidationResult is null.
 *
 * @param {number} maxRetries  Default: 3
 *
 * @returns {{ workflow, importResult, attempts }}
 * @throws  Error after maxRetries are exhausted
 */
async function generateWithRetry(buildMessages, maxRetries = 3) {

  let lastValidation = null

  for (let attempt = 1; attempt <= maxRetries; attempt++) {

    console.log(`\n[LLM] ── Attempt ${attempt}/${maxRetries} ──────────────────`)

    // ── Step 1: Call LLM ─────────────────────
    let rawOutput

    try {
      const messages = buildMessages(lastValidation, attempt)
      rawOutput      = await callLLM(messages)

      console.log(`[LLM] Output received (${rawOutput.length} chars)`)

    } catch (llmError) {
      console.error("[LLM] callLLM error:", llmError.message)

      lastValidation = {
        valid:  false,
        errors: [{
          level:    "structural",
          code:     "INVALID_JSON",
          location: "root",
          message:  `LLM call failed: ${llmError.message}`,
          expected: "A valid JSON string output from the LLM",
          received: null,
        }],
        correction_instructions: "The LLM call failed. Please try again.",
      }

      continue
    }

    // ── Step 2: Parse JSON ────────────────────
    let workflow

    try {
      workflow = parseWorkflowJSON(rawOutput)

    } catch (parseError) {

      console.warn("[LLM] JSON parse failed:", parseError.message)

      lastValidation = {
        valid:  false,
        errors: [{
          level:    "structural",
          code:     "INVALID_JSON",
          location: "root",
          message:  `LLM output is not valid JSON: ${parseError.message}`,
          expected: "A valid JSON object following the Shuffle Workflow Schema",
          received: rawOutput.slice(0, 300),
        }],
        correction_instructions:
          "Output must be pure JSON only. Do not include any text, explanation, " +
          "or markdown outside of the JSON. Return only the JSON object.",
      }

      continue
    }

    // ── Step 3: Validate Level A + B ─────────
    const validation = await validateWorkflow(workflow)

    if (!validation.valid) {
      console.warn(
        `[LLM] Validation failed — ${validation.errors.length} error(s):`,
        validation.errors.map(e => `[${e.code}] ${e.location}`).join(", ")
      )
      lastValidation = { ...validation, attempt }
      continue
    }

    // ── Step 4: Level C — Import to Shuffle ──
    console.log("[LLM] Validation passed — attempting import to Shuffle...")

    try {

      const importResult = await importWorkflowToShuffle(workflow)

      console.log(
        `[LLM] ✅ Import successful — workflow ID: ${importResult.id}` +
        ` (completed in ${attempt} attempt(s))`
      )

      return { workflow, importResult, attempts: attempt }

    } catch (importError) {

      console.warn("[LLM] Import failed:", importError.message)

      lastValidation = {
        ...buildImportError(importError.message),
        attempt,
      }

      if (attempt === maxRetries) break
      continue
    }
  }

  // ── All attempts exhausted ────────────────
  const lastErrors = lastValidation?.errors ?? []
  const summary    = lastErrors
    .map(e => `[${e.code}] ${e.location}: ${e.message}`)
    .join("\n  ")

  throw new Error(
    `Failed to generate a valid workflow after ${maxRetries} attempt(s).\n` +
    `Last errors:\n  ${summary || "Unknown"}`
  )
}

module.exports = {
  callLLM,
  generateWithRetry,
}