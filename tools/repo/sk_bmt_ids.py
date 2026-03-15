"""Canonical BMT ids for the SK project (UUIDs).

These match the keys in gcp/image/projects/sk/bmt_jobs.json. Deterministic:
uuid5(NAMESPACE_DNS, 'bmt-gcloud.sk.<logical_name>').
Use these constants when a default or test needs to reference an SK BMT.
"""

from __future__ import annotations

# Logical name: false_reject_namuh (gte gate)
SK_BMT_FALSE_REJECT_NAMUH = "4a5b6e82-a048-5c96-8734-2f64d2288378"
# Logical name: false_alarm_namuh (lte gate)
SK_BMT_FALSE_ALARM_NAMUH = "ac73397e-1162-5004-9ca2-17c969f53ee5"
