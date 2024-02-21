from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    status,
    Response,
    Request,
    Header,
)
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

# gitlab api commits need base64 encoded content
import base64

import json
import os
import requests
import jwt

from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

import logging
import time

# paths in get requests need to be parsed to uri encoded strings
from urllib.parse import quote

# functions to read and write isa files
from app.api.IO.excelIO import (
    readIsaFile,
    getIsaType,
    writeIsaFile,
    createSheet,
    getSwateSheets,
    appendAssay,
    appendStudy,
)

from app.models.gitlab.projects import *
from app.models.gitlab.arc import *
from app.models.gitlab.commit import *
from app.models.swate.template import *

import hashlib
import tempfile

router = APIRouter()

logging.basicConfig(
    filename="backend.log",
    filemode="w",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)


# Match the given target repo with the address name in the env file (default is the gitlab dev server)
def getTarget(target: str) -> str:
    match target:
        case "dev":
            return "GITLAB_ADDRESS"
        case "freiburg":
            return "GITLAB_FREIBURG"
        case "tübingen":
            return "GITLAB_TUEBINGEN"
        case "plantmicrobe":
            return "GITLAB_PLANTMICROBE"
        case "tuebingen":
            return "GITLAB_TUEBINGEN"
        case other:
            return "GITLAB_ADDRESS"


# get the username using the id
async def getUserName(target: str, userId: int, access_token: str) -> str:
    header = {"Authorization": "Bearer " + access_token}
    userInfo = requests.get(
        f"{os.environ.get(getTarget(target))}/api/v4/users/{userId}",
        headers=header,
    ).json()

    return userInfo["name"]


# decrypt the cookie data with the corresponding public key
def getData(cookie: str):
    # get public key from .env to decode data (in form of a byte string)
    public_key = (
        b"-----BEGIN PUBLIC KEY-----\n"
        + os.environ.get("PUBLIC_RSA").encode()
        + b"\n-----END PUBLIC KEY-----"
    )

    # decode the cookie data
    data = jwt.decode(cookie, public_key, algorithms=["RS256", "HS256"])

    return data


def writeLogJson(endpoint: str, status: int, startTime: float, error=None):
    with open("log.json", "r") as log:
        jsonLog = json.load(log)

    jsonLog.append(
        {
            "endpoint": endpoint,
            "status": status,
            "error": error,
            "date": time.strftime("%d/%m/%Y - %H:%M:%S", time.localtime()),
            "response_time": format(time.time() - startTime),
        }
    )

    with open("log.json", "w") as logWrite:
        json.dump(jsonLog, logWrite, indent=4, separators=(",", ": "))


# get a list of all arcs accessible to the user
@router.get(
    "/arc_list",
    summary="Lists your accessible ARCs",
    status_code=status.HTTP_200_OK,
)
async def list_arcs(request: Request, owned=False):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client connected with no valid cookies/Client is not logged in. Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_file",
            401,
            startTime,
            f"Client connected with no valid cookies/Client is not logged in. Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not logged in",
        )
    if owned == "true":
        arcs = requests.get(
            f"{os.environ.get(target)}/api/v4/projects?per_page=100&min_access_level=10",
            headers=header,
        )
    else:
        arcs = requests.get(
            f"{os.environ.get(target)}/api/v4/projects?per_page=1000",
            headers=header,
        )

    if not arcs.ok:
        logging.warning("Access Token of client is expired!")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Your token is expired! Please login again!",
        )

    project_list = Projects(projects=arcs.json())
    logging.info("Sent list of Arcs")
    writeLogJson("arc_list", 200, startTime)
    return project_list


# get a list of all public arcs
@router.get(
    "/public_arcs", summary="Lists all public ARCs", status_code=status.HTTP_200_OK
)
async def public_arcs(target: str):
    startTime = time.time()
    try:
        target = getTarget(target)
    except:
        writeLogJson(
            "public_arcs",
            404,
            startTime,
            f"Target git not found!",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Target git not found!"
        )

    try:
        # if the requested gitlab is not available after 30s, return error 504
        request = requests.get(
            f"{os.environ.get(target)}/api/v4/projects?per_page=100", timeout=30
        )
    except:
        writeLogJson(
            "public_arcs",
            504,
            startTime,
            f"DataHUB currently not available!!",
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="DataHUB currently not available!!",
        )

    if not request.ok:
        writeLogJson(
            "public_arcs",
            500,
            startTime,
            f"Error retrieving the arcs! ERROR: {request.content}",
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving the arcs! ERROR: {request.content}",
        )

    project_list = Projects(projects=request.json())

    logging.debug("Sent public list of ARCs")
    writeLogJson("public_arcs", 200, startTime)

    return project_list


# get the frontpage tree structure of the arc
@router.get("/arc_tree", summary="Overview of the ARC", status_code=status.HTTP_200_OK)
async def arc_tree(id: int, request: Request):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client has no rights to view this ARC! Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_tree",
            401,
            startTime,
            f"Client has no rights to view this ARC! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )

    arc = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?per_page=100",
        headers=header,
    )

    if not arc.ok:
        arcJson = arc.json()
        logging.error(f"Couldn't find ARC with ID {id}; ERROR: {arc.content[0:100]}")
        writeLogJson(
            "arc_tree",
            404,
            startTime,
            f"Couldn't find ARC with ID {id}; ERROR: {arc.content[0:100]}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Couldn't find ARC with ID {id}; Error: {arcJson['error']}, {arcJson['error_description']}",
        )

    arc_json = Arc(Arc=arc.json())
    logging.info("Sent info of ARC " + str(id))
    writeLogJson("arc_tree", 200, startTime)
    return arc_json


# get a specific tree structure for the given path
@router.get(
    "/arc_path", summary="Subdirectory of the ARC", status_code=status.HTTP_200_OK
)
async def arc_path(id: int, request: Request, path: str):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
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
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )
    arcPath = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?per_page=100&path={path}",
        headers=header,
    )
    # raise error if the given path gives no result
    if not arcPath.ok:
        pathJson = arcPath.json()
        logging.error(f"Path not found! Path: { path } ; ERROR: {arcPath.content}")
        writeLogJson(
            "arc_path",
            404,
            startTime,
            f"Path not found! Path: { path } ; ERROR: {arcPath.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path not found! Error: {pathJson['error']}, {pathJson['error_description']}! Try to login again!",
        )

    arc_json = Arc(Arc=arcPath.json())
    logging.info(f"Sent info of ARC {id} with path {path}")
    writeLogJson("arc_path", 200, startTime)
    return arc_json


# gets the specific file on the given path and either saves it on the backend storage (for isa files) or sends the content directly
@router.get(
    "/arc_file",
    summary="Returns the file on the given path",
    status_code=status.HTTP_200_OK,
)
async def arc_file(id: int, path: str, request: Request, branch="main"):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client is not authorized to get the file! Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_file",
            401,
            startTime,
            f"Client is not authorized to get the file! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to get this file",
        )
    # get HEAD data for fileSize
    # url encode the path
    fileHead = requests.head(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
        headers=header,
    )
    # raise error if file not found
    if not fileHead.ok:
        logging.error(f"File not found! Path: {path}")
        writeLogJson(
            "arc_file",
            404,
            startTime,
            f"File not found! Path: {path}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found! Error: {fileHead.status_code}, Try to log-in again!",
        )

    fileSize = fileHead.headers["X-Gitlab-Size"]

    # if its a isa file, return the content of the file as json to the frontend
    if getIsaType(path) != "":
        # get the raw ISA file
        fileRaw = requests.get(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}/raw?ref={branch}",
            headers=header,
        ).content

        # construct path to save on the backend
        pathName = f"{os.environ.get('BACKEND_SAVE')}{data['target']}-{id}/{path}"

        # create directory for the file to save it, skip if it exists already
        os.makedirs(os.path.dirname(pathName), exist_ok=True)
        with open(pathName, "wb") as file:
            file.write(fileRaw)

        logging.debug("Downloading File to " + pathName)

        # read out isa file and create json
        fileJson = readIsaFile(pathName, getIsaType(path))

        logging.info(f"Sent ISA file {path} from ID: {id}")
        writeLogJson("arc_file", 200, startTime)
        return fileJson["data"]
    # if its not a isa file, return the default metadata of the file to the frontend
    else:
        # if file is too big, skip requesting it
        if int(fileSize) > 10000000:
            logging.warning("File too large! Size: " + fileSize)
            writeLogJson(
                "arc_file",
                413,
                startTime,
                "File too large! Size: " + fileSize,
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large! (over 10 MB)",
            )
        # get the file metadata
        arcFile = requests.get(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
            headers=header,
        )
        logging.info(f"Sent info of {path} from ID: {id}")

        if path.endswith((".txt", ".md", ".html", ".xml")):
            # sanitize content
            # decode the file
            decoded = base64.b64decode(arcFile.json()["content"]).decode("utf-8")

            # remove script and iframe tags
            decoded = decoded.replace("<script>", "---here was a script tag---")
            decoded = decoded.replace("</script>", "")
            decoded = decoded.replace("<iframe>", "---here was a iframe tag---")
            decoded = decoded.replace("</iframe>", "")

            # encode file back and return it to the user
            encoded = decoded.encode("utf-8")
            encoded = base64.b64encode(encoded)

            fileJson = arcFile.json()
            fileJson["content"] = encoded
            writeLogJson("arc_file", 200, startTime)
            return fileJson
        else:
            writeLogJson("arc_file", 200, startTime)
            return arcFile.json()


# reads out the content of the put request body; writes the content to the corresponding isa file on the storage
@router.put("/saveFile", summary="Write content to isa file")
async def saveFile(request: Request):
    startTime = time.time()
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        # get the changes for the isa file from the body
        isaContent = json.loads(requestBody)
        target = data["target"]
    except:
        logging.error(
            f"SaveFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}"
        )
        writeLogJson(
            "saveFile",
            401,
            startTime,
            f"SaveFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    logging.debug(f"Content of isa file change: {isaContent}")
    # write the content to the isa file and get the name of the edited row
    rowName = writeIsaFile(
        isaContent["isaPath"],
        getIsaType(isaContent["isaPath"]),
        isaContent["isaInput"],
        isaContent["isaRepo"],
        target,
    )
    logging.debug("write content to isa file...")
    # the path of the file on the storage for the commit request
    pathName = f"{os.environ.get('BACKEND_SAVE')}{target}-{isaContent['isaRepo']}/{isaContent['isaPath']}"

    logging.debug("committing file to repo...")
    # call the commit function
    try:
        commitResponse = await commitFile(
            request,
            isaContent["isaRepo"],
            isaContent["isaPath"],
            pathName,
            isaContent["arcBranch"],
            rowName,
        )
    except:
        logging.warning(f"Isa file could not be edited! Cookies: {request.cookies}")
        writeLogJson(
            "saveFile",
            400,
            startTime,
            f"Isa file could not be edited! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File could not be edited!",
        )

    logging.info(f"Sent file {isaContent['isaPath']} to ARC {isaContent['isaRepo']}")
    writeLogJson(
        "saveFile",
        200,
        startTime,
    )
    return str(commitResponse)


@router.put("/commitFile", summary="Update the content of the file to the repo")
# sends the http PUT request to the git to commit the file on the given filepath
async def commitFile(
    request: Request, id: int, repoPath, filePath="", branch="main", message=""
):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        # if there is no path, there must be file data in the request body
        if filePath == "":
            fileContent = json.loads(requestBody)
        targetRepo = data["target"]

    except:
        logging.error(
            f"SaveFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}"
        )
        writeLogJson(
            "commitFile",
            400,
            startTime,
            f"SaveFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )
    # create the commit message
    commitMessage = "Updated " + repoPath

    if message != "":
        commitMessage += ", changed " + message

    header = {
        "Authorization": "Bearer " + data["gitlab"],
        "Content-Type": "application/json",
    }
    # if there is a filePath, read out the file and send it to the gitlab
    if filePath != "":
        # data of the commit
        payload = {
            "branch": branch,
            # base64 encoding of the isa file
            "content": base64.b64encode(open(filePath, "rb").read()).decode("utf-8"),
            "commit_message": commitMessage,
            "encoding": "base64",
        }
    # if there is no path, then send the data from the body to the gitlab
    else:
        payload = {
            "branch": branch,
            "content": base64.b64encode(bytes(fileContent["content"], "utf-8")).decode(
                "utf-8"
            ),
            "encoding": "base64",
            "commit_message": commitMessage,
        }

    request = requests.put(
        f"{os.environ.get(getTarget(targetRepo))}/api/v4/projects/{id}/repository/files/{quote(repoPath, safe='')}",
        data=json.dumps(payload),
        headers=header,
    )

    if not request.ok:
        logging.error(f"Couldn't commit to ARC! ERROR: {request.content}")
        writeLogJson(
            "commitFile",
            400,
            startTime,
            f"Couldn't commit to ARC! ERROR: {request.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't commit file to repo! Error: {request.content}",
        )
    logging.info(f"Updated file on path: {repoPath}")
    writeLogJson("commitFile", 200, startTime)
    return request.content


# creates a new project in the repo with a readme file; we then initialize the repo folder on the server with the new id of the ARC;
# then we create the arc and the investigation file and commit the whole structure to the repo
@router.post(
    "/createArc", summary="Creates a new Arc", status_code=status.HTTP_201_CREATED
)
async def createArc(request: Request):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        arcContent = json.loads(requestBody)

        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client not logged in for ARC creation! Cookies: {request.cookies}"
        )
        writeLogJson(
            "createArc",
            401,
            startTime,
            f"Client not logged in for ARC creation! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Please login to create a new ARC",
        )
    # read out the new arc properties
    try:
        name = arcContent["name"]
        description = arcContent["description"]
        investIdentifier = arcContent["investIdentifier"]
    except:
        logging.error(f"Missing content for arc creation! Data: {arcContent}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing content for arc creation!",
        )

    # here we create the project with the readme file
    project = {"name": name, "description": description, "initialize_with_readme": True}

    projectPost = requests.post(
        os.environ.get(target) + "/api/v4/projects",
        headers=header,
        data=json.dumps(project),
    )
    if not projectPost.ok:
        logging.error(f"Couldn't create new ARC! ERROR: {projectPost.content}")
        writeLogJson(
            "createArc",
            500,
            startTime,
            f"Couldn't create new ARC! ERROR: {projectPost.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create new project! Error: {projectPost.content}",
        )

    logging.debug(f"Creating new project with payload {project}")
    # we get all the necessary information back from gitlab, like id, main branch,...
    newArcJson = projectPost.json()
    logging.info(f"Created Arc with Id: {newArcJson['id']}")

    # replace empty space with underscores (arccommander can't process spaces in strings)
    investIdentifier = investIdentifier.replace(" ", "_")

    ## commit the folders and the investigation isa to the repo
    arcData = []

    # fill the payload with all the files and folders

    # isa investigation
    arcData.append(
        {
            "action": "create",
            "file_path": "isa.investigation.xlsx",
            "content": base64.b64encode(
                open(
                    f"{os.environ.get('BACKEND_SAVE')}/isa_files/isa.investigation.xlsx",
                    "rb",
                ).read()
            ).decode("utf-8"),
            "encoding": "base64",
        }
    )

    # .arc folder
    arcData.append(
        {
            "action": "create",
            "file_path": ".arc/.gitkeep",
            "content": None,
        }
    )
    # assays
    arcData.append(
        {
            "action": "create",
            "file_path": "assays/.gitkeep",
            "content": None,
        }
    )

    # runs
    arcData.append(
        {
            "action": "create",
            "file_path": "runs/.gitkeep",
            "content": None,
        }
    )

    # studies
    arcData.append(
        {
            "action": "create",
            "file_path": "studies/.gitkeep",
            "content": None,
        }
    )

    # workflows
    arcData.append(
        {
            "action": "create",
            "file_path": "workflows/.gitkeep",
            "content": None,
        }
    )

    # the arc.cwl
    # currently disabled, as an cwl is no longer required
    """
    arcData.append(
        {
            "action": "create",
            "file_path": "arc.cwl",
            "content": None,
        }
    )
    """
    # wrap the payload into json
    payload = json.dumps(
        {
            "branch": newArcJson["default_branch"],
            "commit_message": "Initial commit of the arc structure",
            "actions": arcData,
        }
    )
    logging.debug(f"Sent commit request to repo with payload {payload}")
    # send the data to the repo
    commitRequest = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{newArcJson['id']}/repository/commits",
        headers=header,
        data=payload,
    )
    if not commitRequest.ok:
        logging.error(
            f"Couldn't commit ARC structure to the Hub! ERROR: {commitRequest.content}"
        )
        writeLogJson(
            "createArc",
            500,
            startTime,
            f"Couldn't commit ARC structure to the Hub! ERROR: {commitRequest.content}",
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't commit the arc to the repo! Error: {commitRequest.content}",
        )
    logging.info(f"Created new ARC with ID: {newArcJson['id']}")

    # write identifier into investigation file
    await arc_file(
        id=newArcJson["id"],
        path="isa.investigation.xlsx",
        request=request,
        branch=newArcJson["default_branch"],
    )
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Identifier", investIdentifier],
        repoId=newArcJson["id"],
        location=data["target"],
    )

    await commitFile(
        request=request,
        id=newArcJson["id"],
        repoPath="isa.investigation.xlsx",
        filePath=f"{os.environ.get('BACKEND_SAVE')}{data['target']}-{newArcJson['id']}/isa.investigation.xlsx",
        branch=newArcJson["default_branch"],
    )
    writeLogJson("createArc", 201, startTime)
    return [projectPost.content, commitRequest.content]


# here we create a assay or study structure and push it to the repo
@router.post(
    "/createISA",
    summary="Creates a new ISA structure",
    status_code=status.HTTP_201_CREATED,
)
async def createIsa(request: Request):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        isaContent = json.loads(requestBody)

        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client not authorized to create new ISA! Cookies: {request.cookies}"
        )
        writeLogJson(
            "createISA",
            401,
            startTime,
            f"Client not authorized to create new ISA! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Not authorized to create new ISA"
        )

    # load the isa properties
    try:
        identifier = isaContent["identifier"]
        id = isaContent["id"]
        type = isaContent["type"]
        branch = isaContent["branch"]
    except:
        logging.error(f"Missing Properties for isa! Data: {isaContent}")
        writeLogJson(
            "createISA",
            400,
            startTime,
            f"Missing Properties for isa! Data: {isaContent}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Properties for the isa!",
        )

    # the identifier must not contain white space
    identifier = identifier.replace(" ", "_")

    ## commit the folders and the investigation isa to the repo
    isaData = []

    match type:
        # if its a study, add a copy of an empty study file found in the backend
        case "studies":
            isaData.append(
                {
                    "action": "create",
                    "file_path": f"{type}/{identifier}/isa.study.xlsx",
                    "content": base64.b64encode(
                        open(
                            f"{os.environ.get('BACKEND_SAVE')}/isa_files/isa.study.xlsx",
                            "rb",
                        ).read()
                    ).decode("utf-8"),
                    "encoding": "base64",
                }
            )

            isaData.append(
                {
                    "action": "create",
                    "file_path": f"{type}/{identifier}/resources/.gitkeep",
                    "content": None,
                }
            )
        # if its an assay, add a copy of an empty assay file from the backend
        case "assays":
            isaData.append(
                {
                    "action": "create",
                    "file_path": f"{type}/{identifier}/isa.assay.xlsx",
                    "content": base64.b64encode(
                        open(
                            f"{os.environ.get('BACKEND_SAVE')}/isa_files/isa.assay.xlsx",
                            "rb",
                        ).read()
                    ).decode("utf-8"),
                    "encoding": "base64",
                }
            )

            isaData.append(
                {
                    "action": "create",
                    "file_path": f"{type}/{identifier}/dataset/.gitkeep",
                    "content": None,
                }
            )
        # if its somehow neither an assay or study to be created
        case other:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot create isa of type " + type,
            )

    # both types have a README.md and two folders called "protocols" and "resources"
    isaData.append(
        {
            "action": "create",
            "file_path": f"{type}/{identifier}/README.md",
            "content": None,
            "encoding": "base64",
        }
    )

    isaData.append(
        {
            "action": "create",
            "file_path": f"{type}/{identifier}/protocols/.gitkeep",
            "content": None,
        }
    )

    # wrap the payload into json
    payload = json.dumps(
        {
            "branch": branch,
            "commit_message": f"Added new {type} {identifier}",
            "actions": isaData,
        }
    )
    logging.debug("Sent commit request with payload " + str(payload))
    # send the data to the repo
    commitRequest = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits",
        headers=header,
        data=payload,
    )
    if not commitRequest.ok:
        logging.error(f"Couldn't commit ISA to ARC! ERROR: {commitRequest.content}")
        writeLogJson(
            "createISA",
            500,
            startTime,
            f"Couldn't commit ISA to ARC! ERROR: {commitRequest.content}",
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't commit ISA structure to repo! Error: {commitRequest.content}",
        )

    logging.info(f"Created {identifier} in {type} for ARC {id}")

    # write identifier into file
    pathName = ""
    match type:
        case "studies":
            # first, get the file
            pathName = f"{type}/{identifier}/isa.study.xlsx"
            await arc_file(
                id,
                path=pathName,
                branch=branch,
                request=request,
            )

            # then write the identifier in the corresponding field
            writeIsaFile(
                path=pathName,
                type="study",
                newContent=["Study Identifier", identifier],
                repoId=id,
                location=data["target"],
            )
        case "assays":
            # first, get the file
            pathName = f"{type}/{identifier}/isa.assay.xlsx"
            await arc_file(
                id,
                path=pathName,
                branch=branch,
                request=request,
            )

            # then write the identifier in the corresponding field
            writeIsaFile(
                path=pathName,
                type="assay",
                newContent=["Measurement Type", identifier],
                repoId=id,
                location=data["target"],
            )
            # edit also the file Name field
            writeIsaFile(
                path=pathName,
                type="assay",
                newContent=["File Name", identifier + "/isa.assay.xlsx", ""],
                repoId=id,
                location=data["target"],
            )
    # send the edited file to the repo
    await commitFile(
        request=request,
        id=id,
        repoPath=pathName,
        filePath=f"{os.environ.get('BACKEND_SAVE')}{data['target']}-{id}/{pathName}",
    )
    writeLogJson(
        "createISA",
        201,
        startTime,
    )
    return commitRequest.content


@router.post(
    "/uploadFile", summary="Uploads the given file to the repo (with or without lfs)"
)
async def uploadFile(request: Request):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        # get the data from the body
        requestForm = await request.form()

        target = getTarget(data["target"])
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
    except:
        logging.error(
            f"uploadFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}"
        )
        writeLogJson(
            "uploadFile",
            400,
            startTime,
            f"uploadFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    try:
        chunkNumber = int(requestForm.get("chunkNumber"))
        totalChunks = int(requestForm.get("totalChunks"))
    except:
        chunkNumber = 0
        totalChunks = 1

    content = await requestForm.get("file").read()
    f = open(
        os.environ.get("BACKEND_SAVE")
        + "cache/"
        + requestForm.get("name")
        + "."
        + str(chunkNumber),
        "wb",
    )
    f.write(content)
    f.close()
    # fullData holds the final file data
    fullData = bytes()
    if chunkNumber + 1 == totalChunks:
        for chunk in range(totalChunks):
            f = open(
                os.environ.get("BACKEND_SAVE")
                + "cache/"
                + requestForm.get("name")
                + "."
                + str(chunk),
                "rb",
            )
            fullData += f.read()
            f.close()

        # clear the chunks
        try:
            for chunk in range(totalChunks):
                os.remove(
                    os.environ.get("BACKEND_SAVE")
                    + "cache/"
                    + f"{requestForm.get('name')}.{chunk}"
                )
        except:
            pass

        # the following code is for uploading a file with LFS (thanks to Julian Weidhase for the code)

        # open up a new hash
        shasum = hashlib.new("sha256")

        if requestForm.get("lfs") == "true":
            logging.debug("Uploading file with lfs...")

            # create a new tempfile to store the data
            tempFile = tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024 * 100, mode="w+b"
            )

            # write the data into the hash and tempfile
            shasum.update(fullData)

            tempFile.write(fullData)

            # jump to file end and read the size
            tempFile.seek(0, 2)

            size = tempFile.tell()

            # get the hash string
            sha256 = shasum.hexdigest()

            # build together the lfs upload json and header
            lfsJson = {
                "operation": "upload",
                "objects": [{"oid": f"{sha256}", "size": f"{size}"}],
                "transfers": ["lfs-standalone-file", "basic"],
                "ref": {"name": f"refs/heads/{requestForm.get('branch')}"},
                "hash_algo": "sha256",
            }

            lfsHeaders = {
                "Accept": "application/vnd.git-lfs+json",
                "Content-type": "application/vnd.git-lfs+json",
            }

            # construct the download url for the file
            downloadUrl = "".join(
                [
                    "https://oauth2:",
                    data["gitlab"],
                    f"@{os.environ.get(target).split('//')[1]}/",
                    f"{requestForm.get('namespace')}.git/info/lfs/objects/batch",
                ]
            )

            r = requests.post(downloadUrl, json=lfsJson, headers=lfsHeaders)

            logging.debug("Posting download URL...")
            try:
                result = r.json()
            except:
                writeLogJson(
                    "uploadFile",
                    500,
                    startTime,
                    f"Error while uploading the file to lfs storage!",
                )
                return "Error: There was an error uploading the file. Please re-authorize and try again!"

            # test if there is a change in the file
            testFail = False
            try:
                test = result["objects"][0]["actions"]

            # if the file is the same, there will be no "actions" attribute
            except:
                testFail = True

            # if the file is new or includes new content, upload it
            if not testFail:
                header_upload = result["objects"][0]["actions"]["upload"]["header"]
                urlUpload = result["objects"][0]["actions"]["upload"]["href"]
                header_upload.pop("Transfer-Encoding")
                tempFile.seek(0, 0)
                res = requests.put(
                    urlUpload,
                    headers=header_upload,
                    data=iter(lambda: tempFile.read(4096 * 4096), b""),
                )

            # build and upload the new pointer file to the arc
            repoPath = quote(requestForm.get("path"), safe="")

            postUrl = f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/{repoPath}"

            pointerContent = (
                f"version https://git-lfs.github.com/spec/v1\n"
                f"oid sha256:{sha256}\nsize {size}\n"
            )

            headers = {
                "Authorization": f"Bearer {data['gitlab']}",
                "Content-Type": "application/json",
            }

            jsonData = {
                "branch": "main",
                "content": pointerContent,
                "commit_message": "create a new lfs pointer file",
            }

            # check if file already exists
            fileHead = requests.head(
                f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/{repoPath}?ref={requestForm.get('branch')}",
                headers=header,
            )
            if fileHead.ok:
                response = requests.put(postUrl, headers=headers, json=jsonData)
            else:
                response = requests.post(postUrl, headers=headers, json=jsonData)

            if not response.ok:
                responseJson = response.json()
                logging.error(f"Couldn't upload to ARC! ERROR: {response.content}")
                writeLogJson(
                    "uploadFile",
                    400,
                    startTime,
                    f"Couldn't upload to ARC! ERROR: {response.content}",
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Couldn't upload file to repo! Error: {responseJson['error']}, {responseJson['error_description']}",
                )

            logging.debug("Uploading pointer file to repo...")
            # logging
            logging.info(
                f"Uploaded new File {requestForm.get('name')} to repo {requestForm.get('id')} on path: {requestForm.get('branch')} with LFS"
            )

            ## add filename to the gitattributes
            url = f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/.gitattributes/raw?ref={requestForm.get('branch')}"

            newLine = f"{requestForm.get('path')} filter=lfs diff=lfs merge=lfs -text\n"

            getResponse = requests.get(url, headers=headers)

            postUrl = f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/{quote('.gitattributes', safe='')}"

            # if .gitattributes doesn't exist, create a new one
            if not getResponse.ok:
                content = newLine

                attributeData = {
                    "branch": requestForm.get("branch"),
                    "content": content,
                    "commit_message": "Create .gitattributes",
                }
                response = requests.post(
                    postUrl, headers=headers, data=json.dumps(attributeData)
                )
                logging.debug("Uploading .gitattributes to repo...")
                writeLogJson(
                    "uploadFile",
                    200,
                    startTime,
                )
                return response.json()

            # if filename is not inside the .gitattributes, add it
            elif not requestForm.get("name") in getResponse.text:
                content = getResponse.text + "\n" + newLine

                attributeData = {
                    "branch": requestForm.get("branch"),
                    "content": content,
                    "commit_message": "Update .gitattributes",
                }

                response = requests.put(
                    postUrl, headers=headers, data=json.dumps(attributeData)
                )
                logging.debug("Updating .gitattributes...")
                writeLogJson(
                    "uploadFile",
                    200,
                    startTime,
                )
                return response.json()
            # if filename already exists, do nothing and just return "File updated"
            else:
                writeLogJson(
                    "uploadFile",
                    200,
                    startTime,
                )
                return "File updated"

        # if its a regular upload without git-lfs
        else:
            # check if file already exists
            fileHead = requests.head(
                f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/{quote(requestForm.get('path'), safe='')}?ref={requestForm.get('branch')}",
                headers=header,
            )
            # if file doesn't exist, upload file
            if not fileHead.ok:
                # gitlab needs to know the branch, the base64 encoded content, a commit message and the format of the encoding (normally base64)
                payload = {
                    "branch": str(requestForm.get("branch")),
                    # base64 encoding of the isa file
                    "content": base64.b64encode(fullData).decode("utf-8"),
                    "commit_message": f"Upload of new File {requestForm.get('name')}",
                    "encoding": "base64",
                }

                # create the file on the gitlab
                request = requests.post(
                    f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/{quote(requestForm.get('path'), safe='')}",
                    data=json.dumps(payload),
                    headers=header,
                )
                statusCode = status.HTTP_201_CREATED

            # if file already exists, update the file
            else:
                payload = {
                    "branch": str(requestForm.get("branch")),
                    # base64 encoding of the isa file
                    "content": base64.b64encode(fullData).decode("utf-8"),
                    "commit_message": f"Updating File {requestForm.get('name')}",
                    "encoding": "base64",
                }

                # update the file to the gitlab
                request = requests.put(
                    f"{os.environ.get(target)}/api/v4/projects/{requestForm.get('id')}/repository/files/{quote(requestForm.get('path'), safe='')}",
                    data=json.dumps(payload),
                    headers=header,
                )
                statusCode = status.HTTP_200_OK

            logging.debug("Uploading file to repo...")
            if not request.ok:
                try:
                    requestJson = request.json()
                except:
                    requestJson = request.content
                logging.error(f"Couldn't upload to ARC! ERROR: {request.content}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Couldn't upload file to repo! Error: {requestJson}",
                )

            # logging
            logging.info(
                f"Uploaded new File {requestForm.get('name')} to repo {requestForm.get('id')} on path: {requestForm.get('path')}"
            )

            response = Response(request.content, statusCode)
            writeLogJson(
                "uploadFile",
                statusCode,
                startTime,
            )
            return response
    else:
        writeLogJson(
            "uploadFile",
            200,
            startTime,
        )
        return f"Received chunk {chunkNumber+1} of {totalChunks} for file {requestForm.get('name')}"


@router.get(
    "/getTemplates",
    summary="Retrieve a list of swate templates",
    status_code=status.HTTP_200_OK,
)
async def getTemplates():
    startTime = time.time()
    # send get request to swate api requesting all templates
    request = requests.get(
        "https://swate.nfdi4plants.org/api/IProtocolAPIv1/getAllProtocolsWithoutXml"
    )

    # if swate is down, return error 500
    if not request.ok:
        logging.error(
            f"There was an error retrieving the swate templates! ERROR: {request.json()}"
        )
        writeLogJson(
            "getTemplates",
            500,
            startTime,
            f"There was an error retrieving the swate templates! ERROR: {request.json()}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't receive swate templates",
        )

    # map the received list to the model 'Templates'
    template_list = Templates(templates=request.json())

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
async def getTemplate(id: str):
    startTime = time.time()
    # wrap the desired id in an json array
    payload = json.dumps([id])

    logging.debug("Getting template with id: " + id)
    # request the template
    request = requests.post(
        "https://swate.nfdi4plants.org/api/IProtocolAPIv1/getProtocolById",
        data=payload,
    )

    # if swate is down (or the desired template somehow not available) return error 400
    if not request.ok:
        logging.error(
            f"There was an error retrieving the swate template with id {id} ! ERROR: {request.json()}"
        )
        writeLogJson(
            "getTemplate",
            400,
            startTime,
            f"There was an error retrieving the swate template with id {id} ! ERROR: {request.json()}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't find template with id: " + id,
        )

    # return just the buildingBlocks part of the template (rest is already known)
    templateBlocks = request.json()["TemplateBuildingBlocks"]

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
    request: Request,
    advanced=False,
):
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
            f"There was an error retrieving the terms for '{input}'! ERROR: {request.json()}"
        )
        writeLogJson(
            "getTerms",
            400,
            startTime,
            f"There was an error retrieving the terms for '{input}'! ERROR: {request.json()}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your request couldn't be processed!",
        )

    logging.info(f"Sent a list of terms for '{input}' to client!")
    writeLogJson("getTerms", 200, startTime)
    # return the list of terms found for the given input
    return request.json()


@router.get(
    "/getTermSuggestionsByParentTerm",
    summary="Retrieve Term suggestions for the given parent term",
    status_code=status.HTTP_200_OK,
)
async def getTermSuggestionsByParentTerm(
    request: Request, parentName: str, parentTermAccession: str
):
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
            f"There was an error retrieving the terms for '{parentName}'! ERROR: {request.json()}"
        )
        writeLogJson(
            "getTermSbPT",
            400,
            startTime,
            f"There was an error retrieving the terms for '{parentName}'! ERROR: {request.json()}",
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
    # return the list of terms found for the given input
    return request.json()


@router.get(
    "/getTermSuggestions",
    summary="Retrieve Term suggestions by given input",
    status_code=status.HTTP_200_OK,
)
async def getTermSuggestions(request: Request, input: str, n=20):
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
            f"There was an error retrieving the terms for '{input}'! ERROR: {request.json()}"
        )
        writeLogJson(
            "getTermSugg.",
            400,
            startTime,
            f"There was an error retrieving the terms for '{input}'! ERROR: {request.json()}",
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
    # return the list of terms found for the given input
    return request.json()


@router.put(
    "/saveSheet",
    summary="Update or save changes to a sheet",
    status_code=status.HTTP_200_OK,
)
async def saveSheet(request: Request):
    startTime = time.time()
    # get the body of the post request
    requestBody = await request.body()

    try:
        content = json.loads(requestBody)
        data = getData(request.cookies.get("data"))
        path = content["path"]
        projectId = content["id"]
        target = data["target"]
        name = content["name"]

        # there should be a parent name and an accession set inside of the body
        templateHead = content["tableHead"]
        templateContent = content["tableContent"]

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
    await arc_file(projectId, path, request)

    pathName = f"{os.environ.get('BACKEND_SAVE')}{target}-{projectId}/{path}"

    # if no sheet name is given, name it "sheet1"
    if name == "":
        name = "sheet1"

    # add the new sheet to the file
    createSheet(templateHead, templateContent, path, projectId, target, name)

    # send the edited file back to gitlab
    response = await commitFile(request, projectId, path, pathName, message=name)
    writeLogJson("saveSheet", 200, startTime)
    return str(response)


@router.get(
    "/getSheets",
    summary="Get the different annotation metadata sheets of an isa file",
    status_code=status.HTTP_200_OK,
)
async def getSheets(request: Request, path: str, id, branch="main"):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        target = getTarget(data["target"])
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getSheets",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the file in the backend
    await arc_file(id, path, request, branch)

    # construct path to the backend
    pathName = f"{os.environ.get('BACKEND_SAVE')}{data['target']}-{id}/{path}"

    # read out the list of swate sheets
    sheets = getSwateSheets(pathName, getIsaType(path))
    writeLogJson("getSheets", 200, startTime)
    return sheets


@router.get(
    "/getChanges",
    summary="Get the commit history of the ARC",
    status_code=status.HTTP_200_OK,
)
async def getChanges(request: Request, id: int):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getChanges",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    commits = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits?per_page=100",
        headers=header,
    )

    if not commits.ok:
        logging.error(f"Commits not found! ID: {id} ; ERROR: {commits.content}")
        writeLogJson(
            "getChanges",
            404,
            startTime,
            f"Commits not found! ID: {id} ; ERROR: {commits.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commits not found! Error: {commits.content}! Try to login again!",
        )
    commitJson = commits.json()

    response = []
    for entry in commitJson:
        response.append(f"{entry['authored_date'].split('T')[0]}: {entry['title']}")

    writeLogJson("getChanges", 200, startTime)
    return response


@router.get(
    "/getStudies", summary="Get a list of current studies", include_in_schema=False
)
async def getStudies(request: Request, id: int):
    startTime = time.time()
    studies = []
    try:
        # request arc studies
        studiesJson = await arc_path(id=id, request=request, path="studies")
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getStudies",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )
    # if its a folder, its a study
    for x in studiesJson.Arc:
        if x.type == "tree":
            studies.append(x.name)
    writeLogJson("getStudies", 200, startTime)
    return studies


@router.get(
    "/getAssays", summary="Get a list of current assays", include_in_schema=False
)
async def getAssays(request: Request, id: int):
    startTime = time.time()
    assays = []
    try:
        # request arc studies
        assaysJson = await arc_path(id=id, request=request, path="assays")
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getAssays",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )
    # if its a folder, its an assay
    for x in assaysJson.Arc:
        if x.type == "tree":
            assays.append(x.name)
    writeLogJson("getAssays", 200, startTime)
    return assays


@router.patch("/syncAssay", summary="Syncs an assay into a study")
async def syncAssay(request: Request):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        fileContent = json.loads(requestBody)
        target = data["target"]

    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "syncAssays",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the necessary information from the request
    try:
        id = fileContent["id"]
        pathToStudy = fileContent["pathToStudy"]
        pathToAssay = fileContent["pathToAssay"]
        assayName = fileContent["assayName"]
        branch = fileContent["branch"]

    except:
        logging.warning(f"Missing Data for Assay sync! Data: {fileContent}")
        writeLogJson(
            "syncAssays",
            400,
            startTime,
            f"Missing Data for Assay sync! Data: {fileContent}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Data!"
        )

    # get the two files in the backend
    await arc_file(id=id, path=pathToAssay, request=request, branch=branch)
    await arc_file(id, pathToStudy, request, branch)

    assayPath = f"{os.environ.get('BACKEND_SAVE')}{target}-{id}/{pathToAssay}"
    studyPath = f"{os.environ.get('BACKEND_SAVE')}{target}-{id}/{pathToStudy}"

    # append the assay to the study
    appendAssay(pathToAssay=assayPath, pathToStudy=studyPath, assayName=assayName)
    logging.debug("committing file to repo...")
    # call the commit function
    try:
        commitResponse = await commitFile(
            request,
            id,
            pathToStudy,
            studyPath,
            branch,
            f": synced {pathToAssay} to {pathToStudy}",
        )
    except:
        logging.warning(
            f"Client is not authorized to commit to ARC! Cookies: {request.cookies}"
        )
        writeLogJson(
            "syncAssays",
            401,
            startTime,
            f"Client is not authorized to commit to ARC! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="No authorized session cookie found",
        )

    logging.info(f"Sent file {pathToStudy} to ARC {id}")
    writeLogJson("syncAssays", 200, startTime)
    # frontend gets the response from the commit post back
    return str(commitResponse)


@router.patch("/syncStudy", summary="Syncs a study into the investigation file")
async def syncStudy(request: Request):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        fileContent = json.loads(requestBody)
        target = data["target"]

    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "syncStudy",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the necessary information from the request
    try:
        id = fileContent["id"]
        pathToStudy = fileContent["pathToStudy"]
        studyName = fileContent["studyName"]
        branch = fileContent["branch"]

    except:
        logging.warning(f"Missing Data for Assay sync! Data: {fileContent}")
        writeLogJson(
            "syncStudy",
            400,
            startTime,
            f"Missing Data for Assay sync! Data: {fileContent}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Data!"
        )

    # get the two files in the backend
    await arc_file(id=id, path="isa.investigation.xlsx", request=request, branch=branch)
    await arc_file(id, pathToStudy, request, branch)

    investPath = f"{os.environ.get('BACKEND_SAVE')}{target}-{id}/isa.investigation.xlsx"
    studyPath = f"{os.environ.get('BACKEND_SAVE')}{target}-{id}/{pathToStudy}"
    # append the study to the investigation file
    appendStudy(pathToInvest=investPath, pathToStudy=studyPath, studyName=studyName)
    logging.debug("committing file to repo...")
    # call the commit function
    try:
        commitResponse = await commitFile(
            request,
            id,
            "isa.investigation.xlsx",
            investPath,
            branch,
            f": synced {pathToStudy} to ISA investigation",
        )
    except:
        logging.warning(
            f"Client is not authorized to commit to ARC! Cookies: {request.cookies}"
        )
        writeLogJson(
            "syncStudy",
            401,
            startTime,
            f"Client is not authorized to commit to ARC! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="No authorized session cookie found",
        )

    logging.info(f"Sent file isa.investigation.xlsx to ARC {id}")
    writeLogJson("syncStudy", 200, startTime)
    # frontend gets a simple 'success' as response
    return str(commitResponse)


# deletes the specific file on the given path
@router.delete(
    "/deleteFile",
    summary="Deletes the file on the given path",
    status_code=status.HTTP_200_OK,
)
async def deleteFile(id: int, path: str, request: Request, branch="main"):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client is not authorized to delete the file! Cookies: {request.cookies}"
        )
        writeLogJson(
            "deleteFile",
            401,
            startTime,
            f"Client is not authorized to delete the file! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to delete this file",
        )

    payload = {"branch": branch, "commit_message": "Delete file " + path}

    deletion = requests.delete(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
        headers=header,
        data=json.dumps(payload),
    )

    if not deletion.ok:
        logging.error(f"Couldn't delete file {path} ! ERROR: {deletion.content}")
        writeLogJson(
            "deleteFile",
            400,
            startTime,
            f"Couldn't delete file {path} ! ERROR: {deletion.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't delete file on repo! Error: {deletion.content}",
        )
    logging.info(f"Deleted file on path: {path}")
    writeLogJson("deleteFile", 200, startTime)
    return "Successfully deleted the file!"


# deletes the specific folder on the given path (including all files)
@router.delete(
    "/deleteFolder",
    summary="Deletes the entire folder on the given path",
    status_code=status.HTTP_200_OK,
)
async def deleteFolder(id: int, path: str, request: Request, branch="main"):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client is not authorized to delete the folder! Cookies: {request.cookies}"
        )
        writeLogJson(
            "deleteFolder",
            401,
            startTime,
            f"Client is not authorized to delete the folder! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to delete this folder",
        )

    # get the content of the folder
    folder = await arc_path(id, request, path)

    # list of all files to be deleted
    payload = []

    # async function filling the payload with all files recursively found in the folder
    async def prepareJson(folder: Arc):
        for entry in folder.Arc:
            # if its a file, add it to the list
            if entry.type == "blob":
                payload.append({"action": "delete", "file_path": entry.path})

            # if its a folder, search the folder for any file
            elif entry.type == "tree":
                await prepareJson(await arc_path(id, request, entry.path))

            # this should never be the case, so pass along anything here
            else:
                pass

    # start searching and filling the payload
    await prepareJson(folder)

    # the final json containing all files to be deleted
    requestData = {
        "branch": branch,
        "commit_message": "Deleting all content from " + path,
        "actions": payload,
    }

    deleteRequest = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits",
        headers=header,
        data=json.dumps(requestData),
    )

    if not deleteRequest.ok:
        logging.error(f"Couldn't delete folder {path} ! ERROR: {deleteRequest.content}")
        writeLogJson(
            "deleteFolder",
            400,
            startTime,
            f"Couldn't delete folder {path} ! ERROR: {deleteRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't delete folder on repo! Error: {deleteRequest.content}",
        )
    logging.info(f"Deleted folder on path: {path}")
    writeLogJson("deleteFolder", 200, startTime)
    return "Successfully deleted the folder!"


# creates a folder on the given path
@router.post(
    "/createFolder",
    summary="Creates a folder on the given path",
    status_code=status.HTTP_201_CREATED,
)
async def createFolder(request: Request):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        folder = json.loads(requestBody)

        target = getTarget(data["target"])
    except:
        logging.warning(
            f"Client not authorized to create new folder! Cookies: {request.cookies}"
        )
        writeLogJson(
            "createFolder",
            401,
            startTime,
            f"Client not authorized to create new folder! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authorized to create new folder",
        )

    # load the properties
    try:
        identifier = folder["identifier"]
        # the identifier must not contain white space
        identifier = identifier.replace(" ", "_")
        path = folder["path"]
        if path == "":
            path = identifier
        else:
            path = f"{path}/{identifier}"
        id = folder["id"]
        payload = {
            "branch": folder["branch"],
            "content": "",
            "commit_message": "Created new folder " + path,
        }
        path += "/.gitkeep"
    except:
        logging.error(f"Missing Properties for folder! Data: {folder}")
        writeLogJson(
            "createFolder",
            400,
            startTime,
            f"Missing Properties for folder! Data: {folder}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Properties for the folder!",
        )

    request = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
        headers=header,
        data=json.dumps(payload),
    )

    if not request.ok:
        logging.error(f"Couldn't create folder {path} ! ERROR: {request.content}")
        writeLogJson(
            "createFolder",
            400,
            startTime,
            f"Couldn't create folder {path} ! ERROR: {request.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't create folder on repo! Error: {request.content}",
        )
    logging.info(f"Created folder on path: {path}")
    writeLogJson("createFolder", 201, startTime)
    return request.content


# get a list of all users for the datahub
@router.get("/getUser", summary="Get a list of all users")
async def getUser(request: Request):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getUser",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    userList = []
    users = requests.head(
        f"{os.environ.get(target)}/api/v4/users?per_page=100",
        headers=header,
    )
    try:
        pages = users.headers["x-total-pages"]
    except:
        writeLogJson(
            "getUser",
            404,
            startTime,
            "No users found! Reason: " + users.reason,
        )
        raise HTTPException(
            status_code=users.status_code,
            detail="No users found! Reason: " + users.reason,
        )

    for x in range(int(pages)):
        users = requests.get(
            f"{os.environ.get(target)}/api/v4/users?per_page=100&without_project_bots=true&page="
            + str(x + 1),
            headers=header,
        )
        userList += users.json()

    logging.info(f"Sent list of all users of the datahub!")
    writeLogJson("getUser", 200, startTime)
    return userList


@router.post(
    "/addUser",
    summary="Adds a user to the project",
    status_code=status.HTTP_201_CREATED,
)
async def addUser(request: Request):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/x-www-form-urlencoded",
        }
        userData = json.loads(requestBody)
        target = getTarget(data["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "addUser",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the id and name of the user
    arcId = userData["id"]
    name = userData["username"]
    userId = userData["userId"]

    # look if the user role is set, else set it to 30 (developer)
    try:
        userRole = userData["role"]
    except:
        userRole = 30

    addRequest = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{arcId}/members",
        headers=header,
        data=f"user_id={userId}&access_level={userRole}",
    )
    if not addRequest.ok:
        logging.error(f"Couldn't add user {name} ! ERROR: {addRequest.content}")
        writeLogJson(
            "addUser",
            400,
            startTime,
            f"Couldn't add user {name} ! ERROR: {addRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't add user to project! Error: {addRequest.content}",
        )
    logging.info(f"Added user {name} to project {arcId} with role {userRole}")
    writeLogJson("addUser", 201, startTime)

    return f"The user {name} was added successfully!"


# get a list of all users for the specific Arc
@router.get("/getArcUser", summary="Get a list of all members of the arc")
async def getArcUser(request: Request, id: int):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getArcUser",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # request to get all users for the specific arc
    users = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/members?per_page=100",
        headers=header,
    )
    if not users.ok:
        userJson = users.json()
        writeLogJson(
            "getArcUser",
            users.status_code,
            startTime,
            f"{userJson['error']}, {userJson['error_description']}",
        )
        raise HTTPException(
            status_code=users.status_code,
            detail=f"{userJson['error']}, {userJson['error_description']}",
        )

    logging.info(f"Sent list of users for project {id}")
    writeLogJson("getArcUser", 200, startTime)
    return users.json()


# removes a user from the specific Arc
@router.delete(
    "/removeUser",
    summary="Removes a user from the project",
)
async def removeUser(request: Request, id: int, userId: int, username: str):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
        }
        target = getTarget(data["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "removeUser",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # request to delete the given user
    removeRequest = requests.delete(
        f"{os.environ.get(target)}/api/v4/projects/{id}/members/{userId}",
        headers=header,
    )
    if not removeRequest.ok:
        logging.error(
            f"Couldn't remove user {username} ! ERROR: {removeRequest.content}"
        )
        writeLogJson(
            "removeUser",
            400,
            startTime,
            f"Couldn't remove user {username} ! ERROR: {removeRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't remove user from project! Error: {removeRequest.content}",
        )
    logging.info(f"Removed user {username} from project {id}")
    writeLogJson("removeUser", 200, startTime)

    return f"The user {username} was removed successfully!"


# edits the role of a user from the specific Arc
@router.put(
    "/editUser",
    summary="Edits a user of the project",
)
async def editUser(request: Request, id: int, userId: int, username: str, role: int):
    startTime = time.time()
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
        }
        target = getTarget(data["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "editUser",
            401,
            startTime,
            f"No authorized Cookie found! Cookies: {request.cookies}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # request to update user with given role
    editRequest = requests.put(
        f"{os.environ.get(target)}/api/v4/projects/{id}/members/{userId}?access_level={role}",
        headers=header,
    )
    if not editRequest.ok:
        logging.error(f"Couldn't edit user {username} ! ERROR: {editRequest.content}")
        writeLogJson(
            "editUser",
            400,
            startTime,
            f"Couldn't edit user {username} ! ERROR: {editRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't edit user from project {id} to role {role}! Error: {editRequest.content}",
        )
    logging.info(f"Edited user {username} from project {id} to role {role}")
    writeLogJson("editUser", 200, startTime)

    return f"The user {username} was edited successfully!"


# sends back a list of metrics for display
@router.get(
    "/getMetrics",
    summary="Returns a json containing the metrics of the api",
    include_in_schema=False,
)
async def getMetrics(request: Request):
    # load the log json containing the data
    try:
        with open("log.json", "r") as log:
            jsonLog = json.load(log)
        if len(jsonLog) < 1:
            raise Exception()
    except:
        raise HTTPException(status_code=500, detail="No Metrics found!")

    # setup the different metrics
    responseTimes = {}
    statusCodes = {}
    errors = []

    # fill the metrics with respective data
    for entry in jsonLog:
        # print(time.strptime(entry["date"], "%d/%m/%Y - %H:%M:%S"))
        # calculate the average response time for each entry point
        try:
            average = responseTimes[entry["endpoint"]][0]
            count = responseTimes[entry["endpoint"]][1]
            responseTime = entry["response_time"]

            newAverage = (float(average) * int(count) + float(responseTime)) / int(
                count + 1
            )

            responseTimes[entry["endpoint"]] = [str(newAverage), count + 1]

        # if there is no entry yet for the endpoint, create one
        except:
            responseTimes[entry["endpoint"]] = [entry["response_time"], 1]

        # calculate the amount of each status code
        try:
            count = statusCodes[entry["status"]]
            statusCodes[entry["status"]] = int(count) + 1
        # if the status code is not listed yet, add it
        except:
            statusCodes[entry["status"]] = 1
        # if there is an error, add it to the array
        if entry["error"] != None:
            errors.append(f"{entry['endpoint']}, {entry['status']}: {entry['error']}")

    return {
        "responseTimes": responseTimes,
        "statusCodes": statusCodes,
        "errors": errors,
    }
