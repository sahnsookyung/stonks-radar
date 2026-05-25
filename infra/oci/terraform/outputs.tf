output "instance_id" {
  description = "OCI instance OCID."
  value       = oci_core_instance.stonks_radar.id
}

output "instance_name" {
  description = "OCI instance display name."
  value       = oci_core_instance.stonks_radar.display_name
}

output "shape" {
  description = "Pinned Always Free shape."
  value       = oci_core_instance.stonks_radar.shape
}

