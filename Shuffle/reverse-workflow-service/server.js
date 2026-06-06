const path = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../.env") })

const express = require("express") // mengambil library express untuk membuat server
const cors = require("cors") // mengambil library cors untuk mengizinkan permintaan dari domain/browser lain
const fs = require("fs") // mengambil library fs untuk menyimpan file debug-payload.json

const { parseWorkflow } = require("./parsers/workflowParser") // mengambil fungsi parseWorkflow dari file workflowParser.js
const { buildGraph } = require("./graph/graphBuilder") // mengambil fungsi buildGraph dari file graphBuilder.js
const driver = require("./neo4j/neo4jDriver") // mengambil driver Neo4j dari file neo4jDriver.js untuk melakukan operasi database Neo4j
const { saveGraphToNeo4j } = require("./neo4j/saveGraph") // mengambil fungsi saveGraphToNeo4j dari file saveGraph.js untuk menyimpan graph ke database Neo4j
const { validateWorkflow } = require("./validators/validateWorkflow") // mengambil fungsi validateWorkflow dari file validateWorkflow.js untuk memvalidasi struktur dasar workflow plan yang diterima dari server.js
const { buildShuffleWorkflow, importWorkflowToShuffle } = require("./builders/buildShuffleWorkflow") // mengambil fungsi buildShuffleWorkflow dan importWorkflowToShuffle dari file buildShuffleWorkflow.js untuk membangun workflow plan yang dapat diimpor ke Shuffle
const { syncAppCatalog } = require("./shuffleApps/syncAppCatalog") // mengambil fungsi syncAppCatalog dari file syncAppCatalog.js untuk menyinkronkan katalog aplikasi dari Shuffle ke Neo4j

// ── Sementara: mock plan menggantikan LLM sampai LLM selesai dibuat ──
const { getMockWorkflowPlan } = require("./mock/mockWorkflowPlan")

const app = express() // membuat instance dari express
app.use(cors()) // mengizinkan semua permintaan dari domain/browser lain
app.use(express.json()) // membuat server dapat membaca data JSON yang dikirimkan 

app.get("/", (req, res) => { // endpoint untuk mengecek apakah service berjalan
  res.send("Reverse Workflow Service Running") // respon jika service berjalan
})

app.post("/api/reverse-workflow", async (req, res) => { //endpoint untuk menerima permintaan reverse workflow
  try { //mengambil workflow_id dari body
    // 1. Terima data dari Shuffle frontend
    const { workflow_id, workflow_name, actions, branches } = req.body
    console.log("[1] Received workflow:", workflow_id, "-", workflow_name)

    // 1.1. Sinkronisasi katalog aplikasi dari Shuffle ke Neo4j
    console.log("[1.1] Syncing App Catalog...")

    await syncAppCatalog()

    console.log("[1.2] App Catalog Synced")
 
    // 2. Parse Shuffle JSON → nodes + edges
    const parsedWorkflow = parseWorkflow(actions, branches)
    // console.log("[2] Workflow parsed:", parsedWorkflow.nodes.length, "nodes,", parsedWorkflow.edges.length, "edges")
 
    // 3. Build graph (nodes + relationships)
    const graphData = buildGraph(parsedWorkflow, workflow_id, workflow_name)
    // console.log("[3] Graph built with", graphData.nodes.length, "nodes and", graphData.relationships.length, "relationships")
 
    // 4. Simpan graph ke Neo4j
    await saveGraphToNeo4j(graphData)
    // console.log("[4] Graph saved to Neo4j")
 
    // // 5. Generate Semantic Workflow Plan
    // // TODO: ganti getMockWorkflowPlan() dengan panggilan LLM
    // const workflowPlan = getMockWorkflowPlan()
    // console.log("[5] Workflow plan generated:", workflowPlan.workflow_name)
 
    // // // 6. Validasi Semantic Workflow Plan
    // // const validationResult = validateWorkflow(workflowPlan)
    // // console.log("[6] Validation result:", validationResult)
 
    // // if (!validationResult.valid) {
    // //   return res.status(400).json({
    // //     success:  false,
    // //     stage:    "validation",
    // //     errors:   validationResult.errors,
    // //     warnings: validationResult.warnings,
    // //   })
    // // }
 
    // // if (validationResult.warnings.length > 0) {
    // //   console.warn("[6] Validation warnings:", validationResult.warnings)
    // // }
 
    // // // 7. Compile plan → Shuffle Workflow JSON
    // // const shuffleWorkflowJson = buildShuffleWorkflow(workflowPlan)
    // // console.log("[7] Compiled workflow:", shuffleWorkflowJson.name, "| actions:", shuffleWorkflowJson.actions.length)
 
    // // 8. Import workflow ke Shuffle via API
    // const importResult = await importWorkflowToShuffle(workflowPlan)
    // console.log("[8] Imported to Shuffle, new workflow ID:", importResult.id)
 
 
    // Response sukses
    res.json({
      success:                 true,
      source_workflow_id:      workflow_id,
      generated_workflow_id:   importResult.id,
      generated_workflow_name: importResult.name,
      validation_warnings:     validationResult.warnings,
      download_url:            "http://localhost:5005/api/download-workflow",
      message:                 "Reverse workflow generated and imported successfully",
    })
 
  }   catch (error) {
    console.error("[error]", error.message)
    res.status(500).json({
      success: false,
      error:   error.message,
    })
  }
})

app.listen(5005, () => {
  console.log("Reverse Workflow Service running on port 5005")
})