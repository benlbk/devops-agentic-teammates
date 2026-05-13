# ---------------------------------------------------------------------------------------------------------------------
# CLOUDFRONT DISTRIBUTION MODULE
# CloudFront with S3 origin (static) and EKS ALB origin (SSR/API)
# ---------------------------------------------------------------------------------------------------------------------

variable "project_name" { type = string }
variable "environment" { type = string }
variable "domain_name" { type = string; default = "" }
variable "acm_certificate_arn" { type = string; default = "" }
variable "alb_domain_name" { type = string }
variable "tags" { type = map(string); default = {} }

# S3 bucket for static assets
resource "aws_s3_bucket" "static_assets" {
  bucket_prefix = "${var.project_name}-${var.environment}-static-"
  tags          = var.tags
}

resource "aws_s3_bucket_versioning" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "static_assets" {
  bucket                  = aws_s3_bucket.static_assets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# OAC for CloudFront → S3
resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${var.project_name}-${var.environment}-s3-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontOAC"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.static_assets.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.main.arn
        }
      }
    }]
  })
}

# CloudFront Distribution
resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = ""
  price_class         = "PriceClass_100"
  comment             = "${var.project_name} ${var.environment} distribution"
  aliases             = var.domain_name != "" ? [var.domain_name] : []

  # S3 origin for static assets (_next/static/*)
  origin {
    domain_name              = aws_s3_bucket.static_assets.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
    origin_id                = "s3-static"
  }

  # ALB origin for SSR/API
  origin {
    domain_name = var.alb_domain_name
    origin_id   = "alb-app"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Static assets cache behavior
  ordered_cache_behavior {
    path_pattern           = "/_next/static/*"
    target_origin_id       = "s3-static"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    min_ttl     = 86400
    default_ttl = 604800
    max_ttl     = 31536000
  }

  # API cache behavior - no caching
  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "alb-app"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Authorization", "Host", "Origin"]
      cookies { forward = "all" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  # Default behavior - SSR via ALB
  default_cache_behavior {
    target_origin_id       = "alb-app"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Host", "Origin"]
      cookies { forward = "all" }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 86400
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.acm_certificate_arn == ""
    acm_certificate_arn            = var.acm_certificate_arn != "" ? var.acm_certificate_arn : null
    ssl_support_method             = var.acm_certificate_arn != "" ? "sni-only" : null
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  tags = var.tags
}

output "distribution_id" { value = aws_cloudfront_distribution.main.id }
output "distribution_domain_name" { value = aws_cloudfront_distribution.main.domain_name }
output "static_assets_bucket" { value = aws_s3_bucket.static_assets.id }
output "static_assets_bucket_arn" { value = aws_s3_bucket.static_assets.arn }
