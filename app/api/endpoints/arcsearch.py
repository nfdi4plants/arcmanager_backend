import json
import logging
import os
from urllib.parse import quote
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

from app.api.IO.excelIO import readIsaFile
from app.api.endpoints.projects import getData, getTarget, public_arcs, writeLogJson
from app.models.gitlab.projects import Projects

router = APIRouter()

logging.basicConfig(
    filename="backend.log",
    filemode="w",
    format="%(asctime)s-%(levelname)s-%(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,
)


async def getStudyAssays(id: int, datahub: str, branch: str, study: str) -> list:
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
                            publication[fullData[i + 1 + y][0]] = fullData[i + 1 + y][x]
                        if len(result) == 3:
                            result[2].append(publication)
                        else:
                            result[1].append(publication)
                        publication = {}

    if len(result) == 2:
        result.insert(0, "")

    return result


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

    for study in studyDict.keys():
        studyAssayList = await getStudyAssays(id, datahub, branch, study)
        studyDict[study] = studyAssayList
        for assay in studyAssayList:
            if assay in assayList:
                assayList.remove(assay)

    if len(assayList) > 0:
        studyDict["other"] = assayList
    return studyDict


@router.post(
    "/createArcJson",
    summary="Creates a json containing all publicly available Arcs",
    include_in_schema=True,
    status_code=status.HTTP_201_CREATED,
)
async def createArcJson():
    fullProjects = []

    def formatTimeString(time: str) -> str:
        parts = time.split("T")

        date = parts[0]

        time = parts[1].split(".")[0]

        return date + " " + time

    data: list[Projects] = []
    for datahub in ["Freiburg", "Plantmicrobe", "Tuebingen"]:

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
