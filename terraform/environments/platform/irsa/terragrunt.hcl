include "root" {
  path = find_in_parent_folders("terragrunt.hcl")
}

terraform {
  source = "../../../modules/irsa"
}

inputs = {
  cluster_oidc_issuer_url = "https://oidc.eks.ap-southeast-1.amazonaws.com/id/AAD79ECFFEBB3296CA8482CE963AD82A"

  roles = {
    agent-orchestrator = {
      namespace       = "agents"
      service_account = "agent-orchestrator"
      role_name       = "agent-orchestrator-role"
      policy_arns = [
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonEventBridgeFullAccess",
        "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
      ]
    }
  }
}
