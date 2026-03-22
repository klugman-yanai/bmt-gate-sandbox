#!/usr/bin/env bash
# Enforce BMT image family policy: image_family, base_image_family, base_image_project
# must match repo vars (or defaults). Used by bmt-image-build.yml.
#
# Env (from workflow vars/inputs):
#   BMT_EXPECTED_IMAGE_FAMILY      expected image family (default: bmt-runtime)
#   BMT_EXPECTED_BASE_IMAGE_FAMILY expected base image family (default: ubuntu-2204-lts)
#   BMT_EXPECTED_BASE_IMAGE_PROJECT expected base image project (default: ubuntu-os-cloud)
#   IMAGE_FAMILY                   actual image family (default: bmt-runtime)
#   BASE_IMAGE_FAMILY              actual base image family (default: ubuntu-2204-lts)
#   BASE_IMAGE_PROJECT             actual base image project (default: ubuntu-os-cloud)

set -euo pipefail

expected_family="${BMT_EXPECTED_IMAGE_FAMILY:-bmt-runtime}"
expected_base_family="${BMT_EXPECTED_BASE_IMAGE_FAMILY:-ubuntu-2204-lts}"
expected_base_project="${BMT_EXPECTED_BASE_IMAGE_PROJECT:-ubuntu-os-cloud}"
image_family="${IMAGE_FAMILY:-bmt-runtime}"
base_image_family="${BASE_IMAGE_FAMILY:-ubuntu-2204-lts}"
base_image_project="${BASE_IMAGE_PROJECT:-ubuntu-os-cloud}"

if [[ "${image_family}" != "${expected_family}" ]]; then
  echo "::error::image_family must be '${expected_family}', got '${image_family}'"
  exit 1
fi
if [[ "${base_image_family}" != "${expected_base_family}" ]]; then
  echo "::error::base_image_family must be '${expected_base_family}', got '${base_image_family}'"
  exit 1
fi
if [[ "${base_image_project}" != "${expected_base_project}" ]]; then
  echo "::error::base_image_project must be '${expected_base_project}', got '${base_image_project}'"
  exit 1
fi
