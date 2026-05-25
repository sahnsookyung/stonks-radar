variable "region" {
  description = "OCI region for the Always Free home region."
  type        = string
}

variable "tenancy_ocid" {
  description = "OCI tenancy OCID for API key authentication. Leave null to use an existing OCI config profile."
  type        = string
  default     = null
}

variable "user_ocid" {
  description = "OCI user OCID for API key authentication. Leave null to use an existing OCI config profile."
  type        = string
  default     = null
}

variable "fingerprint" {
  description = "OCI API key fingerprint. Leave null to use an existing OCI config profile."
  type        = string
  default     = null
  sensitive   = true
}

variable "private_key" {
  description = "OCI API private key content. Prefer CI secrets; leave null for local config/private_key_path."
  type        = string
  default     = null
  sensitive   = true
}

variable "private_key_path" {
  description = "Path to OCI API private key for local operator machines."
  type        = string
  default     = null
  sensitive   = true
}

variable "compartment_ocid" {
  description = "OCI compartment OCID that owns the instance."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain name for the instance."
  type        = string
}

variable "subnet_ocid" {
  description = "Existing public subnet OCID for the instance VNIC."
  type        = string
}

variable "image_ocid" {
  description = "ARM64 Ubuntu image OCID for VM.Standard.A1.Flex."
  type        = string
}

variable "ssh_authorized_keys" {
  description = "Public SSH keys authorized for the default ubuntu user."
  type        = string
  sensitive   = true
}

variable "instance_name" {
  description = "OCI display name and hostname label."
  type        = string
  default     = "stonks-radar"
}

variable "shape" {
  description = "OCI compute shape. Must remain Always Free eligible."
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "ocpus" {
  description = "A1 OCPUs allocated to this instance."
  type        = number
  default     = 2

  validation {
    condition     = var.ocpus == 2
    error_message = "This stack is intentionally pinned to 2 OCPUs for the agreed Always Free envelope."
  }
}

variable "memory_in_gbs" {
  description = "A1 memory allocated to this instance."
  type        = number
  default     = 12

  validation {
    condition     = var.memory_in_gbs == 12
    error_message = "This stack is intentionally pinned to 12 GB RAM for the agreed Always Free envelope."
  }
}

variable "boot_volume_size_in_gbs" {
  description = "Boot volume size. Keep at 50 GB unless the free-tier budget is recalculated."
  type        = number
  default     = 50

  validation {
    condition     = var.boot_volume_size_in_gbs == 50
    error_message = "This stack is intentionally pinned to a 50 GB boot volume for the agreed Always Free envelope."
  }
}
