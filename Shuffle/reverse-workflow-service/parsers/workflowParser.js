// fungsi untuk parsing data actions dan branches yang diterima dari server.js menjadi struktur nodes dan edges yang dapat digunakan untuk membangun graph
const parseWorkflow = (actions, branches) => { 

  // iterasi setiap action yang diterima dan buat node dengan properti yang sesuai dengan data yang diterima
  const nodes = actions.map((action) => { 
    return {
      id: action.id,
      label: action.label,
      app_name: action.app_name,
      action_name: action.name,
      category: action.category,
      position: action.position,
    }
  })

  // iterasi setiap branch yang diterima dan buat edge dengan properti yang sesuai dengan data yang diterima
  const edges = branches.map((branch) => { 
    return {
      source: branch.source_id,
      target: branch.destination_id,
    }
  })

  return {
    nodes,
    edges,
  }
}

module.exports = { // ekspor fungsi parseWorkflow agar dapat digunakan di file lain
  parseWorkflow,
}