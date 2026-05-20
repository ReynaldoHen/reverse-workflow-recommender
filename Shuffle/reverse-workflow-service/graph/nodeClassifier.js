// fungsi untuk mengklasifikasikan node berdasarkan nama aplikasi dan nama aksi yang terkait dengan node tersebut
const classifyNode = (node) => {

  const appName = node.app_name?.toLowerCase() || "" // mengambil nama aplikasi dari properti node dan mengubahnya menjadi huruf kecil untuk memudahkan pencocokan pola, jika tidak ada nama aplikasi maka gunakan string kosong
  const actionName = node.action_name?.toLowerCase() || ""  // mengambil nama aksi dari properti node dan mengubahnya menjadi huruf kecil untuk memudahkan pencocokan pola, jika tidak ada nama aksi maka gunakan string kosong

  // SIEM
  if (
    appName.includes("elastic") ||
    appName.includes("elk")
  ) {
    return "SIEM"
  }

  // Firewall
  if (
    appName.includes("fortigate") ||
    appName.includes("firewall")
  ) {
    return "FIREWALL"
  }

  // Notification
  if (
    appName.includes("slack") ||
    appName.includes("email")
  ) {
    return "NOTIFICATION"
  }

  // Threat Response
  if (
    actionName.includes("block") ||
    actionName.includes("deny")
  ) {
    return "MITIGATION"
  }

  return "ACTION"
}

module.exports = { // ekspor fungsi classifyNode agar dapat digunakan di file lain untuk mengklasifikasikan jenis node berdasarkan properti yang dimiliki
  classifyNode,
}