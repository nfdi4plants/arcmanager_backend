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
