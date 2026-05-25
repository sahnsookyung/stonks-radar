variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for sookyungahn.com."
  type        = string
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID. Required only when managing Web Analytics/RUM state."
  type        = string
  default     = ""
}

variable "hostname" {
  description = "Fully-qualified hostname for the dashboard."
  type        = string
  default     = "stonks.sookyungahn.com"
}

variable "origin_ipv4" {
  description = "Public IPv4 address of the OCI Caddy origin."
  type        = string

  validation {
    condition     = can(cidrhost("${var.origin_ipv4}/32", 0))
    error_message = "origin_ipv4 must be a valid IPv4 address."
  }
}

variable "proxied" {
  description = "Whether Cloudflare should proxy the dashboard hostname."
  type        = bool
  default     = true
}

variable "minimum_tls_version" {
  description = "Minimum TLS version Cloudflare should accept at the edge."
  type        = string
  default     = "1.2"
}

variable "manage_web_analytics" {
  description = "Manage the Cloudflare Web Analytics site with auto-install disabled. Import an existing site before enabling."
  type        = bool
  default     = false
}
