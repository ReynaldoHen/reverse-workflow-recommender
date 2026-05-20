const buildGraph = (parsedWorkflow) => {

  const graph = {
    nodes: [],
    relationships: [],
  }

  // buat node graph
  parsedWorkflow.nodes.forEach((node) => { // iterasi setiap node yang dihasilkan dari parsing workflow

    graph.nodes.push({ // buat node dengan properti yang sesuai dengan data yang dihasilkan dari parsing workflow
      id: node.id,
      type: "ACTION",
      properties: {
        label: node.label,
        app_name: node.app_name,
        action_name: node.action_name,
        category: node.category,
      },
    })
  })

  // buat relationship graph
  parsedWorkflow.edges.forEach((edge) => { // iterasi setiap edge yang dihasilkan dari parsing workflow

    graph.relationships.push({ // buat relationship dengan properti source, target, dan type yang sesuai dengan data yang dihasilkan dari parsing workflow
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