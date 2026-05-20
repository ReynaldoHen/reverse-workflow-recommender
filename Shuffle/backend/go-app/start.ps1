$env:SHUFFLE_OPENSEARCH_URL="https://localhost:9200"
$env:SHUFFLE_ELASTIC="true"
$env:SHUFFLE_OPENSEARCH_USERNAME="admin"
$env:SHUFFLE_OPENSEARCH_PASSWORD="StrongShufflePassword321!"
$env:SHUFFLE_OPENSEARCH_SKIPSSL_VERIFY="true"

go run main.go walkoff.go docker.go