# Terraform Migration Boundary

This directory reserves the canonical infrastructure-as-code boundary. The current
AWS resources predate Terraform and are documented under `infra/ecs`, CloudWatch,
and `AWS_DEPLOYMENT.md`. They must be imported and reconciled before Terraform is
allowed to manage them; creating duplicate production resources would be unsafe.

Recommended modules:

- `network`: VPC, subnets, security groups, and ALBs
- `compute`: ECR, ECS cluster, task definitions, services, and autoscaling
- `data`: RDS, S3, and service integrations
- `observability`: log groups, dashboards, alarms, and SLO notifications
- `dns`: ACM certificates and Route 53 aliases
