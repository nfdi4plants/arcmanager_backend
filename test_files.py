from fastapi.testclient import TestClient
from app.models.gitlab.input import folderContent
from dotenv import load_dotenv
from main import app
import os
from fastapi.encoders import jsonable_encoder

load_dotenv()

routerPrefix = "/arcmanager/api/v1/fnf"

cookie = {"data": os.environ.get("TEST_COOKIE")}

testArc = 230

client = TestClient(app, cookies=cookie)


# test chunk 0
def test_upload0():
    f = open(
        f"{os.environ.get('BACKEND_SAVE')}test_chunks/{testArc}-zip-test.zip.0",
        "rb",
    )
    body = {
        "name": "zip-test.zip",
        "path": "test/zip-test.zip",
        "id": testArc,
        "namespace": "lu98be/testarc",
        "chunkNumber": 0,
        "totalChunks": 3,
    }

    request = client.post(
        f"{routerPrefix}/uploadFile", data=body, files={"file": f.read()}
    )
    f.close()
    assert request.status_code == 202


# test chunk 1
def test_upload1():
    f = open(
        f"{os.environ.get('BACKEND_SAVE')}test_chunks/{testArc}-zip-test.zip.1",
        "rb",
    )
    body = {
        "name": "zip-test.zip",
        "path": "test/zip-test.zip",
        "id": testArc,
        "namespace": "lu98be/testarc",
        "chunkNumber": 1,
        "totalChunks": 3,
    }

    request = client.post(
        f"{routerPrefix}/uploadFile", data=body, files={"file": f.read()}
    )
    f.close()
    assert request.status_code == 202


# test finished upload with last chunk
def test_upload2():
    f = open(
        f"{os.environ.get('BACKEND_SAVE')}test_chunks/{testArc}-zip-test.zip.2",
        "rb",
    )
    body = {
        "name": "zip-test.zip",
        "path": "test/zip-test.zip",
        "id": testArc,
        "namespace": "lu98be/testarc",
        "chunkNumber": 2,
        "totalChunks": 3,
    }

    request = client.post(
        f"{routerPrefix}/uploadFile", data=body, files={"file": f.read()}
    )
    f.close()
    assert request.status_code == 201


def test_deleteFile():
    request = client.delete(
        f"{routerPrefix}/deleteFile",
        params={
            "path": "test/zip-test.zip",
            "id": testArc,
        },
    )
    assert request.status_code == 200


def test_createFolder():
    body = folderContent(
        identifier="test/testFolder", id=testArc, path="", branch="main"
    )

    request = client.post(f"{routerPrefix}/createFolder", json=jsonable_encoder(body))

    assert request.status_code == 201


def test_renameFolder():
    request = client.put(
        f"{routerPrefix}/renameFolder",
        params={
            "id": testArc,
            "oldPath": "test/testFolder",
            "newPath": "test/renamedFolder",
            "branch": "main",
        },
    )

    assert request.status_code == 200


def test_deleteFolder():
    request = client.delete(
        f"{routerPrefix}/deleteFolder",
        params={
            "path": "test/renamedFolder",
            "id": testArc,
        },
    )

    assert request.status_code == 200
