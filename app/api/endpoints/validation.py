import os
import re
from typing import Annotated
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
    Request,
)

import json
import re
import time
import datetime

import requests

from app.models.gitlab.arc import Arc
from app.api.endpoints.projects import (
    arc_file,
    arc_path,
    arc_tree,
    getAssays,
    getData,
    getStudies,
    getTarget,
    writeLogJson,
)

router = APIRouter()

commonToken = Annotated[str, Depends(getData)]


# validates the arc
@router.get(
    "/validateArc",
    summary="Validates the ARC",
    description="Validates the ARC by checking if all necessary folders are present, the investigation has a title, description and all contacts have the necessary fields filled out.",
    response_description="Dictionary containing the individual results of the different checks containing information whether they were successful or what is missing in your ARC",
)
async def validateArc(
    request: Request, id: Annotated[int, Query(ge=1)], token: commonToken
):
    # this is for measuring the response time of the api
    startTime = time.time()

    # set to true if the arc is fully valid
    fullValidArc = True

    # get the json of the ground arc structure
    arc: Arc = await arc_tree(id, token, request)

    # setup a dict containing the results of the different tests
    valid = {"Assays": [], "Studies": []}

    arcContent = checkContent(
        arc,
        ["studies", "assays", "workflows", "runs", "isa.investigation.xlsx"],
    )

    if isinstance(arcContent, str):
        fullValidArc = False

    # check if there are all the necessary folders and the investigation file present inside the ground arc structure
    valid["ARC_Structure"] = arcContent

    ## here we start checking the assays and studies
    # first we get a list of names for the assays and studies
    assays = await getAssays(request, id, token)
    studies = await getStudies(request, id, token)

    # here we check the content of every assay for whether the folders "dataset" and "protocols are present", as well if the assay file is present
    for entry in assays:
        assay = await arc_path(id, request, f"assays/{entry}", token)

        assayContent = checkContent(
            Arc(Arc=json.loads(assay.body)["Arc"]),
            ["dataset", "protocols", "isa.assay.xlsx"],
        )
        if isinstance(assayContent, str):
            fullValidArc = False

        valid["Assays"].append({entry: assayContent})
    # here we check the content of every study whether the folders "resources" and "protocols are present", as well if the study file is present
    for entry in studies:
        study = await arc_path(id, request, f"studies/{entry}", token)

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

    validInvest = await validateInvestigation(request, id, token)

    for entry in validInvest:
        if isinstance(validInvest[entry], list):
            for contact in validInvest[entry]:
                if isinstance(contact, str):
                    fullValidArc = False
                    break
        else:
            if not validInvest[entry]:
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
@router.get(
    "/validateInvest",
    summary="Validates the Investigation file of the ARC",
    description="Validates the investigation file by checking whether all necessary fields are filled out, such as title and description",
    response_description="Dictionary containing information about every necessary field and if they are filled out properly",
)
async def validateInvestigation(
    request: Request, id: Annotated[int, Query(ge=1)], token: commonToken
) -> dict[str, bool | list]:
    startTime = time.time()
    ## here we start checking the fields of the investigation file
    # to check the content of the investigation file, we first need to retrieve it
    try:
        investigation: list = await arc_file(
            id, "isa.investigation.xlsx", request, token
        )
    except:
        writeLogJson("validateInvest", 404, startTime, "No investigation found!")
        return {
            "identifier": False,
            "title": False,
            "description": False,
            "contacts": [],
            "dates": [],
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
        "contacts": await validateContacts(request, id, token),
        "submissionDate": valiDate(
            getField(investigation, "Investigation Submission Date")[1]
        ),
        "releaseDate": valiDate(
            getField(investigation, "Investigation Public Release Date")[1]
        ),
    }
    writeLogJson("validateInvest", 200, startTime)
    return investSection


# validates title, description and identifier in a study (UNUSED)
async def validateStudy(
    request: Request, id: int, path: str, token: commonToken
) -> dict[str, bool]:
    startTime = time.time()
    ## here we start checking the fields of the investigation file
    # to check the content of the investigation file, we first need to retrieve it
    try:
        study: list = await arc_file(id, f"{path}/isa.study.xlsx", request, token)
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


async def validateContacts(request: Request, id: int, token: commonToken) -> list[str | bool]:
    try:
        investigation: list = await arc_file(
            id, "isa.investigation.xlsx", request, token
        )
    except:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No isa.investigation.xlsx found! ARC is not valid!",
        )

    contacts: list[str | bool] = []

    counter = 1

    lastName = getField(investigation, "Investigation Person Last Name")[counter]
    if not (isinstance(lastName, str) and lastName != ""):
        contacts.append("Last Name is missing")

    while isinstance(lastName, str) and lastName != "":
        try:
            orcid = getField(investigation, "Comment[ORCID]")[counter]
        except:
            orcid = ""
        firstName = getField(investigation, "Investigation Person First Name")[counter]
        email = getField(investigation, "Investigation Person Email")[counter]
        affiliation = getField(investigation, "Investigation Person Affiliation")[
            counter
        ]

        isContactsCompleteValid = True

        # check first name
        if not (isinstance(firstName, str) and firstName != ""):
            contacts.append("First Name is missing!")
            isContactsCompleteValid = False
        # check email
        if not (isinstance(email, str) and validMail(email)):
            contacts.append("Email missing or not valid!")
            isContactsCompleteValid = False
        # check affiliation
        if not (isinstance(affiliation, str) and affiliation != ""):
            contacts.append("Affiliation is missing!")
            isContactsCompleteValid = False
        # check orcid
        if not (isinstance(orcid, str) and validORCID(orcid)):
            contacts.append("ORCID is missing or not valid!")
            isContactsCompleteValid = False

        if isContactsCompleteValid:
            contacts.append(isContactsCompleteValid)

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
def checkContent(arc: Arc, content: list[str]) -> bool | str:
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
def valiDate(date: str) -> bool | str:
    try:
        datetime.datetime.fromisoformat(date)
    except:
        return "Date invalid!"
    return True


# validates an email address
def validMail(email: str) -> bool:
    try:
        return not re.match(r"[^@]+@[^@]+\.[^@]+", email) is None
    except:
        return False


# validates an ORCID by number of digits and dashes. VERY BASIC!
# TODO: Check an actual ORCID db --> Could lead to performance drop
def validORCID(orcid: str) -> bool:
    try:
        return not re.match(r"\d{4}-\d{4}-\d{4}-\d{4}", orcid) is None
    except:
        return False



REQUIRED_TOP_LEVEL_CONTENT = [
    ".arc",
    "assays",
    "runs",
    "studies",
    "workflows",
    "isa.investigation.xlsx",
]
REQUIRED_ASSAY_CONTENT = ["dataset", "protocols", "isa.assay.xlsx"]


class ArcValidator:
    """Class for ARC validation."""

    def __init__(
        self, arc_project_id: int, cookie: str, path: str = "", ref: str = "main"
    ) -> None:
        self.full_tree: list[str] = fetch_full_repo_tree(
            arc_project_id, cookie, path, ref
        )
        for it in self.full_tree:
            print(it)
        print("-" * 80)
        self.assays: dict[str, list[str]] = self._get_contents("assays")
        self.runs: dict[str, list[str]] = self._get_contents("runs")
        self.studies: dict[str, list[str]] = self._get_contents("studies")
        self.workflows: dict[str, list[str]] = self._get_contents("workflows")
        print(self.assays)
        print(self.runs)
        print(self.studies)
        print(self.workflows)

        # contains_required_dirs = self.check_repo_structure(REQUIRED_TOP_LEVEL_CONTENT)
        # print(contains_required_dirs)
        validated_assays = self.check_assay_structures(REQUIRED_ASSAY_CONTENT)
        print(f"{validated_assays=}")

    def check_repo_structure(
        self, required_top_level_content: list[str]
    ) -> dict[str, bool]:
        """Check if the ARC repository contains all required top-level directories
        and files.

        Args:
            required_top_level_content: List of directory and file names
                required in an ARC.

        Returns:
            Dictionary with the required directory names as keys and a corresponding
            boolean as value, indicating if the entry is present or not.
        """
        top_level_entries = [x.split("/", maxsplit=1)[0] for x in self.full_tree]
        return {x: x in top_level_entries for x in required_top_level_content}

    def check_assay_structures(
        self, required_assay_content: list[str]
    ) -> dict[str, dict[str, bool]]:
        """Check if each assay contains all required directories and files.

        Args:
            required_assay_content: List of directory and file names that
                are required in an assay entry

        Returns:
            Dictionary with the assay names as keys (str) and inner dictionaries
            as values. The inner dictionary holds the names of the required
            content names as keys (str) and corresponding booleans as value,
            indicating if an entry is present or not.
        """
        assay_validation: dict[str, dict[str, bool]] = dict()
        for assay_name, assay_content in self.assays.items():
            content_dirs = [x.split("/", maxsplit=1)[0] for x in assay_content]
            assay_validation[assay_name] = {
                x: x in content_dirs for x in required_assay_content
            }

        return assay_validation

    def _get_contents(self, dirname: str) -> dict[str, list[str]]:
        directory_lst = [
            x.split("/", maxsplit=1)[1]
            for x in self.full_tree
            if x.split("/")[0] == dirname
        ]
        directory_dict: dict[str, list[str]] = dict()
        for entry in directory_lst:
            if "/" in entry:
                entry_name, entry_content = entry.split("/", maxsplit=1)
                directory_dict.setdefault(entry_name, []).append(entry_content)

        return directory_dict


def fetch_full_repo_tree(
    project_id: int, cookie: str, path: str = "", ref: str = "main"
) -> list[str]:
    token = getData(cookie)
    target = getTarget(token["target"])
    domain = os.environ.get(target)
    url = f"{domain}/api/v4/projects/{project_id}/repository/tree"
    headers = {"Authorization": f"Bearer {token['gitlab']}"}

    tree: list[str] = []
    page = 1

    while True:
        params = {"ref": ref, "path": path, "per_page": 100, "page": page}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        items = response.json()
        if not items:
            break

        for item in items:
            if item["type"] == "tree":
                # Recurse into subdirectory
                tree.extend(fetch_full_repo_tree(project_id, cookie, item["path"], ref))
            elif item["type"] == "blob":
                tree.append(item["path"])

        page += 1

    return tree
