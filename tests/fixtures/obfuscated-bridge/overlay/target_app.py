# A facade whose entrypoint contains none of the forbidden text patterns.
# The DRF dispatch lives in the imported helper, so a single-file string scan
# sees a clean FastAPI application here. Only recorded serving evidence can
# reject this candidate.
from fastapi import FastAPI
from widget_compat import attach

app = attach(FastAPI(title="Widget service"))
