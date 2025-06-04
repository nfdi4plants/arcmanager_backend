from fastapi.testclient import TestClient
from app.models.swate.template import Templates
from app.models.swate.term import Terms
from dotenv import load_dotenv
from main import app
import os
from fastapi.encoders import jsonable_encoder

load_dotenv()

routerPrefix = "/arcmanager/api/v1/tnt"

cookie = {"data": os.environ.get("TEST_COOKIE")}

testArc = 230

client = TestClient(app, cookies=cookie)


def test_getTemplates():
    request = client.get(f"{routerPrefix}/getTemplates")

    assert request.status_code == 200
    assert Templates.model_validate_json(request.content)


def test_getTerms():
    request = client.get(f"{routerPrefix}/getTerms", params={"input": "organism"})

    assert request.status_code == 200
    assert Terms.model_validate_json(request.content)


def test_getTermSuggestions():
    request = client.get(
        f"{routerPrefix}/getTermSuggestionsByParentTerm",
        params={"parentName": "organism", "parentTermAccession": "OBI:0100026"},
    )

    assert request.status_code == 200
    assert Terms.model_validate_json(request.content)


def test_getSheets():
    request = client.get(
        f"{routerPrefix}/getSheets",
        params={
            "path": "assays/assay1/isa.assay.xlsx",
            "id": testArc,
            "branch": "main",
        },
    )

    assert request.status_code == 200
