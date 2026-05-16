# ---------------------------------------------------------------------------------------------------------------------
# EVENTBRIDGE MODULE
# Custom event bus for agent communication with schema registry
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

resource "aws_cloudwatch_event_bus" "agents" {
  name = var.project_name
  tags = var.tags
}

resource "aws_schemas_registry" "agents" {
  name        = "${var.project_name}-${var.environment}"
  description = "Schema registry for agent events"
  tags        = var.tags
}

resource "aws_schemas_schema" "agent_task_requested" {
  name          = "AgentTaskRequested"
  registry_name = aws_schemas_registry.agents.name
  type          = "OpenApi3"
  description   = "Event schema for agent task requests"
  content = jsonencode({
    openapi = "3.0.0"
    info = { title = "AgentTaskRequested", version = "1.0.0" }
    paths = {}
    components = {
      schemas = {
        AWSEvent = {
          type = "object"
          required = ["detail-type", "source", "detail"]
          properties = {
            "detail-type" = { type = "string", enum = ["agent.task.requested"] }
            source        = { type = "string" }
            detail = {
              type = "object"
              properties = {
                agentType = { type = "string", enum = ["plan-collaborate", "code-build", "test-secure", "release-deploy", "operate-monitor"] }
                taskType  = { type = "string" }
                taskId    = { type = "string" }
                context   = { type = "object" }
                policy    = { type = "object" }
              }
            }
          }
        }
      }
    }
  })
}

resource "aws_schemas_schema" "agent_task_completed" {
  name          = "AgentTaskCompleted"
  registry_name = aws_schemas_registry.agents.name
  type          = "OpenApi3"
  description   = "Event schema for agent task completions"
  content = jsonencode({
    openapi = "3.0.0"
    info = { title = "AgentTaskCompleted", version = "1.0.0" }
    paths = {}
    components = {
      schemas = {
        AWSEvent = {
          type = "object"
          required = ["detail-type", "source", "detail"]
          properties = {
            "detail-type" = { type = "string", enum = ["agent.task.completed"] }
            source        = { type = "string" }
            detail = {
              type = "object"
              properties = {
                agentType   = { type = "string" }
                taskType    = { type = "string" }
                taskId      = { type = "string" }
                status      = { type = "string", enum = ["completed", "failed", "cancelled"] }
                output      = { type = "object" }
                nextActions = { type = "array" }
              }
            }
          }
        }
      }
    }
  })
}

# Event rules for routing to agent targets
resource "aws_cloudwatch_event_rule" "code_build_tasks" {
  name           = "${var.project_name}-code-build-tasks"
  event_bus_name = aws_cloudwatch_event_bus.agents.name
  description    = "Route tasks to Code & Build agent"

  event_pattern = jsonencode({
    source      = ["devops-agentic-teammates"]
    detail-type = ["agent.task.requested"]
    detail = {
      agentType = ["code-build"]
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "test_secure_tasks" {
  name           = "${var.project_name}-test-secure-tasks"
  event_bus_name = aws_cloudwatch_event_bus.agents.name
  description    = "Route tasks to Test & Secure agent"

  event_pattern = jsonencode({
    source      = ["devops-agentic-teammates"]
    detail-type = ["agent.task.requested"]
    detail = {
      agentType = ["test-secure"]
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "release_deploy_tasks" {
  name           = "${var.project_name}-release-deploy-tasks"
  event_bus_name = aws_cloudwatch_event_bus.agents.name
  description    = "Route tasks to Release & Deploy agent"

  event_pattern = jsonencode({
    source      = ["devops-agentic-teammates"]
    detail-type = ["agent.task.requested"]
    detail = {
      agentType = ["release-deploy"]
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "operate_monitor_tasks" {
  name           = "${var.project_name}-operate-monitor-tasks"
  event_bus_name = aws_cloudwatch_event_bus.agents.name
  description    = "Route tasks to Operate & Monitor agent"

  event_pattern = jsonencode({
    source      = ["devops-agentic-teammates"]
    detail-type = ["agent.task.requested"]
    detail = {
      agentType = ["operate-monitor"]
    }
  })

  tags = var.tags
}

# Dead letter queue for failed events
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project_name}-${var.environment}-events-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = var.tags
}

output "event_bus_name" { value = aws_cloudwatch_event_bus.agents.name }
output "event_bus_arn" { value = aws_cloudwatch_event_bus.agents.arn }
output "schema_registry_name" { value = aws_schemas_registry.agents.name }
output "dlq_arn" { value = aws_sqs_queue.dlq.arn }
