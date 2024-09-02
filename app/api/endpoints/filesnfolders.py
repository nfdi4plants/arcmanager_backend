import base64
import hashlib
import json
import os
import tempfile
from typing import Annotated
from urllib.parse import quote
from fastapi import (
    APIRouter,
    Cookie,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from app.api.endpoints.projects import (
    arc_path,
    fileSizeReadable,
    getData,
    getTarget,
    writeLogJson,
)
from app.models.gitlab.arc import Arc
from app.models.gitlab.commit import Commit

from app.models.gitlab.input import folderContent

import time
import logging

logging.basicConfig(
    filename="backend.log",
    filemode="a",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)

logging.getLogger("multipart").setLevel(logging.INFO)

from starlette.status import HTTP_401_UNAUTHORIZED

# request sessions to retry the important requests
retry = Retry(
    total=5,
    backoff_factor=4,
    status_forcelist=[500, 502, 429, 503, 504],
    allowed_methods=["POST", "PUT", "HEAD"],
)

adapter = HTTPAdapter(max_retries=retry)

session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)

router = APIRouter()


# remove a file from gitattributes if its no longer lfs tracked (through either deletion or upload directly without lfs)
def removeFromGitAttributes(token, id: int, branch: str, filepath: str) -> str | int:
    try:
        target = getTarget(token["target"])
        headers = {
            "Authorization": f"Bearer {token['gitlab']}",
            "Content-Type": "application/json",
        }
    except:
        return 500
    url = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/.gitattributes/raw?ref={branch}"
    attributes = requests.get(url, headers=headers)

    if not attributes.ok:
        return attributes.status_code
    content = attributes.text
    content = content.replace(f"{filepath} filter=lfs diff=lfs merge=lfs -text\n", "")
    content = content.replace(f"{filepath} filter=lfs diff=lfs merge=lfs\n", "")

    postUrl = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote('.gitattributes', safe='')}"

    attributeData = {
        "branch": branch,
        "content": content,
        "commit_message": "Update .gitattributes",
    }
    try:
        response = session.put(postUrl, headers=headers, data=json.dumps(attributeData))
    except Exception as e:
        logging.error(e)
        return 504

    if not response.ok:
        return response.status_code

    return "Replaced"


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
    namespace: Annotated[str, Form()] = "",
    lfs: Annotated[str, Form()] = False,
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
        f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunkNumber}",
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
                f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunk}",
                "rb",
            )
            fullData += f.read()
            f.close()

        # clear the chunks
        try:
            for chunk in range(totalChunks):
                os.remove(f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunk}")
        except:
            pass

        # open up a new hash
        shasum = hashlib.new("sha256")

        ##########################
        ## START UPLOAD PROCESS ##
        ##########################

        # the following code is for uploading a file with LFS (thanks to Julian Weidhase for the code)
        if lfs == "true":
            if namespace == "":
                raise HTTPException(400, "No Namespace was included!")
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
            try:
                r = session.post(downloadUrl, json=lfsJson, headers=lfsHeaders)
            except Exception as e:
                logging.error(e)
                writeLogJson("uploadFile", 504, startTime, e)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Couldn't upload file to repo! Error: {e}",
                )

            if r.status_code == 401:
                logging.warning(
                    f"Client cookie not authorized! Cookies: {request.cookies}"
                )
                writeLogJson(
                    "uploadFile",
                    401,
                    startTime,
                    f"Client not authorized to create new ISA!",
                )
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail="Not authorized to upload a File! Log in again!",
                )

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
                raise HTTPException(
                    status_code=500,
                    detail="Error: There was an error uploading the file. Please re-authorize and try again!",
                )

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
                fileContent = tempFile.read()

                try:
                    res = session.put(
                        urlUpload,
                        headers=header_upload,
                        data=fileContent,
                    )
                except Exception as e:
                    logging.error(e)
                    writeLogJson("uploadFile", 504, startTime, e)
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Couldn't upload file to repo! Error: {e}",
                    )

                if not res.ok:
                    try:
                        responseJson = res.json()
                        responseJson["error"] != None
                    except:
                        responseJson = {
                            "error": "Couldn't upload file",
                            "error_description": "Couldn't upload file to the lfs storage!",
                        }
                        logging.error(f"Couldn't upload to ARC! ERROR: {res.content}")
                        writeLogJson(
                            "uploadFile",
                            400,
                            startTime,
                            f"Couldn't upload to ARC! ERROR: {res.content}",
                        )
                        raise HTTPException(
                            status_code=res.status_code,
                            detail=f"Couldn't upload file to repo! Error: {responseJson['error']}, {responseJson['error_description']}",
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
                "branch": branch,
                "content": pointerContent,
                "commit_message": "create a new lfs pointer file",
            }

            try:
                # check if file already exists
                fileHead = session.head(
                    f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{repoPath}?ref={branch}",
                    headers=header,
                )
                if fileHead.ok:
                    response = session.put(postUrl, headers=headers, json=jsonData)

                else:
                    response = session.post(postUrl, headers=headers, json=jsonData)

            except Exception as e:
                logging.error(e)
                writeLogJson("uploadFile", 504, startTime, e)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Couldn't upload file to repo! Error: {e}",
                )

            ## if it fails, return an error
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
                f"Uploaded new File {name} to repo {id} on path: {branch} with LFS. Size: {fileSizeReadable(size)}"
            )

            ## add filename to the gitattributes
            url = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/.gitattributes/raw?ref={branch}"

            newLine = f"{path} filter=lfs diff=lfs merge=lfs -text\n"

            try:
                getResponse = session.get(url, headers=headers)
            except Exception as e:
                logging.error(e)
                writeLogJson("uploadFile", 504, startTime, e)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Couldn't upload file to repo! Error: {e}",
                )

            postUrl = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote('.gitattributes', safe='')}"

            # if .gitattributes doesn't exist, create a new one
            if not getResponse.ok:
                content = newLine

                attributeData = {
                    "branch": branch,
                    "content": content,
                    "commit_message": "Create .gitattributes",
                }

                try:
                    response = session.post(
                        postUrl, headers=headers, data=json.dumps(attributeData)
                    )
                except Exception as e:
                    logging.error(e)
                    writeLogJson("uploadFile", 504, startTime, e)
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Couldn't upload file to repo! Error: {e}",
                    )

                if not response.ok:
                    try:
                        responseJson = response.json()
                        responseJson["error"] != None
                    except:
                        responseJson = {
                            "error": "Couldn't create .gitattributes",
                            "error_description": "Couldn't create .gitattributes file in ARC!",
                        }
                    logging.error(f"Couldn't upload to ARC! ERROR: {response.content}")
                    writeLogJson(
                        "uploadFile",
                        response.status_code,
                        startTime,
                        f"Couldn't upload to ARC! ERROR: {response.content}",
                    )
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Couldn't upload file to repo! Error: {responseJson['error']}, {responseJson['error_description']}",
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

                try:
                    response = session.put(
                        postUrl, headers=headers, data=json.dumps(attributeData)
                    )
                except Exception as e:
                    logging.error(e)
                    writeLogJson("uploadFile", 504, startTime, e)
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Couldn't upload file to repo! Error: {e}",
                    )

                if not response.ok:
                    try:
                        responseJson = response.json()
                        responseJson["error"] != None
                    except:
                        responseJson = {
                            "error": "Couldn't add to .gitattributes",
                            "error_description": "Couldn't add file to .gitattributes!",
                        }
                    logging.error(
                        f"Couldn't add to .gitattributes! ERROR: {response.content}"
                    )
                    writeLogJson(
                        "uploadFile",
                        400,
                        startTime,
                        f"Couldn't add to .gitattributes! ERROR: {response.content}",
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Couldn't add file to .gitattributes! Error: {responseJson['error']}, {responseJson['error_description']}",
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
            try:
                # check if file already exists
                fileHead = session.head(
                    f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}?ref={branch}",
                    headers=header,
                )
            except Exception as e:
                logging.error(e)
                writeLogJson("uploadFile", 504, startTime, e)
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=f"Couldn't upload file to repo! Error: {e}",
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
                try:
                    # create the file on the gitlab
                    request = session.post(
                        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                        data=json.dumps(payload),
                        headers=header,
                    )
                except Exception as e:
                    logging.error(e)
                    writeLogJson("uploadFile", 504, startTime, e)
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Couldn't upload file to repo! Error: {e}",
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

                try:
                    # update the file to the gitlab
                    request = session.put(
                        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                        data=json.dumps(payload),
                        headers=header,
                    )
                except Exception as e:
                    logging.error(e)
                    writeLogJson("uploadFile", 504, startTime, e)
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Couldn't upload file to repo! Error: {e}",
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
                    status_code=request.status_code,
                    detail=f"Couldn't upload file to repo! Error: {requestJson}",
                )

            # logging
            logging.info(f"Uploaded new File {name} to repo {id} on path: {path}")
            removeFromGitAttributes(token, id, branch, path)
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
    removeFromGitAttributes(token, id, branch, path)
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

    try:
        response = requests.post(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
            headers=header,
            data=json.dumps(payload),
        )
    except Exception as e:
        logging.error(e)
        writeLogJson("createFolder", 504, startTime, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Couldn't create a new folder! Error: {e}",
        )

    if not response.ok:
        logging.error(f"Couldn't create folder {path} ! ERROR: {response.content}")
        writeLogJson(
            "createFolder",
            400,
            startTime,
            f"Couldn't create folder {path} ! ERROR: {response.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't create folder on repo! Error: {response.content}",
        )
    logging.info(f"Created folder on path: {path}")
    writeLogJson("createFolder", 201, startTime)
    return response.content


# here we create a new isa.datamap for the study
@router.put(
    "/renameFolder",
    summary="Renames a folder",
)
async def renameFolder(
    request: Request,
    data: Annotated[str, Cookie()],
    id: int,
    oldPath: str,
    newPath: str,
    branch="main",
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
            f"Client is not authorized to rename the folder! Cookies: {request.cookies}"
        )
        writeLogJson(
            "deleteFolder",
            401,
            startTime,
            f"Client is not authorized to rename the folder!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to rename this folder",
        )

    oldName = ""
    newName = ""

    old = oldPath.split("/")
    new = newPath.split("/")

    for i, name in enumerate(old):
        if name != new[i]:
            oldName = name
            newName = new[i]
            break

    # get the content of the folder
    folder = await arc_path(id, request, oldPath, data)

    # list of all files to be deleted
    payload = []

    # async function filling the payload with all files recursively found in the folder
    async def prepareJson(folder: Arc):
        for entry in Arc(Arc=json.loads(folder.body)["Arc"]).Arc:
            # if its a file, add it to the list
            if entry.type == "blob":
                payload.append(
                    {
                        "action": "move",
                        "previous_path": entry.path,
                        "file_path": entry.path.replace(
                            oldName + "/", newName + "/", 1
                        ),
                    }
                )

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
        "commit_message": f"Moving all content from {oldPath} to {newPath}",
        "actions": payload,
    }

    try:
        moveRequest = requests.post(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/commits",
            headers=header,
            data=json.dumps(requestData),
        )
    except Exception as e:
        logging.error(e)
        writeLogJson("renameFolder", 504, startTime, e)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Couldn't rename folder! Error: {e}",
        )

    if not moveRequest.ok:
        logging.error(
            f"Couldn't rename folder {oldPath} ! ERROR: {moveRequest.content}"
        )
        writeLogJson(
            "renameFolder",
            400,
            startTime,
            f"Couldn't rename folder {oldName} ! ERROR: {moveRequest.content}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't rename folder on repo! Error: {moveRequest.content}",
        )
    logging.info(f"Renamed folder on path {oldPath} to {newPath}")
    writeLogJson("renameFolder", 200, startTime)
    return "Successfully renamed the folder!"
