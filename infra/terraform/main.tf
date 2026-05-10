terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

variable "region" { default = "us-east-1" }
variable "cluster_name" { default = "predictormaster" }
variable "node_instance_types" { default = ["m6i.xlarge"] }
variable "gpu_instance_types" { default = ["g5.2xlarge"] }

provider "aws" {
  region = var.region
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.5"

  name                 = "${var.cluster_name}-vpc"
  cidr                 = "10.42.0.0/16"
  azs                  = ["${var.region}a", "${var.region}b", "${var.region}c"]
  private_subnets      = ["10.42.1.0/24", "10.42.2.0/24", "10.42.3.0/24"]
  public_subnets       = ["10.42.101.0/24", "10.42.102.0/24", "10.42.103.0/24"]
  enable_nat_gateway   = true
  single_nat_gateway   = true
  enable_dns_hostnames = true
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.29"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets

  enable_irsa = true

  eks_managed_node_groups = {
    cpu = {
      desired_size   = 3
      max_size       = 20
      min_size       = 3
      instance_types = var.node_instance_types
      capacity_type  = "SPOT"
    }
    gpu = {
      desired_size   = 1
      max_size       = 8
      min_size       = 1
      instance_types = var.gpu_instance_types
      capacity_type  = "ON_DEMAND"
      taints = [{
        key    = "nvidia.com/gpu"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
      labels = { "node.kubernetes.io/role" = "gpu" }
    }
  }
}

resource "aws_s3_bucket" "feature_store_offline" {
  bucket        = "${var.cluster_name}-feature-store-offline"
  force_destroy = false
}

resource "aws_s3_bucket_lifecycle_configuration" "tiering" {
  bucket = aws_s3_bucket.feature_store_offline.id
  rule {
    id     = "warm-to-cold"
    status = "Enabled"
    transition { days = 30  storage_class = "STANDARD_IA" }
    transition { days = 180 storage_class = "GLACIER_IR" }
  }
}

output "cluster_name" { value = module.eks.cluster_name }
output "feature_store_bucket" { value = aws_s3_bucket.feature_store_offline.bucket }
