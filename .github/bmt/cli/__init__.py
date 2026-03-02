# Expose shared as the canonical module; also make `from cli import models/gcloud/config` work.
from cli import shared

models = shared
gcloud = shared
config = shared
