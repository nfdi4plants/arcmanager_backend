import json
import os
import requests
import jwt

from jwt.algorithms import RSAAlgorithm

from fastapi import Depends, FastAPI
from fastapi.exceptions import HTTPException
from fastapi.security import (
    OAuth2PasswordBearer,
    OAuth2AuthorizationCodeBearer,
    HTTPBearer,
    APIKeyHeader,
    OAuth2,
)
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER")
KEYCLOAK_ISSUER = "https://auth.dev.escience.uni-freiburg.de/realms/dataplant"
KEYCLOAK_PUBLIC_KEY_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs"
KEYCLOAK_CLIENT_ID = "account"

oauth2_scheme = HTTPBearer()

### CURRENTLY UNUSED ###


async def fetch_public_key():
    response = requests.get(KEYCLOAK_PUBLIC_KEY_URL)
    response.raise_for_status()

    public_keys = []
    jwk_set = response.json()
    for key_dict in jwk_set["keys"]:
        # print("key=", key_dict)
        # print("algorithm", key_dict["alg"])
        if (
            key_dict["use"].lower() == "sig"
            and key_dict["alg"].lower() == os.getenv("OAUTH_ALGORITHM", "RS256").lower()
        ):
            public_key = RSAAlgorithm.from_jwk(json.dumps(key_dict))
            public_keys.append(public_key)
        print("pub key is", public_keys)
    return public_keys


async def validate_access_token(access_token: dict = Depends(oauth2_scheme)):
    print(oauth2_scheme)
    print("type", type(access_token))
    try:
        print("this is my token", access_token.credentials)
        public_keys = await fetch_public_key()

        for key in public_keys:
            print("key===", key)
            print(access_token.credentials)
            decoded_token = jwt.decode(
                access_token.credentials,
                key,
                algorithms=["RS256"],
                audience=KEYCLOAK_CLIENT_ID,
            )
        print("decoded token", decoded_token)

        return access_token.credentials

        # if not valid_token:
        #     raise HTTPException(status_code=401, detail="Invalid access token")

    except Exception as e:
        print("error decoding token", e)
        raise HTTPException(status_code=401, detail="Invalid Access Token")
