const { Pool } = require("pg")

const pool = new Pool({
  host: process.env.POSTGRES_HOST,
  port: process.env.POSTGRES_PORT,
  database: process.env.POSTGRES_DB,
  user: process.env.POSTGRES_USER,
  password: process.env.POSTGRES_PASSWORD,
})

pool.on("connect", () => {
  console.log("[postgres] connected")
})

pool.on("error", (err) => {
  console.error("[postgres]", err.message)
})

module.exports = pool