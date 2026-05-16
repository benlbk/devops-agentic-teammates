include "root" {
  path = find_in_parent_folders("terragrunt.hcl")
}

terraform {
  source = "../../../modules/dynamodb"
}

inputs = {
  state_table_name     = "agent-state"
  audit_table_name     = "agent-audit"
  approvals_table_name = "agent-approvals"
}
