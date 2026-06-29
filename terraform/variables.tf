variable "project_name" {
  type        = string
  description = "Lowercase project identifier."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,31}$", var.project_name))
    error_message = "project_name must start with a letter, use only [a-z0-9-], and be at most 32 characters (ALB/RDS naming compliance)."
  }
}

variable "environment" {
  type        = string
  description = "Deployment environment."
  default     = "dev"
}

variable "aws_region" {
  type        = string
  description = "AWS region."
}

variable "strategy_tier" {
  type        = string
  description = "Cost tier."
  validation {
    condition     = contains(["low_cost", "balanced", "high_performance"], var.strategy_tier)
    error_message = "strategy_tier must be one of: low_cost, balanced, high_performance."
  }
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block (a /16 is assumed for the cidrsubnet allocation)."
}

variable "eks_version" {
  type        = string
  description = "EKS Kubernetes version."
  default     = "1.30"
}

variable "node_instance_type" {
  type        = string
  description = "EC2 instance type for the single EKS worker node."
}
