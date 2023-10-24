import os

import dotenv
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.api.routers import api_router

app = FastAPI(
    docs_url="/arcmanager/api/v1/docs", openapi_url="/arcmanager/api/v1/openapi.json"
)


load_dotenv()

# valid frontend url origins
origins = [
    "https://localhost:5173",
    "https://localhost:4173",
    "http://localhost:5173",
    "http://localhost:4173",
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# secret key has to be static or else there will be mismatching states between the workers (https://stackoverflow.com/questions/61922045/mismatchingstateerror-mismatching-state-csrf-warning-state-not-equal-in-reque)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SECRET_KEY"), max_age=None)

"""
@app.middleware("http")
async def remembersession_middleware(request: Request, call_next):
    response = await call_next(request)
    session = request.cookies.get("session")
    if session:
        response.set_cookie(
            key="session", value=request.cookies.get("session"), httponly=True
        )
    return response
"""

app.include_router(api_router)
