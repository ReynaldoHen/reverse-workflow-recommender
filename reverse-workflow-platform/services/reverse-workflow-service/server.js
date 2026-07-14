const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../.env") })

const express = require("express")

const { parseWorkflow } = require("./parsers/workflowParser")
const { buildGraph } = require("./graph/graphBuilder")
const { saveGraphToNeo4j } = require("./neo4j/saveGraph")
const { syncAppCatalog } = require("./shuffleApps/syncAppCatalog")

const { generateWithRetry } = require("./llm/llmService")
const paperLog = require("./utils/paperLog")
const { getWorkflowContext } = require("./neo4j/queryWorkflowContext")
const { validateWorkflow } = require("./validators/validateWorkflow")

const app = express()

const cors = require("cors")
app.use(cors())
app.use(express.json({ limit: "10mb" }))
app.use(express.urlencoded({ extended: true, limit: "10mb" }))

const statusStore = new Map()
function setStatus(id, status, extra = {}) {
  statusStore.set(id, { workflow_id: id, status, updated_at: new Date().toISOString(), ...extra })
}

app.get("/", (req, res) => {
  res.send("Reverse Workflow Service Running")
})

app.post("/api/reverse-workflow", async (req, res) => {
  const { workflow_id, workflow_name, actions, branches } = req.body
  try {
    console.log("[1] Received workflow:", workflow_id)
    setStatus(workflow_id, "processing")

    const parsed = parseWorkflow(actions, branches)

    paperLog.logParsing(workflow_name || workflow_id, parsed.nodes, parsed.edges)

    const graph = buildGraph(parsed, workflow_id, workflow_name)

    await saveGraphToNeo4j(graph)

    await safeSyncApps()

    const context = await getWorkflowContext(workflow_id)
    if (!context) {
      throw new Error("Workflow context not found in Neo4j")
    }

    const llmResult = await generateWithRetry({
      workflow_id,
      workflow_name,
      sourceNodes: parsed.nodes,
      maxRetries: 3
    })

    // Kasus khusus: tidak ada aksi yang perlu dibalik (semua read-only/utilitas).
    // Ini hasil SUKSES yang benar (no_auto_reverse), bukan kegagalan — tidak ada
    // workflow yang diimpor ke Shuffle sehingga importResult null. Jangan akses .id.
    if (!llmResult.importResult || llmResult.note === "no_auto_reverse") {
      setStatus(workflow_id, "success", {
        note: "no_auto_reverse",
        review_required: llmResult.review_required || []
      })
      return res.json({
        success: true,
        workflow_id,
        generated_workflow_id: null,
        generated_workflow_name: null,
        attempts: llmResult.attempts,
        review_required: llmResult.review_required || [],
        note: "no_auto_reverse",
        message: "Tidak ada aksi yang memerlukan pembalikan (seluruh aksi read-only/utilitas). Tidak ada reverse workflow yang dibuat."
      })
    }

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

app.get("/api/reverse-workflow/status/:id", (req, res) => {
  const st = statusStore.get(req.params.id)
  if (!st) {
    return res.status(404).json({ success: false, error: "workflow_id tidak ditemukan" })
  }
  return res.json({ success: true, ...st })
})

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

async function safeSyncApps() {
  try {
    await syncAppCatalog()
    console.log("[APP] synced")
  } catch (err) {
    console.warn("[APP] sync skipped:", err.message)
  }
}

async function startServer() {
  await safeSyncApps()
  app.listen(5005, () => {
    console.log("Reverse Workflow Service running on port 5005")
  })
}

startServer()
