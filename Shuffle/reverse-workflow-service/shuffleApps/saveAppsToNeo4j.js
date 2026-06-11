const driver = require("../neo4j/neo4jDriver")

// ─────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────

/**
 * Replace ALL app data in Neo4j with fresh data from Shuffle.
 *
 * Strategy: sync_batch_id
 *  1. Generate a unique batchId for this run.
 *  2. MERGE every APP / ACTION_TEMPLATE / PARAMETER_TEMPLATE
 *     and stamp it with the batchId.
 *  3. After all upserts succeed, DELETE nodes whose batchId
 *     is older than this run (i.e. apps removed from Shuffle).
 *  4. Persist sync metadata (timestamp + count) for TTL checks.
 *
 * This is safe against mid-sync failures: if the process dies
 * partway through, no data is lost — the old nodes remain until
 * the next successful full run.
 */
async function saveAppsToNeo4j(apps) {

  const session   = driver.session()
  const batchId   = Date.now().toString()
  let   savedCount = 0

  console.log(
    `[apps] Starting Neo4j sync — batch ${batchId} ` +
    `(${apps.length} apps)`
  )

  try {

    for (const app of apps) {

      // ────────────────────────────────────────
      // APP NODE
      // ────────────────────────────────────────
      await session.run(
        `
        MERGE (a:APP {app_id: $app_id})

        SET a.app_name     = $app_name,
            a.app_version  = $app_version,
            a.small_image  = $small_image,
            a.large_image  = $large_image,
            a.sync_batch   = $batchId
        `,
        {
          app_id:      app.id,
          app_name:    app.name,
          app_version: app.app_version      || "",
          small_image: app.small_image      || "",
          large_image: app.large_image      || "",
          batchId,
        }
      )

      // ────────────────────────────────────────
      // ACTION_TEMPLATE NODES
      // ────────────────────────────────────────
      for (const action of (app.actions || [])) {

        const actionKey = `${app.id}_${action.name}`

        await session.run(
          `
          MERGE (act:ACTION_TEMPLATE {action_key: $action_key})

          SET act.action_name  = $action_name,
              act.action_label = $action_label,
              act.description  = $description,
              act.sync_batch   = $batchId
          `,
          {
            action_key:   actionKey,
            action_name:  action.name,
            action_label: action.label       || "",
            description:  action.description || "",
            batchId,
          }
        )

        // APP ──HAS_ACTION──> ACTION_TEMPLATE
        await session.run(
          `
          MATCH (a:APP           {app_id:     $app_id})
          MATCH (act:ACTION_TEMPLATE {action_key: $action_key})
          MERGE (a)-[:HAS_ACTION]->(act)
          `,
          { app_id: app.id, action_key: actionKey }
        )

        // ────────────────────────────────────────
        // PARAMETER_TEMPLATE NODES
        // ────────────────────────────────────────
        for (const param of (action.parameters || [])) {

          const paramKey = `${actionKey}_${param.name}`

          await session.run(
            `
            MERGE (p:PARAMETER_TEMPLATE {parameter_key: $paramKey})

            SET p.parameter_name = $parameter_name,
                p.required       = $required,
                p.parameter_type = $parameter_type,
                p.description    = $description,
                p.sync_batch     = $batchId
            `,
            {
              paramKey,
              parameter_name: param.name,
              required:       param.required        || false,
              parameter_type: param.schema?.type    || "string",
              description:    param.description     || "",
              batchId,
            }
          )

          // ACTION_TEMPLATE ──REQUIRES_PARAMETER──> PARAMETER_TEMPLATE
          await session.run(
            `
            MATCH (act:ACTION_TEMPLATE  {action_key:    $action_key})
            MATCH (p:PARAMETER_TEMPLATE {parameter_key: $paramKey})
            MERGE (act)-[:REQUIRES_PARAMETER]->(p)
            `,
            { action_key: actionKey, paramKey }
          )
        }
      }

      savedCount++
    }

    // ────────────────────────────────────────
    // REPLACE: remove stale nodes from old batches
    // ────────────────────────────────────────
    console.log("[apps] Removing stale nodes from previous batches...")

    // detach-delete stale PARAMETERs
    const delParams = await session.run(
      `
      MATCH (p:PARAMETER_TEMPLATE)
      WHERE p.sync_batch <> $batchId OR p.sync_batch IS NULL
      WITH  p, count(p) AS n
      DETACH DELETE p
      RETURN n
      `,
      { batchId }
    )

    // detach-delete stale ACTIONs
    const delActions = await session.run(
      `
      MATCH (act:ACTION_TEMPLATE)
      WHERE act.sync_batch <> $batchId OR act.sync_batch IS NULL
      WITH  act, count(act) AS n
      DETACH DELETE act
      RETURN n
      `,
      { batchId }
    )

    // detach-delete stale APPs
    const delApps = await session.run(
      `
      MATCH (a:APP)
      WHERE a.sync_batch <> $batchId OR a.sync_batch IS NULL
      WITH  a, count(a) AS n
      DETACH DELETE a
      RETURN n
      `,
      { batchId }
    )

    // ────────────────────────────────────────
    // PERSIST SYNC METADATA (for TTL checks)
    // ────────────────────────────────────────
    await session.run(
      `
      MERGE (m:APP_SYNC_META {id: "singleton"})

      SET m.last_synced_at = datetime(),
          m.last_batch_id  = $batchId,
          m.total_apps     = $total
      `,
      { batchId, total: savedCount }
    )

    console.log(
      `[apps] Sync complete — ${savedCount} apps saved to Neo4j`
    )

  } catch (error) {

    console.error("[apps] saveAppsToNeo4j error:", error)
    throw error   // re-throw so syncAppCatalog can handle it

  } finally {

    await session.close()
  }
}

module.exports = { saveAppsToNeo4j }