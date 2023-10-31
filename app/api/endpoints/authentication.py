import json
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.config import Config
from app.api.endpoints.projects import getUserName

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
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="tuebingen",
    server_metadata_url="https://gitlab.nfdi4plants.de/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="freiburg",
    server_metadata_url="https://git.nfdi4plants.org/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="plantmicrobe",
    server_metadata_url="https://gitlab.plantmicrobe.de/.well-known/openid-configuration",
    client_kwargs={"scope": "openid api profile"},
)


# redirect user to requested keycloak to enter login credentials
@router.get("/login", summary="Initiate login process for specified DataHUB")
async def login(request: Request, datahub: str):
    redirect_uri = (
        "https://nfdi4plants.de/arcmanager/api/v1/auth/callback?datahub=" + datahub
    )

    # construct authorization url for requested datahub and redirect
    if datahub == "dev":
        return await oauth.dev.authorize_redirect(request, redirect_uri)
    elif datahub == "tübingen":
        # change uri with 'ü' to 'ue'
        redirect_uri = (
            "https://nfdi4plants.de/arcmanager/api/v1/auth/callback?datahub=tuebingen"
        )
        return await oauth.tuebingen.authorize_redirect(request, redirect_uri)
    elif datahub == "freiburg":
        return await oauth.freiburg.authorize_redirect(request, redirect_uri)
    elif datahub == "plantmicrobe":
        return await oauth.plantmicrobe.authorize_redirect(request, redirect_uri)
    elif datahub == "tuebingen":
        return await oauth.tuebingen.authorize_redirect(request, redirect_uri)
    else:
        return "invalid DataHUB selection"


# retrieve tokens after successful login and store it in session object
@router.get(
    "/callback",
    summary="Redirection after successful user login and creation of server-side user session",
)
async def callback(request: Request, datahub: str):
    # response = RedirectResponse("http://localhost:5173")
    response = RedirectResponse("https://nfdi4plants.de/arcmanager/app/index.html")

    try:
        if datahub == "dev":
            token = await oauth.dev.authorize_access_token(request)
        elif datahub == "tuebingen":
            token = await oauth.tuebingen.authorize_access_token(request)
        elif datahub == "freiburg":
            token = await oauth.freiburg.authorize_access_token(request)
        elif datahub == "plantmicrobe":
            token = await oauth.plantmicrobe.authorize_access_token(request)

    except OAuthError as error:
        return HTMLResponse(f"<h1>{error}</h1>")

    try:
        access_token = token.get("access_token")
    except:
        raise OAuthError(description="Failed retrieving the token data")

    userInfo = token.get("userinfo")["sub"]
    cookieData = {
        "gitlab": access_token,
        "target": datahub,
    }
    # read out private key from .env
    pr_key = (
        b"-----BEGIN RSA PRIVATE KEY-----\n"
        + os.environ.get("PRIVATE_RSA").encode()
        + b"\n-----END RSA PRIVATE KEY-----"
    )

    # encode cookie data with rsa key
    encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")
    request.session["data"] = encodedCookie
    response.set_cookie(
        "data", encodedCookie, httponly=True, secure=True, samesite="strict"
    )
    response.set_cookie("logged_in", "true", httponly=False)
    response.set_cookie(
        "username",
        await getUserName(datahub, userInfo, access_token),
        httponly=False,
    )

    request.session.clear()
    return response


@router.get("/logout", summary="Manually delete server-side user session")
async def logout(request: Request):
    response = Response("logout successful", media_type="text/plain")

    # if the user logs out, delete the "data" cookie containing the gitlab token, as well as the other cookies set
    response.delete_cookie("data")
    response.delete_cookie("logged_in")
    response.delete_cookie("username")
    request.cookies.clear()
    return response
