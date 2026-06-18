function buildReverseWorkflowPrompt({
  workflow = {},
  nodes = [],
  relationships = [],
}) {
  return {
    system: `
You are a SOAR workflow reconstruction engine.

Your job:
- Rebuild a valid Shuffle SOAR reverse workflow JSON
- Based ONLY on provided graph context
- Do NOT hallucinate apps or actions
- Use only available apps/actions from app_catalog
- Output MUST be same as this JSON format (no markdown)
- Refered taking data from postgres database by app_id
`,

    input: {
      workflow: {
        id: workflow?.workflow_id || "",
        name: workflow?.workflow_name || "",
        description: workflow?.description || ""
      },

      graph: {
        nodes,
        relationships
      },

      resolved_apps = await app_registry.get_map()
    },

    output_format: {
      workflow: {
        name: "string",
        description: "string",
        actions: [
          {
            id: "string",
            app_name: "string",
            app_id: "string",
            action_name: "string",
            label: "string",
            parameters: {}
          }
        ],
        edges: [
          {
            source: "string",
            target: "string",
            condition: "string"
          }
        ]
      }
    },

    rules: [
      "Only use apps from app_catalog",
      "Preserve graph structure",
      "Ensure first node is start node",
      "Do not invent parameters",
      "If missing info, infer conservatively"
    ]
  }
}

module.exports = { buildReverseWorkflowPrompt }