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
    client_id="2f92f5957e88abb828a215fbad2efee5627b404f10ffcf66e4354726c288aa99",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="tübingen",
    server_metadata_url="https://gitlab.nfdi4plants.de/.well-known/openid-configuration",
    client_id="f5566a7704e4e9e0b5fa3b1b603ef90a0d6ede269987fd82ffeca7475cb8b88c",
    client_secret="4a7e106e78782117e64e6ec04a0107f6ebd79c10696f4b1ff992ead874d90fd5",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="freiburg",
    server_metadata_url="https://git.nfdi4plants.org/.well-known/openid-configuration",
    client_id="b28f5ab578608aec89be0867e3284a6c421b49abb4560fd985bea2ee29130405",
    client_secret="cb0476093ac11cab11b352c23bc3ebc260fbbe3d510d3558be62c8ea9999998c",
    client_kwargs={"scope": "openid profile api"},
)

oauth.register(
    name="plantmicrobe",
    server_metadata_url="https://gitlab.plantmicrobe.de/.well-known/openid-configuration",
    client_id="b74a844b1a32125a69842c66935244879adfb0e888a6db3b56ed288892de24d7",
    client_secret="f182497b71fad82482e5989af2d3607ca7d96e47a7f6fb9f8e836460feb5905c",
    client_kwargs={"scope": "openid api profile"},
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
        return await oauth.tübingen.authorize_redirect(request, redirect_uri)
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

    token = ""
    test = RedirectResponse("http://localhost:5173")

    try:
        if datahub == "dev":
            token = await oauth.dev.authorize_access_token(request)
        elif datahub == "tübingen":
            token = await oauth.tübingen.authorize_access_token(request)
        elif datahub == "freiburg":
            token = await oauth.freiburg.authorize_access_token(request)
        elif datahub == "plantmicrobe":
            token = await oauth.plantmicrobe.authorize_access_token(request)

    except OAuthError as error:
        return HTMLResponse(f"<h1>{error.error}</h1>")

    access_token = token.get("access_token")
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
    test.set_cookie(
        "data", encodedCookie, httponly=True, secure=True, samesite="strict"
    )
    test.set_cookie("logged_in", "true", httponly=False)
    test.set_cookie(
        "username",
        await getUserName(datahub, userInfo, access_token),
        httponly=False,
    )

    request.session.clear()
    return test


@router.get("/logout", summary="Manually delete server-side user session")
async def logout(request: Request):
    response = Response("logout successful", media_type="text/plain")

    # if the user logs out, delete the "data" cookie containing the gitlab token
    response.delete_cookie("data")
    response.delete_cookie("logged_in")
    response.delete_cookie("username")
    request.cookies.clear()
    return response
