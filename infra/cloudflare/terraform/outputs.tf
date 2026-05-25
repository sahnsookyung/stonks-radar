output "hostname" {
  description = "Dashboard hostname managed by this stack."
  value       = var.hostname
}

output "dns_record_id" {
  description = "Cloudflare DNS record ID for the dashboard A record."
  value       = cloudflare_dns_record.stonks_radar.id
}

output "web_analytics_site_id" {
  description = "Cloudflare Web Analytics site ID when managed by this stack."
  value       = try(cloudflare_web_analytics_site.stonks_radar[0].id, null)
}
