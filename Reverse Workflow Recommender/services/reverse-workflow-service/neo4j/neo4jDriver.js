const path   = require("path")
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const neo4j = require("neo4j-driver")

const NEO4J_URI      = process.env.NEO4J_URI      || "bolt://localhost:7687"
const NEO4J_USERNAME = process.env.NEO4J_USERNAME  || "neo4j"
const NEO4J_PASSWORD = process.env.NEO4J_PASSWORD  || ""

const driver = neo4j.driver(
  NEO4J_URI,
  neo4j.auth.basic(NEO4J_USERNAME, NEO4J_PASSWORD),
  {
    connectionTimeoutMillis: 10_000,
    maxConnectionPoolSize:   10,
  }
)

driver.verifyConnectivity()
  .then(() => console.log("[neo4j] Connected to Neo4j Aura"))
  .catch(err => console.warn("[neo4j] Warning: Could not verify Neo4j connectivity:", err.message))

module.exports = driver