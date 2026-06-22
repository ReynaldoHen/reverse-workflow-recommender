const driver = require("../neo4j/neo4jDriver")

async function getWorkflowContext(workflowId) {
  const session = driver.session()

  try {
    const result = await session.run(
      `
        MATCH (w:WORKFLOW {workflow_id: $workflowId})
        OPTIONAL MATCH (w)-[:CONTAINS]->(a:ACTION)
        OPTIONAL MATCH (a)-[:USES_APP]->(APP:APP)
        OPTIONAL MATCH (a)-[:HAS_REVERSE]->(rev:REVERSE_ACTION)

        RETURN
          w AS WORKFLOW,
          collect(DISTINCT a)   AS nodes,
          collect(DISTINCT APP) AS apps,
          collect(DISTINCT {
            source_action_id:    rev.source_action_id,
            reverse_action_name: rev.reverse_action_name,
            status:              rev.status,
            reason:              rev.reason
          }) AS reverseMap
      `,
      { workflowId }
    )

    const record = result.records?.[0]

    if (!record) {
      console.warn("[LLM] Workflow not found in Neo4j")
      return null
    }

    return {
      workflow: record.get("WORKFLOW")?.properties || {},
      nodes: record.get("nodes").map(n => n.properties),
      appCatalog: record.get("apps").map(a => a.properties),
      reverseMap: record.get("reverseMap").filter(r => r.source_action_id !== null),
      relationships: []
    }

  } finally {
    await session.close()
  }
}

module.exports = { getWorkflowContext }
