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

import shutil
import jwt

import logging

# paths in get requests need to be parsed to uri encoded strings
from urllib.parse import quote

# functions to read and write isa files
from app.api.middlewares.excelIO import (
    readIsaFile,
    getIsaType,
    writeIsaFile,
    appendStudy,
    createSheet,
    getSwateSheets,
)

from app.api.middlewares.oauth_authentication import *
from app.models.gitlab.projects import *
from app.models.gitlab.arc import *
from app.models.keycloak.access_token import *
from app.models.gitlab.commit import *
from app.models.swate.template import *

router = APIRouter()

logging.basicConfig(
    filename="backend.log",
    filemode="w",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)


# Match the given target repo with the address name in the env file
def getTarget(target: str):
    match target:
        case "dev":
            return "GITLAB_ADDRESS"
        case "freiburg":
            return "GITLAB_FREIBURG"
        case "tübingen":
            return "GITLAB_TUEBINGEN"
        case "plantmicrobe":
            return "GITLAB_PLANTMICROBE"
        case other:
            return "GITLAB_ADDRESS"


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


# get a list of all arcs accessible to the user
@router.get(
    "/arc_list",
    summary="Lists your accessible ARCs",
    status_code=status.HTTP_200_OK,
)
async def list_arcs(request: Request, owned=False):
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            "Client connected with no valid cookies/Client is not logged in. Cookies: "
            + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not logged in",
        )
    if owned == "true":
        arcs = requests.get(
            os.environ.get(target)
            + "/api/v4/projects?per_page=1000&min_access_level=10",
            headers=header,
        )
    else:
        arcs = requests.get(
            os.environ.get(target) + "/api/v4/projects?per_page=1000",
            headers=header,
        )

    if not arcs.ok:
        print(arcs.content)
        logging.warning("Access Token of client is expired!")
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Your token is expired! Please login again!",
        )

    project_list = Projects(projects=arcs.json())
    logging.info("Sent list of Arcs")
    return project_list


# get a list of all public arcs
@router.get(
    "/public_arcs", summary="Lists all public ARCs", status_code=status.HTTP_200_OK
)
async def public_arcs(target: str):
    try:
        target = getTarget(target)
    except:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Target git not found!"
        )

    request = requests.get(os.environ.get(target) + "/api/v4/projects?per_page=1000")

    project_list = Projects(projects=request.json())

    return project_list


# get the frontpage tree structure of the arc
@router.get("/arc_tree", summary="Overview of the ARC", status_code=status.HTTP_200_OK)
async def arc_tree(id: int, request: Request):
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            "Client has no rights to view this ARC! Cookies: " + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )

    arc = requests.get(
        os.environ.get(target)
        + "/api/v4/projects/"
        + str(id)
        + "/repository/tree?per_page=100",
        headers=header,
    )

    if not arc.ok:
        logging.error(
            "Couldn't find ARC with ID "
            + str(id)
            + "; ERROR: "
            + str(arc.content[0:100])
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Couldn't find ARC with ID "
            + str(id)
            + "; Error: "
            + str(arc.content),
        )

    arc_json = Arc(Arc=arc.json())
    logging.info("Sent info of ARC " + str(id))

    return arc_json


# get a specific tree structure for the given path
@router.get(
    "/arc_path", summary="Subdirectory of the ARC", status_code=status.HTTP_200_OK
)
async def arc_path(id: int, request: Request, path: str):
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            "Client is not authorized to view ARC "
            + str(id)
            + " ; Cookies: "
            + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to view this ARC",
        )
    arcPath = requests.get(
        os.environ.get(target)
        + "/api/v4/projects/"
        + str(id)
        + "/repository/tree?per_page=100&path="
        + path,
        headers=header,
    )
    # raise error if the given path gives no result
    if not arcPath.ok:
        logging.error(
            "Path not found! Path: " + path + " ; ERROR: " + str(arcPath.content)
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Path not found! Error: " + str(arcPath.content),
        )

    arc_json = Arc(Arc=arcPath.json())
    logging.info("Sent info of ARC " + str(id) + " with path " + path)

    return arc_json


# gets the specific file on the given path and either saves it on the backend storage (for isa files) or sends the content directly
@router.get(
    "/arc_file",
    summary="Returns the file on the given path",
    status_code=status.HTTP_200_OK,
)
async def arc_file(id: int, path: str, request: Request, branch="main"):
    try:
        data = getData(request.cookies.get("data"))
        header = {"Authorization": "Bearer " + data["gitlab"]}
        target = getTarget(data["target"])
    except:
        logging.warning(
            "Client is not authorized to get the file! Cookies: " + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to get this file",
        )
    # get HEAD data for fileSize
    fileHead = requests.head(
        os.environ.get(target) + "/api/v4/projects/" + str(id) + "/repository/files/"
        # url encode the path
        + quote(path, safe="") + "?ref=" + branch,
        headers=header,
    )
    # raise error if file not found
    if not fileHead.ok:
        logging.error(
            "File not found! Path: " + path + " ; ERROR: " + str(fileHead.content)
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found! Error: " + str(fileHead.content),
        )

    fileSize = fileHead.headers["X-Gitlab-Size"]

    # if file is too big, skip downloading it
    if int(fileSize) > 10000000:
        logging.warning("File too large! Size: " + fileSize)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large! (over 10 MB)",
        )

    # if its a isa file, return the content of the file as json to the frontend
    if getIsaType(path) != "":
        # get the raw ISA file
        fileRaw = requests.get(
            os.environ.get(target)
            + "/api/v4/projects/"
            + str(id)
            + "/repository/files/"
            + quote(path, safe="")
            + "/raw?ref="
            + branch,
            headers=header,
        ).content

        # construct path to save on the backend
        pathName = (
            os.environ.get("BACKEND_SAVE") + data["target"] + "-" + str(id) + "/" + path
        )

        # create directory for the file to save it, skip if it exists already
        os.makedirs(os.path.dirname(pathName), exist_ok=True)
        with open(pathName, "wb") as file:
            file.write(fileRaw)

        logging.debug("Downloading File to " + pathName)

        # read out isa file and create json
        fileJson = readIsaFile(pathName, getIsaType(path))

        logging.info(
            "Sent ISA file "
            + path
            + " from ID: "
            + str(id)
            + " to "
            + request.client.host
        )

        return fileJson["data"]
    # if its not a isa file, return the default metadata of the file to the frontend
    else:
        # get the file metadata
        arcFile = requests.get(
            os.environ.get(target)
            + "/api/v4/projects/"
            + str(id)
            + "/repository/files/"
            + quote(path, safe="")
            + "?ref="
            + branch,
            headers=header,
        )
        logging.info(
            "Sent info of "
            + path
            + " from ID: "
            + str(id)
            + " to "
            + request.client.host
        )
        return arcFile.json()


# reads out the content of the post request body; writes the content to the corresponding isa file on the storage
@router.post("/saveFile", summary="Write isa/overwrite isa file to backend storage")
async def saveFile(request: Request):
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        isaContent = json.loads(requestBody)
        target = data["target"]
    except:
        logging.error(
            "SaveFile Request couldn't be processed! Cookies: "
            + str(request.cookies)
            + " ; Body: "
            + str(request.body)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    logging.debug("Content of isa file change: " + str(isaContent))
    # write the content to the isa file
    writeIsaFile(
        isaContent["isaPath"],
        getIsaType(isaContent["isaPath"]),
        isaContent["rowId"],
        isaContent["isaOld"],
        isaContent["isaInput"],
        isaContent["isaRepo"],
        target,
    )
    logging.debug("write content to isa file...")
    # the path of the file on the storage for the commit request
    pathName = (
        os.environ.get("BACKEND_SAVE")
        + data["target"]
        + "-"
        + str(isaContent["isaRepo"])
        + "/"
        + isaContent["isaPath"]
    )
    logging.debug("committing file to repo...")
    # call the commit function
    try:
        commitResponse = await commitFile(
            request,
            isaContent["isaRepo"],
            isaContent["isaPath"],
            pathName,
            isaContent["arcBranch"],
        )
    except:
        logging.warning(
            "Client is not authorized to commit to ARC! Cookies: "
            + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="No authorized session cookie found",
        )

    logging.info(
        "Sent file " + isaContent["isaPath"] + " to ARC " + str(isaContent["isaRepo"])
    )
    # frontend gets a simple 'success' as response
    return str(commitResponse)


@router.post("/commitFile", summary="Update the content of the file on the repo")
# sends the http PUT request to the git to commit the file on the given filepath
async def commitFile(
    request: Request,
    id: int,
    repoPath,
    filePath="",
    branch="main",
):
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        fileContent = json.loads(requestBody)
        targetRepo = data["target"]

    except:
        logging.error(
            "SaveFile Request couldn't be processed! Cookies: "
            + str(request.cookies)
            + " ; Body: "
            + str(request.body)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    header = {
        "Authorization": "Bearer " + data["gitlab"],
        "Content-Type": "application/json",
    }
    if filePath != "":
        # data of the commit
        payload = {
            "branch": branch,
            # base64 encoding of the isa file
            "content": base64.b64encode(open(filePath, "rb").read()).decode("utf-8"),
            "commit_message": "Updated " + repoPath,
            "encoding": "base64",
        }
    else:
        payload = {
            "branch": branch,
            "content": base64.b64encode(bytes(fileContent["content"], "utf-8")).decode(
                "utf-8"
            ),
            "encoding": "base64",
            "commit_message": "Updated " + repoPath,
        }

    request = requests.put(
        os.environ.get(getTarget(targetRepo))
        + "/api/v4/projects/"
        + str(id)
        + "/repository/files/"
        + quote(repoPath, safe=""),
        data=json.dumps(payload),
        headers=header,
    )

    if not request.ok:
        logging.error("Couldn't commit to ARC! ERROR: " + str(request.content))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't commit file to repo! Error: " + str(request.content),
        )
    logging.info("Updated file on path: " + str(repoPath))
    return request.content


# creates a new project in the repo with a readme file; we then initialize the repo folder on the server with the new id of the ARC;
# then we use the arccommander to create the arc and the investigation file and commit the whole structure to the repo
@router.get(
    "/createArc", summary="Creates a new Arc", status_code=status.HTTP_201_CREATED
)
async def createArc(
    request: Request,
    name: str,
    description: str,
    investIdentifier: str,
):
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(data["target"])
    except:
        logging.warning(
            "Client not logged in for ARC creation! Cookies: " + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Please login to create a new ARC",
        )

    # here we create the project with the readme file
    project = {"name": name, "description": description, "initialize_with_readme": True}

    projectPost = requests.post(
        os.environ.get(target) + "/api/v4/projects",
        headers=header,
        data=json.dumps(project),
    )
    if not projectPost.ok:
        logging.error("Couldn't create new ARC! ERROR: " + str(projectPost.content))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't create new project! Error: " + str(projectPost.content),
        )

    logging.debug("Creating new project with payload " + str(project))
    # we get all the necessary information back from gitlab, like id, main branch,...
    newArcJson = projectPost.json()
    logging.info("Created Arc with Id: " + str(newArcJson["id"]))

    pathName = (
        os.environ.get("BACKEND_SAVE") + data["target"] + "-" + str(newArcJson["id"])
    )
    # create directory for the file to save it, skip if it exists already
    os.makedirs(pathName, exist_ok=True)

    # create the arc structure in the newly created repo
    os.chdir(pathName)
    try:
        arc = os.popen("arc init")
        output = arc.read()
    except:
        print("An error creating the arc structure occurred")
        if output:
            logging.error("Couldn't create arc with arccommander! " + output)
        else:
            logging.error("Couldn't create arc with arccommander!")

        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't create arc with arccommander",
        )

    # replace empty space with underscores (arccommander can't process spaces in strings)
    investIdentifier = investIdentifier.replace(" ", "_")
    try:
        invest = os.popen("arc i create -i " + investIdentifier)
        outputInv = invest.read()
    except:
        print("An error creating the investigation file occurred")
        if outputInv:
            logging.error("Couldn't create investigation file! " + outputInv)
        else:
            logging.error("couldn't create investigation file")

        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't create investigation file with arccommander",
        )

    logging.debug("created arc and investigation file")

    ## commit the folders and the investigation isa to the repo
    arcData = []
    folders = os.listdir()
    # fill the payload with all the files and folders
    for i in range(len(folders)):
        match folders[i]:
            case "isa.investigation.xlsx":
                arcData.append(
                    {
                        "action": "create",
                        "file_path": "isa.investigation.xlsx",
                        "content": base64.b64encode(
                            open(pathName + "/isa.investigation.xlsx", "rb").read()
                        ).decode("utf-8"),
                        "encoding": "base64",
                    }
                )
            # we ignore any readme files
            case "README.md":
                continue
            # we also ignore the hidden .git folder created by the arccommander
            case ".git":
                continue

            case other:
                arcData.append(
                    {
                        "action": "create",
                        "file_path": folders[i] + "/.gitkeep",
                        "content": None,
                    }
                )
    # wrap the payload into json
    payload = json.dumps(
        {
            "branch": newArcJson["default_branch"],
            "commit_message": "Initial commit of the arc structure",
            "actions": arcData,
        }
    )
    logging.debug("Sent commit request to repo with payload " + str(payload))
    # send the data to the repo
    commitRequest = requests.post(
        os.environ.get(target)
        + "/api/v4/projects/"
        + str(newArcJson["id"])
        + "/repository/commits",
        headers=header,
        data=payload,
    )
    if not commitRequest.ok:
        logging.error(
            "Couldn't commit ARC structure to the Hub! ERROR: "
            + str(commitRequest.content)
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't commit the arc to the repo! Error: "
            + str(commitRequest.content),
        )

    # print(commitRequest.json())
    # TODO remove the arc structure to save space
    # shutil.rmtree(pathName)

    logging.info("Created new ARC with ID: " + str(newArcJson["id"]))
    return [projectPost.content, commitRequest.content]


# here we create a assay or study structure with the arccommander and push it to the repo
@router.get(
    "/createISA",
    summary="Creates a new ISA structure",
    status_code=status.HTTP_201_CREATED,
)
async def createIsa(
    request: Request, identifier: str, id: int, type: str, branch="main"
):
    try:
        data = getData(request.cookies.get("data"))
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(data["target"])
    except:
        logging.warning(
            "Client not authorized to create new ISA! Cookies: " + str(request.cookies)
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Not authorized to create new ISA"
        )

    pathName = os.environ.get("BACKEND_SAVE") + data["target"] + "-" + str(id)
    # create directory for the file to save it, skip if it exists already
    os.makedirs(pathName, exist_ok=True)

    os.chdir(pathName)

    identifier = identifier.replace(" ", "_")

    match type:
        case "studies":
            try:
                study = os.popen("arc study init --identifier " + identifier)
                # wait until the arccommander is finished
                studyOut = study.read()
                logging.debug(
                    "created new study file " + identifier + " on " + pathName
                )
                pathName = pathName + "/studies/" + identifier
            except:
                if studyOut:
                    logging.error(
                        "Couldn't create study with arccommander! " + studyOut
                    )
                else:
                    logging.error("Couldn't create study with arccommander!")

                raise HTTPException(
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Couldn't create study structure with arccommander",
                )

        case "assays":
            try:
                assay = os.popen("arc assay init -a " + identifier)
                # wait until the arccommander is finished
                assayOut = assay.read()
                logging.debug(
                    "created new assay file " + identifier + " on " + pathName
                )
                pathName = pathName + "/assays/" + identifier
            except:
                if assayOut:
                    logging.error(
                        "Couldn't create assay with arccommander! " + assayOut
                    )
                else:
                    logging.error("Couldn't create assay with arccommander!")

                raise HTTPException(
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Couldn't create assay structure with arccommander",
                )

        case other:
            logging.error("can only create ISA of type study or assay, not " + type)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Type not found, can only create study or assay file",
            )

    ## commit the folders and the investigation isa to the repo
    isaData = []

    os.chdir(pathName)
    folders = os.listdir()
    # fill the payload with all the files and folders
    for i in range(len(folders)):
        match folders[i]:
            case "isa.study.xlsx":
                isaData.append(
                    {
                        "action": "create",
                        "file_path": type + "/" + identifier + "/isa.study.xlsx",
                        "content": base64.b64encode(
                            open(pathName + "/isa.study.xlsx", "rb").read()
                        ).decode("utf-8"),
                        "encoding": "base64",
                    }
                )

            case "isa.assay.xlsx":
                isaData.append(
                    {
                        "action": "create",
                        "file_path": type + "/" + identifier + "/isa.assay.xlsx",
                        "content": base64.b64encode(
                            open(pathName + "/isa.assay.xlsx", "rb").read()
                        ).decode("utf-8"),
                        "encoding": "base64",
                    }
                )

            case "README.md":
                isaData.append(
                    {
                        "action": "create",
                        "file_path": type + "/" + identifier + "/README.md",
                        "content": base64.b64encode(
                            open(pathName + "/README.md", "rb").read()
                        ).decode("utf-8"),
                        "encoding": "base64",
                    }
                )
            # if its a folder, create the folder with a .gitkeep file
            case other:
                isaData.append(
                    {
                        "action": "create",
                        "file_path": type
                        + "/"
                        + identifier
                        + "/"
                        + folders[i]
                        + "/.gitkeep",
                        "content": None,
                    }
                )
    # wrap the payload into json
    payload = json.dumps(
        {
            "branch": branch,
            "commit_message": "Added new " + type + " " + identifier,
            "actions": isaData,
        }
    )
    logging.debug("Sent commit request with payload " + str(payload))
    # send the data to the repo
    commitRequest = requests.post(
        os.environ.get(target) + "/api/v4/projects/" + str(id) + "/repository/commits",
        headers=header,
        data=payload,
    )
    if not commitRequest.ok:
        logging.error(
            "Couldn't commit ISA to ARC! ERROR: " + str(commitRequest.content)
        )
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't commit ISA structure to repo! Error: "
            + str(commitRequest.content),
        )

    logging.info("Created " + identifier + " in " + type + " for ARC " + str(id))
    return commitRequest.content


@router.post(
    "/uploadFile",
    summary="Uploads the given file to the repo",
    status_code=status.HTTP_201_CREATED,
)
async def uploadFile(request: Request):
    requestBody = await request.body()
    try:
        data = getData(request.cookies.get("data"))
        fileContent = json.loads(requestBody)
        target = getTarget(data["target"])
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
    except:
        logging.error(
            "uploadFile Request couldn't be processed! Cookies: "
            + str(request.cookies)
            + " ; Body: "
            + str(request.body)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    payload = {
        "branch": str(fileContent["branch"]),
        # base64 encoding of the isa file
        "content": fileContent["content"],
        "commit_message": "Upload of new File " + str(fileContent["name"]),
        "encoding": "base64",
    }
    request = requests.post(
        os.environ.get(target)
        + "/api/v4/projects/"
        + str(fileContent["id"])
        + "/repository/files/"
        + quote(fileContent["path"], safe=""),
        data=json.dumps(payload),
        headers=header,
    )
    logging.debug("Uploading file to repo...")
    if not request.ok:
        logging.error("Couldn't upload to ARC! ERROR: " + str(request.content))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't upload file to repo! Error: " + str(request.content),
        )

    logging.info(
        "Uploaded new File "
        + str(fileContent["name"])
        + " to repo "
        + str(fileContent["id"])
        + " on path: "
        + str(fileContent["path"])
    )
    return request.content


@router.get(
    "/getTemplates",
    summary="Retrieve a list of swate templates",
    status_code=status.HTTP_200_OK,
)
async def getTemplates():
    # send get request to swate api requesting all templates
    request = requests.get(
        "https://swate.nfdi4plants.org/api/IProtocolAPIv1/getAllProtocolsWithoutXml"
    )

    # if swate is down, return error 500
    if not request.ok:
        logging.error(
            "There was an error retrieving the swate templates! ERROR: "
            + str(request.json())
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't receive swate templates",
        )

    # map the received list to the model 'Templates'
    template_list = Templates(templates=request.json())

    logging.info("Sent list of swate templates to client!")

    # return the templates
    return template_list


@router.get(
    "/getTemplate",
    summary="Retrieve the specific template",
    status_code=status.HTTP_200_OK,
)
async def getTemplate(id: str):
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
            "There was an error retrieving the swate template with id "
            + id
            + " ! ERROR: "
            + str(request.json())
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't find template with id: " + id,
        )

    # return just the buildingBlocks part of the template (rest is already known)
    templateBlocks = request.json()["TemplateBuildingBlocks"]

    logging.info("Sending template with id " + id + " to client!")

    return templateBlocks


@router.post(
    "/getTerms",
    summary="Retrieve Terms for the given query and parent term",
    status_code=status.HTTP_200_OK,
)
async def getTerms(
    input: str,
    request: Request,
    advanced=False,
):
    # get the body of the post request
    requestBody = await request.body()

    try:
        content = json.loads(requestBody)

        # there should be a parent name and an accession set inside of the body
        parentName = content["parent_name"]
        parentTermAccession = content["parent_accession"]

    # if there are either the name or the accession missing, return error 400
    except:
        logging.warning(
            "Client request couldn't be processed because either the parent name or accession is missing!"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't retrieve parent_term name and/or accession",
        )

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
            logging.debug(
                "Getting an extended list of terms for the input '" + input + "'!"
            )
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
                "Getting an specific list of terms for the input '"
                + input
                + "' with parent '"
                + parentName
                + "'!"
            )
    # if there is a timeout, respond with an error 503
    except requests.exceptions.Timeout:
        logging.warning("Request took to long! Sending timeout error to client...")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="No term could be found in time!",
        )

    # if there is a different kind of error, return error 400
    except:
        logging.error(
            "There was an error retrieving the terms for '"
            + input
            + "'! ERROR: "
            + str(request.json())
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your request couldn't be processed!",
        )

    logging.info("Sent a list of terms for '" + input + "' to client!")
    # return the list of terms found for the given input
    return request.json()


@router.post(
    "/saveTemplate",
    summary="Update or save changes to a template",
    status_code=status.HTTP_200_OK,
)
async def saveTemplate(request: Request):
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Couldn't retrieve content of table",
        )
    # get the file in the backend

    await arc_file(projectId, path, request)

    pathName = (
        os.environ.get("BACKEND_SAVE") + target + "-" + str(projectId) + "/" + path
    )

    createSheet(templateHead, templateContent, path, projectId, target, name)

    response = await commitFile(request, projectId, path, pathName)

    return str(response)


@router.get(
    "/getSheets",
    summary="Get the different non metadata sheets of an isa file",
    status_code=status.HTTP_200_OK,
)
async def getSheets(request: Request, path: str, id, branch="main"):
    try:
        data = getData(request.cookies.get("data"))
        target = getTarget(data["target"])
        header = {
            "Authorization": "Bearer " + data["gitlab"],
            "Content-Type": "application/json",
        }
    except:
        logging.warning("No authorized Cookie found! Cookies: " + str(request.cookies))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authorized cookie found!",
        )

    await arc_file(id, path, request)

    # construct path to the backend
    pathName = (
        os.environ.get("BACKEND_SAVE") + data["target"] + "-" + str(id) + "/" + path
    )

    sheets = getSwateSheets(pathName, getIsaType(path))

    return sheets
