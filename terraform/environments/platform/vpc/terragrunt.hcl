include "root" {
  path = find_in_parent_folders("terragrunt.hcl")
}

terraform {
  source = "../../../modules/vpc"
}

inputs = {
  vpc_cidr              = "10.0.0.0/16"
  enable_vpc_endpoints  = true
}
