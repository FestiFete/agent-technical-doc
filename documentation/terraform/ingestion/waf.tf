# ============================================================================
# WAF + CloudFront devant l'API Gateway HTTP API du webhook (SEC-F1, audit
# audit/20260721-133806/02-security.md). WAFv2 ne peut pas s'attacher
# directement à une HTTP API (aws_apigatewayv2_api) : seules les REST API
# (API Gateway v1), ALB, CloudFront, AppSync, Cognito, App Runner et Amplify
# sont des cibles supportées. On place donc CloudFront devant l'API Gateway
# existante (inchangée, routes/intégrations/throttle intacts) et on attache
# le WebACL à CloudFront — le pattern documenté par AWS pour protéger une
# HTTP API avec WAF.
#
# Le WebACL scope=CLOUDFRONT (et sa logging configuration) doit être créé en
# us-east-1 quelle que soit la région du reste de la stack (contrainte AWS
# globale, cf. provider aws.us_east_1 dans providers.tf).
#
# Défense en profondeur : ce WAF s'ajoute à la vérification HMAC déjà en
# place dans la Lambda webhook (documentation/scripts/lambdas/webhook-receiver/handler.py)
# et au throttle de l'API Gateway ($default stage), il ne les remplace pas.
# Limite connue : l'URL execute-api native de l'API Gateway reste techniquement
# joignable directement (bypass du WAF) — hors périmètre de SEC-F1 tel que
# scoré par l'audit ; à traiter séparément si nécessaire (ex. secret partagé
# en en-tête d'origine, vérifié côté Lambda).
# ============================================================================

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudwatch_log_group" "waf" {
  provider          = aws.us_east_1
  name              = "aws-waf-logs-${local.name}-webhook"
  retention_in_days = var.log_retention_days
}

resource "aws_wafv2_web_acl" "webhook" {
  provider    = aws.us_east_1
  name        = "${local.name}-webhook-waf"
  description = "Defense-in-depth devant le webhook public (${local.name}) : Core rule set + Known Bad Inputs + rate-limit IP."
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "AWS-AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common-rule-set"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "AWS-AWSManagedRulesKnownBadInputsRuleSet"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  # Garde-fou volumétrique par IP source. Seuil volontairement généreux (min.
  # AWS = 100/5min) : les deliveries GitHub proviennent d'un pool d'IP partagé
  # entre de nombreux dépôts/organisations (cf. https://api.github.com/meta,
  # clé "hooks") ; un seuil trop bas bloquerait du trafic légitime multi-dépôts.
  # Ce n'est pas le seul frein au trafic abusif : le throttle API Gateway
  # ($default stage, 10 rps/20 burst) et la vérification HMAC dans la Lambda
  # restent en place derrière.
  rule {
    name     = "RateLimitPerIP"
    priority = 3

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-webhook-waf"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_logging_configuration" "webhook" {
  provider                = aws.us_east_1
  resource_arn            = aws_wafv2_web_acl.webhook.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]
}

resource "aws_cloudfront_distribution" "webhook" {
  enabled             = true
  is_ipv6_enabled     = true
  comment             = "${local.name} — WAF front pour l'API Gateway webhook (SEC-F1)"
  price_class         = "PriceClass_100"
  web_acl_id          = aws_wafv2_web_acl.webhook.arn
  wait_for_deployment = false

  origin {
    origin_id   = "webhook-api-gateway"
    domain_name = replace(aws_apigatewayv2_api.webhook.api_endpoint, "https://", "")

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "webhook-api-gateway"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]

    # Le webhook ne doit jamais être mis en cache ; tous les en-têtes/query
    # strings (hors Host) doivent être transmis tels quels à l'origine, car
    # la signature HMAC GitHub porte sur le corps brut de la requête.
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
