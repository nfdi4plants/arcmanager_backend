# arcmanager_backend

This is the Backend for the ARCmanager.
It runs with [FastAPI](https://fastapi.tiangolo.com/) and [uvicorn](https://www.uvicorn.org/).

Both need to be installed first:

```sh
pip install fastapi
```

```sh
pip install "uvicorn[standard]"
```

To run the server first activate your virtual environment

Then install the dependencies from requirements.txt with:

```sh
pip install -r requirements.txt
```

For development run:

```sh
uvicorn main:app --reload
```

For production run:

```sh
uvicorn main:app
```

For local development change the code in [authentication.py](./app/api/endpoints/authentication.py) to:

```python
backend_address = "http://localhost:8000/arcmanager/api/v1/auth/"
# backend_address = "https://nfdi4plants.de/arcmanager/api/v1/auth/"

redirect = "http://localhost:5173"
# redirect = "https://nfdi4plants.de/arcmanager/app/index.html"
```

To test the backend, browse to: [localhost](http://localhost:8000/arcmanager/api/v1/docs).

Most requests require you to be [logged in](http://localhost:8000/arcmanager/api/v1/auth/login?datahub=tuebingen).

The backend also requires a _.env_ file that contains the following filled out parameters:

```
GITLAB_ADDRESS=https://gitdev.nfdi4plants.org
GITLAB_FREIBURG=https://git.nfdi4plants.org
GITLAB_TUEBINGEN=https://gitlab.nfdi4plants.de
GITLAB_PLANTMICROBE=https://gitlab.plantmicrobe.de
GITLAB_TUEBINGEN_TESTENV=https://gitlab.test-nfdi4plants.de
FDAT=https://fdat.uni-tuebingen.de
BACKEND_SAVE=**Path to store backend data**
SECRET_KEY=**random password string **
PRIVATE_RSA=**Private RSA key (used for jwt token)**
PUBLIC_RSA=**Public RSA key (used for jwt token)**

DEV_CLIENT_ID=**application id**
DEV_CLIENT_SECRET=**application password**
TUEBINGEN_CLIENT_ID=**application id**
TUEBINGEN_CLIENT_SECRET=**application password**
FREIBURG_CLIENT_ID=**application id**
FREIBURG_CLIENT_SECRET=**application password**
PLANTMICROBE_CLIENT_ID=**application id**
PLANTMICROBE_CLIENT_SECRET=**application password**
TUEBINGEN_TESTENV_CLIENT_ID=**application id**
TUEBINGEN_TESTENV_CLIENT_SECRET=**application password**
FDAT_CLIENT_ID=**application id**
FDAT_CLIENT_SECRET=**application password**

METRICS=**random password**
FERNET=**Fernet string (used to independently encrypt the user gitlab token)**
TEST_COOKIE=**a test cookie (containing all necessary data), used for pytesting the application**
```

Every Datahub needs an application used for authentication and token retrieval.
Fill in the respective fields with the client id and password of the respective application.

Fdat uses the same mechanics, but works here as an Invenio storage enabling the publishing of ARCs.
