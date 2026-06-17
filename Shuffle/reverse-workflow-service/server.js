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
// LLM + PROMPT
// ─────────────────────────────
const { buildReverseWorkflowPrompt } =
  require("./prompt/buildReverseWorkflowPrompt")

const { generateWithRetry } =
  require("./llm/llmService")

const { getWorkflowContext } =
  require("./neo4j/queryWorkflowContext")

// ─────────────────────────────
// POST PROCESSING
// ─────────────────────────────
const { buildShuffleWorkflow, importWorkflowToShuffle } =
  require("./builders/buildShuffleWorkflow")

const app = express()
app.use(cors())
app.use(express.json({ limit: "10mb" }))
app.use(express.urlencoded({ extended: true, limit: "10mb" }))

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
  try {
    const { workflow_id, workflow_name, actions, branches } = req.body

    console.log("[1] Received workflow:", workflow_id)

    // 1. Parse
    const parsed = parseWorkflow(actions, branches)

    // 2. Build Graph
    const graph = buildGraph(parsed, workflow_id, workflow_name)

    // 3. Save Graph (Neo4j)
    await saveGraphToNeo4j(graph)

    // 4. Sync Apps (safe)
    await safeSyncApps()

    // 5. Get Neo4j context
    const context = await getWorkflowContext(workflow_id)
    if (!context) {
      throw new Error("Workflow context not found in Neo4j")
    }

    // 6. Build prompt
    const prompt = buildReverseWorkflowPrompt(context)
    // console.dir(prompt, { depth: null })

    // 7. Call LLM + Validate Output LLM + Import to Shuffle
    const llmResult = await generateWithRetry(JSON.stringify(prompt, null, 2))

    // ─────────────────────────────
    // RESPONSE
    // ─────────────────────────────
    return res.json({
      success: true,
      workflow_id,
      generated_workflow_id: importResult.id,
      generated_workflow_name: importResult.name,
      attempts: llmResult.attempts,
      message: "Reverse workflow generated successfully"
    })

  } catch (error) {
    console.error("[ERROR]", error.message)

    return res.status(500).json({
      success: false,
      error: error.message
    })
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