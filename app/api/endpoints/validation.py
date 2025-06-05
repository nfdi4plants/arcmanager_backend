from io import BytesIO
import os
import re
from typing import Annotated
import urllib.parse
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

from pydantic import BaseModel, Field
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




from typing import Any

class ArcValidator:
    """Class for ARC validation."""

    REQUIRED_TOP_LEVEL_CONTENT: list[str] = [
        ".arc",
        "assays",
        "runs",
        "studies",
        "workflows",
        "isa.investigation.xlsx",
    ]
    REQUIRED_ASSAY_CONTENT: list[str] = ["dataset", "protocols", "isa.assay.xlsx"]
    REQUIRED_STUDY_CONTENT: list[str] = ["resources", "protocols", "isa.study.xlsx"]
    REQUIRED_INVESTIGATION_COLUMNS: dict[str, str] = {
        "identifier": "Investigation Identifier",
        "title": "Investigation Title",
        "description": "Investigation Description",
    }
    ADDITIONAL_INVESTIGATION_COLUMNS: dict[str, str] = {
        "last_name": "Investigation Person Last Name",
        "first_name": "Investigation Person First Name",
        "email": "Investigation Person Email",
        "affiliation": "Investigation Person Affiliation",
        "orcid": "Comment[ORCID]",
        "submission_date": "Investigation Submission Date",
        "release_date": "Investigation Public Release Date",
    }




    def __init__(self, arc_project_id: int, cookie: str) -> None:
        self.full_tree: list[str] = self._fetch_full_repo_tree(
            arc_project_id, cookie, "", "main"
        )

        # contains_required_dirs = self.check_repo_structure()
        # print(contains_required_dirs)
        validated_assays = self.check_assay_structures()
        # print(f"{validated_assays=}")

    def check_repo_structure(self) -> dict[str, bool]:
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
        return {x: x in top_level_entries for x in self.REQUIRED_TOP_LEVEL_CONTENT}

    def check_assay_structures(self) -> dict[str, dict[str, bool]]:
        assays = self._get_dir_contents("assays")
        return self._check_sub_dir_structures(assays, self.REQUIRED_ASSAY_CONTENT)

    def check_study_structures(self) -> dict[str, dict[str, bool]]:
        studies = self._get_dir_contents("studies")
        return self._check_sub_dir_structures(studies, self.REQUIRED_STUDY_CONTENT)

    def check_isa_investigation_file(self, excel_bytes: BytesIO):
        if "isa.investigation.xlsx" not in self.full_tree:
            raise ValueError("`isa.investigation.xlsx` missing in ARC")

        sheets = pd.read_excel(excel_bytes, index_col=0, sheet_name=None)
        try:
            sheet = sheets[sheet_name]
        except KeyError:
            raise KeyError(f"No sheet named `{sheet_name}`")


        validation_required_columns: dict[str, bool] = dict()
        for key, value in self.REQUIRED_INVESTIGATION_COLUMNS.items():
            if value not in sheet.index:
                raise KeyError(f"{value} not found in isa.investigation.xlsx")

            to_validate = sheet.loc[value]
            is_valid = isinstance(to_validate, str) and to_validate != ""
            validation_required_columns[key] = is_valid

        validation_additional_columns: dict[str, list[bool]] = dict()
        for key, value in self.ADDITIONAL_INVESTIGATION_COLUMNS.items():
            if value not in sheet.index:
                raise KeyError(f"{value} not found in isa.investigation.xlsx")

            to_validate: list[Any] = [x for x in sheet.loc[value] if not pd.isna(x)]

            match key:
                case "last_name" | "first_name" | "affiliation":
                    is_valid = [isinstance(x, str) and x != "" for x in to_validate]
                case "email":
                    is_valid = [validMail(x) for x in to_validate]
                case "orcid":
                    is_valid = [validORCID(x) for x in to_validate]
                case "submission_data" | "release_date":
                    # TODO: valiDate should only return boolean
                    is_valid = [valiDate(x) for x in to_validate]
                case _:
                    raise NotImplementedError(f"No validation implemented for `{key}`.")

            validation_additional_columns[key] = is_valid







    def _check_sub_dir_structures(
        self, dir_to_check: dict[str, list[str]], required_content: list[str]
    ) -> dict[str, dict[str, bool]]:
        """Check if a sub directory contains all required directories and files.

        Args:
            required_content: List of directory and file names that
                are required in an assay entry

        Returns:
            Dictionary with the names as keys (str) and inner dictionaries
            as values. The inner dictionary holds the names of the required
            content names as keys (str) and corresponding booleans as value,
            indicating if an entry is present or not.
        """
        validated: dict[str, dict[str, bool]] = dict()
        for name, content in dir_to_check.items():
            content_dirs = [x.split("/", maxsplit=1)[0] for x in content]
            validated[name] = {x: x in content_dirs for x in required_content}

        return validated

    def _get_dir_contents(self, dirname: str) -> dict[str, list[str]]:
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

    def _get_excel_values_to_check(self, excel_bytes: BytesIO, sheet_name: str, keys: dict[str, str]) -> dict[str, list[Any]]:
        sheets = pd.read_excel(excel_bytes, index_col=0, sheet_name=None)
        try:
            sheet = sheets[sheet_name]
        except KeyError:
            raise KeyError(f"No sheet named `{sheet_name}`")

        rows_to_validate = {}
        for origin_key,target_key in keys.items():
            if target_key in sheet.index:
                rows_to_validate[origin_key] = [x for x in sheet.loc[target_key] if not pd.isna(x)]
            else:
                raise KeyError(f"{target_key} not found in isa.investigation.xlsx")

        return rows_to_validate

    def _fetch_full_repo_tree(
        self, project_id: int, cookie: str, path: str = "", ref: str = "main"
    ) -> list[str]:
        """Fetch the entire tree of the Gitlab repository.

        Args:
            project_id: ID of the ARC.
            cookie: Authorization cookie.
            path: Path to start fetching. Default: "" for starting at top-level
            ref: Branch for fetching. Default: 'main' branch

        Returns:
            List of all full paths (str) files and directories in the Gitlab repo.
        """
        token = getData(cookie)
        target = getTarget(token["target"])
        domain = os.environ.get(target)
        headers = {"Authorization": f"Bearer {token['gitlab']}"}
        url = f"{domain}/api/v4/projects/{project_id}/repository/tree"

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
                    tree.extend(
                        self._fetch_full_repo_tree(
                            project_id, cookie, item["path"], ref
                        )
                    )
                elif item["type"] == "blob":
                    tree.append(item["path"])

            page += 1

        return tree

    def _fetch_raw_file(
        self, project_id: int, cookie: str, filepath: str, ref: str = "main"
    ) -> BytesIO:
        token = getData(cookie)
        target = getTarget(token["target"])
        domain = os.environ.get(target)
        headers = {"Authorization": f"Bearer {token['gitlab']}"}
        encoded_path = urllib.parse.quote_plus(filepath)
        url = f"{domain}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw?ref={ref}"

        response = requests.get(url, headers=headers)
        return BytesIO(response.content)
