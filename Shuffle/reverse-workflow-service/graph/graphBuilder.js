const buildGraph = (parsedWorkflow, workflowId, workflowName) => {

  // membuat array targetIds yang berisi id dari setiap target dalam parsedWorkflow.edges untuk membantu mencari startNode yang tidak menjadi target dari edge manapun
  const targetIds =
    parsedWorkflow.edges.map(
      edge => edge.target
    )

  // mencari node dalam parsedWorkflow.nodes yang id-nya tidak ada dalam targetIds, yang berarti node tersebut tidak menjadi target dari edge manapun dan kemungkinan besar merupakan start node dalam workflow
  const startNode =
    parsedWorkflow.nodes.find(
      node => !targetIds.includes(node.id)
    )

  // inisialisasi struktur graph dengan properti nodes (array) dan relationships (array) yang akan diisi berdasarkan parsedWorkflow
  const graph = {
    nodes: [],
    relationships: [],
  }

  // menambahkan node untuk workflow itu sendiri dengan tipe "WORKFLOW" dan properti yang sesuai dengan data yang diterima
  graph.nodes.push({ 
    id: workflowId,

    type: "WORKFLOW",

    properties: {
      workflow_id: workflowId,

      workflow_name: workflowName,

      description:
        parsedWorkflow.description || "",

      start:
        startNode?.id || "",
    },
  })

  // iterasi setiap node dalam parsedWorkflow.nodes untuk menambahkan node ke struktur graph dengan tipe "ACTION" dan properti yang sesuai dengan data yang diterima
  parsedWorkflow.nodes.forEach((node) => { 

    graph.nodes.push({
      id: node.id,
      type: "ACTION",

      properties: {
        id: node.id,
        label: node.label,
        app_name: node.app_name,
        action_name: node.action_name,
        category: node.category,
        position: JSON.stringify(node.position || {}),
        app_id: node.app_id,
        app_version: node.app_version,
        isStartNode: startNode?.id === node.id,
        environment: node.environment || "Cloud",
        parameters:
          JSON.stringify(
            node.parameters || []
          ),
      },
    })

    // menambahkan relationship dari workflow ke setiap node dengan tipe "CONTAINS" untuk menunjukkan bahwa workflow mengandung action tersebut
    graph.relationships.push({
      source: workflowId,
      target: node.id,
      type: "CONTAINS",
      properties: {
        label: "contains_action",
      },
    })
  })

  // iterasi setiap edge dalam parsedWorkflow.edges untuk menambahkan relationship ke struktur graph dengan tipe "CONNECTS_TO" dan properti yang sesuai dengan data yang diterima
  parsedWorkflow.edges.forEach((edge) => {

    graph.relationships.push({
      source: edge.source,
      target: edge.target,
      type: "CONNECTS_TO",
      properties: {
        conditions:
          edge.conditions || "",

        label:
          edge.label || "",
      },
    })
  })

  return graph
}

module.exports = {
  buildGraph,
}