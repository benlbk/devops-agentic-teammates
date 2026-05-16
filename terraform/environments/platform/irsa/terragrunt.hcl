include "root" {
  path = find_in_parent_folders("terragrunt.hcl")
}

terraform {
  source = "../../../modules/irsa"
}

dependency "eks" {
  config_path = "../eks"
}

inputs = {
  cluster_oidc_issuer_url = dependency.eks.outputs.cluster_oidc_issuer_url

  roles = {
    agent-orchestrator = {
      namespace       = "agents"
      service_account = "agent-orchestrator"
      policy_arns = [
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonEventBridgeFullAccess",
        "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
      ]
    }
  }
}
