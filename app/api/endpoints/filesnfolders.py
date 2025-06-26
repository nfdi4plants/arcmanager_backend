import base64
import hashlib
import json
import os
import tempfile
from typing import Annotated
from urllib.parse import quote
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
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

from app.models.gitlab.input import LFSUpload, folderContent

import time
import logging

from dotenv import load_dotenv

from starlette.status import HTTP_401_UNAUTHORIZED

# request sessions to retry the important requests
retry = Retry(
    total=3,
    backoff_factor=5,
    status_forcelist=[500, 502, 429, 503, 504, 400],
    allowed_methods=["POST", "PUT", "HEAD"],
)

adapter = HTTPAdapter(max_retries=retry)

session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)

router = APIRouter()

commonToken = Annotated[str, Depends(getData)]

load_dotenv()

tempfile.tempdir = os.environ.get("BACKEND_SAVE") + "cache"

logging.getLogger("python_multipart").setLevel(logging.INFO)


# remove a file from gitattributes if its no longer lfs tracked (through either deletion or upload directly without lfs)
def removeFromGitAttributes(
    token,
    id: int,
    branch: str,
    filepath: str | list[str],
    rename=False,
    newPath: list[str] = [""],
) -> str | int:
    try:
        target = getTarget(token["target"])
        headers = {
            "Authorization": f"Bearer {token['gitlab']}",
            "Content-Type": "application/json",
        }
    except:
        raise HTTPException(status_code=500, detail="Gitlab token was not found!")

    for x in range(5):
        time.sleep(x)
        url = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/.gitattributes/raw?ref={branch}"
        attributes = requests.get(url, headers=headers)

        if attributes.status_code == 404:
            return "Nothing to remove!"

        if attributes.ok:

            content = attributes.text

            found = False

            if type(filepath) is list:
                for i, entry in enumerate(filepath):
                    if entry in content:
                        found = True

                    if rename:
                        content = content.replace(
                            f"{entry} filter=lfs diff=lfs merge=lfs -text\n",
                            f"{newPath[i]} filter=lfs diff=lfs merge=lfs -text\n",
                        )
                        content = content.replace(
                            f"{entry} filter=lfs diff=lfs merge=lfs\n",
                            f"{newPath[i]} filter=lfs diff=lfs merge=lfs\n",
                        )
                    else:
                        content = content.replace(
                            f"{entry} filter=lfs diff=lfs merge=lfs -text\n", ""
                        )
                        content = content.replace(
                            f"{entry} filter=lfs diff=lfs merge=lfs\n", ""
                        )
            else:
                if filepath in content:
                    found = True
                content = content.replace(
                    f"{filepath} filter=lfs diff=lfs merge=lfs -text\n", ""
                )
                content = content.replace(
                    f"{filepath} filter=lfs diff=lfs merge=lfs\n", ""
                )

            postUrl = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote('.gitattributes', safe='')}"

            attributeData = {
                "branch": branch,
                "content": content,
                "commit_message": "Update .gitattributes",
            }
            if found:
                try:
                    response = requests.put(
                        postUrl, headers=headers, data=json.dumps(attributeData)
                    )
                except Exception as e:
                    logging.error(e)
                    raise HTTPException(status_code=500, detail="ERROR: " + str(e))
                if response.status_code == 400:
                    logging.DEBUG("Retry removing entry from gitattributes")
                if not response.ok and response.status_code != 400:
                    return response.status_code

                if response.ok:
                    return "Replaced"
            else:
                return "No entry found!"

    # if after 5 tries the .gitattributes wasn't found or somehow else not modified, return an error
    logging.warning(".gitattributes could not be modified for " + str(filepath))
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="ERROR: .gitattributes could not be updated! Please add entry for file "
        + str(filepath),
    )


def fileChecker(id: int, name: str, totalChunks: int):
    for chunk in range(totalChunks):
        try:
            f = open(
                f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunk}",
                "rb",
            )
            f.close()
        except FileNotFoundError:
            logging.error(
                f"File {id}-{name}.{chunk} not found in cache! Requesting new upload!"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"File {id}-{name}.{chunk} not found in cache! Please upload the file again!",
                headers={
                    "missing-package": str(chunk),
                    "Access-Control-Expose-Headers": "missing-package",
                },
            )


# either caches the given byte chunk or uploads the file directly (merges all the byte chunks as soon as all have been received)
@router.post(
    "/uploadFile",
    summary="Uploads the given file to the repo (with or without lfs)",
    status_code=status.HTTP_201_CREATED,
    description="Uploads the given file to the ARC on the given path. ARCmanager utilizes chunking of files for better upload. All chunks have to be numbered and the total number of chunks has to be provided(defaults are provided). For files larger than 50mb it is recommended to use LFS (set to true).",
    response_description="Response of the commit from Gitlab.",
)
async def uploadFile(
    request: Request,
    token: commonToken,
    file: Annotated[bytes, File()],
    name: Annotated[str, Form()],
    id: Annotated[int, Form(ge=1)],
    path: Annotated[str, Form()],
    branch: Annotated[str, Form()] = "main",
    namespace: Annotated[str, Form()] = "",
    lfs: Annotated[LFSUpload, Form()] = "false",
    chunkNumber: Annotated[int, Form(ge=0)] = 0,
    totalChunks: Annotated[int, Form(ge=1)] = 1,
) -> Commit | dict | str:
    startTime = time.time()
    try:
        target = getTarget(token["target"])
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
    except:
        logging.error(f"uploadFile Request couldn't be processed! Body: {request.body}")
        writeLogJson(
            "uploadFile",
            400,
            startTime,
            f"uploadFile Request couldn't be processed! Body: {request.body}",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Couldn't read request"
        )

    tempFile = tempfile.TemporaryFile(
        prefix="temp_",
        dir=os.environ.get("BACKEND_SAVE") + "cache",
    )

    f = open(
        f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunkNumber}",
        "wb",
    )
    f.write(file)
    f.close()

    # check every 20th chunk if the token is still valid
    if chunkNumber % 20 == 0:
        # check if user token is still valid by requesting the repository tree
        arc = requests.head(
            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?per_page=100&ref={branch}",
            headers=header,
        )
        if not arc.ok:
            logging.warning(f"Token expired!")
            writeLogJson(
                "uploadFile",
                arc.status_code,
                startTime,
                f"Token expired!",
            )
            raise HTTPException(
                status_code=arc.status_code,
                detail=f"Token expired! Please refresh your session!",
            )

    # open up a new hash
    shasum = hashlib.new("sha256")

    # if the current chunk is the last chunk, merge all chunks together and write them into the temporary file
    if chunkNumber + 1 == totalChunks:
        fileChecker(id, name, totalChunks)

        for chunk in range(totalChunks):
            f = open(
                f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunk}",
                "rb",
            )
            chunkData = f.read()
            shasum.update(chunkData)
            tempFile.write(chunkData)

            f.close()

            # clear the chunk
            try:
                os.remove(f"{os.environ.get('BACKEND_SAVE')}cache/{id}-{name}.{chunk}")
            except:
                logging.warning(f"Failed to remove chunk {chunk} for file {name}")

        # go to the start of the tempfile
        tempFile.seek(0)

        ##########################
        ## START UPLOAD PROCESS ##
        ##########################

        # the following code is for uploading a file with LFS (code based on ARCfs from Dataplant)
        if lfs.value == "true":
            if namespace == "":
                logging.error(
                    f"No namespace included for file {name}. Namespace: {namespace}"
                )
                raise HTTPException(400, "No Namespace was included!")
            logging.debug("Uploading file with lfs...")

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

            headers = {
                "Authorization": f"Bearer {token['gitlab']}",
                "Content-Type": "application/json",
            }

            # construct the download url for the file
            downloadUrl = f"https://oauth2:{token['gitlab']}@{os.environ.get(target).split('//')[1]}/{namespace}.git/info/lfs/objects/batch"

            x = -1

            # loop the upload process in case there is an 400 error returned after uploading the pointer file
            # (indicating that the file wasn't properly uploaded to lfs storage in the first place)
            while x < 3:
                x += 1
                # sleep for 10 secs increasing for each retry
                time.sleep(x * 10)
                if x > 0:
                    logging.debug("Retry " + str(x) + " for file: " + name)

                ### Start upload process ###

                # asking gitlab for the lfs address for the file
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
                    logging.warning(f"Client cookie not authorized!")
                    writeLogJson(
                        "uploadFile",
                        401,
                        startTime,
                        f"Client not authorized to create new ISA!",
                    )
                    raise HTTPException(
                        status_code=HTTP_401_UNAUTHORIZED,
                        detail="Not authorized to upload a File! Log in again or refresh the session!",
                    )
                logging.debug("Uploading file to lfs...")
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

                try:
                    logging.debug(name + ": " + str(sha256))
                except:
                    logging.debug("Result for " + name + ": " + str(r.content))

                # test if there is a change in the file
                testFail = False
                try:
                    test = result["objects"][0]["actions"]

                # if the file is the same, there will be no "actions" attribute and therefore no upload is needed
                except:
                    testFail = True

                # if the file is new or includes new content, upload it
                if not testFail:
                    # get header data
                    header_upload = result["objects"][0]["actions"]["upload"]["header"]

                    # get the upload link
                    urlUpload = result["objects"][0]["actions"]["upload"]["href"]
                    header_upload.pop("Transfer-Encoding")

                    # start at the beginning of the file
                    tempFile.seek(0, 0)

                    # upload the full file to lfs
                    try:
                        res = session.put(
                            urlUpload,
                            headers=header_upload,
                            data=tempFile,
                            stream=True,
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
                            logging.error(
                                f"Couldn't upload to ARC! ERROR: {res.content}"
                            )
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

                logging.debug("Uploading pointer file to repo...")

                # build and upload the new pointer file to the arc
                repoPath = quote(path, safe="")

                postUrl = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{repoPath}"

                pointerContent = (
                    f"version https://git-lfs.github.com/spec/v1\n"
                    f"oid sha256:{sha256}\nsize {size}\n"
                )

                jsonData = {
                    "branch": branch,
                    "content": pointerContent,
                    "commit_message": "Create a new lfs pointer file",
                }

                try:
                    # check if file already exists
                    fileHead = session.head(
                        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{repoPath}?ref={branch}",
                        headers=header,
                    )

                    # if file exists, a put request is needed as the file is being updated
                    if fileHead.ok:
                        response = session.put(postUrl, headers=headers, json=jsonData)

                    # if the head request fails, the files does not exist yet and needs to be send via http POST
                    else:
                        response = session.post(postUrl, headers=headers, json=jsonData)

                except Exception as e:
                    logging.error(e)
                    if fileHead.ok:
                        response = requests.put(postUrl, headers=headers, json=jsonData)
                    else:
                        response = requests.post(
                            postUrl, headers=headers, json=jsonData
                        )

                ## if the pointer upload fails, return an error or start again (in case of an 400 error, indicating gitlab being overwhelmed currently)
                if not response.ok and response.status_code != 400:
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
                        response.status_code,
                        startTime,
                        f"Couldn't upload to ARC! ERROR: {response.content}",
                    )
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Couldn't upload file to repo! Error: {responseJson['error']}, {responseJson['error_description']}",
                    )

                else:
                    # return exception if upload failed after 3 tries
                    if x >= 2 and response.status_code == 400:
                        logging.error(
                            f"File {path} failed to upload after three tries! ERROR: {response.content}"
                        )
                        writeLogJson(
                            "uploadFile",
                            500,
                            startTime,
                            f"Couldn't upload to ARC after three tries! ERROR: {response.content}",
                        )
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"File {name} failed to upload after three tries! ERROR: {response.content}",
                        )

                    # check if response actually was successful, else the loop will start back at the beginning
                    if response.ok:
                        # check availability to make sure, the file also was properly uploaded in the lfs
                        logging.debug("Checking availability for " + name)
                        lfsJsonDown = {
                            "operation": "download",
                            "objects": [{"oid": f"{sha256}", "size": f"{size}"}],
                            "transfers": ["lfs-standalone-file", "basic"],
                            "ref": {"name": f"refs/heads/{branch}"},
                            "hash_algo": "sha256",
                        }

                        # request the download url for the file from lfs
                        try:
                            downloadCheck = session.post(downloadUrl, json=lfsJsonDown)
                        except Exception as e:
                            logging.error(e)
                            writeLogJson("uploadFile", 504, startTime, e)
                            raise HTTPException(
                                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                                detail=f"Couldn't check file status! Error: {e}",
                            )
                        if downloadCheck.ok:
                            try:
                                # get the download url and header for the file
                                checkResult = downloadCheck.json()
                                try:
                                    header_download = checkResult["objects"][0][
                                        "actions"
                                    ]["download"]["header"]
                                except:
                                    header_download = {
                                        "Authorization": f"Bearer {token['gitlab']}"
                                    }
                                urlDownload = checkResult["objects"][0]["actions"][
                                    "download"
                                ]["href"]

                                try:
                                    # make a simple head request just to see whether the file is existing (we dont need to download it)
                                    lfsCheck = session.head(
                                        urlDownload,
                                        headers=header_download,
                                    )
                                except Exception as e:
                                    logging.error(e)
                                    writeLogJson("uploadFile", 504, startTime, e)
                                    raise HTTPException(
                                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                                        detail=f"Couldn't check file status! Error: {e}",
                                    )

                                # if file is available, break loop
                                if lfsCheck.ok:
                                    logging.debug(f"Upload of file {name} successful")
                                    x = 3

                                # if file is missing it indicates a failed upload attempt -> go back to the start of the loop
                                else:
                                    logging.warning(
                                        f"File {name} not found in LFS storage, retrying upload process..."
                                    )
                            except Exception as e:
                                logging.error(e)

            ### end of loop ###

            # logging
            logging.info(
                f"Uploaded File {name} to repo {id} on path: {path} with LFS. Size: {fileSizeReadable(size)}"
            )

            ### loop gitattributes ###

            for y in range(5):
                ## add filename to the gitattributes
                url = f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/.gitattributes/raw?ref={branch}"

                newLine = f"{path} filter=lfs diff=lfs merge=lfs -text\n"

                # get the .gitattributes (for every retry sleep 2 sec in between)
                try:
                    if y > 0:
                        logging.debug("Retrying retrieving .gitattributes...")
                    time.sleep(y * 2)
                    getResponse = session.get(url, headers=headers)
                except Exception as e:
                    logging.error(e)
                    writeLogJson("uploadFile", 504, startTime, e)
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=f"Couldn't update .gitattributes! Error: {e}",
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
                        response = requests.post(
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
                        logging.error(
                            f"Couldn't upload to ARC! ERROR: {response.content}"
                        )
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
                        response = requests.put(
                            postUrl, headers=headers, data=json.dumps(attributeData)
                        )
                    except Exception as e:
                        logging.error(e)
                        writeLogJson("uploadFile", 504, startTime, e)
                        raise HTTPException(
                            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail=f"Couldn't upload file to repo! Error: {e}",
                        )

                    if not response.ok and response.status_code != 400:
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

                    elif response.ok:
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
            x = -1
            while x < 3:
                x += 1
                # sleep for 10 secs increasing for each retry
                time.sleep(x * 10)
                if x > 0:
                    logging.debug("Retry " + str(x) + " for file: " + name)

                ### Start upload process ###
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
                        "content": base64.b64encode(tempFile.read()).decode("utf-8"),
                        "commit_message": f"Upload of new File {name}",
                        "encoding": "base64",
                    }
                    try:
                        # create the file on the gitlab
                        uploadResponse = session.post(
                            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                            data=json.dumps(payload),
                            headers=header,
                        )
                    except Exception as e:
                        logging.error(e)
                        uploadResponse = requests.post(
                            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                            data=json.dumps(payload),
                            headers=header,
                        )
                    if not uploadResponse.ok and uploadResponse.status_code != 400:
                        logging.error(
                            f"Couldn't upload file! ERROR: {uploadResponse.content}"
                        )
                        writeLogJson(
                            "uploadFile",
                            504,
                            startTime,
                            f"Couldn't upload file! ERROR: {uploadResponse.content}",
                        )
                        raise HTTPException(
                            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail=f"Couldn't upload file to repo! Error: {uploadResponse.content}",
                        )

                    statusCode = status.HTTP_201_CREATED

                # if file already exists, update the file
                else:
                    payload = {
                        "branch": branch,
                        # base64 encoding of the isa file
                        "content": base64.b64encode(tempFile.read()).decode("utf-8"),
                        "commit_message": f"Updating File {name}",
                        "encoding": "base64",
                    }

                    try:
                        # update the file to the gitlab
                        uploadResponse = session.put(
                            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                            data=json.dumps(payload),
                            headers=header,
                        )
                    except Exception as e:
                        logging.error(e)
                        # update the file to the gitlab
                        uploadResponse = session.put(
                            f"{os.environ.get(target)}/api/v4/projects/{id}/repository/files/{quote(path, safe='')}",
                            data=json.dumps(payload),
                            headers=header,
                        )
                    if not uploadResponse.ok and uploadResponse.status_code != 400:
                        logging.error(
                            f"Couldn't upload file! ERROR: {uploadResponse.content}"
                        )
                        writeLogJson(
                            "uploadFile",
                            504,
                            startTime,
                            f"Couldn't upload file! ERROR: {uploadResponse.content}",
                        )
                        raise HTTPException(
                            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                            detail=f"Couldn't upload file to repo! Error: {uploadResponse.content}",
                        )

                    statusCode = status.HTTP_200_OK

                # if file was uploaded, break the loop
                if uploadResponse.ok:
                    logging.debug(f"Upload of file {name} successful")
                    x = 3

                # return exception if upload failed after 3 tries
                if x >= 2 and uploadResponse.status_code == 400:
                    logging.error(
                        f"File {path} failed to upload after three tries! ERROR: {uploadResponse.content}"
                    )
                    writeLogJson(
                        "uploadFile",
                        500,
                        startTime,
                        f"Couldn't upload to ARC after three tries! ERROR: {uploadResponse.content}",
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"File {name} failed to upload after three tries! ERROR: {uploadResponse.content}",
                    )

            # logging
            logging.info(f"Uploaded new File {name} to repo {id} on path: {path}")
            removeFromGitAttributes(token, id, branch, path)
            response = Response(uploadResponse.content, statusCode)
            writeLogJson(
                "uploadFile",
                statusCode,
                startTime,
            )
            return response

    # log the current progress and return the confirmation
    else:
        writeLogJson(
            "uploadFile",
            202,
            startTime,
        )
        logging.debug(
            f"Received chunk {chunkNumber+1} of {totalChunks} for file {name}"
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
    description="Deletes the file on the given path. This only works for single files. For full folders use /deleteFolder",
    response_description="Successfully deleted the file!",
)
async def deleteFile(
    id: Annotated[int, Query(ge=1)],
    path: str,
    request: Request,
    token: commonToken,
    branch: str = "main",
):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(f"Client is not authorized to delete the file!")
        writeLogJson(
            "deleteFile",
            401,
            startTime,
            f"Client is not authorized to delete the file!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to delete this file! Please authorize or refresh session!",
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
    description="Deletes the folder on the given path. This works through iterating all entries on the given folder path and deleting every single entry in one large commit.",
    response_description="Successfully deleted the folder",
)
async def deleteFolder(
    id: Annotated[int, Query(ge=1)],
    path: str,
    request: Request,
    token: commonToken,
    branch: str = "main",
):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(f"Client is not authorized to delete the folder!")
        writeLogJson(
            "deleteFolder",
            401,
            startTime,
            f"Client is not authorized to delete the folder!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to delete this folder! Please authorize or refresh session!",
        )

    # get the number of pages
    arcPath = session.head(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?path={path}&ref={branch}",
        headers=header,
    )
    if not arcPath.ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Path {path} does not exist! Please reload your Arc!",
        )

    pages = int(arcPath.headers["X-Total-Pages"])

    # list of all files to be deleted
    payload = []

    # list of file names, that will be deleted from gitattributes after the remove request was successful
    fileNames: list[str] = []

    for page in range(1, pages + 1):

        # get the content of the folder
        folder = await arc_path(id, request, path, token, page)

        # async function filling the payload with all files recursively found in the folder
        async def prepareJson(folder: Arc):
            for entry in Arc(Arc=json.loads(folder.body)["Arc"]).Arc:
                # if its a file, add it to the list
                if entry.type == "blob":
                    payload.append({"action": "delete", "file_path": entry.path})
                    fileNames.append(entry.path)

                # if its a folder, search the folder for any file
                elif entry.type == "tree":
                    await prepareJson(
                        await arc_path(id, request, entry.path, token, page)
                    )

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
    else:
        removeFromGitAttributes(token, id, branch, fileNames)

    logging.info(f"Deleted folder on path: {path}")
    writeLogJson("deleteFolder", 200, startTime)
    return "Successfully deleted the folder!"


# creates a folder on the given path
@router.post(
    "/createFolder",
    summary="Creates a folder on the given path",
    status_code=status.HTTP_201_CREATED,
    description="Creates a new folder with the given identifier on the given path. This is done through uploading a empty '.gitkeep' file on the newly folder path.",
    response_description="Response of the commit from Gitlab.",
)
async def createFolder(request: Request, folder: folderContent, token: commonToken):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }

        target = getTarget(token["target"])
    except:
        logging.warning(f"Client not authorized to create new folder!")
        writeLogJson(
            "createFolder",
            401,
            startTime,
            f"Client not authorized to create new folder!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Not authorized to create new folder! Please authorize or refresh session!",
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
    description="Renames a folder given on the oldPath to the new folder name given on the full newPath. This is done by iterating through all entries in the oldPath folder and moving all entries to the newPath.",
    response_description="Successfully renamed the folder!",
)
async def renameFolder(
    request: Request,
    token: commonToken,
    id: Annotated[int, Query(ge=1)],
    oldPath: str,
    newPath: str,
    branch: str = "main",
):
    startTime = time.time()
    try:
        header = {
            "Authorization": "Bearer " + token["gitlab"],
            "Content-Type": "application/json",
        }
        target = getTarget(token["target"])
    except:
        logging.warning(f"Client is not authorized to rename the folder!")
        writeLogJson(
            "deleteFolder",
            401,
            startTime,
            f"Client is not authorized to rename the folder!",
        )
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="You are not authorized to rename this folder! Please authorize or refresh session!",
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

    # get the number of pages
    arcPath = session.head(
        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?path={oldPath}&ref={branch}",
        headers=header,
    )

    pages = int(arcPath.headers["X-Total-Pages"])

    # list of all files to be deleted
    payload = []

    fileNames = []
    newNames = []

    for page in range(1, pages + 1):
        # get the content of the folder
        folder = await arc_path(id, request, oldPath, token, page)

        # async function filling the payload with all files recursively found in the folder
        async def prepareJson(folder: Arc):
            for entry in Arc(Arc=json.loads(folder.body)["Arc"]).Arc:
                # if its a file, add it to the list
                if entry.type == "blob":
                    newPath = entry.path.replace(oldName + "/", newName + "/", 1)
                    payload.append(
                        {
                            "action": "move",
                            "previous_path": entry.path,
                            "file_path": newPath,
                        }
                    )
                    fileNames.append(entry.path)
                    newNames.append(newPath)

                # if its a folder, search the folder for any file
                elif entry.type == "tree":
                    # get the number of pages
                    subPath = session.head(
                        f"{os.environ.get(target)}/api/v4/projects/{id}/repository/tree?path={entry.path}&ref={branch}",
                        headers=header,
                    )
                    if subPath.ok:
                        for subPage in range(
                            1, int(subPath.headers["X-Total-Pages"]) + 1
                        ):
                            await prepareJson(
                                await arc_path(id, request, entry.path, token, subPage)
                            )

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
    else:
        removeFromGitAttributes(token, id, branch, fileNames, True, newNames)
    logging.info(f"Renamed folder on path {oldPath} to {newPath}")
    writeLogJson("renameFolder", 200, startTime)
    return "Successfully renamed the folder!"
