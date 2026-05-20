const buildGraph = (parsedWorkflow, workflowId, workflowName) => { // fungsi untuk membangun graph dari hasil parsing workflow dengan parameter parsedWorkflow, workflowId, dan workflowName
  // graph dibuat dulu
  const graph = {
    nodes: [],
    relationships: [],
  }
  
  // buat node untuk workflow itu sendiri
  graph.nodes.push({ // buat node untuk workflow itu sendiri dengan properti id, type, dan properties yang sesuai dengan data yang diterima dari server.js
    id: workflowId,
    type: "WORKFLOW",
    properties: {
      workflow_name: workflowName,
    },
  })

  // buat node graph
  parsedWorkflow.nodes.forEach((node) => {

    graph.nodes.push({
      id: node.id,
      type: "ACTION",
      properties: {
        label: node.label,
        app_name: node.app_name,
        action_name: node.action_name,
        category: node.category,
      },
    })

    // relationship workflow -> action
    graph.relationships.push({
      source: workflowId,
      target: node.id,
      type: "CONTAINS",
    })
  })


  // buat relationship graph
  parsedWorkflow.edges.forEach((edge) => {

    graph.relationships.push({
      source: edge.source,
      target: edge.target,
      type: "CONNECTS_TO",
    })
  })

  return graph
}

module.exports = { // ekspor fungsi buildGraph agar dapat digunakan di file lain
  buildGraph,
}