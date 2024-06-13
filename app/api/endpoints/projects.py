from typing import Annotated
from fastapi import (
    APIRouter,
    Body,
    Cookie,
    File,
    Form,
    HTTPException,
    status,
    Response,
    Request,
    Header,
)
from fastapi.responses import JSONResponse, HTMLResponse
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

from pdf2image import convert_from_bytes  # type: ignore
from io import BytesIO

# paths in get requests need to be parsed to uri encoded strings
from urllib.parse import quote

# functions to read and write isa files
from app.api.IO.excelIO import (
    readExcelFile,
    readIsaFile,
    getIsaType,
    writeIsaFile,
    appendAssay,
    appendStudy,
)

from app.models.gitlab.input import (
    arcContent,
    datamapContent,
    folderContent,
    newIsa,
    isaContent,
    syncAssayContent,
    syncStudyContent,
)
from app.models.gitlab.projects import Projects
from app.models.gitlab.arc import Arc
from app.models.gitlab.commit import Commit
from app.models.gitlab.file import FileContent

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

    return jwt.decode(cookie, public_key, algorithms=["RS256", "HS256"])


# writes the log entry into the json log file
def writeLogJson(endpoint: str, status: int, startTime: float, error=None):
    try:
        with open("log.json", "r") as log:
            jsonLog = json.load(log)

        jsonLog.append(
            {
                "endpoint": endpoint,
                "status": status,
                "error": error,
                "date": time.strftime("%d/%m/%Y - %H:%M:%S", time.localtime()),
                "response_time": time.time() - startTime,
            }
        )

        with open("log.json", "w") as logWrite:
            json.dump(jsonLog, logWrite, indent=4, separators=(",", ": "))
    except:
        logging.warning("Error while logging to log json!")


# get a list of all arcs accessible to the user
@router.get(
    "/arc_list",
    summary="Lists your accessible ARCs",
    status_code=status.HTTP_200_OK,
)
async def list_arcs(
    request: Request, data: Annotated[str, Cookie()], owned=False, page=1
) -> Projects:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client connected with no valid cookies/Client is not logged in. Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_list",
            401,
            startTime,
            f"Client connected with no valid cookies/Client is not logged in.",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not logged in",
        )

    arcList = []

    if owned == "true":
        # first find out how many pages of arcs there are for us to get (check if there are more than 100 arcs at once available)
        arcs = requests.get(
            f"{os.environ.get(target)}/api/v4/projects?min_access_level=30&page={page}",
            headers=header,
        )
        # if there is an error retrieving the content
        if not arcs.ok:
            logging.warning(arcs.content)
            try:
                arcsJson = arcs.json()
            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )
            try:
                message = arcsJson["message"]
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail=message,
                )
            except:
                error = arcsJson["error"]
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail=error + ", " + arcsJson["error_description"],
                )

        try:
            arcList = arcs.json()
            pages = int(arcs.headers["X-Total-Pages"])
            # if there is an error parsing the data to json, throw an exception
        except:
            writeLogJson(
                "arc_list",
                500,
                startTime,
                f"Error while parsing the list of ARCs!",
            )
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error while parsing the list of ARCs!",
            )

    # same procedure, but for general available arcs, not just private ones (more likely to be more than 100)
    else:
        arcs = requests.get(
            f"{os.environ.get(target)}/api/v4/projects?page={page}",
            headers=header,
        )
        if not arcs.ok:
            logging.warning(arcs.content)
            try:
                arcsJson = arcs.json()
            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )
            error = arcsJson["error"]
            raise HTTPException(
                status_code=arcs.status_code,
                detail=error + ", " + arcsJson["error_description"],
            )

        try:
            arcList = arcs.json()
            pages = int(arcs.headers["X-Total-Pages"])

        except:
            writeLogJson(
                "arc_list",
                500,
                startTime,
                f"Error while parsing the list of ARCs!",
            )
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error while parsing the list of ARCs!",
            )

    logging.info("Sent list of Arcs")
    writeLogJson("arc_list", 200, startTime)
    return JSONResponse(
        jsonable_encoder(Projects(projects=arcList)),
        headers={
            "total-pages": str(pages),
            "Access-Control-Expose-Headers": "total-pages",
        },
    )


# get a list of all public arcs
@router.get(
    "/public_arcs", summary="Lists all public ARCs", status_code=status.HTTP_200_OK
)
async def public_arcs(target: str, page=1) -> Projects:
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
            f"{os.environ.get(target)}/api/v4/projects?page={page}",
            timeout=30,
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
    try:
        requestJson = request.json()
        pages = int(request.headers["X-Total-Pages"])
    except:
        writeLogJson(
            "public_arcs",
            500,
            startTime,
            f"Error while parsing the list of ARCs!",
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error while parsing the list of ARCs!",
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

    logging.debug("Sent public list of ARCs")
    writeLogJson("public_arcs", 200, startTime)
    return JSONResponse(
        jsonable_encoder(Projects(projects=requestJson)),
        headers={
            "total-pages": str(pages),
            "Access-Control-Expose-Headers": "total-pages",
        },
    )


# get the frontpage tree structure of the arc
@router.get("/arc_tree", summary="Overview of the ARC", status_code=status.HTTP_200_OK)
async def arc_tree(
    id: int, data: Annotated[str, Cookie()], request: Request, branch="main"
) -> Arc:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client has no rights to view this ARC! Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_tree",
            401,
            startTime,
            f"Client has no rights to view this ARC!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )

    arc = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?per_page=100&ref={branch}",
        headers=header,
    )
    try:
        arcJson = arc.json()
    except:
        writeLogJson(
            "arc_tree",
            404,
            startTime,
            f"ARC with ID {id} is empty!",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No Content found!"
        )
    if not arc.ok:
        logging.error(f"Couldn't find ARC with ID {id}; ERROR: {arc.content[0:100]}")
        writeLogJson(
            "arc_tree",
            404,
            startTime,
            f"Couldn't find ARC with ID {id}; ERROR: {arc.content[0:100]}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Couldn't find ARC with ID {id}; Error: {arc.content[0:100]}",
        )

    logging.info("Sent info of ARC " + str(id))
    writeLogJson("arc_tree", 200, startTime)
    return Arc(Arc=arcJson)


# get a specific tree structure for the given path
@router.get(
    "/arc_path", summary="Subdirectory of the ARC", status_code=status.HTTP_200_OK
)
async def arc_path(
    id: int,
    request: Request,
    path: str,
    data: Annotated[str, Cookie()],
    page=1,
    branch="main",
) -> Arc:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client is not authorized to view ARC {id}; Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_path",
            401,
            startTime,
            f"Client is not authorized to view ARC {id}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )
    arcPath = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?path={path}&page={page}&ref={branch}",
        headers=header,
    )

    try:
        pathJson = arcPath.json()
        pages = int(arcPath.headers["X-Total-Pages"])

    except:
        pathJson = {
            "error": "Parsing Error",
            "error_description": "There was an error parsing the path data for the ARC!",
        }

    # raise error if the given path gives no result
    if not arcPath.ok:
        logging.error(f"Path not found! Path: { path } ; ERROR: {arcPath.content}")
        writeLogJson(
            "arc_path",
            404,
            startTime,
            f"Path not found! Path: { path } ; ERROR: {arcPath.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path not found! Error: {arcPath.content}! Try to login again!",
        )

    logging.info(f"Sent info of ARC {id} with path {path}")
    writeLogJson("arc_path", 200, startTime)
    return JSONResponse(
        jsonable_encoder(Arc(Arc=pathJson)),
        headers={
            "total-pages": str(pages),
            "Access-Control-Expose-Headers": "total-pages",
        },
    )


# gets the specific file on the given path and either saves it on the backend storage (for isa files) or sends the content directly
@router.get(
    "/arc_file",
    summary="Returns the file on the given path",
    status_code=status.HTTP_200_OK,
)
async def arc_file(
    id: int, path: str, request: Request, data: Annotated[str, Cookie()], branch="main"
) -> FileContent | list[list] | dict:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client is not authorized to get the file! Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_file",
            401,
            startTime,
            f"Client is not authorized to get the file!",
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
        pathName = f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{id}/{path}"

        # create directory for the file to save it, skip if it exists already
        os.makedirs(os.path.dirname(pathName), exist_ok=True)
        with open(pathName, "wb") as file:
            file.write(fileRaw)

        logging.debug("Downloading File to " + pathName)

        # read out isa file and create json
        fileJson = readIsaFile(pathName, getIsaType(path))

        logging.info(f"Sent ISA file {path} from ID: {id}")
        writeLogJson("arc_file", 200, startTime)
        if getIsaType(path) == "datamap":
            return fileJson
        return fileJson["data"]
    # if its not a isa file, return the default metadata of the file to the frontend
    else:
        # if file is too big, skip requesting it
        if int(fileSize) > 50000000:
            logging.warning("File too large! Size: " + fileSize)
            writeLogJson(
                "arc_file",
                413,
                startTime,
                "File too large! Size: " + fileSize,
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File too large! (over 50 MB)",
            )
        # get the file metadata
        arcFile = requests.get(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
            headers=header,
        )
        logging.info(f"Sent info of {path} from ID: {id}")
        try:
            arcFileJson = arcFile.json()
        except:
            writeLogJson(
                "arc_file",
                500,
                startTime,
                f"Error while retrieving the content of the file!",
            )
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error while retrieving the content of the file!",
            )

        if path.lower().endswith((".txt", ".md", ".html", ".xml")):
            # sanitize content
            # decode the file

            decoded = base64.b64decode(arcFileJson["content"]).decode(
                "utf-8", "replace"
            )

            # remove script and iframe tags
            decoded = decoded.replace("<script>", "---here was a script tag---")
            decoded = decoded.replace("</script>", "")
            decoded = decoded.replace("<iframe>", "---here was a iframe tag---")
            decoded = decoded.replace("</iframe>", "")

            # encode file back and return it to the user
            encoded = decoded.encode("utf-8")
            encoded = base64.b64encode(encoded)

            fileJson = arcFileJson
            fileJson["content"] = encoded
            writeLogJson("arc_file", 200, startTime)
            return fileJson
        elif path.lower().endswith(".xlsx"):
            decoded = base64.b64decode(arcFileJson["content"])
            return readExcelFile(decoded)
        # if its a pdf, return a html file containing the pdf as images
        elif path.lower().endswith(".pdf"):
            fileName = arcFileJson["file_name"]
            html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                <title>{fileName}</title>
                <style>
                img {{
                    display: block;
                    margin-left: auto;
                    margin-right: auto;
                    margin-bottom: 1em;
                    width: 100%;
                    }}
                </style>
                </head>
                <body>
                """

            decoded = base64.b64decode(arcFileJson["content"])
            try:
                images = convert_from_bytes(
                    decoded,
                    # remove for linux
                    poppler_path=os.environ.get("BACKEND_SAVE") + "poppler/bin",
                )
            except:
                writeLogJson(
                    "arc_file",
                    500,
                    startTime,
                    "File is not a valid pdf or stored as LFS!",
                )
                raise HTTPException(
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="File is not a supported pdf file or stored as LFS!",
                )
            for img in images:
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                html += f"<img src='data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}' />"

            html += "</body></html>"
            logging.info(f"Sent pdf {fileName} from ID: {id}")
            writeLogJson("arc_file", 200, startTime)
            return HTMLResponse(html)
        else:
            writeLogJson("arc_file", 200, startTime)
            return arcFileJson


# reads out the content of the put request body; writes the content to the corresponding isa file on the storage
@router.put("/saveFile", summary="Write content to isa file")
async def saveFile(
    request: Request, isaContent: isaContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        target = token["target"]
    except:
        logging.error(f"SaveFile Request couldn't be processed! Body: {request.body}")
        writeLogJson(
            "saveFile",
            401,
            startTime,
            f"SaveFile Request couldn't be processed! Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    logging.debug(f"Content of isa file change: {isaContent}")

    rowName = isaContent.isaInput[0]
    if isaContent.multiple:
        for entry in isaContent.isaInput:
            writeIsaFile(
                isaContent.isaPath,
                getIsaType(isaContent.isaPath),
                entry,
                isaContent.isaRepo,
                target,
            )
        rowName = "multiple fields"
    else:
        # write the content to the isa file and get the name of the edited row
        rowName = writeIsaFile(
            isaContent.isaPath,
            getIsaType(isaContent.isaPath),
            isaContent.isaInput,
            isaContent.isaRepo,
            target,
        )
    logging.debug("write content to isa file...")
    # the path of the file on the storage for the commit request
    pathName = f"{os.environ.get('BACKEND_SAVE')}{target}-{isaContent.isaRepo}/{isaContent.isaPath}"

    logging.debug("committing file to repo...")
    # call the commit function
    try:
        commitResponse = await commitFile(
            request,
            isaContent.isaRepo,
            isaContent.isaPath,
            data,
            pathName,
            isaContent.arcBranch,
            rowName,
        )
    except:
        logging.warning(f"Isa file could not be edited!")
        writeLogJson(
            "saveFile",
            400,
            startTime,
            f"Isa file could not be edited!",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File could not be edited!",
        )

    logging.info(f"Sent file {isaContent.isaPath} to ARC {isaContent.isaRepo}")
    writeLogJson(
        "saveFile",
        200,
        startTime,
    )
    return str(commitResponse)


@router.put("/commitFile", summary="Update the content of the file to the repo")
# sends the http PUT request to the git to commit the file on the given filepath
async def commitFile(
    request: Request,
    id: int,
    repoPath,
    data: Annotated[str, Cookie()],
    filePath="",
    branch="main",
    message="",
):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
        token = getData(data)
        # if there is no path, there must be file data in the request body
        if filePath == "":
            fileContent = json.loads(requestBody)
        targetRepo = token["target"]

    except:
        logging.error(
            f"SaveFile Request couldn't be processed! Cookies: {request.cookies} ; Body: {request.body}"
        )
        writeLogJson(
            "commitFile",
            400,
            startTime,
            f"SaveFile Request couldn't be processed! Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )
    # create the commit message
    commitMessage = "Updated " + repoPath

    if message != "":
        commitMessage += ", changed " + message

    header = {
        "Authorization": "Bearer " + token["gitlab"],
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
async def createArc(
    request: Request, arcContent: arcContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client not logged in for ARC creation! Cookies: {request.cookies}"
        )
        writeLogJson(
            "createArc",
            401,
            startTime,
            f"Client not logged in for ARC creation!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Please login to create a new ARC",
        )
    # read out the new arc properties
    try:
        name = arcContent.name
        description = arcContent.description
        investIdentifier = arcContent.investIdentifier
    except:
        logging.error(f"Missing content for arc creation! Data: {arcContent}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing content for arc creation!",
        )

    # here we create the project with the readme file
    project = {
        "name": name,
        "description": description,
        "initialize_with_readme": True,
        "visibility": "private",
    }

    # add arc to group, if it is requested
    if arcContent.groupId != None:
        project["namespace_id"] = arcContent.groupId

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
    try:
        newArcJson = projectPost.json()
    except:
        writeLogJson(
            "createArc",
            500,
            startTime,
            f"Error while retrieving data for new ARC!",
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error while retrieving data for new ARC!",
        )

    logging.info(f"Created Arc with Id: {newArcJson['id']}")

    # replace empty space with underscores
    investIdentifier = investIdentifier.replace(" ", "_")

    ## commit the folders and the investigation isa to the repo

    # fill the payload with all the files and folders
    arcData = [
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
        },
        {
            "action": "create",
            "file_path": ".arc/.gitkeep",
            "content": None,
        },
        {
            "action": "create",
            "file_path": "assays/.gitkeep",
            "content": None,
        },
        {
            "action": "create",
            "file_path": "runs/.gitkeep",
            "content": None,
        },
        {
            "action": "create",
            "file_path": "studies/.gitkeep",
            "content": None,
        },
        {
            "action": "create",
            "file_path": "workflows/.gitkeep",
            "content": None,
        },
    ]

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
        data=data,
        branch=newArcJson["default_branch"],
    )
    # fill in the identifier, name and description of the arc into the investigation file
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Identifier", investIdentifier],
        repoId=newArcJson["id"],
        location=token["target"],
    )
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Title", name],
        repoId=newArcJson["id"],
        location=token["target"],
    )
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Description", description],
        repoId=newArcJson["id"],
        location=token["target"],
    )

    await commitFile(
        request=request,
        id=newArcJson["id"],
        repoPath="isa.investigation.xlsx",
        data=data,
        filePath=f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{newArcJson['id']}/isa.investigation.xlsx",
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
async def createIsa(
    request: Request, isaContent: newIsa, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client not authorized to create new ISA! Cookies: {request.cookies}"
        )
        writeLogJson(
            "createISA",
            401,
            startTime,
            f"Client not authorized to create new ISA!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Not authorized to create new ISA"
        )

    # load the isa properties
    try:
        identifier = isaContent.identifier
        id = isaContent.id
        type = isaContent.type
        branch = isaContent.branch
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

    match type:
        # if its a study, add a copy of an empty study file found in the backend
        case "studies":
            isaData = [
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
                },
                {
                    "action": "create",
                    "file_path": f"{type}/{identifier}/resources/.gitkeep",
                    "content": None,
                },
            ]
        # if its an assay, add a copy of an empty assay file from the backend
        case "assays":
            isaData = [
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
                },
                {
                    "action": "create",
                    "file_path": f"{type}/{identifier}/dataset/.gitkeep",
                    "content": None,
                },
            ]

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
            await arc_file(id, path=pathName, branch=branch, request=request, data=data)

            # then write the identifier in the corresponding field
            writeIsaFile(
                path=pathName,
                type="study",
                newContent=["Study Identifier", identifier],
                repoId=id,
                location=token["target"],
            )
            # edit also the file Name field
            writeIsaFile(
                path=pathName,
                type="study",
                newContent=[
                    "Study File Name",
                    f"studies/{identifier}/isa.study.xlsx",
                    "",
                ],
                repoId=id,
                location=token["target"],
            )
        case "assays":
            # first, get the file
            pathName = f"{type}/{identifier}/isa.assay.xlsx"
            await arc_file(id, path=pathName, branch=branch, request=request, data=data)

            # then write the identifier in the corresponding field
            writeIsaFile(
                path=pathName,
                type="assay",
                newContent=["Assay Measurement Type", identifier],
                repoId=id,
                location=token["target"],
            )
            # edit also the file Name field
            writeIsaFile(
                path=pathName,
                type="assay",
                newContent=[
                    "Assay File Name",
                    f"assays/{identifier}/isa.assay.xlsx",
                    "",
                ],
                repoId=id,
                location=token["target"],
            )
    # send the edited file to the repo
    await commitFile(
        request=request,
        id=id,
        repoPath=pathName,
        data=data,
        filePath=f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{id}/{pathName}",
    )
    writeLogJson(
        "createISA",
        201,
        startTime,
    )
    return commitRequest.content


# either caches the given byte chunk or uploads the file directly (merges all the byte chunks as soon as all have been received)
@router.post(
    "/uploadFile",
    summary="Uploads the given file to the repo (with or without lfs)",
    status_code=status.HTTP_201_CREATED,
)
async def uploadFile(
    request: Request,
    data: Annotated[str, Cookie()],
    file: Annotated[bytes, File()],
    name: Annotated[str, Form()],
    id: Annotated[int, Form()],
    branch: Annotated[str, Form()],
    path: Annotated[str, Form()],
    namespace: Annotated[str, Form()],
    lfs: Annotated[str, Form()],
    chunkNumber: Annotated[int, Form()] = 0,
    totalChunks: Annotated[int, Form()] = 1,
) -> Commit | dict | str:
    startTime = time.time()
    try:
        token = getData(data)
        target = getTarget(token["target"])
        header = {
            "Authorization": "Bearer " + token["gitlab"],
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
            f"uploadFile Request couldn't be processed! Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    f = open(
        os.environ.get("BACKEND_SAVE") + "cache/" + name + "." + str(chunkNumber),
        "wb",
    )
    f.write(file)
    f.close()
    # fullData holds the final file data
    fullData = bytes()

    # if the current chunk is the last chunk, merge all chunks together and write them into fullData
    if chunkNumber + 1 == totalChunks:
        for chunk in range(totalChunks):
            f = open(
                os.environ.get("BACKEND_SAVE") + "cache/" + name + "." + str(chunk),
                "rb",
            )
            fullData += f.read()
            f.close()

        # clear the chunks
        try:
            for chunk in range(totalChunks):
                os.remove(os.environ.get("BACKEND_SAVE") + "cache/" + f"{name}.{chunk}")
        except:
            pass

        # open up a new hash
        shasum = hashlib.new("sha256")

        # the following code is for uploading a file with LFS (thanks to Julian Weidhase for the code)
        if lfs == "true":
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
                "ref": {"name": f"refs/heads/{branch}"},
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
                    token["gitlab"],
                    f"@{os.environ.get(target).split('//')[1]}/",
                    f"{namespace}.git/info/lfs/objects/batch",
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
            repoPath = quote(path, safe="")

            postUrl = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{repoPath}"

            pointerContent = (
                f"version https://git-lfs.github.com/spec/v1\n"
                f"oid sha256:{sha256}\nsize {size}\n"
            )

            headers = {
                "Authorization": f"Bearer {token['gitlab']}",
                "Content-Type": "application/json",
            }

            jsonData = {
                "branch": "main",
                "content": pointerContent,
                "commit_message": "create a new lfs pointer file",
            }

            # check if file already exists
            fileHead = requests.head(
                f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{repoPath}?ref={branch}",
                headers=header,
            )
            if fileHead.ok:
                response = requests.put(postUrl, headers=headers, json=jsonData)
            else:
                response = requests.post(postUrl, headers=headers, json=jsonData)

            if not response.ok:
                try:
                    responseJson = response.json()
                    responseJson["error"] != None
                except:
                    responseJson = {
                        "error": "Couldn't upload file",
                        "error_description": "Couldn't upload pointer file to the ARC!",
                    }
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
                f"Uploaded new File {name} to repo {id} on path: {branch} with LFS"
            )

            ## add filename to the gitattributes
            url = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/.gitattributes/raw?ref={branch}"

            newLine = f"{path} filter=lfs diff=lfs merge=lfs -text\n"

            getResponse = requests.get(url, headers=headers)

            postUrl = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote('.gitattributes', safe='')}"

            # if .gitattributes doesn't exist, create a new one
            if not getResponse.ok:
                content = newLine

                attributeData = {
                    "branch": branch,
                    "content": content,
                    "commit_message": "Create .gitattributes",
                }
                response = requests.post(
                    postUrl, headers=headers, data=json.dumps(attributeData)
                )
                logging.debug("Uploading .gitattributes to repo...")
                writeLogJson(
                    "uploadFile",
                    201,
                    startTime,
                )
                try:
                    responseJson = response.json()
                except:
                    responseJson = {}

                return responseJson

            # if filename is not inside the .gitattributes, add it
            elif not name in getResponse.text:
                content = getResponse.text + "\n" + newLine

                attributeData = {
                    "branch": branch,
                    "content": content,
                    "commit_message": "Update .gitattributes",
                }

                response = requests.put(
                    postUrl, headers=headers, data=json.dumps(attributeData)
                )
                logging.debug("Updating .gitattributes...")
                writeLogJson(
                    "uploadFile",
                    201,
                    startTime,
                )
                try:
                    responseJson = response.json()
                except:
                    responseJson = {}

                return responseJson
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
                f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
                headers=header,
            )
            # if file doesn't exist, upload file
            if not fileHead.ok:
                # gitlab needs to know the branch, the base64 encoded content, a commit message and the format of the encoding (normally base64)
                payload = {
                    "branch": str(branch),
                    # base64 encoding of the isa file
                    "content": base64.b64encode(fullData).decode("utf-8"),
                    "commit_message": f"Upload of new File {name}",
                    "encoding": "base64",
                }

                # create the file on the gitlab
                request = requests.post(
                    f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                    data=json.dumps(payload),
                    headers=header,
                )
                statusCode = status.HTTP_201_CREATED

            # if file already exists, update the file
            else:
                payload = {
                    "branch": branch,
                    # base64 encoding of the isa file
                    "content": base64.b64encode(fullData).decode("utf-8"),
                    "commit_message": f"Updating File {name}",
                    "encoding": "base64",
                }

                # update the file to the gitlab
                request = requests.put(
                    f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
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
            logging.info(f"Uploaded new File {name} to repo {id} on path: {path}")

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
            202,
            startTime,
        )
        return Response(
            json.dumps(
                f"Received chunk {chunkNumber+1} of {totalChunks} for file {name}"
            ),
            202,
        )


# returns a list of the last 100 changes made to the ARC
@router.get(
    "/getChanges",
    summary="Get the commit history of the ARC",
    status_code=status.HTTP_200_OK,
)
async def getChanges(
    request: Request, id: int, data: Annotated[str, Cookie()], branch="main"
) -> list:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getChanges",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    commits = requests.get(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits?per_page=100&ref_name={branch}",
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
    try:
        commitJson = commits.json()
    except:
        commitJson = {}

    writeLogJson("getChanges", 200, startTime)
    return [
        f"{entry['authored_date'].split('T')[0]}: {entry['title']}"
        for entry in commitJson
    ]


# returns a list of all study names
@router.get(
    "/getStudies", summary="Get a list of current studies", include_in_schema=False
)
async def getStudies(
    request: Request, id: int, data: Annotated[str, Cookie()], branch="main"
) -> list:
    startTime = time.time()
    try:
        # request arc studies
        studiesJson = await arc_path(
            id=id, request=request, path="studies", data=data, branch=branch
        )
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getStudies",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    writeLogJson("getStudies", 200, startTime)
    return [
        x["name"] for x in json.loads(studiesJson.body)["Arc"] if x["type"] == "tree"
    ]


# returns a list of all assay names
@router.get(
    "/getAssays", summary="Get a list of current assays", include_in_schema=False
)
async def getAssays(
    request: Request, id: int, data: Annotated[str, Cookie()], branch="main"
) -> list:
    startTime = time.time()
    try:
        # request arc assays
        assaysJson = await arc_path(
            id=id, request=request, path="assays", data=data, branch=branch
        )
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getAssays",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    writeLogJson("getAssays", 200, startTime)
    return [
        x["name"] for x in json.loads(assaysJson.body)["Arc"] if x["type"] == "tree"
    ]


# writes all the assay data into the isa file of the selected study (adds a new column with the data)
@router.patch("/syncAssay", summary="Syncs an assay into a study")
async def syncAssay(
    request: Request, syncContent: syncAssayContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        target = token["target"]

    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "syncAssays",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the necessary information from the request
    try:
        id = syncContent.id
        pathToStudy = syncContent.pathToStudy
        pathToAssay = syncContent.pathToAssay
        assayName = syncContent.assayName
        branch = syncContent.branch

    except:
        logging.warning(f"Missing Data for Assay sync! Data: {syncContent}")
        writeLogJson(
            "syncAssays",
            400,
            startTime,
            f"Missing Data for Assay sync! Data: {syncContent}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Data!"
        )

    # get the two files in the backend
    await arc_file(id=id, path=pathToAssay, request=request, branch=branch, data=data)
    await arc_file(id, pathToStudy, request, data, branch)

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
            data,
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
            f"Client is not authorized to commit to ARC!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="No authorized session cookie found",
        )

    logging.info(f"Sent file {pathToStudy} to ARC {id}")
    writeLogJson("syncAssays", 200, startTime)
    # frontend gets the response from the commit post back
    return str(commitResponse)


# writes all the study data into the investigation file (appends the rows of the study to the investigation)
@router.patch("/syncStudy", summary="Syncs a study into the investigation file")
async def syncStudy(
    request: Request, syncContent: syncStudyContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        target = token["target"]

    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "syncStudy",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    # get the necessary information from the request
    try:
        id = syncContent.id
        pathToStudy = syncContent.pathToStudy
        studyName = syncContent.studyName
        branch = syncContent.branch

    except:
        logging.warning(f"Missing Data for Assay sync! Data: {syncContent}")
        writeLogJson(
            "syncStudy",
            400,
            startTime,
            f"Missing Data for Assay sync! Data: {syncContent}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Data!"
        )

    # get the two files in the backend
    await arc_file(
        id=id, path="isa.investigation.xlsx", request=request, data=data, branch=branch
    )
    await arc_file(id, pathToStudy, request, data, branch)

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
            data,
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
            f"Client is not authorized to commit to ARC!",
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
async def deleteFile(
    id: int, path: str, request: Request, data: Annotated[str, Cookie()], branch="main"
):
    startTime = time.time()
    try:
        token = getData(data)
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client is not authorized to delete the file! Cookies: {request.cookies}"
        )
        writeLogJson(
            "deleteFile",
            401,
            startTime,
            f"Client is not authorized to delete the file!",
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
async def deleteFolder(
    id: int, path: str, request: Request, data: Annotated[str, Cookie()], branch="main"
):
    startTime = time.time()
    try:
        token = getData(data)
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client is not authorized to delete the folder! Cookies: {request.cookies}"
        )
        writeLogJson(
            "deleteFolder",
            401,
            startTime,
            f"Client is not authorized to delete the folder!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to delete this folder",
        )

    # get the content of the folder
    folder = await arc_path(id, request, path, data)

    # list of all files to be deleted
    payload = []

    # async function filling the payload with all files recursively found in the folder
    async def prepareJson(folder: Arc):
        for entry in Arc(Arc=json.loads(folder.body)["Arc"]).Arc:
            # if its a file, add it to the list
            if entry.type == "blob":
                payload.append({"action": "delete", "file_path": entry.path})

            # if its a folder, search the folder for any file
            elif entry.type == "tree":
                await prepareJson(await arc_path(id, request, entry.path, data))

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
async def createFolder(
    request: Request, folder: folderContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }

        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client not authorized to create new folder! Cookies: {request.cookies}"
        )
        writeLogJson(
            "createFolder",
            401,
            startTime,
            f"Client not authorized to create new folder!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authorized to create new folder",
        )

    # load the properties
    try:
        identifier = folder.identifier
        # the identifier must not contain white space
        identifier = identifier.replace(" ", "_")
        path = folder.path
        if path == "":
            path = identifier
        else:
            path = f"{path}/{identifier}"
        id = folder.id
        payload = {
            "branch": folder.branch,
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


# sends back a list of metrics for display
@router.get(
    "/getMetrics",
    summary="Returns a json containing the metrics of the api",
    include_in_schema=False,
)
async def getMetrics(request: Request, pwd: str):
    if os.environ.get("METRICS") != pwd:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Wrong Password!")

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


# returns the list of different branches
@router.get(
    "/getBranches",
    summary="Get a list of different branches for the arc",
)
async def getBranches(
    request: Request, id: int, data: Annotated[str, Cookie()]
) -> list:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client is not authorized to view ARC {id}; Cookies: {request.cookies}"
        )
        writeLogJson(
            "getBranches",
            401,
            startTime,
            f"Client is not authorized to view ARC {id}",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )
    try:
        # request branches
        branches = requests.get(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/branches",
            headers=header,
        )
        branchJson = branches.json()

    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getBranches",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )
    writeLogJson("getBranches", 200, startTime)
    return [x["name"] for x in branchJson]


@router.post(
    "/createArcJson",
    summary="Creates a json containing all publicly available Arcs",
    include_in_schema=True,
    status_code=status.HTTP_201_CREATED,
)
async def createArcJson():
    fullProjects = []

    async def getLicenseData(id: int, datahub: str):
        request = requests.get(
            f"{os.environ.get(getTarget(datahub))}/api/v4/projects/{id}?license=true",
        )
        branches = requests.get(
            f"{os.environ.get(getTarget(datahub))}/api/v4/projects/{id}/repository/branches",
        )
        branches = [x["name"] for x in branches.json()]
        try:
            projectJson = request.json()
            license = projectJson["license"]
        except:
            license = {}

        return license

    async def getInvestData(id: int, datahub: str, branch: str):
        # contains [identifier, [contacts], [publications]]
        result = [[], []]

        target = getTarget(datahub)

        # check if isa investigation is present
        identifierHead = requests.head(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/isa.investigation.xlsx?ref={branch}",
        )

        if identifierHead.ok:
            # get the raw ISA file
            fileRaw = requests.get(
                f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/isa.investigation.xlsx/raw?ref={branch}"
            ).content

            # construct path to save on the backend
            pathName = (
                f"{os.environ.get('BACKEND_SAVE')}{datahub}-{id}/isa.investigation.xlsx"
            )

            # create directory for the file to save it, skip if it exists already
            os.makedirs(os.path.dirname(pathName), exist_ok=True)
            with open(pathName, "wb") as file:
                file.write(fileRaw)

            logging.debug("Downloading File to " + pathName)

            # read out isa file and create json
            fileJson = readIsaFile(pathName, "investigation")
            for i, entry in enumerate(fileJson["data"]):
                if "Investigation Identifier" in entry:
                    result.insert(0, entry[1])

                # retrieve the contacts
                if "INVESTIGATION CONTACTS" in entry:
                    fullData = fileJson["data"]
                    contact = {}
                    for x in range(1, len(entry)):
                        if fullData[i + 1][x] != None and fullData[i + 1][x] != "":
                            for y in range(11):
                                contact[fullData[i + 1 + y][0]] = fullData[i + 1 + y][x]
                            if len(result) == 3:
                                result[1].append(contact)
                            else:
                                result[0].append(contact)
                            contact = {}

                # retrieve the publications
                if "INVESTIGATION PUBLICATIONS" in entry:
                    fullData = fileJson["data"]
                    publication = {}
                    for x in range(1, len(entry)):
                        if fullData[i + 2][x] != None and fullData[i + 2][x] != "":
                            for y in range(7):
                                publication[fullData[i + 1 + y][0]] = fullData[
                                    i + 1 + y
                                ][x]
                            if len(result) == 3:
                                result[2].append(publication)
                            else:
                                result[1].append(publication)
                            publication = {}

        if len(result) == 2:
            result.insert(0, "")

        return result

    def formatTimeString(time: str) -> str:
        parts = time.split("T")

        date = parts[0]

        time = parts[1].split(".")[0]

        return date + " " + time

    async def getAssayStudyRel(id: int, datahub: str, branch: str) -> dict:
        assays = requests.get(
            f"{os.environ.get(getTarget(datahub))}/api/v4/projects/{id}/repository/tree?path=assays&ref={branch}",
        )
        assayList = []
        if assays.ok:
            assayList = [x["name"] for x in assays.json() if x["type"] == "tree"]

        studies = requests.get(
            f"{os.environ.get(getTarget(datahub))}/api/v4/projects/{id}/repository/tree?path=studies&ref={branch}",
        )
        studyDict = {}
        if studies.ok:
            studyDict = {x["name"]: [] for x in studies.json() if x["type"] == "tree"}

        async def getStudyAssays(
            id: int, datahub: str, branch: str, study: str
        ) -> list:
            target = getTarget(datahub)

            # check if study file is present
            studiesHead = requests.head(
                f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote('studies/'+study+'/isa.study.xlsx', safe='')}?ref={branch}",
            )
            if studiesHead.ok:
                # get the raw ISA file
                fileRaw = requests.get(
                    f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote('studies/'+study+'/isa.study.xlsx', safe='')}/raw?ref={branch}"
                ).content

                # construct path to save on the backend
                pathName = f"{os.environ.get('BACKEND_SAVE')}{datahub}-{id}/studies/{study}/isa.study.xlsx"

                # create directory for the file to save it, skip if it exists already
                os.makedirs(os.path.dirname(pathName), exist_ok=True)
                with open(pathName, "wb") as file:
                    file.write(fileRaw)

                logging.debug("Downloading File to " + pathName)
                # read out isa file and create json
                fileJson = readIsaFile(pathName, "study")
                for entry in fileJson["data"]:
                    if "Study Assay File Name" in entry:
                        entry.pop(0)
                        if entry[0] != None:
                            if "/" in entry[0]:
                                return [x.split("/")[-2] for x in entry if x != None]
                            elif "\\" in entry[0]:
                                return [x.split("\\")[-2] for x in entry if x != None]
                        else:
                            return []
            return []

        for study in studyDict.keys():
            studyAssayList = await getStudyAssays(id, datahub, branch, study)
            studyDict[study] = studyAssayList
            for assay in studyAssayList:
                if assay in assayList:
                    assayList.remove(assay)

        if len(assayList) > 0:
            studyDict["other"] = assayList
        return studyDict

    data: list[Projects] = []
    for datahub in ["freiburg", "plantmicrobe", "tuebingen"]:

        projects = await public_arcs(datahub)
        pages = int(projects.headers.get("total-pages"))
        data = Projects(projects=json.loads(projects.body)["projects"]).projects

        for i in range(2, pages + 1):
            projects = await public_arcs(datahub, i)
            data += Projects(projects=json.loads(projects.body)["projects"]).projects

        for i, arc in enumerate(data):
            investData = await getInvestData(arc.id, datahub, arc.default_branch)

            fullProjects.append(
                {
                    "datahub": datahub,
                    "id": arc.id,
                    "name": arc.name,
                    "description": arc.description,
                    "topics": arc.topics,
                    "author": {
                        "name": arc.namespace.name,
                        "username": arc.namespace.full_path,
                    },
                    "created_at": formatTimeString(arc.created_at),
                    "last_activity": formatTimeString(arc.last_activity_at),
                    "license": await getLicenseData(arc.id, datahub),
                    "identifier": investData[0],
                    "url": arc.http_url_to_repo,
                    "assay_study_relation": await getAssayStudyRel(
                        arc.id, datahub, arc.default_branch
                    ),
                    "contacts": investData[1],
                    "publications": investData[2],
                }
            )

    with open("searchableArcs.json", "w", encoding="utf8") as f:
        json.dump(fullProjects, f, ensure_ascii=False)
    f.close()
    return fullProjects


@router.get(
    "/getArcJson",
    summary="Get the json containing information about all public arcs",
)
async def getArcJson():
    data = []

    try:
        with open("searchableArcs.json", "r", encoding="utf8") as f:
            data = json.load(f)
        f.close()
    except:
        raise HTTPException(
            status_code=500, detail="Error reading the Arcs Json. Try recreating it!"
        )

    return data


# here we create a new isa.datamap for the study
@router.post(
    "/addDatamap",
    summary="Creates a new datamap",
    status_code=status.HTTP_201_CREATED,
)
async def addDatamap(
    request: Request, datamapContent: datamapContent, data: Annotated[str, Cookie()]
):
    startTime = time.time()
    try:
        token = getData(data)
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client not authorized to create new datamap! Cookies: {request.cookies}"
        )
        writeLogJson(
            "addDatamap",
            401,
            startTime,
            f"Client not authorized to create new datamap!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authorized to create new datamap",
        )

    # load the isa properties
    try:
        id = datamapContent.id
        path = datamapContent.path
        branch = datamapContent.branch
    except:
        logging.error(f"Missing Properties for datamap! Data: {datamapContent}")
        writeLogJson(
            "addDatamap",
            400,
            startTime,
            f"Missing Properties for datamap! Data: {datamapContent}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Properties for the datamap!",
        )

    ## commit the folders and the investigation isa to the repo

    datamap = [
        {
            "action": "create",
            "file_path": f"{path}/isa.datamap.xlsx",
            "content": base64.b64encode(
                open(
                    f"{os.environ.get('BACKEND_SAVE')}/isa_files/isa.datamap.xlsx",
                    "rb",
                ).read()
            ).decode("utf-8"),
            "encoding": "base64",
        },
    ]

    # wrap the payload into json
    payload = json.dumps(
        {
            "branch": branch,
            "commit_message": f"Added new datamap",
            "actions": datamap,
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
        logging.error(f"Couldn't commit datamap to ARC! ERROR: {commitRequest.content}")
        writeLogJson(
            "addDatamap",
            500,
            startTime,
            f"Couldn't commit datamap to ARC! ERROR: {commitRequest.content}",
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't commit datamap to repo! Error: {commitRequest.content}",
        )

    logging.info(f"Created datamap in study {path} for ARC {id}")

    writeLogJson(
        "addDatamap",
        201,
        startTime,
    )
    return commitRequest.content


# returns a list of all groups the user is part of
@router.get("/getGroups", summary="Get a list of the users groups")
async def getGroups(request: Request, data: Annotated[str, Cookie()]) -> list:
    startTime = time.time()
    try:
        token = getData(data)
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
        # request arc studies
        groups = requests.get(
            f"{os.environ.get(target)}/api/v4/groups",
            headers=header,
        )

        groupsJson = groups.json()
    except:
        logging.warning(f"No authorized Cookie found! Cookies: {request.cookies}")
        writeLogJson(
            "getStudies",
            401,
            startTime,
            f"No authorized Cookie found!",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    writeLogJson("getStudies", 200, startTime)
    return [{"name": x["name"], "id": x["id"]} for x in groupsJson]
