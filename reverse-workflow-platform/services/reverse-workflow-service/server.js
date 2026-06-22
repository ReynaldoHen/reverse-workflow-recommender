const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../.env") })

const express = require("express")
const cors = require("cors")

// ─────────────────────────────
// CORE PIPELINE MODULES
// ─────────────────────────────
const { parseWorkflow } = require("./parsers/workflowParser")
const { buildGraph } = require("./graph/graphBuilder")
const { saveGraphToNeo4j } = require("./neo4j/saveGraph")
const { syncAppCatalog } = require("./shuffleApps/syncAppCatalog")

// ─────────────────────────────
// LLM + VALIDATION
// ─────────────────────────────
const { generateWithRetry } = require("./llm/llmService")
const { getWorkflowContext } = require("./neo4j/queryWorkflowContext")
const { validateWorkflow } = require("./validators/validateWorkflow")

const app = express()
app.use(cors())
app.use(express.json({ limit: "10mb" }))
app.use(express.urlencoded({ extended: true, limit: "10mb" }))

// ─────────────────────────────
// STATUS STORE (in-memory)
// ─────────────────────────────
const statusStore = new Map()
function setStatus(id, status, extra = {}) {
  statusStore.set(id, { workflow_id: id, status, updated_at: new Date().toISOString(), ...extra })
}

// ─────────────────────────────
// HEALTH
// ─────────────────────────────
app.get("/", (req, res) => {
  res.send("Reverse Workflow Service Running")
})

// ─────────────────────────────
// MAIN PIPELINE
// ─────────────────────────────
app.post("/api/reverse-workflow", async (req, res) => {
  const { workflow_id, workflow_name, actions, branches } = req.body
  try {
    console.log("[1] Received workflow:", workflow_id)
    setStatus(workflow_id, "processing")

    // 1. Parse
    const parsed = parseWorkflow(actions, branches)

    // 2. Build Graph (termasuk REVERSE_ACTION + HAS_REVERSE)
    const graph = buildGraph(parsed, workflow_id, workflow_name)

    // 3. Save Graph (Neo4j)
    await saveGraphToNeo4j(graph)

    // 4. Sync Apps (safe)
    await safeSyncApps()

    // 5. Verify Neo4j context exists
    const context = await getWorkflowContext(workflow_id)
    if (!context) {
      throw new Error("Workflow context not found in Neo4j")
    }

    // 6. Call LLM + Validate Output + Import to Shuffle
    const llmResult = await generateWithRetry({
      workflow_id,
      workflow_name,
      maxRetries: 3
    })

    setStatus(workflow_id, "success", {
      generated_workflow_id: llmResult.importResult.id,
      review_required: llmResult.review_required || []
    })

    return res.json({
      success: true,
      workflow_id,
      generated_workflow_id: llmResult.importResult.id,
      generated_workflow_name: llmResult.importResult.name,
      attempts: llmResult.attempts,
      review_required: llmResult.review_required || [],
      message: "Reverse workflow generated successfully (draft — perlu peninjauan analis)"
    })

  } catch (error) {
    console.error("[ERROR]", error.message)
    setStatus(workflow_id, "failed", { error: error.message })

    return res.status(500).json({
      success: false,
      error: error.message
    })
  }
})

// ─────────────────────────────
// STATUS — GET /api/reverse-workflow/status/:id
// ─────────────────────────────
app.get("/api/reverse-workflow/status/:id", (req, res) => {
  const st = statusStore.get(req.params.id)
  if (!st) {
    return res.status(404).json({ success: false, error: "workflow_id tidak ditemukan" })
  }
  return res.json({ success: true, ...st })
})

// ─────────────────────────────
// VALIDATE — POST /api/validate-workflow (tanpa import)
// ─────────────────────────────
app.post("/api/validate-workflow", async (req, res) => {
  try {
    const { workflow, workflow_id } = req.body
    if (!workflow) {
      return res.status(400).json({ success: false, error: "field 'workflow' wajib diisi" })
    }
    const result = await validateWorkflow(workflow, workflow_id || null)
    return res.json({ success: true, ...result })
  } catch (error) {
    return res.status(500).json({ success: false, error: error.message })
  }
})

// ─────────────────────────────
// SAFE SYNC
// ─────────────────────────────
async function safeSyncApps() {
  try {
    await syncAppCatalog()
    console.log("[APP] synced")
  } catch (err) {
    console.warn("[APP] sync skipped:", err.message)
  }
}

// ─────────────────────────────
// START SERVER
// ─────────────────────────────
async function startServer() {
  await safeSyncApps()
  app.listen(5005, () => {
    console.log("Reverse Workflow Service running on port 5005")
  })
}

startServer()
