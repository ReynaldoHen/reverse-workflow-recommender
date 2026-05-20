const driver = require("./neo4jDriver") // mengambil driver Neo4j dari file neo4jDriver.js untuk melakukan operasi database Neo4j

// fungsi untuk menyimpan graph ke database Neo4j Aura dengan menggunakan driver yang telah dibuat
const saveGraphToNeo4j = async (graphData) => {

  const session = driver.session() // membuat session untuk menjalankan query ke database Neo4j

  try {
    // simpan nodes
    for (const node of graphData.nodes) {
      await session.run(
        `
        MERGE (n:Action {id: $id})
        SET n.label = $label,
            n.app_name = $app_name,
            n.action_name = $action_name,
            n.category = $category
        `,
        {
          id: node.id,
          label: node.properties.label,
          app_name: node.properties.app_name,
          action_name: node.properties.action_name,
          category: node.properties.category,
        }
      )
    }
    // simpan relationships
    for (const rel of graphData.relationships) {

    const relationshipType = rel.type || "CONNECTS_TO"

    await session.run(
        `
        MATCH (a:Action {id: $source})
        MATCH (b:Action {id: $target})

        MERGE (a)-[r:${relationshipType}]->(b)
        `,
        {
        source: rel.source,
        target: rel.target,
        }
    )
    }

    console.log("Graph saved to Neo4j") // jika graph berhasil disimpan ke database Neo4j, log pesan sukses di console
  } catch (error) {
    console.error("Neo4j Save Error:", error) // jika terjadi error saat menyimpan graph ke database Neo4j, log error di console
  } finally {
    await session.close() // menutup session setelah selesai menjalankan query untuk menyimpan graph ke database Neo4j
  }
}

module.exports = { // ekspor fungsi saveGraphToNeo4j agar dapat digunakan di file lain untuk menyimpan graph ke database Neo4j
  saveGraphToNeo4j,
}