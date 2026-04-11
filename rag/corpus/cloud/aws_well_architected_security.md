---
id: aws_well_architected_security
artifact_type: cloud
doc_type: cloud
title: AWS Well-Architected Framework — Security Pillar
description: Bonnes pratiques de sécurité cloud AWS — IAM, chiffrement, logging, réseau
tags: [aws, cloud, security, well-architected, iam, vpc, kms, cloudtrail]
keywords: [iam, vpc, kms, cloudtrail, guardduty, waf, s3, encryption, mfa]
---

# AWS Well-Architected — Pilier Sécurité

## 1. IAM — Principe du moindre privilège

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3ReadOnly",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-company-bucket",
        "arn:aws:s3:::my-company-bucket/*"
      ]
    }
  ]
}
```

```bash
# Analyser les permissions inutilisées avec IAM Access Analyzer
aws accessanalyzer create-analyzer \
  --analyzer-name company-analyzer \
  --type ACCOUNT

# Générer une politique basée sur les logs CloudTrail
aws iam generate-service-last-accessed-details \
  --arn arn:aws:iam::123456789:role/MyRole
```

## 2. Chiffrement au repos et en transit (KMS)

```hcl
# Terraform — Clé KMS dédiée par environnement
resource "aws_kms_key" "main" {
  description             = "Clé KMS pour l'application en production"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootAccess"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })

  tags = local.common_tags
}

# S3 avec chiffrement SSE-KMS
resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    bucket_key_enabled = true
  }
}
```

## 3. VPC — Architecture multi-couches

```hcl
# 3 couches : Public (ALB) / Private App / Private Data
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}

# Public subnets — ALB uniquement
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false  # pas d'IP publique auto
}

# Private subnets — Application (ECS/EKS)
resource "aws_subnet" "private_app" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
}

# Private subnets — Base de données (RDS)
resource "aws_subnet" "private_data" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 20}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
}
```

## 4. CloudTrail — Audit complet

```hcl
resource "aws_cloudtrail" "main" {
  name                          = "production-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  kms_key_id = aws_kms_key.cloudtrail.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true

    data_resource {
      type   = "AWS::S3::Object"
      values = ["arn:aws:s3:::"]
    }
  }

  tags = local.common_tags
}
```

## 5. GuardDuty — Détection des menaces

```hcl
resource "aws_guardduty_detector" "main" {
  enable = true

  datasources {
    s3_logs {
      enable = true
    }
    kubernetes {
      audit_logs {
        enable = true
      }
    }
    malware_protection {
      scan_ec2_instance_with_findings {
        ebs_volumes {
          enable = true
        }
      }
    }
  }
}
```

## 6. WAF — Protection des APIs publiques

```hcl
resource "aws_wafv2_web_acl" "api" {
  name  = "api-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # Règle 1 : Rate limiting
  rule {
    name     = "RateLimitRule"
    priority = 1

    action { block {} }

    statement {
      rate_based_statement {
        limit              = 2000  # requêtes / 5 minutes par IP
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitRule"
      sampled_requests_enabled   = true
    }
  }

  # Règle 2 : AWS Managed Rules (OWASP Top 10)
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 2

    override_action { none {} }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }
}
```

## 7. Checklist Sécurité AWS

```
✅ MFA activé sur tous les comptes IAM, surtout root
✅ Pas de clés d'accès pour le compte root
✅ Rotation automatique des clés KMS
✅ Versioning activé sur les buckets S3 critiques
✅ Accès public bloqué sur tous les buckets S3
✅ CloudTrail activé sur toutes les régions
✅ GuardDuty activé
✅ Security Hub activé avec les standards CIS
✅ Config Rules configurées
✅ VPC Flow Logs activés
✅ Chiffrement en transit (TLS 1.2+) enforced
✅ Secrets dans Secrets Manager (pas dans les variables d'environnement)
```
