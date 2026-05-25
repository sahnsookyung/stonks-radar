# OCI Terraform

This stack codifies the Stonks Radar OCI origin as a single Always Free Ampere A1 instance:

Requires Terraform `>= 1.6`.

- `VM.Standard.A1.Flex`
- `2 OCPU`
- `12 GB RAM`
- `50 GB boot volume`
- Existing public subnet
- No managed database, load balancer, NAT gateway, object storage, or other paid resources

The variables deliberately validate the agreed Always Free envelope. If this shape changes, update the free-tier capacity model in `scripts/deploy_preflight.py` first and rerun `npm run deploy:preflight`.

For the existing manually-created instance, import before applying:

```bash
cd infra/oci/terraform
cp terraform.tfvars.example production.tfvars
terraform init
terraform import -var-file=production.tfvars oci_core_instance.stonks_radar <instance_ocid>
terraform plan -var-file=production.tfvars
```

For a new instance:

```bash
cd infra/oci/terraform
terraform init
terraform plan -var-file=production.tfvars
terraform apply -var-file=production.tfvars
```

Required OCI identity permissions should be scoped to the target compartment and limited to compute instance, VNIC, image read, subnet read, and boot-volume operations needed for this single instance. Keep Terraform state private; it contains infrastructure identifiers and may contain sensitive metadata.

In CI, pass OCI provider credentials through secrets mapped to Terraform variables: `TF_VAR_tenancy_ocid`, `TF_VAR_user_ocid`, `TF_VAR_fingerprint`, and `TF_VAR_private_key`. Local operators can instead use `private_key_path` or an existing OCI config profile.
