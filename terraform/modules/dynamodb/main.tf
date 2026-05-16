# ---------------------------------------------------------------------------------------------------------------------
# DYNAMODB MODULE
# Agent state table with PK/SK design, GSIs, TTL, and PITR
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

variable "state_table_name" {
  type    = string
  default = ""
}

variable "audit_table_name" {
  type    = string
  default = ""
}

variable "approvals_table_name" {
  type    = string
  default = ""
}

locals {
  state_table_name     = var.state_table_name != "" ? var.state_table_name : "${var.project_name}-${var.environment}-agent-state"
  audit_table_name     = var.audit_table_name != "" ? var.audit_table_name : "${var.project_name}-${var.environment}-audit-log"
  approvals_table_name = var.approvals_table_name != "" ? var.approvals_table_name : "${var.project_name}-${var.environment}-approvals"
}

resource "aws_dynamodb_table" "agent_state" {
  name         = local.state_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  # GSI1: Query by repository
  global_secondary_index {
    name            = "GSI1-Repository"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  # GSI2: Query by status
  global_secondary_index {
    name            = "GSI2-Status"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "TTL"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-agent-state"
  })

  lifecycle {
    ignore_changes = [ttl]
  }
}

# Approval requests table
resource "aws_dynamodb_table" "approvals" {
  name         = local.approvals_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "TTL"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-approvals"
  })
}

# Audit log table
resource "aws_dynamodb_table" "audit_log" {
  name         = local.audit_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  ttl {
    attribute_name = "TTL"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-audit-log"
  })
}

output "agent_state_table_name" { value = aws_dynamodb_table.agent_state.name }
output "agent_state_table_arn" { value = aws_dynamodb_table.agent_state.arn }
output "approvals_table_name" { value = aws_dynamodb_table.approvals.name }
output "approvals_table_arn" { value = aws_dynamodb_table.approvals.arn }
output "audit_log_table_name" { value = aws_dynamodb_table.audit_log.name }
output "audit_log_table_arn" { value = aws_dynamodb_table.audit_log.arn }
