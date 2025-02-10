from enum import Enum
from typing import Annotated
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    status,
    Response,
    Request,
)
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.encoders import jsonable_encoder

# gitlab api commits need base64 encoded content
import base64

import json
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import jwt

from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

import logging
import time

from cryptography.fernet import Fernet
from app.models.gitlab.banner import Banner, Banners
from app.models.gitlab.file import FileContent
from app.models.gitlab.targets import Targets
from pdf2image import convert_from_bytes  # type: ignore

# paths in get requests need to be parsed to uri encoded strings
from urllib.parse import quote
from io import BytesIO

# functions to read and write isa files
from app.api.IO.excelIO import (
    getIsaType,
    readExcelFile,
    readIsaFile,
    writeIsaFile,
    appendAssay,
    appendStudy,
)

from app.models.gitlab.input import (
    arcContent,
    datamapContent,
    isaContent,
    newIsa,
    syncAssayContent,
    syncStudyContent,
)
from app.models.gitlab.projects import Projects
from app.models.gitlab.arc import Arc

router = APIRouter()

logging.basicConfig(
    filename="backend.log",
    filemode="a",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)

logging.getLogger("multipart").setLevel(logging.INFO)

# request sessions to retry the important requests
retry = Retry(
    total=5,
    backoff_factor=4,
    status_forcelist=[500, 502, 429, 503, 504],
    allowed_methods=["POST", "PUT", "HEAD", "GET"],
)

adapter = HTTPAdapter(max_retries=retry)

session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)


# sanitize input
def sanitizeInput(input: str | list) -> str:
    if type(input) is list:
        return [sanitizeInput(entry) for entry in input]

    if type(input) is str:
        return input.replace("<", "&lt;").replace(">", "&gt;")
    return input


# Match the given target repo with the address name in the env file (default is the tübingen gitlab)
def getTarget(target: str) -> str:
    match target.lower():
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
        case "tuebingen_testenv":
            return "GITLAB_TUEBINGEN_TESTENV"
        case other:
            return "GITLAB_TUEBINGEN"


# get the username using the id
async def getUserName(target: str, userId: int, access_token: str) -> str:
    header = {"Authorization": "Bearer " + access_token}
    try:
        userInfo = requests.get(
            f"{os.environ.get(getTarget(target))}/api/v4/users/{userId}",
            headers=header,
        ).json()

        return userInfo["name"]
    except:
        return "username"


# decrypt the cookie data with the corresponding public key
def getData(data: Annotated[str, Cookie()]):
    # get public key from .env to decode data (in form of a byte string)
    public_key = (
        b"-----BEGIN PUBLIC KEY-----\n"
        + os.environ.get("PUBLIC_RSA").encode()
        + b"\n-----END PUBLIC KEY-----"
    )

    try:
        decodedToken = jwt.decode(data, public_key, algorithms=["RS256", "HS256"])
        fernetKey = os.environ.get("FERNET").encode()
        decodedToken["gitlab"] = (
            Fernet(fernetKey).decrypt(decodedToken["gitlab"].encode()).decode()
        )
    except:
        logging.warning(
            f"Client connected with no valid cookies/Client is not logged in. Cookies: {data}"
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not logged in",
        )

    return decodedToken


commonToken = Annotated[str, Depends(getData)]


# writes the log entry into the json log file
def writeLogJson(endpoint: str, status: int, startTime: float, error=None):
    try:
        with open("log.json", "r") as log:
            jsonLog = json.load(log)

        jsonLog.append(
            {
                "endpoint": endpoint,
                "status": status,
                "error": str(error),
                "date": time.strftime("%d/%m/%Y - %H:%M:%S", time.localtime()),
                "response_time": time.time() - startTime,
            }
        )

        with open("log.json", "w") as logWrite:
            json.dump(jsonLog, logWrite, indent=4, separators=(",", ": "))
    except:
        logging.warning("Error while logging to log json!")


# converts bit size into human readable byte size
def fileSizeReadable(size: int) -> str:
    for unit in ("bytes", "Kb", "Mb", "Gb"):
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size} Bits"


# checks whether the assay is already linked in a study (if so, update the data)
async def checkAssayLink(
    id: int, path: str, request: Request, token: commonToken, branch="main"
):
    try:
        studies = await getStudies(request, id, token, branch)

        for study in studies:
            studyPath = "studies/" + study + "/isa.study.xlsx"
            studyTest = await arc_file(id, studyPath, request, token, branch)

            for entry in studyTest:
                if "Study Assay File Name" in entry:
                    logging.debug(
                        f"Syncing {path} into {study} after link was found..."
                    )
                    if path in entry:
                        syncData = syncAssayContent(
                            id=id,
                            pathToAssay=path,
                            pathToStudy=studyPath,
                            branch=branch,
                            assayName=path.split("/")[-2],
                        )
                        await syncAssay(request, syncData, token)
                        await checkStudyLink(
                            id,
                            studyPath,
                            request,
                            token,
                            branch,
                        )
                        return True
                    else:
                        return entry
            # if the field wasn't found, it doesn't exist. Therefore return False
        return False
    except:
        logging.warning(f"Failed to sync {path} into {study}")
        return False


# checks whether the study is already linked in the investigation (if so, update it)
async def checkStudyLink(
    id: int, path: str, request: Request, token: commonToken, branch="main"
):
    try:
        investTest = await arc_file(
            id, "isa.investigation.xlsx", request, token, branch
        )

        for entry in investTest:
            if "Study File Name" in entry:
                logging.debug(f"Link found; Syncing {path} into investigation...")
                if path in entry:
                    syncData = syncStudyContent(
                        id=id,
                        pathToStudy=path,
                        studyName=path.split("/")[-2],
                        branch=branch,
                    )
                    await syncStudy(request, syncData, token)
                    return True
        # if the field wasn't found, it doesn't exist. Therefore return False
        return False
    except:
        logging.warning(f"Failed to sync {path} into investigation")
        return False


# get a list of all arcs accessible to the user
@router.get(
    "/arc_list",
    summary="Lists your accessible ARCs",
    description="Retrieve a list of all ARCs viewable and accessible for you. This includes public projects, internal projects and projects where you are a member of. Each page has 20 entries.",
    response_description="Array containing up to 20 ARCs/Projects wih detailed information, such as id, name, description, creation date and more.",
    status_code=status.HTTP_200_OK,
)
async def list_arcs(
    request: Request,
    token: commonToken,
    owned: Annotated[
        bool,
        Query(),
    ] = False,
    page: Annotated[int, Query(ge=1)] = 1,
) -> Projects:
    startTime = time.time()
    try:
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
            detail="You are not logged in! Please authorize or refresh session!",
        )

    arcList = []

    if owned:
        # first find out how many pages of arcs there are for us to get (check if there are more than 100 arcs at once available)
        try:
            arcs = session.get(
                f"{os.environ.get(target)}/api/v4/projects?min_access_level=30&page={page}",
                headers=header,
            )
        except Exception as e:
            logging.error(e)
            writeLogJson("arc_list", 504, startTime, e)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Couldn't retrieve list of ARCs! Error: {e}",
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
                error = arcsJson["error"]
                errorDescription = arcsJson["error_description"]
            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail=str(arcsJson),
                )
            raise HTTPException(
                status_code=arcs.status_code,
                detail=error + ", " + errorDescription,
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
        try:
            arcs = session.get(
                f"{os.environ.get(target)}/api/v4/projects?page={page}",
                headers=header,
            )
        except Exception as e:
            logging.error(e)
            writeLogJson("arc_list", 504, startTime, e)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Couldn't retrieve list of ARCs! Error: {e}",
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
            try:
                error = arcsJson["error"]
                errorDescription = arcsJson["error_description"]

            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )
            raise HTTPException(
                status_code=arcs.status_code,
                detail=error + ", " + errorDescription,
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


# head request option for arc_list, so that you only receive the number of pages
@router.head(
    "/arc_list",
    summary="Just sends the headers containing the pages count",
    include_in_schema=False,
)
async def list_arcs_head(
    request: Request,
    token: commonToken,
    owned: Annotated[
        bool,
        Query(),
    ] = False,
):
    startTime = time.time()
    try:
        header = {"Authorization": "Bearer " + token["gitlab"]}
        target = getTarget(token["target"])
    except:
        logging.warning(
            f"Client connected with no valid cookies/Client is not logged in. Cookies: {request.cookies}"
        )
        writeLogJson(
            "arc_list_head",
            401,
            startTime,
            f"Client connected with no valid cookies/Client is not logged in.",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not logged in! Please authorize or refresh session!",
        )

    if owned:
        # first find out how many pages of arcs there are for us to get (check if there are more than 100 arcs at once available)
        arcs = requests.head(
            f"{os.environ.get(target)}/api/v4/projects?min_access_level=30",
            headers=header,
        )
        # if there is an error retrieving the content
        if not arcs.ok:
            try:
                arcsJson = arcs.json()
            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )

            try:
                error = arcsJson["error"]
                errorDescription = arcsJson["error_description"]

            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )
            raise HTTPException(
                status_code=arcs.status_code,
                detail=error + ", " + errorDescription,
            )

        try:
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
        arcs = requests.head(
            f"{os.environ.get(target)}/api/v4/projects",
            headers=header,
        )
        if not arcs.ok:
            try:
                arcsJson = arcs.json()
            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )
            try:
                error = arcsJson["error"]
                errorDescription = arcsJson["error_description"]

            except:
                raise HTTPException(
                    status_code=arcs.status_code,
                    detail="Error retrieving the ARCs! Please login again!",
                )
            raise HTTPException(
                status_code=arcs.status_code,
                detail=error + ", " + errorDescription,
            )
        try:
            pages = int(arcs.headers["X-Total-Pages"])

        except:
            writeLogJson(
                "arc_list_head",
                500,
                startTime,
                f"Error while parsing the list of ARCs!",
            )
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error while parsing the list of ARCs!",
            )

    logging.info("Sent list of Arc list headers")
    writeLogJson("arc_list_head", 200, startTime)
    return Response(
        headers={
            "total-pages": str(pages),
            "Access-Control-Expose-Headers": "total-pages",
        },
    )


# get a list of all public arcs
@router.get(
    "/public_arcs",
    summary="Lists all public ARCs",
    description="Retrieve a list of all publicly available ARCs. Each page has 20 entries.",
    response_description="Array containing up to 20 ARCs/Projects wih detailed information, such as id, name, description, creation date and more.",
    status_code=status.HTTP_200_OK,
)
async def public_arcs(
    target: Targets, page: Annotated[int, Query(ge=1)] = 1
) -> Projects:
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
            timeout=15,
        )
        if request.status_code == 502 or request.status_code == 503:
            raise Exception()

        requestJson = request.json()
        pages = int(request.headers["X-Total-Pages"])
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
            status_code=request.status_code,
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
@router.get(
    "/arc_tree",
    summary="Overview of the ARC",
    description="Get the frontpage folder structure of an ARC.",
    response_description="Array containing the different names of the files and folders of the frontpage, like 'assays' or 'isa.investigation.xlsx'.",
    status_code=status.HTTP_200_OK,
)
async def arc_tree(
    id: Annotated[int, Query(ge=1)],
    token: commonToken,
    request: Request,
    branch: Annotated[str, Query()] = "main",
) -> Arc:
    startTime = time.time()
    try:
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
            detail="You are not authorized to view this ARC! Please authorize or refresh session!",
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
    "/arc_path",
    summary="Subdirectory of the ARC",
    description="Get the file and folder structure of the specific path inside the ARC.",
    response_description="Array containing the different names of the files and folders for the given path similar to /arc_tree",
    status_code=status.HTTP_200_OK,
)
async def arc_path(
    id: Annotated[int, Query(ge=1)],
    request: Request,
    path: str,
    token: commonToken,
    page: Annotated[int, Query(ge=1)] = 1,
    branch: Annotated[str, Query()] = "main",
) -> Arc:
    startTime = time.time()
    try:
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
            detail="You are not authorized to view this ARC! Please authorize or refresh session!",
        )

    try:
        arcPath = session.get(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?path={path}&page={page}&ref={branch}",
            headers=header,
        )
    except Exception as e:
        logging.error(e)
        writeLogJson("arc_path", 504, startTime, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Couldn't retrieve content of the path! Error: {e}",
        )

    # if total pages header is available, forward it
    try:
        pages = int(arcPath.headers["X-Total-Pages"])
        header = {
            "total-pages": str(pages),
            "Access-Control-Expose-Headers": "total-pages",
        }
    except:
        header = {}

    try:
        pathJson = arcPath.json()
    except:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parsing Error! Error: There was an error parsing the path data for the ARC!!",
        )

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
        headers=header,
    )


# gets the specific file on the given path and either saves it on the backend storage (for isa files) or sends the content directly
@router.get(
    "/arc_file",
    summary="Returns the file on the given path",
    description="Get the file on the given path. This can be an isa file or something else. LFS files will return the pointer file.",
    response_description="Detailed information of the file, like name, encoding, content, id and more. If its an isa file, it will return a list containing every row of the table as an Array.",
    status_code=status.HTTP_200_OK,
)
async def arc_file(
    id: Annotated[int, Query(ge=1)],
    path: str,
    request: Request,
    token: commonToken,
    branch: str = "main",
) -> FileContent | list[list] | dict:
    startTime = time.time()
    try:
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
            detail="You are not authorized to get this file! Please authorize or refresh session!",
        )
    # get HEAD data for fileSize
    # url encode the path
    fileHead = session.head(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
        headers=header,
    )
    # raise error if file not found
    if not fileHead.ok:
        logging.error(f"File not found! Path: {path}")
        writeLogJson(
            "arc_file",
            fileHead.status_code,
            startTime,
            f"File not found! Path: {path}",
        )
        if fileHead.status_code == 401:
            raise HTTPException(
                status_code=fileHead.status_code,
                detail=f"{path.split('/')[-1]} not accessible! Error: Not authorized to view the file! Please login again!",
            )
        raise HTTPException(
            status_code=fileHead.status_code,
            detail=f"{path.split('/')[-1]} not found! Error: {fileHead.status_code}!",
        )

    fileSize = fileHead.headers["X-Gitlab-Size"]

    altRetry = Retry(
        total=5,
        backoff_factor=4,
        status_forcelist=[500, 400, 502, 429, 503, 504, 404],
        allowed_methods=["POST", "PUT", "HEAD", "GET"],
    )

    altAdapter = HTTPAdapter(max_retries=altRetry)

    altSession = requests.Session()

    altSession.mount("https://", altAdapter)
    altSession.mount("http://", altAdapter)

    # if its a isa file, return the content of the file as json to the frontend
    if getIsaType(path) != "":

        try:
            # get the raw ISA file
            fileRaw = altSession.get(
                f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}/raw?ref={branch}",
                headers=header,
            ).content
        except Exception as e:
            logging.error(e)
            writeLogJson("arc_file", 504, startTime, e)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"File not found! Error: {e}, Try to log-in again!",
            )

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
            logging.warning("File too large! Size: " + fileSizeReadable(int(fileSize)))
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

        try:
            # get the file metadata
            arcFile = altSession.get(
                f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
                headers=header,
            )
        except Exception as e:
            logging.error(e)
            writeLogJson("arc_file", 504, startTime, e)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"File not found! Error: {e}, Try to log-in again!",
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
@router.put(
    "/saveFile",
    summary="Write content to isa file",
    description="Writes the given row/rows into the isa file on the given path.",
    response_description="Response of the commit request from Gitlab.",
)
async def saveFile(request: Request, isaContent: isaContent, token: commonToken):
    startTime = time.time()
    try:
        isaContent.isaInput = sanitizeInput(isaContent.isaInput)
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
            token,
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

    if "assays" in isaContent.isaPath:
        await checkAssayLink(
            isaContent.isaRepo, isaContent.isaPath, request, token, isaContent.arcBranch
        )
    elif "studies" in isaContent.isaPath:
        await checkStudyLink(
            isaContent.isaRepo, isaContent.isaPath, request, token, isaContent.arcBranch
        )

    logging.info(f"Sent file {isaContent.isaPath} to ARC {isaContent.isaRepo}")
    writeLogJson(
        "saveFile",
        200,
        startTime,
    )
    return str(commitResponse)


@router.put(
    "/commitFile",
    summary="Update the content of the file to the repo",
    description="Writes the content into the file on the given path (repoPath). If filePath (used for isa files) is given, the file data is read from backend storage and uploaded to the ARC. If not, then provide the file content as base64 in the request body.",
    response_description="Response of the commit request from Gitlab.",
)
# sends the http PUT request to the git to commit the file on the given filepath
async def commitFile(
    request: Request,
    id: Annotated[int, Query(ge=1)],
    repoPath: str,
    token: commonToken,
    filePath: str = "",
    branch: str = "main",
    message: str = "",
):
    startTime = time.time()
    # get the data from the body
    requestBody = await request.body()
    try:
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
        commitMessage += ", changed " + sanitizeInput(message)

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

    try:
        response = session.put(
            f"{os.environ.get(getTarget(targetRepo))}/api/v4/projects/{id}/repository/files/{quote(repoPath, safe='')}",
            data=json.dumps(payload),
            headers=header,
        )
    except Exception as e:
        logging.error(e)
        writeLogJson("commitFile", 504, startTime, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Couldn't upload data to the ARC! Error: {e}",
        )

    if not response.ok:
        logging.error(f"Couldn't commit to ARC! ERROR: {response.content}")
        writeLogJson(
            "commitFile",
            400,
            startTime,
            f"Couldn't commit to ARC! ERROR: {response.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't commit file to repo! Error: {response.content}",
        )
    logging.info(f"Updated file on path: {repoPath}")
    writeLogJson("commitFile", 200, startTime)
    return response.content


# creates a new project in the repo with a readme file; we then initialize the repo folder on the server with the new id of the ARC;
# then we create the arc and the investigation file and commit the whole structure to the repo
@router.post(
    "/createArc",
    summary="Creates a new Arc",
    status_code=status.HTTP_201_CREATED,
    description="Creates a new Project with the given Information and fills it with the necessary files and folders to start your ARC.",
    response_description="Response from gitlab containing the various information of your new created project.",
)
async def createArc(request: Request, arcContent: arcContent, token: commonToken):
    startTime = time.time()
    try:
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
            detail="Please login to create a new ARC or refresh the session!",
        )
    # read out the new arc properties
    try:
        name = sanitizeInput(arcContent.name)
        description = sanitizeInput(arcContent.description)
        investIdentifier = sanitizeInput(arcContent.investIdentifier)
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

    try:
        projectPost = session.post(
            os.environ.get(target) + "/api/v4/projects",
            headers=header,
            data=json.dumps(project),
        )
    except Exception as e:
        logging.error(e)
        writeLogJson("createArc", 504, startTime, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Couldn't upload file to repo! Error: {e}",
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

    # allow force push
    try:
        branchForcePush = requests.patch(
            os.environ.get(target)
            + f"/api/v4/projects/{newArcJson['id']}/protected_branches/{newArcJson['default_branch']}?allow_force_push=true",
            headers=header,
        )
    except Exception as e:
        logging.error(e)

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
    try:
        # send the data to the repo
        commitRequest = session.post(
            f"{os.environ.get(target)}/api/v4/projects/{newArcJson['id']}/repository/commits",
            headers=header,
            data=payload,
        )
    except:
        logging.error(f"Couldn't upload content to ARC! ERROR: {commitRequest.content}")
        writeLogJson(
            "createArc",
            500,
            startTime,
            f"Couldn't upload content to ARC! ERROR: {commitRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't upload content to new ARC! Error: {commitRequest.content}",
        )

    if not commitRequest.ok:
        logging.error(f"Couldn't upload content to ARC! ERROR: {commitRequest.content}")
        writeLogJson(
            "createArc",
            500,
            startTime,
            f"Couldn't upload content to ARC! ERROR: {commitRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't upload content to new ARC! Error: {commitRequest.content}",
        )
    else:
        logging.info(f"Created new ARC with ID: {newArcJson['id']}")

        # write identifier into investigation file
        await arc_file(
            id=newArcJson["id"],
            path="isa.investigation.xlsx",
            request=request,
            token=token,
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
            token=token,
            filePath=f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{newArcJson['id']}/isa.investigation.xlsx",
            branch=newArcJson["default_branch"],
        )

        # allow force push
        try:
            branchForcePush = requests.patch(
                os.environ.get(target)
                + f"/api/v4/projects/{newArcJson['id']}/protected_branches/{newArcJson['default_branch']}?allow_force_push=true",
                headers=header,
            )
        except Exception as e:
            logging.error(e)

        writeLogJson("createArc", 201, startTime)
    return [projectPost.content, commitRequest.content]


@router.post(
    "/repairArc",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
    summary="Repairs an arc that was created with just a readme file",
)
async def repairArc(
    request: Request,
    token: commonToken,
    arcContent: arcContent,
    id: int,
    branch="main",
):
    startTime = time.time()
    try:
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
            detail="Please login to repair the ARC or refresh the session!",
        )

    # read out the new arc properties
    try:
        name = sanitizeInput(arcContent.name)
        description = sanitizeInput(arcContent.description)
        investIdentifier = sanitizeInput(arcContent.investIdentifier)
    except:
        logging.error(f"Missing content for arc creation! Data: {arcContent}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing content for arc creation!",
        )

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
            "branch": branch,
            "commit_message": "Initial commit of the arc structure",
            "actions": arcData,
        }
    )
    logging.debug(f"Sent commit request to repo with payload {payload}")
    # send the data to the repo
    commitRequest = requests.post(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits",
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
    logging.info(f"Created new ARC with ID: {id}")

    # write identifier into investigation file
    await arc_file(
        id=id,
        path="isa.investigation.xlsx",
        request=request,
        token=token,
        branch=branch,
    )
    # fill in the identifier, name and description of the arc into the investigation file
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Identifier", investIdentifier],
        repoId=id,
        location=token["target"],
    )
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Title", name],
        repoId=id,
        location=token["target"],
    )
    writeIsaFile(
        path="isa.investigation.xlsx",
        type="investigation",
        newContent=["Investigation Description", description],
        repoId=id,
        location=token["target"],
    )

    await commitFile(
        request=request,
        id=id,
        repoPath="isa.investigation.xlsx",
        token=token,
        filePath=f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{id}/isa.investigation.xlsx",
        branch=branch,
    )

    return commitRequest.content


# here we create a assay or study structure and push it to the repo
@router.post(
    "/createISA",
    summary="Creates a new ISA structure",
    status_code=status.HTTP_201_CREATED,
    description="Creates a new assay/study with the given name. It will include the excel file, a readme as well as all required folders for the isa type.",
    response_description="Response of the commit request from Gitlab.",
)
async def createIsa(request: Request, isaContent: newIsa, token: commonToken):
    startTime = time.time()
    try:
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
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authorized to create new ISA! Please authorize or refresh session!",
        )

    # load the isa properties
    try:
        identifier = sanitizeInput(isaContent.identifier)
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
    try:
        commitRequest = session.post(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits",
            headers=header,
            data=payload,
        )
    except Exception as e:
        logging.error(e)
        writeLogJson("createISA", 504, startTime, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Couldn't create new ISA! Error: {e}",
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
                id, path=pathName, branch=branch, request=request, token=token
            )

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
            await arc_file(
                id, path=pathName, branch=branch, request=request, token=token
            )

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
        token=token,
        filePath=f"{os.environ.get('BACKEND_SAVE')}{token['target']}-{id}/{pathName}",
    )
    writeLogJson(
        "createISA",
        201,
        startTime,
    )
    return commitRequest.content


# returns a list of the last 100 changes made to the ARC
@router.get(
    "/getChanges",
    summary="Get the commit history of the ARC",
    status_code=status.HTTP_200_OK,
    description="Gives you the 100 latest entries of the commit history.",
    response_description="Array containing the latest 100 entries of the history stored in an array of strings.",
)
async def getChanges(
    request: Request,
    id: Annotated[int, Query(ge=1)],
    token: commonToken,
    branch: str = "main",
) -> list:
    startTime = time.time()
    try:
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
    request: Request, id: int, token: commonToken, branch="main"
) -> list:
    startTime = time.time()
    try:
        # request arc studies
        studiesJson = await arc_path(
            id=id, request=request, path="studies", token=token, branch=branch
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
            detail="No authorized cookie found! Please authorize or refresh session!",
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
    request: Request, id: int, token: commonToken, branch="main"
) -> list:
    startTime = time.time()
    try:
        # request arc assays
        assaysJson = await arc_path(
            id=id, request=request, path="assays", token=token, branch=branch
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
            detail="No authorized cookie found! Please authorize or refresh session!",
        )

    writeLogJson("getAssays", 200, startTime)
    return [
        x["name"] for x in json.loads(assaysJson.body)["Arc"] if x["type"] == "tree"
    ]


# writes all the assay data into the isa file of the selected study (adds a new column with the data)
@router.patch(
    "/syncAssay",
    summary="Syncs an assay into a study",
    description="Writes the assay data into the 'Study Assay' part of the given study file, therefore syncing and connecting it to a study.",
    response_description="Response of the commit request from Gitlab.",
)
async def syncAssay(
    request: Request, syncContent: syncAssayContent, token: commonToken
):
    startTime = time.time()
    try:
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
            detail="No authorized cookie found! Please authorize or refresh session!",
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
    try:
        await arc_file(
            id=id, path=pathToAssay, request=request, branch=branch, token=token
        )
    except:
        raise HTTPException(
            status_code=404,
            detail=f"Study '{assayName}' has no isa.assay.xlsx file! Please add/upload one!",
        )
    try:
        await arc_file(id, pathToStudy, request, token, branch)
    except:
        raise HTTPException(
            status_code=404,
            detail=f"Study '{pathToStudy}' has no isa.study.xlsx file! Please add/upload one!",
        )

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
            token,
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
            detail="No authorized session cookie found! Please authorize or refresh session!",
        )

    logging.info(f"Sent file {pathToStudy} to ARC {id}")
    writeLogJson("syncAssays", 200, startTime)
    # frontend gets the response from the commit post back
    return str(commitResponse)


# writes all the study data into the investigation file (appends the rows of the study to the investigation)
@router.patch(
    "/syncStudy",
    summary="Syncs a study into the investigation file",
    description="Writes the full study data into the investigation file or appending it underneath if a study is already in existence. This will sync the study and the assays synced to the study to the investigation file.",
    response_description="Response of the commit request from Gitlab.",
)
async def syncStudy(
    request: Request, syncContent: syncStudyContent, token: commonToken
):
    startTime = time.time()
    try:
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
            detail="No authorized cookie found! Please authorize or refresh session!",
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
    try:
        await arc_file(
            id=id,
            path="isa.investigation.xlsx",
            request=request,
            token=token,
            branch=branch,
        )
    except:
        raise HTTPException(
            status_code=404,
            detail=f"No isa.investigation.xlsx found! Please add/upload one!",
        )
    try:
        await arc_file(id, pathToStudy, request, token, branch)
    except:
        raise HTTPException(
            status_code=404,
            detail=f"Study '{studyName}' has no isa.study.xlsx file! Please add/upload one!",
        )

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
            token,
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
            detail="No authorized session cookie found! Please authorize or refresh session!",
        )

    logging.info(f"Sent file isa.investigation.xlsx to ARC {id}")
    writeLogJson("syncStudy", 200, startTime)
    # frontend gets a simple 'success' as response
    return str(commitResponse)


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
        if entry["error"] != None and entry["error"] != "None":
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
    description="Get a list of the names of the different branches of your ARC.",
    response_description="List of strings containing the different branch names.",
)
async def getBranches(
    request: Request, id: Annotated[int, Query(ge=1)], token: commonToken
) -> list:
    startTime = time.time()
    try:
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
            detail="You are not authorized to view this ARC! Please authorize or refresh session!",
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
            detail="No authorized cookie found! Please authorize or refresh session!",
        )
    writeLogJson("getBranches", 200, startTime)
    try:
        return [x["name"] for x in branchJson]
    except:
        return ["main"]


# here we create a new isa.datamap for the study
@router.post(
    "/addDatamap",
    summary="Creates a new datamap",
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def addDatamap(
    request: Request, datamapContent: datamapContent, token: commonToken
):
    startTime = time.time()
    try:
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
            detail="Not authorized to create new datamap! Please authorize or refresh session!",
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


# get the newest broadcast message (banner) from the gitlab (if its an active message)
@router.get(
    "/getBanner",
    summary="Get the newest banner from the datahub",
    description="Get a single banner containing the newest broadcasted message from the datahub (if its active)",
    response_description="JSON containing the message, start time and more.",
    status_code=status.HTTP_200_OK,
)
async def getBanner(request: Request, token: commonToken) -> Banner | None:
    startTime = time.time()
    try:
        target = getTarget(token["target"])
    except:
        logging.warning(f"Client not authorized! Cookies: {request.cookies}")
        writeLogJson(
            "addDatamap",
            401,
            startTime,
            f"Client not authorized!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authorized! Please authorize or refresh session!",
        )

    # send the data to the repo
    bannerRequest = requests.get(
        f"{os.environ.get(target)}/api/v4/broadcast_messages",
    )
    if not bannerRequest.ok:
        logging.error(f"Couldn't get datahub banner! ERROR: {bannerRequest.content}")
        writeLogJson(
            "addDatamap",
            bannerRequest.status_code,
            startTime,
            f"Couldn't get datahub banner! ERROR: {bannerRequest.content}",
        )
        raise HTTPException(
            status_code=bannerRequest.status_code,
            detail=f"Couldn't receive newest Datahub banner! Error: {bannerRequest.content}",
        )

    try:
        banners = Banners(banners=bannerRequest.json())

        for entry in banners.banners:
            if entry.active:
                writeLogJson(
                    "getBanner",
                    200,
                    startTime,
                )
                return entry
        writeLogJson(
            "getBanner",
            200,
            startTime,
        )
        return None
    except Exception as e:
        logging.error(f"Couldn't get datahub banner! ERROR: {e}")
        writeLogJson(
            "addDatamap",
            500,
            startTime,
            f"Couldn't get datahub banner! ERROR: {e}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Couldn't receive newest Datahub banner!",
        )
