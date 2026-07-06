const safe = (val, fallback = "") => {
  return val === undefined || val === null ? fallback : val
}

const parseWorkflow = (actions, branches) => {

  const nodes = actions.map((action) => {
    return {
      id: safe(action.id),
      label: safe(action.label, action.name),
      app_name: safe(action.app_name),
      action_name: safe(action.action_name || action.name),
      category: safe(action.category),
      position: safe(action.position, { x: 0, y: 0 }),
      app_id: safe(action.app_id),
      app_version: safe(action.app_version),
      isStartNode: !!action.isStartNode,
      environment: safe(action.environment),
      parameters: Array.isArray(action.parameters) ? action.parameters : [],
    }
  })

  const edges = branches.map((branch) => {
    return {
      source: safe(branch.source_id),
      target: safe(branch.destination_id),
      label: safe(branch.label, ""),
      conditions: safe(branch.conditions, ""),
    }
  })

  return {
    nodes,
    edges,
  }
}

module.exports = {
  parseWorkflow,
}