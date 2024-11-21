import os

import dotenv
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.api.routers import api_router
import urllib3.util.connection

description = """
The **ARCmanager** can be found [here](https://nfdi4plants.de/arcmanager/app/index.html)

The code for the front- and backend can be found on the DataPLANT Github here:

[Frontend](https://github.com/nfdi4plants/arcmanager_frontend)
[Backend](https://github.com/nfdi4plants/arcmanager_backend)
"""

app = FastAPI(
    title="ARCmanager API",
    summary="ARCmanager API enables you to read out and write to your ARC in any datahub",
    docs_url="/arcmanager/api/v1/docs",
    openapi_url="/arcmanager/api/v1/openapi.json",
    version="1.1.2",
    description=description,
)

# clear the current log
with open("log.json", "w") as log:
    log.write("[]")
log.close()

load_dotenv()

# valid frontend url origins
origins = [
    "https://localhost:5173",
    "https://localhost:4173",
    "http://localhost:5173",
    "http://localhost:4173",
    "https://nfdi4plants.de/arcmanager/app/index.html",
    "https://nfdi4plants.de",
]

# requests module tries ipv6 first for every request which creates problems with the plantmicrobe hub; this disables ipv6 and forces ipv4, solving the issue for now ---- currently disabled as ipv6 seems to be working fine for now
# urllib3.util.connection.HAS_IPV6 = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# secret key has to be static or else there will be mismatching states between the workers (https://stackoverflow.com/questions/61922045/mismatchingstateerror-mismatching-state-csrf-warning-state-not-equal-in-reque)
app.add_middleware(
    SessionMiddleware, secret_key=os.environ.get("SECRET_KEY"), max_age=None
)

app.include_router(api_router)
