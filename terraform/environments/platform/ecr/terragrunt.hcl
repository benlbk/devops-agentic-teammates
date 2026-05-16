include "root" {
  path = find_in_parent_folders("terragrunt.hcl")
}

terraform {
  source = "../../../modules/ecr"
}

inputs = {
  repositories = [
    "agent-orchestrator",
    "target-frontend",
    "target-backend",
    "dashboard",
  ]
}
