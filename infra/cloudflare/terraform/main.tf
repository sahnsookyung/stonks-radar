resource "cloudflare_dns_record" "stonks_radar" {
  zone_id = var.cloudflare_zone_id
  name    = var.hostname
  type    = "A"
  content = var.origin_ipv4
  ttl     = 1
  proxied = var.proxied
  comment = "Managed by Terraform: Stonks Radar OCI origin"
}

resource "cloudflare_zone_setting" "ssl" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "ssl"
  value      = "full"
}

resource "cloudflare_zone_setting" "always_use_https" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_zone_setting" "automatic_https_rewrites" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "automatic_https_rewrites"
  value      = "on"
}

resource "cloudflare_zone_setting" "brotli" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "brotli"
  value      = "on"
}

resource "cloudflare_zone_setting" "http3" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "http3"
  value      = "on"
}

resource "cloudflare_zone_setting" "minimum_tls_version" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "min_tls_version"
  value      = var.minimum_tls_version
}

resource "cloudflare_zone_setting" "rocket_loader" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "rocket_loader"
  value      = "off"
}

resource "cloudflare_web_analytics_site" "stonks_radar" {
  count = var.manage_web_analytics ? 1 : 0

  account_id   = var.cloudflare_account_id
  auto_install = false
  host         = var.hostname
  zone_tag     = var.cloudflare_zone_id
}
