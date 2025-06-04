import datetime
from fastapi.testclient import TestClient
from app.models.gitlab.projects import Projects
from app.models.gitlab.arc import Arc
from app.models.gitlab.file import FileContent
from app.models.gitlab.input import isaContent, syncAssayContent, syncStudyContent
from app.models.gitlab.banner import Banner
from dotenv import load_dotenv
from main import app
import os
from fastapi.encoders import jsonable_encoder

load_dotenv()

routerPrefix = "/arcmanager/api/v1/projects"

cookie = {"data": os.environ.get("TEST_COOKIE")}

testArc = 230

client = TestClient(app, cookies=cookie)


def test_getArcs():
    response = client.get(f"{routerPrefix}/arc_list")
    assert response.status_code == 200
    assert Projects.model_validate_json(response.content)


def test_public_arcs():
    response = client.get(f"{routerPrefix}/public_arcs", params={"target": "tuebingen"})
    assert response.status_code == 200
    assert Projects.model_validate_json(response.content)


def test_arc_tree():
    response = client.get(f"{routerPrefix}/arc_tree", params={"id": testArc})
    assert response.status_code == 200
    assert Arc.model_validate_json(response.content)

    testFail = client.get(f"{routerPrefix}/arc_tree", params={"id": 232})

    assert testFail.status_code == 404


def test_arc_path():
    response = client.get(
        f"{routerPrefix}/arc_path", params={"id": testArc, "path": "assays"}
    )
    assert response.status_code == 200
    assert Arc.model_validate_json(response.content)


def test_arc_file():
    # returns a dict struct
    response = client.get(
        f"{routerPrefix}/arc_file",
        params={"id": testArc, "path": "isa.investigation.xlsx"},
    )

    # returns a FileContent Model
    readme = client.get(
        f"{routerPrefix}/arc_file",
        params={"id": testArc, "path": "README.md"},
    )
    assert response.status_code == 200
    assert readme.status_code == 200

    assert FileContent.model_validate_json(readme.content)


def test_saveFile():
    body = isaContent(
        isaInput=[
            "Investigation Identifier",
            "testarc_arcmanager",
            "",
            "this test was successful",
        ],
        isaPath="isa.investigation.xlsx",
        isaRepo=testArc,
        arcBranch="main",
    )

    request = client.put(f"{routerPrefix}/saveFile", json=jsonable_encoder(body))

    assert request.status_code == 200


def test_commitFile():
    currentTime = datetime.datetime.today().strftime("%d.%m.%Y-%H:%M")
    content = {"content": f"{currentTime} -- Test was successful!"}

    request = client.put(
        f"{routerPrefix}/commitFile",
        json=jsonable_encoder(content),
        params={"id": testArc, "repoPath": "test/test.txt"},
    )

    assert request.status_code == 200


def test_getChanges():
    response = client.get(f"{routerPrefix}/getChanges", params={"id": testArc})

    assert response.status_code == 200


def test_syncAssay():
    body = syncAssayContent(
        id=testArc,
        pathToAssay="assays/assay1/isa.assay.xlsx",
        pathToStudy="studies/study1/isa.study.xlsx",
        assayName="assay1",
        branch="main",
    )

    request = client.patch(f"{routerPrefix}/syncAssay", json=jsonable_encoder(body))

    assert request.status_code == 200


def test_syncStudy():
    body = syncStudyContent(
        id=testArc,
        pathToStudy="studies/study1/isa.study.xlsx",
        studyName="study1",
        branch="main",
    )

    request = client.patch(f"{routerPrefix}/syncStudy", json=jsonable_encoder(body))

    assert request.status_code == 200


def test_getBranches():
    response = client.get(f"{routerPrefix}/getBranches", params={"id": testArc})

    assert response.status_code == 200


def test_getBanner():
    response = client.get(f"{routerPrefix}/getBanner")

    assert response.status_code == 200

    # only validate if there is content
    if response.content:
        assert Banner.model_validate_json(response.content)
