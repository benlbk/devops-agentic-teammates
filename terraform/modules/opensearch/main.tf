# ---------------------------------------------------------------------------------------------------------------------
# OPENSEARCH SERVERLESS MODULE
# Vector search collection for codebase RAG
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" {
  type = string
}
variable "environment" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}
variable "vpc_id" {
  type = string
}
variable "private_subnet_ids" {
  type = list(string)
}

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = "${var.project_name}-${var.environment}-enc"
  type = "encryption"
  policy = jsonencode({
    Rules = [{
      ResourceType = "collection"
      Resource     = ["collection/${var.project_name}-${var.environment}-rag"]
    }]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network" {
  name = "${var.project_name}-${var.environment}-net"
  type = "network"
  policy = jsonencode([{
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${var.project_name}-${var.environment}-rag"]
      },
      {
        ResourceType = "dashboard"
        Resource     = ["collection/${var.project_name}-${var.environment}-rag"]
      }
    ]
    AllowFromPublic = false
    SourceVPCEs     = [aws_opensearchserverless_vpc_endpoint.main.id]
  }])
}

resource "aws_opensearchserverless_vpc_endpoint" "main" {
  name               = "${var.project_name}-${var.environment}-vpce"
  vpc_id             = var.vpc_id
  subnet_ids         = var.private_subnet_ids
}

resource "aws_opensearchserverless_collection" "rag" {
  name = "${var.project_name}-${var.environment}-rag"
  type = "VECTORSEARCH"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
  ]

  tags = var.tags
}

resource "aws_opensearchserverless_access_policy" "agents" {
  name = "${var.project_name}-${var.environment}-access"
  type = "data"
  policy = jsonencode([{
    Rules = [
      {
        ResourceType = "index"
        Resource     = ["index/${var.project_name}-${var.environment}-rag/*"]
        Permission   = ["aoss:CreateIndex", "aoss:UpdateIndex", "aoss:DescribeIndex", "aoss:ReadDocument", "aoss:WriteDocument"]
      },
      {
        ResourceType = "collection"
        Resource     = ["collection/${var.project_name}-${var.environment}-rag"]
        Permission   = ["aoss:CreateCollectionItems", "aoss:DescribeCollectionItems", "aoss:UpdateCollectionItems"]
      }
    ]
    Principal = ["*"]
  }])
}

output "collection_endpoint" { value = aws_opensearchserverless_collection.rag.collection_endpoint }
output "collection_arn" { value = aws_opensearchserverless_collection.rag.arn }
output "collection_id" { value = aws_opensearchserverless_collection.rag.id }
