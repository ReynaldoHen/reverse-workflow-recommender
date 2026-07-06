const driver = require("../neo4j/neo4jDriver")

const safe = (v) => {
  if (v === null || v === undefined) return ""
  if (typeof v === "object") return JSON.stringify(v)
  return v
}

async function saveAppsToNeo4j(apps) {
  const session = driver.session()
  const batchId = Date.now().toString()

  console.log(`[apps] Saving ${apps.length} apps (batch ${batchId})`)

  try {

    for (const app of apps) {

      await session.run(
        `
        MERGE (a:APP {app_id: $app_id})
        SET a.app_name     = $app_name,
            a.app_version  = $app_version,
            a.large_image  = $large_image,
            a.sync_batch   = $batchId
        `,
        {
          app_id: app.id,
          app_name: safe(app.name),
          app_version: safe(app.app_version),
          large_image: safe(app.large_image),
          batchId,
        }
      )

      for (const action of (app.actions || [])) {

        const actionKey = `${app.id}_${action.name}`

        await session.run(
          `
          MERGE (a:ACTION_TEMPLATE {action_key: $key})
          SET a.name        = $name,
              a.label       = $label,
              a.description = $description,
              a.parameters  = $parameters,
              a.sync_batch  = $batchId
          `,
          {
            key: actionKey,
            name: safe(action.name),
            label: safe(action.label),
            description: safe(action.description),
            parameters: safe(action.parameters),
            batchId,
          }
        )

        await session.run(
          `
          MATCH (APP:APP {app_id: $app_id})
          MATCH (act:ACTION_TEMPLATE {action_key: $key})
          MERGE (APP)-[:HAS_ACTION]->(act)
          `,
          {
            app_id: app.id,
            key: actionKey,
          }
        )

        for (const param of (action.parameters || [])) {

          const paramKey = `${actionKey}_${param.name}`

          await session.run(
            `
            MERGE (p:PARAMETER_TEMPLATE {parameter_key: $paramKey})
            SET p.parameter_name = $name,
                p.required       = $required,
                p.parameter_type = $type,
                p.description    = $description,
                p.sync_batch     = $batchId
            `,
            {
              paramKey,
              name: safe(param.name),
              required: !!param.required,
              type: safe(param.schema?.type || param.type || "string"),
              description: safe(param.description),
              batchId,
            }
          )

          await session.run(
            `
            MATCH (act:ACTION_TEMPLATE {action_key: $actionKey})
            MATCH (p:PARAMETER_TEMPLATE {parameter_key: $paramKey})
            MERGE (act)-[:REQUIRES_PARAMETER]->(p)
            `,
            {
              actionKey,
              paramKey,
            }
          )
        }
      }
    }

    await session.run(
      `
      MERGE (m:APP_SYNC_META {id: "singleton"})
      SET m.last_synced_at = datetime(),
          m.total_apps     = $total,
          m.last_batch_id  = $batchId
      `,
      {
        total: apps.length,
        batchId,
      }
    )

    console.log("[apps] Sync complete")

  } catch (err) {
    console.error("[apps] Neo4j error:", err.message)
    throw err
  } finally {
    await session.close()
  }
}

module.exports = {
  saveAppsToNeo4j
}