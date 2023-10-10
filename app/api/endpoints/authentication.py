import json
from fastapi import (
    APIRouter,
    Request,
)
from starlette.config import Config

# from starlette.requests import Request
from starlette.responses import HTMLResponse
from authlib.integrations.starlette_client import OAuth, OAuthError

router = APIRouter()

## Read Oauth client info from .env for production
config = Config(".env")
oauth = OAuth(config)
# oauth = OAuth()

oauth.register(
    name="dev",
    server_metadata_url="http://127.0.0.1:8080/realms/dataplant-dev/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="tuebingen",
    server_metadata_url="",
    client_kwargs={"scope": "openid email profile"},
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
    try:
        if datahub == "dev":
            token = await oauth.dev.authorize_access_token(request)
        elif datahub == "tübingen":
            token = await oauth.tuebingen.authorize_access_token(request)
        elif datahub == "freiburg":
            token = await oauth.freiburg.authorize_access_token(request)
        elif datahub == "plantmicrobe":
            token = await oauth.plantmicrobe.authorize_access_token(request)
    except OAuthError as error:
        return HTMLResponse(f"<h1>{error.error}</h1>")
    user = token.get("userinfo")
    access_token = token.get("access_token")
    if user:
        request.session["user"] = dict(user)
        request.session["access_token"] = access_token
    return "login successful"


@router.get("/logout", summary="Manually delete server-side user session")
async def logout(request: Request):
    request.session.pop("user", None)
    return "logout successful"
