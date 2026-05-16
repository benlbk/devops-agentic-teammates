output "collection_endpoint" {
  description = "OpenSearch Serverless collection endpoint"
  value       = aws_opensearchserverless_collection.rag.collection_endpoint
}

output "collection_arn" {
  description = "OpenSearch Serverless collection ARN"
  value       = aws_opensearchserverless_collection.rag.arn
}

output "collection_id" {
  description = "OpenSearch Serverless collection ID"
  value       = aws_opensearchserverless_collection.rag.id
}

output "vpc_endpoint_id" {
  description = "VPC endpoint ID for OpenSearch"
  value       = aws_opensearchserverless_vpc_endpoint.main.id
}
