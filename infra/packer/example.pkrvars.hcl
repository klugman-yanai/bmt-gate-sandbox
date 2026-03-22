# Copy to local.pkrvars.hcl (gitignored) and fill in values.
# Usage: packer build -var-file=local.pkrvars.hcl bmt-runtime.pkr.hcl

gcp_project     = "your-gcp-project"
gcp_zone        = "europe-west4-a"
gcs_bucket      = "your-bmt-bucket"
service_account = "bmt-vm-sa@your-gcp-project.iam.gserviceaccount.com"
network         = "default"
# subnetwork    = ""              # leave empty for default
# tags          = ["bmt-runtime"]
# machine_type  = "e2-standard-4"
# image_family  = "bmt-runtime"
