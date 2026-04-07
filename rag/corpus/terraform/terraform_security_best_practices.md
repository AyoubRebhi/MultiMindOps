---
id: terraform_security_best_practices
artifact_type: terraform
doc_type: terraform
title: Terraform IaC Security Best Practices
description: Bonnes pratiques de sécurité pour Terraform — State, Variables, Providers, Modules
tags: [terraform, iac, security, tfsec, checkov, state, aws, cloud]
keywords: [backend, state, encryption, secret, variable, provider, module, tfsec]
---

# Terraform Security Best Practices

## 1. Structure de projet recommandée

```
terraform/
├── main.tf           # Ressources principales
├── variables.tf      # Déclarations de variables
├── outputs.tf        # Outputs
├── providers.tf      # Configuration des providers
├── versions.tf       # Contraintes de versions
├── locals.tf         # Variables locales calculées
└── modules/
    └── vpc/
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
```

## 2. Backend sécurisé — State distant et chiffré

```hcl
# versions.tf
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend S3 + DynamoDB pour le state locking
  backend "s3" {
    bucket         = "company-terraform-state"
    key            = "production/api/terraform.tfstate"
    region         = "eu-west-1"
    encrypt        = true
    kms_key_id     = "arn:aws:kms:eu-west-1:123456789:key/mrk-xxx"
    dynamodb_table = "terraform-state-lock"
  }
}
```

## 3. Variables sensibles — Ne jamais mettre en clair

```hcl
# variables.tf
variable "db_password" {
  description = "Mot de passe de la base de données"
  type        = string
  sensitive   = true  # masqué dans les logs et outputs
}

variable "api_key" {
  description = "Clé API externe"
  type        = string
  sensitive   = true
}

# NE JAMAIS faire :
# variable "db_password" { default = "mysecretpassword" }
```

```bash
# Injection via variables d'environnement (CI/CD)
export TF_VAR_db_password=$(aws secretsmanager get-secret-value \
  --secret-id prod/db/password --query SecretString --output text)
```

## 4. Outputs sécurisés

```hcl
# outputs.tf
output "db_endpoint" {
  description = "Endpoint de la base de données"
  value       = aws_db_instance.main.endpoint
  sensitive   = false
}

# Marquer les outputs sensibles
output "db_password" {
  value     = aws_db_instance.main.password
  sensitive = true
}
```

## 5. Exemple — VPC avec subnets privés et publics

```hcl
# main.tf
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = local.common_tags
}

resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = var.availability_zones[count.index]

  # Pas d'IP publique automatique pour les subnets privés
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, { Name = "private-${count.index}" })
}
```

## 6. Security Groups restrictifs

```hcl
resource "aws_security_group" "api" {
  name        = "api-sg"
  description = "Security group pour l'API"
  vpc_id      = aws_vpc.main.id

  # Ingress — uniquement ce qui est nécessaire
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Trafic depuis l'ALB uniquement"
  }

  # Egress — restreindre si possible
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS sortant uniquement"
  }

  # INTERDIT — 0.0.0.0/0 sur port 22 ou 3306
  # ingress { from_port = 22  cidr_blocks = ["0.0.0.0/0"] }
}
```

## 7. Scanner IaC avec tfsec et Checkov

```bash
# tfsec — analyse statique de sécurité
tfsec . --severity HIGH

# Checkov — règles CIS et bonnes pratiques
checkov -d . --framework terraform --check CKV_AWS_*

# Terrascan — multi-cloud
terrascan scan -t terraform -d .

# Intégration CI/CD (GitHub Actions)
- name: Run tfsec
  uses: aquasecurity/tfsec-action@v1.0.0
  with:
    severity: HIGH
```

## 8. Locals — Centraliser les tags

```hcl
# locals.tf
locals {
  common_tags = {
    Environment = var.environment
    Project     = var.project_name
    ManagedBy   = "terraform"
    Owner       = var.team_name
    CostCenter  = var.cost_center
  }
}
```

## 9. Modules versionnés

```hcl
# Utiliser des modules depuis un registry avec version fixe
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.5.1"  # toujours pinned — ne jamais utiliser "latest"

  name = "${var.project_name}-vpc"
  cidr = "10.0.0.0/16"
}
```
