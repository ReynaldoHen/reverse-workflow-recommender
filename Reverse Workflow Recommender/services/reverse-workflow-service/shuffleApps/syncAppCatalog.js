const { fetchAllApps } = require("./fetchApps")
const { saveAppsToNeo4j } = require("./saveAppsToNeo4j")
const { saveAppsToPostgres } = require("./saveAppsToPostgres")
const driver = require("../neo4j/neo4jDriver")

const TTL_HOURS = parseInt(process.env.APP_SYNC_TTL_HOURS || "24", 10)

async function checkSyncNeeded() {
  const session = driver.session()

  try {
    const result = await session.run(`
      OPTIONAL MATCH (m:APP_SYNC_META {id: "singleton"})
      OPTIONAL MATCH (n:APP)
      RETURN 
        m.last_synced_at AS lastSyncedAt,
        m.total_apps AS totalApps,
        count(n) AS appCount
    `)

    const record = result.records?.[0]

    if (!record) {
      console.log("[apps] No sync meta found → force sync")
      return { needed: true }
    }

    const appCount = record.get("appCount")?.toNumber?.() || 0
    const rawTs = record.get("lastSyncedAt") || null

    if (!rawTs || appCount === 0) {
      console.log("[apps] Sync required (empty DB)")
      return { needed: true }
    }

    const lastSyncedAt = new Date(rawTs.toString())
    const ageHours = (Date.now() - lastSyncedAt.getTime()) / 3_600_000

    if (ageHours > TTL_HOURS) {
      console.log(`[apps] Sync required (stale ${ageHours.toFixed(1)}h)`)
      return { needed: true }
    }

    console.log(`[apps] Cache fresh (${ageHours.toFixed(1)}h old)`)
    return { needed: false }

  } catch (err) {
    console.warn("[apps] TTL check failed → forcing sync:", err.message)
    return { needed: true }
  } finally {
    await session.close()
  }
}

async function syncAppCatalog() {
  console.log("[apps] ── App Catalog Sync ──────────────────")
  console.log(`[apps] TTL = ${TTL_HOURS}h`)

  const { needed } = await checkSyncNeeded()

  if (!needed) {
    return { success: true, skipped: true }
  }

  try {
    const apps = await fetchAllApps()

    if (!apps?.length) {
      console.warn("[apps] Empty catalog → skip sync")
      return { success: false, reason: "empty_catalog" }
    }

    await saveAppsToNeo4j(apps)
    await saveAppsToPostgres(apps)

    console.log(`[apps] Neo4j + PostgreSQL synced (${apps.length} apps)`)
    return { success: true, count: apps.length }

  } catch (err) {
    console.error("[apps] Sync failed:", err.message)
    return { success: false, error: err.message }
  }
}

module.exports = {
  syncAppCatalog,
  checkSyncNeeded
}