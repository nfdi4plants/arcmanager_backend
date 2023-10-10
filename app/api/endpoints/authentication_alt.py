import json
from fastapi import APIRouter, Request, Response, HTTPException, status

import jwt
import os

import requests

router = APIRouter()


@router.post(
    "/login", summary="Initiate login with given keycloak token and target gitlab"
)
async def login(request: Request):
    # get the body of the request
    requestBody = await request.body()
    loginContent = json.loads(requestBody)

    try:
        # the request should contain the keycloak access token and the name of the target repo
        token = loginContent["token"]
        target = loginContent["target"]
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No token and/or target hub found!",
        )

    header = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }

    # match the name of the target with its corresponding address of the keycloak and retrieve the gitlab access token
    match target:
        case "dev":
            gitToken = requests.get(
                "http://localhost:8080/realms/arcmanager/broker/Gitlab_Dev/token",
                headers=header,
            )

        case "freiburg":
            gitToken = requests.get(
                "http://localhost:8080/realms/arcmanager/broker/Gitlab/token",
                headers=header,
            )

        case "tübingen":
            gitToken = requests.get(
                "http://localhost:8080/realms/arcmanager/broker/Gitlab_Tu/token",
                headers=header,
            )

        case "plantmicrobe":
            gitToken = requests.get(
                "http://localhost:8080/realms/arcmanager/broker/Gitlab_Pm/token",
                headers=header,
            )

        case other:
            gitToken = requests.get(
                "http://localhost:8080/realms/arcmanager/broker/Gitlab_Dev/token",
                headers=header,
            )

    # if the retrieving process didn't work, return exception
    if not gitToken.ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your access token is not authorized to access the hub!",
        )

    response = Response("Success", media_type="text/plain")

    # wrap the gitlab access token and the target name into the cookie payload
    cookieData = {
        "gitlab": gitToken.json()["access_token"],
        "target": loginContent["target"],
    }
    # read out private key from .env
    pr_key = (
        b"-----BEGIN RSA PRIVATE KEY-----\n"
        + os.environ.get("PRIVATE_RSA").encode()
        + b"\n-----END RSA PRIVATE KEY-----"
    )
    # encode cookie data with rsa key
    encodedCookie = jwt.encode(cookieData, pr_key, algorithm="RS256")

    # set the encoded cookie in the response
    response.set_cookie("data", encodedCookie, httponly=True, secure=True)

    return response


@router.get("/logout", summary="Manually delete client side 'data' cookie")
async def logout(request: Request):
    response = Response("logout successful", media_type="text/plain")

    # if the user logs out, delete the "data" cookie containing the gitlab token
    response.delete_cookie("data")
    return response
