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
    Depends,
    HTTPException,
    Query,
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
    filemode="a",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)

commonToken = Annotated[str, Depends(getData)]


# sends back the list of templates used by the swate alpha
@router.get(
    "/getTemplates",
    summary="Retrieve a list of swate templates",
    status_code=status.HTTP_200_OK,
    description="Get a list of all currently available templates",
    response_description="Array containing all templates with detailed information, such as name, description, table layout, author etc.",
)
async def getTemplates() -> Templates:
    startTime = time.time()
    # send get request to swate api requesting all templates
    request = requests.get(
        "https://swate-alpha.nfdi4plants.org/api/ITemplateAPIv1/getTemplates"
    )
    try:
        templateJson = request.json()
    except:
        templateJson = {}

    # first try the old way to list the templates
    try:
        templateList = [json.loads(x) for x in templateJson]

        # include list of custom templates
        templatePath = os.environ.get("BACKEND_SAVE") + "templates"
        listOfTemplates = os.listdir(templatePath)

        for entry in listOfTemplates:
            with open(templatePath + "/" + entry, "r") as f:
                data = json.load(f)
                templateList.append(data)
                f.close()
    except:
        pass

    # if it fails try the new alternative way
    try:
        templateList2 = [x for x in json.loads(templateJson)]
        # include list of custom templates
        templatePath = os.environ.get("BACKEND_SAVE") + "templates"
        listOfTemplates = os.listdir(templatePath)

        for entry in listOfTemplates:
            with open(templatePath + "/" + entry, "r") as f:
                data = json.load(f)
                templateList2.append(data)
                f.close()

    except:
        templateJson = {}

    # if swate is down, return error
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
            status_code=request.status_code,
            detail="Couldn't receive swate templates",
        )

    logging.info("Sent list of swate templates to client!")
    writeLogJson(
        "getTemplates",
        200,
        startTime,
    )
    # return the templates
    try:
        return Templates(templates=templateList)
    except:
        return Templates(templates=templateList2)


# gets a specific template by its id (from swate) UNUSED
@router.get(
    "/getTemplate",
    summary="Retrieve the specific template",
    status_code=status.HTTP_200_OK,
    deprecated=True,
    include_in_schema=False,
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

    logging.info(f"Sending template with id {id} to client!")
    writeLogJson(
        "getTemplate",
        200,
        startTime,
    )
    return TemplateBB(templateBB=templateJson["TemplateBuildingBlocks"])


# gets a list of fitting terms for the given input, parent name and accession
@router.get(
    "/getTerms",
    summary="Retrieve Terms for the given query",
    status_code=status.HTTP_200_OK,
    description="Get a list of all available terms for the given query",
    response_description="Array containing up to 50 terms related to the input query with name, description, ontology reference and more.",
)
async def getTerms(
    input: str,
) -> Terms:
    startTime = time.time()
    # the following requests will timeout after 7s (10s for extended), because swate could otherwise freeze the backend by not returning any answer
    try:
        request = requests.post(
            "https://swate-alpha.nfdi4plants.org/api/IOntologyAPIv3/searchTerm",
            data=json.dumps(
                [
                    {
                        "limit": 50,
                        "query": input,
                    }
                ]
            ),
            timeout=10,
        )
        logging.debug(f"Getting a list of terms for the input '{input}'!")

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
    summary="Retrieve Term suggestions for the given query and parent term",
    status_code=status.HTTP_200_OK,
    description="Get a list of all available terms for the given query in relation to the parentTermAccession value",
    response_description="Array containing terms related to the input query and parent accession with name, description, ontology reference and more.",
)
async def getTermSuggestionsByParentTerm(
    parentName: str, parentTermAccession: str
) -> Terms:
    startTime = time.time()
    # the following requests will timeout after 7s (10s for extended), because swate could otherwise freeze the backend by not returning any answer
    try:
        # default is an request call containing the parentTerm values
        request = requests.post(
            "https://swate-alpha.nfdi4plants.org/api/IOntologyAPIv2/getAllTermsByParentTerm",
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


## UNUSED
@router.get(
    "/getTermSuggestions",
    summary="Retrieve Term suggestions by given input",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
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
    description="Create/Update a new swate annotation sheet containing the table data given in the request body. The layout is structured columnwise, meaning the first array in tablehead array adresses the first column and so on.",
    response_description="Response of the commit from Gitlab.",
)
async def saveSheet(request: Request, content: sheetContent, token: commonToken):
    startTime = time.time()
    try:
        target = token["target"]

        path = content.path
        projectId = content.id
        name = content.name
        branch = content.branch

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
    await arc_file(projectId, path, request, token)

    pathName = f"{os.environ.get('BACKEND_SAVE')}{target}-{projectId}/{path}"

    # if no sheet name is given, name it "sheet1"
    if name == "":
        name = "sheet1"

    # add the new sheet to the file
    createSheet(content, target)

    name = name.replace(" ", "_")

    # send the edited file back to gitlab
    response = await commitFile(
        request, projectId, path, token, pathName, message=name, branch=branch
    )
    writeLogJson("saveSheet", 200, startTime)
    return str(response)


@router.get(
    "/getSheets",
    summary="Get the different annotation metadata sheets of an isa file",
    status_code=status.HTTP_200_OK,
    description="Get a list containing the different swate sheets and a list containing their names.",
    response_description="Two lists, one containing the different swate sheets data and one list containing their different names",
)
async def getSheets(
    request: Request,
    path: str,
    id: Annotated[int, Query(ge=1)],
    token: commonToken,
    branch: str = "main",
) -> tuple[list, list[str]]:
    startTime = time.time()

    # get the file in the backend
    await arc_file(id, path, request, token, branch)

    # construct path to the backend
    pathName = f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{id}/{path}"

    writeLogJson("getSheets", 200, startTime)
    return getSwateSheets(pathName, getIsaType(path))


@router.put(
    "/saveTemplate",
    summary="Update or save changes to a template",
    status_code=status.HTTP_204_NO_CONTENT,
    description="If you use the template editor or upload a custom made template through this endpoint it will be stored in the backend storage and is available through the /getTemplates endpoint later on",
    response_description="Empty response",
)
async def saveTemplate(request: Request, content: templateContent):
    startTime = time.time()

    # get the full template data
    try:
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

    # replace empty space with underscores
    identifier = identifier.replace(" ", "_")

    # construct the path; the template gets stored as name-identifier.json
    pathName = f"{os.environ.get('BACKEND_SAVE')}templates/{str(username['firstName']).replace(' ', '_')}-{str(username['lastName']).replace(' ', '_')}-{identifier}.json"

    # setup empty header and values lists
    tableHeader = []
    tableValues = []

    # for every column in the table fill the header and values lists
    for i, entry in enumerate(table):

        # if its the input or output column
        if entry["name"] == "Input" or entry["name"] == "Output":
            tableHeader.append(
                {"headertype": entry["name"], "values": [entry["annotationValue"]]}
            )
            tableValues.append([[i, 0], {"celltype": "FreeText", "values": [""]}])

        # if its a regular column
        else:

            # a header column is structured as dict with headertype and a list named values, containing the 3 important values for that column
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

            # if its a unit, the values are different and contain the term accession values for the unit
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

            # if its a regular column without unit, the term accession values are empty
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

    # construct the finished template just as it is stored inside of the swate alpha
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

    # save the template as json on the backend
    try:
        with open(pathName, "w", encoding="utf-8") as f:
            json.dump(jsonFile, f, ensure_ascii=False, indent=4)
    except:
        logging.error("An error occurred trying to save the template!")
        writeLogJson(
            "saveTemplate", 500, startTime, "Error trying to save the template!"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't save template!",
        )

    logging.info(
        f"Saved Template with name {username['firstName']}-{username['lastName']}-{identifier}.json"
    )

    writeLogJson("saveTemplate", 200, startTime)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
