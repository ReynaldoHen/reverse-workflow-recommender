const driver = require("./neo4jDriver")

function sanitizeProps(props) {
  const out = {}
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined) { out[k] = null }
    else if (typeof v === "object") { out[k] = JSON.stringify(v) }
    else { out[k] = v }
  }
  return out
}

const saveGraphToNeo4j = async (graphData) => {
  const session = driver.session()

  try {

    for (const node of graphData.nodes) {

      const props = sanitizeProps(node.properties)

      if (node.type === "WORKFLOW") {
        await session.run(
          `MERGE (n:WORKFLOW {workflow_id: $id})
           SET n.workflow_id = $id, n += $props`,
          { id: node.id, props }
        )
      }

      else if (node.type === "ACTION") {
        await session.run(
          `MERGE (n:ACTION {action_id: $id})
           SET n.action_id = $id, n += $props`,
          { id: node.id, props }
        )
      }

      else if (node.type === "APP") {
        await session.run(
          `MERGE (n:APP {app_id: $id})
           SET n.app_id = $id, n += $props`,
          { id: node.id, props }
        )
      }

      else if (node.type === "REVERSE_ACTION") {
        await session.run(
          `MERGE (n:REVERSE_ACTION {rev_id: $id})
           SET n.rev_id = $id, n += $props`,
          { id: node.id, props }
        )
      }
    }

    for (const rel of graphData.relationships) {

      await session.run(
        `
        MATCH (a)
        WHERE (a:WORKFLOW AND a.workflow_id = $source)
           OR (a:ACTION AND a.action_id = $source)
           OR (a:APP AND a.app_id = $source)
           OR (a:REVERSE_ACTION AND a.rev_id = $source)

        MATCH (b)
        WHERE (b:WORKFLOW AND b.workflow_id = $target)
           OR (b:ACTION AND b.action_id = $target)
           OR (b:APP AND b.app_id = $target)
           OR (b:REVERSE_ACTION AND b.rev_id = $target)

        MERGE (a)-[r:${rel.type}]->(b)
        SET r += $props
        `,
        {
          source: rel.source,
          target: rel.target,
          props: sanitizeProps(rel.properties)
        }
      )
    }

    console.log("Graph saved to Neo4j")

  } catch (error) {
    console.error("Neo4j Save Error:", error)
  } finally {
    await session.close()
  }
}

module.exports = { saveGraphToNeo4j }
