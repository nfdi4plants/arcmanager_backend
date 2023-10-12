import json
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.config import Config

# from starlette.requests import Request
from starlette.responses import HTMLResponse
from authlib.integrations.starlette_client import OAuth, OAuthError

router = APIRouter()

import jwt
import os

## Read Oauth client info from .env for production
config = Config(".env")
oauth = OAuth(config)
# oauth = OAuth()

oauth.register(
    name="dev",
    server_metadata_url="https://gitdev.nfdi4plants.org/.well-known/openid-configuration",
    client_id="2f92f5957e88abb828a215fbad2efee5627b404f10ffcf66e4354726c288aa99",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="tuebingen",
    server_metadata_url="https://gitlab.nfdi4plants.de/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="freiburg",
    server_metadata_url="",
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="plantmicrobe",
    server_metadata_url="",
    client_kwargs={"scope": "openid email profile"},
)


# redirect user to requested keycloak to enter login credentials
@router.get("/login", summary="Initiate login process for specified DataHUB")
async def login(request: Request, datahub: str):
    redirect_uri = request.url_for("callback")
    # redirect_uri = "https://nfdi4plants.de/arcmanager/api/v1/auth/callback"
    # store requested datahub in user session
    request.session["datahub"] = datahub
    # construct authorization url for requested datahub and redirect
    if datahub == "dev":
        return await oauth.dev.authorize_redirect(request, redirect_uri)
    elif datahub == "tübingen":
        return await oauth.tuebingen.authorize_redirect(request, redirect_uri)
    elif datahub == "freiburg":
        return await oauth.freiburg.authorize_redirect(request, redirect_uri)
    elif datahub == "plantmicrobe":
        return await oauth.plantmicrobe.authorize_redirect(request, redirect_uri)
    else:
        return "invalid DataHUB selection"


# retrieve tokens after successful login and store it in session object
@router.get(
    "/callback",
    summary="Redirection after successful user login and creation of server-side user session",
)
async def callback(request: Request):
    # read requested datahub from user session
    datahub = request.session.get("datahub")
    response = Response(
        "Success",
        media_type="text/plain",
    )
    token = ""
    test = RedirectResponse("https://localhost:5173")

    try:
        if datahub == "dev":
            token = await oauth.dev.authorize_access_token(request)
            access_token = token.get("access_token")
            cookieData = {
                "gitlab": access_token,
                "target": datahub,
                "token": token,
            }
            # read out private key from .env
            pr_key = (
                b"-----BEGIN RSA PRIVATE KEY-----\n"
                + os.environ.get("PRIVATE_RSA").encode()
                + b"\n-----END RSA PRIVATE KEY-----"
            )
            # encode cookie data with rsa key
            encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")
            response.set_cookie("data", encodedCookie, httponly=True, secure=True)
            test.set_cookie(
                "data",
                encodedCookie,
                httponly=True,
                secure=True,
            )
        elif datahub == "tuebingen":
            token = await oauth.tuebingen.authorize_access_token(request)
            access_token = token.get("access_token")
            cookieData = {
                "gitlab": access_token,
                "target": datahub,
                "token": token,
            }
            # read out private key from .env
            pr_key = (
                b"-----BEGIN RSA PRIVATE KEY-----\n"
                + os.environ.get("PRIVATE_RSA").encode()
                + b"\n-----END RSA PRIVATE KEY-----"
            )
            # encode cookie data with rsa key
            encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")
            response.set_cookie("data", encodedCookie, httponly=True, secure=True)
        elif datahub == "freiburg":
            token = await oauth.freiburg.authorize_access_token(request)
        elif datahub == "plantmicrobe":
            token = await oauth.plantmicrobe.authorize_access_token(request)

    except OAuthError as error:
        return HTMLResponse(f"<h1>{error.error}</h1>")
    return test


@router.get("/logout", summary="Manually delete server-side user session")
async def logout(request: Request):
    request.session.pop("user", None)
    return "logout successful"
