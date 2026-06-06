const { fetchApps } = require("./fetchApps")
const { saveAppsToNeo4j } = require("./saveAppsToNeo4j")

async function syncAppCatalog() {

  console.log(
    "[apps] Starting App Catalog Sync..."
  )

  const apps = await fetchApps()

  if (!apps || apps.length === 0) {

    console.warn(
      "[apps] No apps found. Sync skipped."
    )

    return
  }

  await saveAppsToNeo4j(apps)

  console.log(
    "[apps] App Catalog Sync Complete"
  )
}

module.exports = {
  syncAppCatalog,
}