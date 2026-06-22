const { resolveReverse } = require("../config/reverseMap")

const inferRole = (node) => {
  const name = (node.label || node.action_name || "").toLowerCase()

  if (name.includes("alert") || name.includes("trigger")) return "TRIGGER"
  if (name.includes("block") || name.includes("quarantine")) return "RESPONSE"
  if (name.includes("scan") || name.includes("check") || name.includes("lookup")) return "ANALYSIS"
  return "ENRICHMENT"
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
    const actionName = node.action_name || node.label || ""

    // ─────────────────────────────
    // ACTION NODE
    // ─────────────────────────────
    graph.nodes.push({
      id: node.id,
      type: "ACTION",
      properties: {
        action_id: node.id,
        workflow_id: workflowId,
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
    // WORKFLOW → ACTION
    // ─────────────────────────────
    graph.relationships.push({
      source: workflowId,
      target: node.id,
      type: "CONTAINS",
      properties: { label: "workflow_contains_action" }
    })

    // ─────────────────────────────
    // ACTION → APP (ONLY IF EXISTS)
    // ─────────────────────────────
    if (node.app_id) {
      graph.relationships.push({
        source: node.id,
        target: node.app_id,
        type: "USES_APP",
        properties: { app_name: node.app_name || "" }
      })
    }

    // ─────────────────────────────
    // REVERSE_ACTION NODE + HAS_REVERSE (pemetaan reverse eksplisit di graph)
    // ─────────────────────────────
    const rev = resolveReverse(actionName, node.app_name || "")
    const revId = `REV_${node.id}`

    graph.nodes.push({
      id: revId,
      type: "REVERSE_ACTION",
      properties: {
        rev_id: revId,
        source_action_id: node.id,
        source_action_name: actionName,
        reverse_action_name: rev.reverse_action_name,
        app_name: node.app_name || "",
        app_id: node.app_id || "",
        status: rev.status,           // auto_mapped | needs_llm | requires_manual_review
        reason: rev.reason
      },
    })

    graph.relationships.push({
      source: node.id,
      target: revId,
      type: "HAS_REVERSE",
      properties: { status: rev.status }
    })
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
