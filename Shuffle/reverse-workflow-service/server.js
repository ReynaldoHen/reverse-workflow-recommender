const express = require("express") // mengambil library express untuk membuat server
const cors = require("cors") // mengambil library cors untuk mengizinkan permintaan dari domain/browser lain
const { parseWorkflow } = require("./parsers/workflowParser") // mengambil fungsi parseWorkflow dari file workflowParser.js
const { buildGraph } = require("./graph/graphBuilder") // mengambil fungsi buildGraph dari file graphBuilder.js
const driver = require("./neo4j/neo4jDriver") // mengambil driver Neo4j dari file neo4jDriver.js untuk melakukan operasi database Neo4j
const { saveGraphToNeo4j } = require("./neo4j/saveGraph") // mengambil fungsi saveGraphToNeo4j dari file saveGraph.js untuk menyimpan graph ke database Neo4j

const app = express() // membuat instance dari express

app.use(cors()) // mengizinkan semua permintaan dari domain/browser lain
app.use(express.json()) // membuat server dapat membaca data JSON yang dikirimkan 

app.get("/", (req, res) => { // endpoint untuk mengecek apakah service berjalan
  res.send("Reverse Workflow Service Running") // respon jika service berjalan
})

app.post("/api/reverse-workflow", async (req, res) => { //endpoint untuk menerima permintaan reverse workflow
  try { //mengambil workflow_id dari body
    // 1. Mengambil data workflow_id, workflow_name, actions, dan branches dari body permintaan yang dikirimkan ke endpoint ini
    const { workflow_id, workflow_name, actions, branches } = req.body
    console.log("Received workflow id:", workflow_id) // menampilkan workflow_id yang diterima di console untuk debugging
    // console.log("Received workflow name:", workflow_name) //  menampilkan nama workflow yang diterima
    // console.log("Received actions:", actions) //  menampilkan isi actions yang diterima
    // console.log("Received branches:", branches) //  menampilkan isi branches yang diterima
    
    // 2. Memanggil fungsi parseWorkflow dengan data actions dan branches untuk mendapatkan struktur nodes dan edges yang dapat digunakan untuk membangun graph
    const parsedWorkflow = parseWorkflow(actions, branches) // memanggil fungsi parseWorkflow dengan data actions dan branches untuk mendapatkan struktur nodes dan edges
    // console.dir(parsedWorkflow, { depth: null }) // menampilkan hasil parsing workflow di console untuk debugging

    // 3. Memanggil fungsi buildGraph dengan hasil parsing workflow untuk mendapatkan struktur graph yang terdiri dari nodes dan relationships
    const graphData = buildGraph(parsedWorkflow) // memanggil fungsi buildGraph dengan hasil parsing workflow untuk mendapatkan struktur graph yang terdiri dari nodes dan relationships
    // console.dir(graphData, { depth: null }) // menampilkan hasil building graph di console untuk debugging

    // 4. Melakukan operasi dengan graphData, seperti menyimpan ke database Neo4j atau melakukan analisis lebih lanjut
    await saveGraphToNeo4j(graphData) // memanggil fungsi saveGraphToNeo4j untuk menyimpan graph ke database Neo4j dengan menggunakan driver yang telah dibuat

    // -------------------------------------------------------------------
    res.json({ // mengirim respon sukses dengan workflow_id yang diterima
      success: true,
      workflow_id,
      message: "Reverse workflow executed successfully",
    })

  } catch (error) { // jika terjadi error, log error dan kirim respon error
    console.error(error)

    res.status(500).json({ // status 500 = pesan error
      success: false,
      error: error.message,
    })
  }
})

app.listen(5005, () => { // menjalankan server pada port 5005
  console.log("Reverse Workflow Service running on port 5005")
})