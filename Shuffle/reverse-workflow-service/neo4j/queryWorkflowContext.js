const driver = require("../neo4j/neo4jDriver")

async function getWorkflowContext(workflowId) {
  const session = driver.session()

  try {
    const result = await session.run(
      `
        MATCH (w:WORKFLOW {workflow_id: $workflowId})
        OPTIONAL MATCH (w)-[:CONTAINS]->(a:ACTION)
        OPTIONAL MATCH (a)-[:USES_APP]->(app:APP)

        RETURN 
        w AS workflow,
        collect(DISTINCT a) AS nodes,
        collect(DISTINCT app) AS apps
      `,
      { workflowId }
    )

    const record = result.records?.[0]

    if (!record) {
      console.warn("[LLM] Workflow not found in Neo4j")
      return null
    }

    return {
      workflow: record.get("workflow")?.properties || {},
      nodes: record.get("nodes").map(n => n.properties),
      appCatalog: record.get("apps").map(a => a.properties),
      relationships: []
    }

  } finally {
    await session.close()
  }
}

module.exports = { getWorkflowContext }