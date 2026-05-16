# ---------------------------------------------------------------------------------------------------------------------
# API GATEWAY MODULE - Agent Control Plane REST API
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" {
  type = string
}
variable "environment" {
  type = string
}
variable "event_bus_arn" {
  type = string
}
variable "tags" {
  type    = map(string)
  default = {}
}

resource "aws_api_gateway_rest_api" "main" {
  name        = "${var.project_name}-${var.environment}-api"
  description = "Agent Control Plane API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = var.tags
}

# Webhook resource
resource "aws_api_gateway_resource" "webhooks" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "webhooks"
}

resource "aws_api_gateway_resource" "github_webhook" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.webhooks.id
  path_part   = "github"
}

resource "aws_api_gateway_method" "github_webhook_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.github_webhook.id
  http_method   = "POST"
  authorization = "NONE"
}

# Agents resource
resource "aws_api_gateway_resource" "agents" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "agents"
}

resource "aws_api_gateway_resource" "agent_tasks" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.agents.id
  path_part   = "tasks"
}

resource "aws_api_gateway_method" "agent_tasks_get" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.agent_tasks.id
  http_method   = "GET"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.lambda.id
}

resource "aws_api_gateway_method" "agent_tasks_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.agent_tasks.id
  http_method   = "POST"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.lambda.id
}

# Lambda authorizer
resource "aws_api_gateway_authorizer" "lambda" {
  name                   = "${var.project_name}-authorizer"
  rest_api_id            = aws_api_gateway_rest_api.main.id
  authorizer_uri         = aws_lambda_function.authorizer.invoke_arn
  type                   = "TOKEN"
  authorizer_credentials = aws_iam_role.api_gateway.arn
}

# API Gateway IAM Role
resource "aws_iam_role" "api_gateway" {
  name_prefix = "${var.project_name}-${var.environment}-apigw-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "api_gateway" {
  name_prefix = "invoke-lambda-"
  role        = aws_iam_role.api_gateway.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action   = "lambda:InvokeFunction"
      Effect   = "Allow"
      Resource = [aws_lambda_function.authorizer.arn, aws_lambda_function.event_router.arn]
    }]
  })
}

# Authorizer Lambda
resource "aws_lambda_function" "authorizer" {
  function_name = "${var.project_name}-${var.environment}-authorizer"
  runtime       = "python3.12"
  handler       = "index.handler"
  role          = aws_iam_role.lambda_authorizer.arn
  timeout       = 10

  filename         = data.archive_file.authorizer.output_path
  source_code_hash = data.archive_file.authorizer.output_base64sha256

  environment {
    variables = {
      PROJECT_NAME = var.project_name
      ENVIRONMENT  = var.environment
    }
  }

  tags = var.tags
}

data "archive_file" "authorizer" {
  type        = "zip"
  output_path = "${path.module}/authorizer.zip"

  source {
    content = <<-PYTHON
import os
import json

def handler(event, context):
    token = event.get("authorizationToken", "")
    method_arn = event.get("methodArn", "")

    # Validate token (implement proper JWT validation)
    if not token or not token.startswith("Bearer "):
        raise Exception("Unauthorized")

    return {
        "principalId": "agent-api-user",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": "Allow",
                "Resource": method_arn,
            }],
        },
    }
PYTHON
    filename = "index.py"
  }
}

resource "aws_iam_role" "lambda_authorizer" {
  name_prefix = "${var.project_name}-${var.environment}-auth-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "lambda_authorizer_basic" {
  role       = aws_iam_role.lambda_authorizer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Event Router Lambda (T-012)
resource "aws_lambda_function" "event_router" {
  function_name = "${var.project_name}-${var.environment}-event-router"
  runtime       = "python3.12"
  handler       = "index.handler"
  role          = aws_iam_role.event_router.arn
  timeout       = 30
  memory_size   = 256

  filename         = data.archive_file.event_router.output_path
  source_code_hash = data.archive_file.event_router.output_base64sha256

  environment {
    variables = {
      EVENT_BUS_NAME = "${var.project_name}-${var.environment}"
      PROJECT_NAME   = var.project_name
      ENVIRONMENT    = var.environment
    }
  }

  tags = var.tags
}

data "archive_file" "event_router" {
  type        = "zip"
  output_path = "${path.module}/event_router.zip"

  source {
    content = <<-PYTHON
import os
import json
import hashlib
import hmac
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

events_client = boto3.client("events")
secrets_client = boto3.client("secretsmanager")
EVENT_BUS_NAME = os.environ["EVENT_BUS_NAME"]

def verify_github_signature(payload_body: str, signature: str, secret: str) -> bool:
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload_body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

def route_github_event(event_type: str, payload: dict) -> dict:
    routing = {
        "pull_request": "code-build",
        "push": "code-build",
        "issues": "plan-collaborate",
        "issue_comment": "plan-collaborate",
        "check_run": "test-secure",
        "workflow_run": "test-secure",
        "release": "release-deploy",
    }
    agent_type = routing.get(event_type, "code-build")
    action = payload.get("action", "unknown")

    task_type_map = {
        ("pull_request", "opened"): "code-review",
        ("pull_request", "synchronize"): "code-review",
        ("pull_request", "closed"): "pr-closed",
        ("push", "unknown"): "code-push",
        ("issues", "opened"): "issue-created",
        ("workflow_run", "completed"): "workflow-completed",
        ("release", "published"): "release-published",
    }
    task_type = task_type_map.get((event_type, action), f"{event_type}-{action}")

    return {"agentType": agent_type, "taskType": task_type}

def handler(event, context):
    logger.info("Received event: %s", json.dumps(event, default=str))

    body = event.get("body", "{}")
    headers = event.get("headers", {})

    # Determine event source
    github_event = headers.get("X-GitHub-Event", headers.get("x-github-event", ""))

    if github_event:
        payload = json.loads(body) if isinstance(body, str) else body
        routing = route_github_event(github_event, payload)

        repo = payload.get("repository", {}).get("full_name", "unknown")
        pr_number = payload.get("pull_request", {}).get("number") or payload.get("number")

        entry = {
            "Source": "devops-agentic-teammates",
            "DetailType": "agent.task.requested",
            "EventBusName": EVENT_BUS_NAME,
            "Detail": json.dumps({
                "agentType": routing["agentType"],
                "taskType": routing["taskType"],
                "context": {
                    "repository": repo,
                    "prNumber": pr_number,
                    "githubEvent": github_event,
                    "action": payload.get("action"),
                    "sender": payload.get("sender", {}).get("login"),
                },
                "payload": payload,
            }),
        }

        events_client.put_events(Entries=[entry])
        logger.info("Routed %s event to %s agent", github_event, routing["agentType"])

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Event routed", "agent": routing["agentType"]}),
        }

    return {"statusCode": 400, "body": json.dumps({"error": "Unknown event source"})}
PYTHON
    filename = "index.py"
  }
}

resource "aws_iam_role" "event_router" {
  name_prefix = "${var.project_name}-${var.environment}-router-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "event_router_basic" {
  role       = aws_iam_role.event_router.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "event_router_events" {
  name_prefix = "eventbridge-"
  role        = aws_iam_role.event_router.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["events:PutEvents"]
        Effect   = "Allow"
        Resource = var.event_bus_arn
      },
      {
        Action   = ["secretsmanager:GetSecretValue"]
        Effect   = "Allow"
        Resource = "*"
        Condition = {
          StringLike = {
            "secretsmanager:ResourceTag/Project" = var.project_name
          }
        }
      },
    ]
  })
}

# API Gateway integration with event router Lambda
resource "aws_api_gateway_integration" "github_webhook" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.github_webhook.id
  http_method             = aws_api_gateway_method.github_webhook_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.event_router.invoke_arn
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.event_router.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

# WAF
resource "aws_wafv2_web_acl" "api" {
  name  = "${var.project_name}-${var.environment}-api-waf"
  scope = "REGIONAL"

  default_action { allow {} }

  rule {
    name     = "rate-limit"
    priority = 1

    action { block {} }

    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-rate-limit"
    }
  }

  rule {
    name     = "aws-managed-common-rules"
    priority = 2

    override_action { none {} }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-common-rules"
    }
  }

  visibility_config {
    sampled_requests_enabled   = true
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-api-waf"
  }

  tags = var.tags
}

# Deployment
resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  depends_on = [
    aws_api_gateway_integration.github_webhook,
  ]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "main" {
  deployment_id = aws_api_gateway_deployment.main.id
  rest_api_id   = aws_api_gateway_rest_api.main.id
  stage_name    = var.environment

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${var.project_name}-${var.environment}"
  retention_in_days = 30
  tags              = var.tags
}

resource "aws_wafv2_web_acl_association" "api" {
  resource_arn = aws_api_gateway_stage.main.arn
  web_acl_arn  = aws_wafv2_web_acl.api.arn
}

output "api_endpoint" { value = aws_api_gateway_stage.main.invoke_url }
output "api_id" { value = aws_api_gateway_rest_api.main.id }
output "webhook_url" { value = "${aws_api_gateway_stage.main.invoke_url}/webhooks/github" }
