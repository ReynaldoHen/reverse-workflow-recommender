const path   = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const neo4j = require("neo4j-driver")

// Baca dari .env — nama variable sesuai dengan .env kamu:
//   NEO4J_URI=neo4j+s://3b0d8adf.databases.neo4j.io   (Aura pakai neo4j+s://)
//   NEO4J_USERNAME=3b0d8adf
//   NEO4J_PASSWORD=eR7unbRMFnRxTMFhnggbSjxk9UQAjBWqq23QnoKrAxU
const NEO4J_URI      = process.env.NEO4J_URI      || "bolt://localhost:7687"
const NEO4J_USERNAME = process.env.NEO4J_USERNAME  || "neo4j"
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD  || ""

const driver = neo4j.driver(
  NEO4J_URI,
  neo4j.auth.basic(NEO4J_USERNAME, NEO4J_PASSWORD),
  {
    // Neo4j Aura memerlukan TLS — driver otomatis handle ini via neo4j+s://
    // Timeout yang sedikit lebih longgar untuk koneksi cloud
    connectionTimeoutMillis: 10_000,
    maxConnectionPoolSize:   10,
  }
)

// Verifikasi koneksi saat startup (opsional — log warning jika gagal, tidak crash)
driver.verifyConnectivity()
  .then(() => console.log("[neo4j] Connected to Neo4j Aura:", NEO4J_URI))
  .catch(err => console.warn("[neo4j] Warning: Could not verify Neo4j connectivity:", err.message))

module.exports = driver