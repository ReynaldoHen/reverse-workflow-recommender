const path = require("path")
// mengambil library dotenv untuk membaca file .env yang berisi konfigurasi seperti URI, username, dan password untuk koneksi ke database Neo4j
require("dotenv").config({ path: path.resolve(__dirname, "../../.env") })

const neo4j = require("neo4j-driver") // mengambil library neo4j-driver untuk membuat koneksi ke database Neo4j

const driver = neo4j.driver( // membuat instance driver untuk koneksi ke database Neo4j dengan menggunakan URI, username, dan password yang diambil dari file .env
  process.env.NEO4J_URI,
  neo4j.auth.basic(
    process.env.NEO4J_USERNAME,
    process.env.NEO4J_PASSWORD
  )
)

module.exports = driver // ekspor driver agar dapat digunakan di file lain untuk melakukan operasi database Neo4j