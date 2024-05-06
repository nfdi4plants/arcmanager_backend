from typing import Annotated
from fastapi import (
    APIRouter,
    Body,
    Cookie,
    Depends,
    HTTPException,
    status,
    Response,
    Request,
    Header,
)

import json
import os
import requests

import logging
import time
import datetime

from app.models.gitlab.arc import Arc

from app.api.endpoints.projects import (
    arc_file,
    arc_path,
    arc_tree,
    getAssays,
    getStudies,
    getData,
    getTarget,
    writeLogJson,
)

router = APIRouter()

logging.basicConfig(
    filename="backend.log",
    filemode="w",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)


# validates the arc
@router.get(
    "/validateArc",
    summary="Validates the ARC, checking if it's ready for publishing",
)
async def validateArc(request: Request, id: int, data: Annotated[str, Cookie()]):
    # this is for measuring the response time of the api
    startTime = time.time()

    # here we retrieve the gitlab access token from the cookies and use it for potential requests to gitlab (e.g. creating a badge or tag)
    try:
        token = getData(data)

        # use this header for all requests to gitlab
        header = {"Authorization": "Bearer " + token["gitlab"]}

        # here we get the targeted git. Use it through "os.environ.get(target)" to get the base address of the gitlab, like "https://gitlab.nfdi4plants.de" (which is stored in the .env)
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client is not authorized to view ARC {id}; Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_path",
            401,
            startTime,
            f"Client is not authorized to view ARC {id}; Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )

    # get the json of the ground arc structure
    arc: Arc = await arc_tree(id, data, request)

    # setup a dict containing the results of the different tests
    valid = {"Assays": [], "Studies": []}

    # check if there are all the necessary folders and the investigation file present inside the ground arc structure
    valid["ARC structure"] = checkContent(
        arc,
        ["studies", "assays", "workflows", "runs", "isa.investigation.xlsx", ".arc"],
    )

    # if the ground structure is valid, then we proceed and check the assays and studies
    if type(valid["ARC structure"]) == bool:
        ## here we start checking the assays and studies
        # first we get a list of names for the assays and studies
        assays = await getAssays(request, id, data)
        studies = await getStudies(request, id, data)

        # here we check the content of every assay whether the folders "dataset" and "protocols are present", as well if the assay file is present
        for entry in assays:
            assay = await arc_path(id, request, f"assays/{entry}", data)
            valid["Assays"].append(
                {
                    entry: checkContent(
                        Arc(Arc=json.loads(assay.body)["Arc"]),
                        ["dataset", "protocols", "isa.assay.xlsx"],
                    )
                }
            )
        # here we check the content of every study whether the folders "resources" and "protocols are present", as well if the study file is present
        for entry in studies:
            study = await arc_path(id, request, f"studies/{entry}", data)
            valid["Studies"].append(
                {
                    entry: checkContent(

                        Arc(Arc=json.loads(study.body)["Arc"]),
                        ["resources", "protocols", "isa.study.xlsx"],
                    ),
                  
                    # TODO: Fix validation at validateStudy and re-implement
                    # "identifier": await validateStudy(
                    #     request, id, f"studies/{entry}", data
                    # ),

                }
            )
        # add the results of the investigation validation to the valid dict
        # TODO: Fix validation at validateInvest and re-implement
        # valid["investigation"] = await validateInvestigation(request, id, data)

    # save the response time and return the dict to the user
    writeLogJson("validateArc", 200, startTime)
    return valid


# validate the investigation file
@router.get("/validateInvest", summary="Validates the Investigation file of the ARC")
async def validateInvestigation(
    request: Request, id: int, data: Annotated[str, Cookie()]
) -> dict[str, bool]:
    startTime = time.time()
    ## here we start checking the fields of the investigation file
    # to check the content of the investigation file, we first need to retrieve it
    # TODO: Does not find the file!
    try:
        investigation: list = await arc_file(
            id, "isa.investigation.xlsx", request, data
        )
    except:
        writeLogJson("validateInvest", 404, startTime, "No investigation found!")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No isa.investigation.xlsx found! ARC is not valid!",
        )
    # a first structure to check the 5 basic investigation identifier
    investSection: dict[str, bool] = {
        # here we check if the identifier field is filled out with a valid string
        "identifier": type(getField(investigation, "Investigation Identifier")[1])
        == str,
        "title": type(getField(investigation, "Investigation Title")[1]) == str,
        "description": type(getField(investigation, "Investigation Description")[1])
        == str,
        # here we check if the submission date field is filled out with an ISO 8601 formatted date string
        "submission": valiDate(
            getField(investigation, "Investigation Submission Date")[1]
        ),
        "public": valiDate(
            getField(investigation, "Investigation Public Release Date")[1]
        ),
    }
    writeLogJson("validateInvest", 200, startTime)
    return investSection


@router.get("/validateStudy", summary="Validates the Investigation file of the ARC")
async def validateStudy(
    request: Request, id: int, path: str, data: Annotated[str, Cookie()]
) -> dict[str, bool]:
    startTime = time.time()
    ## here we start checking the fields of the investigation file
    # to check the content of the investigation file, we first need to retrieve it
    try:
        study: list = await arc_file(id, f"{path}/isa.study.xlsx", request, data)
    except:
        writeLogJson("validateStudy", 404, startTime, "No study found!")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No isa.study.xlsx found! Study is not valid!",
        )
    # a first structure to check the 5 basic investigation identifier
    studySection: dict[str, bool] = {
        # here we check if the identifier field is filled out with a valid string
        "identifier": type(getField(study, "Study Identifier")[1]) == str,
        "title": type(getField(study, "Study Title")[1]) == str,
        "description": type(getField(study, "Study Description")[1]) == str,
        # here we check if the submission date field is filled out with an ISO 8601 formatted date string
        "submission": valiDate(getField(study, "Study Submission Date")[1]),
        "public": valiDate(getField(study, "Study Public Release Date")[1]),
    }
    writeLogJson("validateStudy", 200, startTime)
    return studySection


# check whether the necessary folders and files are present
def checkContent(arc: Arc, content: list) -> bool | str:
    # if the name is found in the list, remove it
    for entry in arc.Arc:
        if entry.name in content:
            content.remove(entry.name)

    # if there is something left in the list, it wasn't found inside the arc and is therefore missing
    if len(content) > 0:
        return f"Missing: {content}"
    else:
        return True


# returns the content of the field with the given name (it looks something like "[Investigation Identifier, testArc]")
def getField(isaFile: list, fieldName: str) -> list:
    # return the first row containing the field name
    for entry in isaFile:
        if fieldName in entry:
            return entry
    # if the field wasn't found, it doesn't exist. Therefore return None
    return [fieldName, None]


# validates a date value
def valiDate(date: str) -> bool:
    try:
        datetime.datetime.fromisoformat(date)
    except:
        return False
    return True
