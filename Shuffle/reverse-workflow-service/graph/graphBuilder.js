const inferRole = (node) => {
  const name = (node.label || node.action_name || "").toLowerCase()

  if (name.includes("alert") || name.includes("trigger")) return "TRIGGER"
  if (name.includes("block") || name.includes("quarantine")) return "RESPONSE"
  if (name.includes("scan") || name.includes("check") || name.includes("lookup")) return "ANALYSIS"
  return "ENRICHMENT"
}

// APP node id standardization (IMPORTANT for Neo4j consistency)
const makeAppNodeId = (app_id) => {
  if (!app_id) return null
  return `APP_${app_id}`
}

const buildGraph = (parsedWorkflow, workflowId, workflowName) => {

  const targetIds = new Set(parsedWorkflow.edges.map(e => e.target))

  const startNode = parsedWorkflow.nodes.find(
    node => !targetIds.has(node.id)
  )

  const graph = {
    nodes: [],
    relationships: [],
  }

  // ─────────────────────────────────────────────
  // WORKFLOW NODE
  // ─────────────────────────────────────────────
  graph.nodes.push({
    id: workflowId,
    type: "WORKFLOW",
    properties: {
      workflow_id: workflowId,
      workflow_name: workflowName,
      description: parsedWorkflow.description || "",
      start_node: startNode?.id || null
    },
  })

  parsedWorkflow.nodes.forEach((node) => {

    const role = inferRole(node)

    // ─────────────────────────────
    // ACTION NODE
    // ─────────────────────────────
    graph.nodes.push({
      id: node.id,
      type: "ACTION",
      properties: {
        action_id: node.id,
        label: node.label || node.action_name || "",
        app_name: node.app_name || "",
        action_name: node.action_name || "",
        app_id: node.app_id || "",
        app_version: node.app_version || "",
        role: role,
        position: JSON.stringify(node.position || {}),
        is_start: startNode?.id === node.id,
        parameters: JSON.stringify(node.parameters || [])
      },
    })

    // ─────────────────────────────
    // WORKFLOW → ACTION (IMPORTANT RELATION)
    // ─────────────────────────────
    graph.relationships.push({
      source: workflowId,
      target: node.id,
      type: "CONTAINS",
      properties: {
        label: "workflow_contains_action"
      }
    })

    // ─────────────────────────────
    // ACTION → APP (ONLY IF EXISTS)
    // ─────────────────────────────
    if (node.app_id) {
      graph.relationships.push({
        source: node.id,
        target: node.app_id,
        type: "USES_APP",
        properties: {
          app_name: node.app_name || ""
        }
      })
    }
  })

  // ─────────────────────────────
  // EDGE RELATIONSHIPS (FLOW LOGIC)
  // ─────────────────────────────
  parsedWorkflow.edges.forEach((edge) => {

    graph.relationships.push({
      source: edge.source,
      target: edge.target,
      type: "NEXT",
      properties: {
        condition: edge.conditions || "",
        label: edge.label || ""
      },
    })
  })

  return graph
}

module.exports = { buildGraph }