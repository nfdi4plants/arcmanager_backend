import datetime
import json
import logging
import os
import time
from typing import Annotated
import uuid
from fastapi import (
    APIRouter,
    Cookie,
    HTTPException,
    status,
    Response,
    Request,
    Header,
)
import requests

from app.api.IO.excelIO import createSheet, getIsaType, getSwateSheets
from app.api.endpoints.projects import arc_file, commitFile, getData, writeLogJson
from app.models.gitlab.input import sheetContent, templateContent
from app.models.swate.template import Templates
from app.models.swate.templateBuildingBlock import TemplateBB
from app.models.swate.term import Terms

router = APIRouter()

logging.basicConfig(
    filename="backend.log",
    filemode="w",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)


@router.get(
    "/getTemplates",
    summary="Retrieve a list of swate templates",
    status_code=status.HTTP_200_OK,
)
async def getTemplates() -> Templates:
    startTime = time.time()
    # send get request to swate api requesting all templates
    request = requests.get(
        "https://swate-alpha.nfdi4plants.org/api/ITemplateAPIv1/getTemplates"
    )
    try:
        templateJson = request.json()
        templateList = []
        for x in templateJson:
            templateList.append(json.loads(x))

        # include list of custom templates
        templatePath = os.environ.get("BACKEND_SAVE") + "templates"
        listOfTemplates = os.listdir(templatePath)

        for entry in listOfTemplates:
            with open(templatePath + "/" + entry, "r") as f:
                data = json.load(f)
                templateList.append(data)
                f.close()

    except:
        templateJson = {}

    # if swate is down, return error 500
    if not request.ok:
        logging.error(
            f"There was an error retrieving the swate templates! ERROR: {templateJson}"
        )
        writeLogJson(
            "getTemplates",
            500,
            startTime,
            f"There was an error retrieving the swate templates! ERROR: {templateJson}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't receive swate templates",
        )

    # map the received list to the model 'Templates'
    template_list = Templates(templates=templateList)

    logging.info("Sent list of swate templates to client!")
    writeLogJson(
        "getTemplates",
        200,
        startTime,
    )
    # return the templates
    return template_list


@router.get(
    "/getTemplate",
    summary="Retrieve the specific template",
    status_code=status.HTTP_200_OK,
)
async def getTemplate(id: str) -> TemplateBB:
    startTime = time.time()
    # wrap the desired id in an json array
    payload = json.dumps([id])

    logging.debug("Getting template with id: " + id)
    # request the template
    request = requests.post(
        "https://swate.nfdi4plants.org/api/IProtocolAPIv1/getProtocolById",
        data=payload,
    )
    try:
        templateJson = request.json()
    except:
        templateJson = {}
    # if swate is down (or the desired template somehow not available) return error 400
    if not request.ok:
        logging.error(
            f"There was an error retrieving the swate template with id {id} ! ERROR: {templateJson}"
        )
        writeLogJson(
            "getTemplate",
            400,
            startTime,
            f"There was an error retrieving the swate template with id {id} ! ERROR: {templateJson}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't find template with id: " + id,
        )

    # return just the buildingBlocks part of the template (rest is already known)
    templateBlocks = TemplateBB(templateBB=templateJson["TemplateBuildingBlocks"])

    logging.info(f"Sending template with id {id} to client!")
    writeLogJson(
        "getTemplate",
        200,
        startTime,
    )
    return templateBlocks


@router.get(
    "/getTerms",
    summary="Retrieve Terms for the given query and parent term",
    status_code=status.HTTP_200_OK,
)
async def getTerms(
    input: str,
    parentName: str,
    parentTermAccession: str,
    advanced=False,
) -> Terms:
    startTime = time.time()
    # the following requests will timeout after 7s (10s for extended), because swate could otherwise freeze the backend by not returning any answer
    try:
        # if there is an extended search requested, make an advanced search call
        if advanced == "true":
            request = requests.post(
                "https://swate.nfdi4plants.org/api/IOntologyAPIv2/getTermsForAdvancedSearch",
                data=json.dumps(
                    [
                        {
                            "Ontologies": None,
                            "TermName": input,
                            "TermDefinition": "",
                            "KeepObsolete": False,
                        }
                    ]
                ),
                timeout=10,
            )
            logging.debug(f"Getting an extended list of terms for the input '{input}'!")
        else:
            # default is an request call containing the parentTerm values
            request = requests.post(
                "https://swate.nfdi4plants.org/api/IOntologyAPIv2/getTermSuggestionsByParentTerm",
                data=json.dumps(
                    [
                        {
                            "n": 20,
                            "parent_term": {
                                "Name": parentName,
                                "TermAccession": parentTermAccession,
                            },
                            "query": input,
                        }
                    ]
                ),
                timeout=7,
            )
            logging.debug(
                f"Getting an specific list of terms for the input '{input}' with parent '{parentName}'!"
            )
        try:
            termJson = request.json()
        except:
            termJson = {}
    # if there is a timeout, respond with an error 504
    except requests.exceptions.Timeout:
        logging.warning("Request took to long! Sending timeout error to client...")
        writeLogJson(
            "getTerms",
            504,
            startTime,
            "Request took to long! Sending timeout error to client...",
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="No term could be found in time!",
        )

    # if there is a different kind of error, return error 400
    except:
        logging.error(
            f"There was an error retrieving the terms for '{input}'! ERROR: {termJson}"
        )
        writeLogJson(
            "getTerms",
            400,
            startTime,
            f"There was an error retrieving the terms for '{input}'! ERROR: {termJson}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your request couldn't be processed!",
        )

    logging.info(f"Sent a list of terms for '{input}' to client!")
    writeLogJson("getTerms", 200, startTime)
    try:
        output = Terms(terms=termJson)
    except:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No valid Terms could be found/parsed!",
        )

    # return the list of terms found for the given input
    return output


@router.get(
    "/getTermSuggestionsByParentTerm",
    summary="Retrieve Term suggestions for the given parent term",
    status_code=status.HTTP_200_OK,
)
async def getTermSuggestionsByParentTerm(
    parentName: str, parentTermAccession: str
) -> Terms:
    startTime = time.time()
    # the following requests will timeout after 7s (10s for extended), because swate could otherwise freeze the backend by not returning any answer
    try:
        # default is an request call containing the parentTerm values
        request = requests.post(
            "https://swate.nfdi4plants.org/api/IOntologyAPIv2/getAllTermsByParentTerm",
            data=json.dumps(
                [
                    {
                        "Name": parentName,
                        "TermAccession": parentTermAccession,
                    }
                ]
            ),
            timeout=7,
        )
        logging.debug(
            f"Getting list of suggestion terms for the parent '{parentName}'!"
        )
        try:
            termJson = request.json()
        except:
            termJson = {}
    # if there is a timeout, respond with error 504
    except requests.exceptions.Timeout:
        logging.warning("Request took to long! Sending timeout error to client...")
        writeLogJson(
            "getTermSbPT",
            504,
            startTime,
            "Request took to long! Sending timeout error to client...",
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="No terms could be found in time!",
        )

    # if there is a different kind of error, return error 400
    except:
        logging.error(
            f"There was an error retrieving the terms for '{parentName}'! ERROR: {termJson}"
        )
        writeLogJson(
            "getTermSbPT",
            400,
            startTime,
            f"There was an error retrieving the terms for '{parentName}'! ERROR: {termJson}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your request couldn't be processed!",
        )
    logging.info(f"Sent a list of terms for '{parentName}' to client!")
    writeLogJson(
        "getTermSbPT",
        200,
        startTime,
    )
    try:
        output = Terms(terms=termJson)
    except:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No valid Terms could be found/parsed!",
        )

    # return the list of terms found for the given input
    return output


@router.get(
    "/getTermSuggestions",
    summary="Retrieve Term suggestions by given input",
    status_code=status.HTTP_200_OK,
)
async def getTermSuggestions(input: str, n=20) -> Terms:
    startTime = time.time()
    # the following requests will timeout after 7s (10s for extended), because swate could otherwise freeze the backend by not returning any answer
    try:
        # default is an request call containing the parentTerm values
        request = requests.post(
            "https://swate.nfdi4plants.org/api/IOntologyAPIv2/getTermSuggestions",
            data=json.dumps(
                [
                    {
                        "n": n,
                        "ontology": None,
                        "query": input,
                    }
                ]
            ),
            timeout=7,
        )
        try:
            termJson = request.json()
        except:
            termJson = {}

        logging.debug(f"Getting list of suggestion terms for the input '{input}'!")
    # if there is a timeout, respond with an error 504
    except requests.exceptions.Timeout:
        logging.warning("Request took to long! Sending timeout error to client...")
        writeLogJson(
            "getTermSugg.",
            504,
            startTime,
            "Request took to long! Sending timeout error to client...",
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="No terms could be found in time!",
        )

    # if there is a different kind of error, return error 400
    except:
        logging.error(
            f"There was an error retrieving the terms for '{input}'! ERROR: {termJson}"
        )
        writeLogJson(
            "getTermSugg.",
            400,
            startTime,
            f"There was an error retrieving the terms for '{input}'! ERROR: {termJson}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your request couldn't be processed!",
        )
    logging.info(f"Sent a list of terms for '{input}' to client!")
    writeLogJson(
        "getTermSugg.",
        200,
        startTime,
    )
    try:
        output = Terms(terms=termJson)
    except:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No valid Terms could be found/parsed!",
        )

    # return the list of terms found for the given input
    return output


@router.put(
    "/saveSheet",
    summary="Update or save changes to a sheet",
    status_code=status.HTTP_200_OK,
)
async def saveSheet(
    request: Request, content: sheetContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        target = token["target"]

        path = content.path
        projectId = content.id
        name = content.name

    # if there are either the name or the accession missing, return error 400
    except:
        logging.warning("Client request couldn't be processed, the content is missing!")
        writeLogJson(
            "saveSheet",
            400,
            startTime,
            "Client request couldn't be processed, the content is missing!",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't retrieve content of table",
        )

    # get the file in the backend
    await arc_file(projectId, path, request, data)

    pathName = f"{os.environ.get('BACKEND_SAVE')}{target}-{projectId}/{path}"

    # if no sheet name is given, name it "sheet1"
    if name == "":
        name = "sheet1"

    # add the new sheet to the file
    createSheet(content, target)

    # send the edited file back to gitlab
    response = await commitFile(request, projectId, path, data, pathName, message=name)
    writeLogJson("saveSheet", 200, startTime)
    return str(response)


@router.get(
    "/getSheets",
    summary="Get the different annotation metadata sheets of an isa file",
    status_code=status.HTTP_200_OK,
)
async def getSheets(
    request: Request, path: str, id, data: Annotated[str, Cookie()], branch="main"
) -> tuple[list, list[str]]:
    startTime = time.time()
    try:
        token = getData(data)
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getSheets",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the file in the backend
    await arc_file(id, path, request, data, branch)

    # construct path to the backend
    pathName = f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{id}/{path}"

    # read out the list of swate sheets
    sheets = getSwateSheets(pathName, getIsaType(path))
    writeLogJson("getSheets", 200, startTime)
    return sheets


@router.put(
    "/saveTemplate",
    summary="Update or save changes to a template",
    status_code=status.HTTP_200_OK,
)
async def saveTemplate(
    request: Request, content: templateContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        target = token["target"]

        table = content.table
        name = content.name
        identifier = content.identifier
        description = content.description
        organisation = content.organisation
        version = content.version
        username = content.username
        tags = content.tags

        id = str(uuid.uuid4())
    # if there are either the name or the accession missing, return error 400
    except:
        logging.warning("Client request couldn't be processed, the content is missing!")
        writeLogJson(
            "saveTemplate",
            400,
            startTime,
            "Client request couldn't be processed, the content is missing!",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't retrieve content of table",
        )

    pathName = f"{os.environ.get('BACKEND_SAVE')}templates/{username['firstName']}-{username['lastName']}-{identifier}.json"

    tableHeader = []
    tableValues = []

    for i, entry in enumerate(table):
        if entry["name"] == "Input" or entry["name"] == "Output":
            tableHeader.append(
                {"headertype": entry["name"], "values": [entry["annotationValue"]]}
            )
            tableValues.append([[i, 0], {"celltype": "FreeText", "values": [""]}])
        else:
            tableHeader.append(
                {
                    "headertype": entry["name"],
                    "values": [
                        {
                            "annotationValue": entry["annotationValue"],
                            "termSource": entry["termSource"],
                            "termAccession": entry["termAccession"],
                        }
                    ],
                }
            )
            if type(entry["unit"]) == dict:
                tableValues.append(
                    [
                        [i, 0],
                        {
                            "celltype": "Unitized",
                            "values": [
                                "",
                                {
                                    "annotationValue": entry["unit"]["name"],
                                    "termSource": entry["unit"]["termSource"],
                                    "termAccession": entry["unit"]["termAccession"],
                                },
                            ],
                        },
                    ]
                )
            else:
                tableValues.append(
                    [
                        [i, 0],
                        {
                            "celltype": "Term",
                            "values": [
                                {
                                    "annotationValue": "",
                                    "termSource": "",
                                    "termAccession": "",
                                }
                            ],
                        },
                    ]
                )

    tableFormatted = {"name": identifier, "header": tableHeader, "values": tableValues}

    jsonFile = {
        "id": id,
        "table": tableFormatted,
        "name": name,
        "description": description,
        "organisation": organisation,
        "version": version,
        "authors": [username],
        "endpoint_repositories": [],
        "tags": tags,
        "last_updated": str(datetime.datetime.now()),
    }

    with open(pathName, "w", encoding="utf-8") as f:
        json.dump(jsonFile, f, ensure_ascii=False, indent=4)

    writeLogJson("saveTemplate", 200, startTime)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
