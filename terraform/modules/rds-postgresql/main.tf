# ---------------------------------------------------------------------------------------------------------------------
# RDS POSTGRESQL MODULE
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" { type = string }
variable "environment" { type = string }
variable "vpc_id" { type = string }
variable "db_subnet_group_name" { type = string }
variable "private_subnet_cidrs" { type = list(string) }
variable "instance_class" { type = string; default = "db.t3.medium" }
variable "allocated_storage" { type = number; default = 20 }
variable "engine_version" { type = string; default = "15.4" }
variable "database_name" { type = string; default = "appdb" }
variable "multi_az" { type = bool; default = false }
variable "tags" { type = map(string); default = {} }

resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-${var.environment}-rds-"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.private_subnet_cidrs
    description = "PostgreSQL from private subnets"
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  })
}

resource "random_password" "master" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "rds_credentials" {
  name_prefix = "${var.project_name}-${var.environment}-rds-"
  description = "RDS master credentials"
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "rds_credentials" {
  secret_id = aws_secretsmanager_secret.rds_credentials.id
  secret_string = jsonencode({
    username = "dbadmin"
    password = random_password.master.result
    host     = aws_db_instance.main.address
    port     = 5432
    dbname   = var.database_name
  })
}

resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.project_name}-${var.environment}-pg15-"
  family      = "postgres15"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  tags = var.tags
}

resource "aws_db_instance" "main" {
  identifier_prefix = "${var.project_name}-${var.environment}-"

  engine               = "postgres"
  engine_version       = var.engine_version
  instance_class       = var.instance_class
  allocated_storage    = var.allocated_storage
  max_allocated_storage = var.allocated_storage * 5

  db_name  = var.database_name
  username = "dbadmin"
  password = random_password.master.result

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  multi_az               = var.multi_az

  storage_encrypted = true
  storage_type      = "gp3"

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  deletion_protection       = var.environment == "production"
  skip_final_snapshot       = var.environment != "production"
  final_snapshot_identifier = var.environment == "production" ? "${var.project_name}-${var.environment}-final" : null

  performance_insights_enabled = true
  monitoring_interval          = 60
  monitoring_role_arn          = aws_iam_role.rds_monitoring.arn

  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = merge(var.tags, {
    Name = "${var.project_name}-${var.environment}-postgres"
  })
}

resource "aws_iam_role" "rds_monitoring" {
  name_prefix = "${var.project_name}-${var.environment}-rds-mon-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

output "db_instance_endpoint" { value = aws_db_instance.main.endpoint }
output "db_instance_address" { value = aws_db_instance.main.address }
output "db_instance_port" { value = aws_db_instance.main.port }
output "db_instance_name" { value = aws_db_instance.main.db_name }
output "db_credentials_secret_arn" { value = aws_secretsmanager_secret.rds_credentials.arn }
output "db_security_group_id" { value = aws_security_group.rds.id }
