# Expose shared as the canonical module; also make `from bmt import models/gcloud/config` work.
from bmt import shared

models = shared
gcloud = shared
config = shared
