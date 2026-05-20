const driver = require("./neo4jDriver") // mengambil driver Neo4j dari file neo4jDriver.js untuk melakukan operasi database Neo4j

// fungsi untuk menyimpan graph ke database Neo4j Aura dengan menggunakan driver yang telah dibuat
const saveGraphToNeo4j = async (graphData) => {

  const session = driver.session() // membuat session untuk menjalankan query ke database Neo4j

  try {
    // simpan nodes
    for (const node of graphData.nodes) {

      // default type jika kosong
      const nodeType = node.type || "ACTION"

      await session.run(
        `
        MERGE (n:Entity:${nodeType} {id: $id})
        SET n.id = $id
        SET n += $properties
        `,
        {
          id: node.id,
          properties: node.properties || {},
        }
      )
    }
    // simpan relationships
    for (const rel of graphData.relationships) {
    
    // console.log("REL:", rel) // menampilkan isi rel yang akan disimpan ke database Neo4j untuk debugging

    const relationshipType = rel.type || "CONNECTS_TO"

    await session.run(
      `
      MATCH (a:Entity)
      WHERE a.id = $source

      MATCH (b:Entity)
      WHERE b.id = $target

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