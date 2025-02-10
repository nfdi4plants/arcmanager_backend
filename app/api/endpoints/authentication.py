import json
from typing import Annotated
from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
import requests
from starlette.config import Config
import urllib
from app.api.endpoints.projects import getUserName
from cryptography.fernet import Fernet

# from starlette.requests import Request
from starlette.responses import HTMLResponse
from authlib.integrations.starlette_client import OAuth, OAuthError

from app.models.gitlab.input import pat
from app.models.gitlab.targets import Targets

router = APIRouter()

import jwt
import os

import time

## Read Oauth client info from .env for production
config = Config(".env")
oauth = OAuth(config)

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

oauth.register(
    name="tuebingen_testenv",
    server_metadata_url="https://gitlab.test-nfdi4plants.de/.well-known/openid-configuration",
    client_kwargs={"scope": "openid api profile"},
)

oauth.register(
    name="fdat",
    authorize_url="https://fdat.uni-tuebingen.de/oauth/authorize",
    access_token_url="https://fdat.uni-tuebingen.de/oauth/token ",
    client_kwargs={"scope": "user:email"},
)

# backend_address = "http://localhost:8000/arcmanager/api/v1/auth/"
backend_address = "https://nfdi4plants.de/arcmanager/api/v1/auth/"

# redirect = "http://localhost:5173"
redirect = "https://nfdi4plants.de/arcmanager/app/index.html"


def encryptToken(content: bytes) -> bytes:
    fernetKey = os.environ.get("FERNET").encode()
    return Fernet(fernetKey).encrypt(content)


# Match the given target repo with the address name in the env file (default is the tübingen gitlab)
def getTarget(target: str) -> str:
    match target.lower():
        case "dev":
            return "GITLAB_ADDRESS"
        case "freiburg":
            return "GITLAB_FREIBURG"
        case "tübingen":
            return "GITLAB_TUEBINGEN"
        case "plantmicrobe":
            return "GITLAB_PLANTMICROBE"
        case "tuebingen":
            return "GITLAB_TUEBINGEN"
        case "tuebingen_testenv":
            return "GITLAB_TUEBINGEN_TESTENV"
        case other:
            return "GITLAB_TUEBINGEN"


def writeLogJson(endpoint: str, status: int, startTime: float, error=None):
    try:
        with open("log.json", "r") as log:
            jsonLog = json.load(log)

        jsonLog.append(
            {
                "endpoint": endpoint,
                "status": status,
                "error": str(error),
                "date": time.strftime("%d/%m/%Y - %H:%M:%S", time.localtime()),
                "response_time": time.time() - startTime,
            }
        )

        with open("log.json", "w") as logWrite:
            json.dump(jsonLog, logWrite, indent=4, separators=(",", ": "))
    except:
        print("Error while logging to json!")


# redirect user to requested keycloak to enter login credentials
@router.get(
    "/login",
    summary="Initiate login process for specified DataHUB",
    description="Starts the authentication process to your chosen datahub (note: this only works in browser line directly, not through the docs due to redirects)",
    response_description="Redirect to the authentication server of the respective datahub",
    status_code=302,
)
async def login(request: Request, datahub: Targets):
    redirect_uri = f"{backend_address}callback?datahub={datahub.value}"
    try:
        # construct authorization url for requested datahub and redirect
        if datahub == "dev":
            return await oauth.dev.authorize_redirect(request, redirect_uri)
        elif datahub == "tübingen":
            # change uri with 'ü' to 'ue'
            redirect_uri = f"{backend_address}callback?datahub=tuebingen"
            return await oauth.tuebingen.authorize_redirect(request, redirect_uri)
        elif datahub == "freiburg":
            return await oauth.freiburg.authorize_redirect(request, redirect_uri)
        elif datahub == "plantmicrobe":
            return await oauth.plantmicrobe.authorize_redirect(request, redirect_uri)
        elif datahub == "tuebingen":
            return await oauth.tuebingen.authorize_redirect(request, redirect_uri)
        elif datahub == "tuebingen_testenv":
            return await oauth.tuebingen_testenv.authorize_redirect(
                request, redirect_uri
            )
        elif datahub == "fdat":
            return await oauth.fdat.authorize_redirect(request, redirect_uri)
        else:
            return "invalid DataHUB selection"

    # if authentication fails (e.g. due to a timeout), then return back to the frontend containing an error in the cookies
    except:
        response = RedirectResponse(redirect)
        response.set_cookie("error", "DataHUB not available")
        return response


# retrieve tokens after successful login and store it in session object
@router.get(
    "/callback",
    summary="Redirection after successful user login and creation of server-side user session",
    include_in_schema=False,
)
async def callback(request: Request, datahub: str):
    startTime = time.time()
    response = RedirectResponse(redirect)
    try:
        if datahub == "dev":
            token = await oauth.dev.authorize_access_token(request)
        elif datahub == "tuebingen":
            token = await oauth.tuebingen.authorize_access_token(request)
        elif datahub == "freiburg":
            token = await oauth.freiburg.authorize_access_token(request)
        elif datahub == "plantmicrobe":
            token = await oauth.plantmicrobe.authorize_access_token(request)
        elif datahub == "tuebingen_testenv":
            token = await oauth.tuebingen_testenv.authorize_access_token(request)
        elif datahub == "fdat":
            return response
            token = await oauth.fdat.authorize_access_token(request)
            print(token)

    except OAuthError as error:
        return HTMLResponse(f"<h1>{error}</h1>")
    except Exception as error:
        print(error)
        response = RedirectResponse(redirect)
        response.set_cookie(
            "error", "DataHUB not available", secure=True, samesite="strict"
        )
        return response

    try:
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
    except:
        raise OAuthError(description="Failed retrieving the token data")

    userInfo = token.get("userinfo")["sub"]

    # read out private key from .env
    pr_key = (
        b"-----BEGIN RSA PRIVATE KEY-----\n"
        + os.environ.get("PRIVATE_RSA").encode()
        + b"\n-----END RSA PRIVATE KEY-----"
    )
    cookieData = {
        "gitlab": encryptToken(access_token.encode()).decode(),
        "target": datahub,
        "refresh": encryptToken(refresh_token.encode()).decode(),
    }
    # encode cookie data with rsa key
    encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")
    request.session["data"] = encodedCookie
    response.set_cookie(
        "data",
        encodedCookie,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/arcmanager/api",
    )
    response.set_cookie(
        "logged_in", "true", httponly=False, secure=True, samesite="strict"
    )
    response.set_cookie(
        "timer", time.time(), httponly=False, secure=True, samesite="strict"
    )

    try:
        username = await getUserName(datahub, userInfo, access_token)
        response.set_cookie(
            "username",
            urllib.parse.quote(username),
            httponly=False,
            secure=True,
            samesite="strict",
        )
    except:
        response.set_cookie(
            "username", "user", httponly=False, secure=True, samesite="strict"
        )
    # delete any leftover error cookie
    response.delete_cookie("error")

    request.session.clear()
    try:
        writeLogJson("callback", 307, startTime)
    except:
        pass
    return response


@router.get(
    "/logout",
    summary="Manually delete server-side user session",
    description="Logs you out of the datahub by removing all cookies set after the login containing the access token and more.",
    response_description="logout successful",
)
async def logout(request: Request):
    response = Response("logout successful", media_type="text/plain")

    # if the user logs out, delete the "data" cookie containing the gitlab token, as well as the other cookies set
    response.delete_cookie("data", path="/arcmanager/api")
    # delete the old data cookies as well (those missing the path parameter)
    response.delete_cookie("data")
    response.delete_cookie("logged_in")
    response.delete_cookie("username")
    response.delete_cookie("timer")
    response.delete_cookie("pat")
    request.cookies.clear()
    return response


@router.get(
    "/refresh",
    summary="Manually refresh user session",
    description="Refreshes your access token using the refresh token with a new one",
    response_description="refresh successful",
)
async def refresh(data: Annotated[str, Cookie()]):
    startTime = time.time()
    ## Decode Cookie ##
    # get public key from .env to decode data (in form of a byte string)
    public_key = (
        b"-----BEGIN PUBLIC KEY-----\n"
        + os.environ.get("PUBLIC_RSA").encode()
        + b"\n-----END PUBLIC KEY-----"
    )

    try:
        decodedToken = jwt.decode(data, public_key, algorithms=["RS256", "HS256"])

        fernetKey = os.environ.get("FERNET").encode()
        access_token = (
            Fernet(fernetKey).decrypt(decodedToken["gitlab"].encode()).decode()
        )
        refresh_token = (
            Fernet(fernetKey).decrypt(decodedToken["refresh"].encode()).decode()
        )
        target = decodedToken["target"]

    except:
        writeLogJson("refresh", 500, startTime, "Could not refresh token!")
        raise HTTPException(
            status_code=500,
            detail=f"Could not refresh access token! Please login again!",
        )

    response = Response("Session refresh was successful!", media_type="text/plain")

    # application id and secret for the datahub
    app_id = os.environ.get(f"{target.upper()}_CLIENT_ID")
    app_secret = os.environ.get(f"{target.upper()}_CLIENT_SECRET")

    header = {
        "Authorization": "Bearer " + access_token,
    }

    refreshRequest = requests.post(
        f"{os.environ.get(getTarget(target))}/oauth/token",
        data={
            "client_id": app_id,
            "client_secret": app_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "redirect_uri": f"{backend_address}callback?datahub={target}",
        },
        headers=header,
    )

    # build the new cookie using the new access token and refresh token
    if refreshRequest.ok:
        result = refreshRequest.json()

        new_access = result["access_token"]
        new_refresh = result["refresh_token"]

        # read out private key from .env
        pr_key = (
            b"-----BEGIN RSA PRIVATE KEY-----\n"
            + os.environ.get("PRIVATE_RSA").encode()
            + b"\n-----END RSA PRIVATE KEY-----"
        )
        cookieData = {
            "gitlab": encryptToken(new_access.encode()).decode(),
            "target": target,
            "refresh": encryptToken(new_refresh.encode()).decode(),
        }
        # encode cookie data with rsa key
        encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")
        response.set_cookie(
            "data",
            encodedCookie,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/arcmanager/api",
        )
        response.set_cookie(
            "timer", time.time(), httponly=False, secure=True, samesite="strict"
        )
        writeLogJson("refresh", 200, startTime)
        return response

    else:
        writeLogJson(
            "refresh", refreshRequest.status_code, startTime, "Could not refresh token!"
        )
        raise HTTPException(
            status_code=refreshRequest.status_code,
            detail=f"Could not refresh access token! Please login again!",
        )


@router.put(
    "/addPAT",
    summary="Add your personal access token",
    description="Add your Personal Access Token (PAT) to your session, extending it to the expiration date of your token",
    response_description="Your PAT was set successfully",
)
async def addPAT(data: Annotated[str, Cookie()], pat: pat):
    startTime = time.time()

    ## Decode Cookie ##
    # get public key from .env to decode data (in form of a byte string)
    public_key = (
        b"-----BEGIN PUBLIC KEY-----\n"
        + os.environ.get("PUBLIC_RSA").encode()
        + b"\n-----END PUBLIC KEY-----"
    )
    try:
        decodedToken = jwt.decode(data, public_key, algorithms=["RS256", "HS256"])

    except:
        writeLogJson("addPAT", 500, startTime, "Could not add PAT!")
        raise HTTPException(
            status_code=500,
            detail=f"Could not add PAT! Please login again!",
        )

    response = Response(
        "Your Personal Access token was added successfully!", media_type="text/plain"
    )

    # read out private key from .env
    pr_key = (
        b"-----BEGIN RSA PRIVATE KEY-----\n"
        + os.environ.get("PRIVATE_RSA").encode()
        + b"\n-----END RSA PRIVATE KEY-----"
    )
    cookieData = {
        "gitlab": encryptToken(pat.pat.encode()).decode(),
        "target": decodedToken["target"],
        "refresh": decodedToken["refresh"],
    }
    # encode cookie data with rsa key
    encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")
    response.set_cookie(
        "data",
        encodedCookie,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/arcmanager/api",
    )
    response.set_cookie("pat", "true", httponly=False, secure=True, samesite="strict")
    writeLogJson("addPAT", 200, startTime)
    return response
