# arcmanager_backend

This is the Backend for the arcmanager.
It runs with fastapi and uvicorn

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

To test the backend, browse to: [localhost](http://localhost:8000/docs)

Currently the backend connects mainly to [gitdev.nfdi4plants.org](https://gitdev.nfdi4plants.org/explore)