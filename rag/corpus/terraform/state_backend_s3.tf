# =============================================================================
# Terraform Remote State Backend — S3 + DynamoDB Locking
# This pattern is the production standard for Terraform state management.
# Resources: aws_s3_bucket, aws_dynamodb_table, terraform backend "s3"
# =============================================================================

# ---------------------------------------------------------------------------
# BOOTSTRAP FILE (bootstrap/main.tf) — run ONCE to create the backend infra
# After this runs, move state to the remote backend using `terraform init -migrate-state`
# ---------------------------------------------------------------------------

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5.0"
}

provider "aws" {
  region = "us-east-1"
}

# ---------------------------------------------------------------------------
# S3 bucket for Terraform state files
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "terraform_state" {
  bucket = "my-company-terraform-state-prod"

  # prevent_destroy protects the bucket from accidental `terraform destroy`
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name      = "terraform-state"
    ManagedBy = "terraform"
    Purpose   = "remote-state"
  }
}

# Enable versioning — allows rollback to any previous state file
resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Enable server-side encryption with AES-256 (or use KMS key ARN for stricter control)
resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block all public access — state files must never be public
resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# DynamoDB table for state locking and consistency
# Prevents two engineers (or CI runs) from applying simultaneously
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "terraform_locks" {
  name         = "terraform-state-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name      = "terraform-state-lock"
    ManagedBy = "terraform"
    Purpose   = "state-locking"
  }
}

# ---------------------------------------------------------------------------
# BACKEND CONFIGURATION (used in ALL other Terraform modules/root configs)
# Place this block in versions.tf or backend.tf — NOT in main.tf
# ---------------------------------------------------------------------------
#
# terraform {
#   backend "s3" {
#     bucket         = "my-company-terraform-state-prod"
#     key            = "prod/vpc/terraform.tfstate"      # unique path per workspace
#     region         = "us-east-1"
#     encrypt        = true                               # encrypt at rest
#     dynamodb_table = "terraform-state-locks"           # locking table
#     profile        = "terraform-ci"                    # AWS CLI profile (optional)
#   }
# }
#
# WORKSPACE KEY PATTERN (recommended):
#   key = "${var.environment}/${var.component}/terraform.tfstate"
# Examples:
#   prod/vpc/terraform.tfstate
#   prod/eks-cluster/terraform.tfstate
#   staging/rds/terraform.tfstate

# ---------------------------------------------------------------------------
# IAM Policy: grant CI/CD role access to state bucket + lock table
# ---------------------------------------------------------------------------

resource "aws_iam_policy" "terraform_state_access" {
  name        = "TerraformStateAccess"
  description = "Grants read/write access to Terraform remote state (S3 + DynamoDB)"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.terraform_state.arn,
          "${aws_s3_bucket.terraform_state.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeTable"
        ]
        Resource = aws_dynamodb_table.terraform_locks.arn
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "state_bucket_name" {
  description = "S3 bucket name for Terraform state"
  value       = aws_s3_bucket.terraform_state.id
}

output "state_bucket_arn" {
  description = "ARN of the Terraform state S3 bucket"
  value       = aws_s3_bucket.terraform_state.arn
}

output "dynamodb_lock_table" {
  description = "DynamoDB table name used for state locking"
  value       = aws_dynamodb_table.terraform_locks.name
}
