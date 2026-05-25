resource "oci_core_instance" "stonks_radar" {
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_ocid
  display_name        = var.instance_name
  shape               = var.shape

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_in_gbs
  }

  create_vnic_details {
    assign_public_ip = true
    display_name     = "${var.instance_name}-vnic"
    hostname_label   = replace(var.instance_name, "_", "-")
    subnet_id        = var.subnet_ocid
  }

  metadata = {
    ssh_authorized_keys = var.ssh_authorized_keys
    user_data           = base64encode(templatefile("${path.module}/cloud-init.yaml.tftpl", {}))
  }

  source_details {
    source_id               = var.image_ocid
    source_type             = "image"
    boot_volume_size_in_gbs = var.boot_volume_size_in_gbs
  }

  freeform_tags = {
    app        = "stonks-radar"
    managed_by = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

