import logging
import os

import dotenv
from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from app.api.routers import api_router

description = """
The **ARCmanager** can be found [here](https://nfdi4plants.de/arcmanager/app/index.html)

The code for the front- and backend can be found on the DataPLANT Github here:

[Frontend](https://github.com/nfdi4plants/arcmanager_frontend)
[Backend](https://github.com/nfdi4plants/arcmanager_backend)
"""

logging.basicConfig(
    filename="backend.log",
    filemode="a",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)

app = FastAPI(
    title="ARCmanager API",
    summary="ARCmanager API enables you to read out and write to your ARC in any datahub",
    docs_url="/arcmanager/api/v1/docs",
    openapi_url="/arcmanager/api/v1/openapi.json",
    version="1.1.9",
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    logging.debug(f"Cookies: {request.cookies}")
    logging.error(f"{exc}")
    content = {
        "status_code": 422,
        "detail": f"Try clearing your browser data and cookies! ERROR: {exc_str}",
    }
    return JSONResponse(
        content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )
