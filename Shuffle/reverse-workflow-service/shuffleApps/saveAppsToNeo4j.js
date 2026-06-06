const driver = require("../neo4j/neo4jDriver")

async function saveAppsToNeo4j(apps) {

  const session = driver.session()

  try {

    for (const app of apps) {

      // =====================================================
      // APP NODE
      // =====================================================
      await session.run(
        `
        MERGE (a:APP {app_id:$app_id})

        SET a.app_name = $app_name,
            a.app_version = $app_version,
            a.small_image = $small_image,
            a.large_image = $large_image
        `,
        {
          app_id: app.id,
          app_name: app.name,
          app_version: app.app_version,
          small_image: app.small_image || "",
          large_image: app.large_image || "",
        }
      )

      // =====================================================
      // ACTIONS_TEMPLATE
      // =====================================================
      for (const action of (app.actions || [])) {

        const actionKey =
          `${app.id}_${action.name}`

        await session.run(
          `
          MERGE (act:ACTION_TEMPLATE {
            action_key:$action_key
          })

          SET act.action_name = $action_name,
              act.action_label = $action_label,
              act.description = $description
          `,
          {
            action_key: actionKey,
            action_name: action.name,
            action_label: action.label || "",
            description: action.description || "",
          }
        )

        // APP -> ACTION
        await session.run(
          `
          MATCH (a:APP {app_id:$app_id})
          MATCH (act:ACTION_TEMPLATE {
            action_key:$action_key
          })

          MERGE (a)-[:HAS_ACTION]->(act)
          `,
          {
            app_id: app.id,
            action_key: actionKey,
          }
        )

        // =====================================================
        // PARAMETER_TEMPLATE
        // =====================================================
        for (const param of (action.parameters || [])) {

          const parameterKey =
            `${actionKey}_${param.name}`

          await session.run(
            `
            MERGE (p:PARAMETER_TEMPLATE {
              parameter_key:$parameter_key
            })

            SET p.parameter_name = $parameter_name,
                p.required = $required,
                p.parameter_type = $parameter_type,
                p.description = $description
            `,
            {
              parameter_key: parameterKey,
              parameter_name: param.name,
              required: param.required || false,
              parameter_type:
                param.schema?.type || "string",
              description:
                param.description || "",
            }
          )

          await session.run(
            `
            MATCH (act:ACTION_TEMPLATE {
              action_key:$action_key
            })

            MATCH (p:PARAMETER_TEMPLATE {
              parameter_key:$parameter_key
            })

            MERGE (act)-[:REQUIRES_PARAMETER]->(p)
            `,
            {
              action_key: actionKey,
              parameter_key: parameterKey,
            }
          )
        }
      }
    }

    console.log(
      `[apps] ${apps.length} apps synced to Neo4j`
    )

  } catch (error) {

    console.error(
      "[apps] saveAppsToNeo4j error:",
      error
    )

  } finally {

    await session.close()

  }
}

module.exports = {
  saveAppsToNeo4j,
}