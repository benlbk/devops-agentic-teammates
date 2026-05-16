include "root" {
  path = find_in_parent_folders("terragrunt.hcl")
}

terraform {
  source = "../../../modules/eks-cluster"
}

dependency "vpc" {
  config_path = "../vpc"
}

inputs = {
  cluster_name       = "mies-eks"
  cluster_version    = "1.31"
  vpc_id             = dependency.vpc.outputs.vpc_id
  private_subnet_ids = dependency.vpc.outputs.private_subnet_ids

  node_groups = {
    agent-workers = {
      instance_types = ["m6i.xlarge", "m6i.2xlarge"]
      min_size       = 2
      max_size       = 10
      desired_size   = 2
      labels         = { "workload-type" = "agent" }
      taints         = []
    }
    dashboard = {
      instance_types = ["t3.large"]
      min_size       = 1
      max_size       = 3
      desired_size   = 1
      labels         = { "workload-type" = "dashboard" }
      taints         = []
    }
  }

  enable_cluster_autoscaler = true
}
