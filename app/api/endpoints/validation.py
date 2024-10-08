import re
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
    summary="Validates the ARC",
)
async def validateArc(request: Request, id: int, data: Annotated[str, Cookie()]):
    # this is for measuring the response time of the api
    startTime = time.time()

    # set to true if the arc is fully valid
    fullValidArc = True

    # get the json of the ground arc structure
    arc: Arc = await arc_tree(id, data, request)

    # setup a dict containing the results of the different tests
    valid = {"Assays": [], "Studies": []}

    arcContent = checkContent(
        arc,
        ["studies", "assays", "workflows", "runs", "isa.investigation.xlsx", ".arc"],
    )

    if isinstance(arcContent, str):
        fullValidArc = False

    # check if there are all the necessary folders and the investigation file present inside the ground arc structure
    valid["ARC_Structure"] = arcContent

    ## here we start checking the assays and studies
    # first we get a list of names for the assays and studies
    assays = await getAssays(request, id, data)
    studies = await getStudies(request, id, data)

    # here we check the content of every assay for whether the folders "dataset" and "protocols are present", as well if the assay file is present
    for entry in assays:
        assay = await arc_path(id, request, f"assays/{entry}", data)

        assayContent = checkContent(
            Arc(Arc=json.loads(assay.body)["Arc"]),
            ["dataset", "protocols", "isa.assay.xlsx"],
        )
        if isinstance(assayContent, str):
            fullValidArc = False

        valid["Assays"].append({entry: assayContent})
    # here we check the content of every study whether the folders "resources" and "protocols are present", as well if the study file is present
    for entry in studies:
        study = await arc_path(id, request, f"studies/{entry}", data)

        studyContent = checkContent(
            Arc(Arc=json.loads(study.body)["Arc"]),
            ["resources", "protocols", "isa.study.xlsx"],
        )
        if isinstance(studyContent, str):
            fullValidArc = False

        valid["Studies"].append(
            {
                entry: studyContent,
            }
        )

    validInvest = await validateInvestigation(request, id, data)

    for entry in validInvest:
        if isinstance(validInvest[entry], list):
            for contact in validInvest[entry]:
                if isinstance(contact, str):
                    print(contact)
                    fullValidArc = False
                    break
        else:
            if not validInvest[entry]:
                print(entry)
                fullValidArc = False
                break

    # add the results of the investigation validation to the valid dict
    valid["Investigation"] = validInvest

    # if arc is fully valid, add an additional validation value
    if fullValidArc:
        valid["ARC"] = True

    # save the response time and return the dict to the user
    writeLogJson("validateArc", 200, startTime)
    return valid


# validate the investigation file
@router.get("/validateInvest", summary="Validates the Investigation file of the ARC")
async def validateInvestigation(
    request: Request, id: int, data: Annotated[str, Cookie()]
) -> dict[str, bool | list]:
    startTime = time.time()
    ## here we start checking the fields of the investigation file
    # to check the content of the investigation file, we first need to retrieve it
    try:
        investigation: list = await arc_file(
            id, "isa.investigation.xlsx", request, data
        )
    except:
        writeLogJson("validateInvest", 404, startTime, "No investigation found!")
        return {
            "identifier": False,
            "title": False,
            "description": False,
            "contacts": [],
        }
    # a first structure to check the basic investigation identifier
    investSection: dict[str, bool | list] = {
        # here we check if the identifier field is filled out with a valid string
        "identifier": isinstance(
            getField(investigation, "Investigation Identifier")[1], str
        ),
        "title": isinstance(getField(investigation, "Investigation Title")[1], str),
        "description": isinstance(
            getField(investigation, "Investigation Description")[1], str
        ),
        "contacts": await validateContacts(request, id, data),
    }
    writeLogJson("validateInvest", 200, startTime)
    return investSection


# validates title, description and identifier in a study (UNUSED)
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
        "identifier": isinstance(getField(study, "Study Identifier")[1], str),
        "title": isinstance(getField(study, "Study Title")[1], str),
        "description": isinstance(getField(study, "Study Description")[1], str),
    }
    writeLogJson("validateStudy", 200, startTime)
    return studySection


async def validateContacts(
    request: Request, id: int, data: Annotated[str, Cookie()]
) -> list:
    try:
        investigation: list = await arc_file(
            id, "isa.investigation.xlsx", request, data
        )
    except:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No isa.investigation.xlsx found! ARC is not valid!",
        )

    contacts = []

    counter = 1

    lastName = getField(investigation, "Investigation Person Last Name")[counter]

    while isinstance(lastName, str) and lastName != "":
        firstName = getField(investigation, "Investigation Person First Name")[counter]
        email = getField(investigation, "Investigation Person Email")[counter]
        affiliation = getField(investigation, "Investigation Person Affiliation")[
            counter
        ]

        # check first name
        if isinstance(firstName, str) and firstName != "":
            # check email
            if isinstance(email, str) and validMail(email):
                # check affiliation
                if isinstance(affiliation, str) and affiliation != "":
                    contacts.append(True)
                else:
                    contacts.append("Affiliation is missing!")
            else:
                contacts.append("Email missing or not valid!")
        else:
            contacts.append("First Name is missing!")

        counter += 1
        # if there is no next entry, break the loop
        try:
            lastName = getField(investigation, "Investigation Person Last Name")[
                counter
            ]
        except:
            break

    return contacts


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


# validates an email address
def validMail(email: str) -> bool:
    try:
        return not re.match(r"[^@]+@[^@]+\.[^@]+", email) is None
    except:
        return False
