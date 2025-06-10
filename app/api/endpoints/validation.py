from __future__ import annotations

import datetime
import json
import os
import re
import time
import urllib.parse
from io import BytesIO
from typing import Annotated

import pandas as pd
import requests
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field

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
from app.models.gitlab.arc import Arc

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




from enum import Enum
from pprint import pprint
from typing import Any


class ArcValidationResponse(BaseModel):
    structure: ValidationResult
    isa_investigation: IsaInvestigation
    assays: list[Assay]
    studies: list[Study]
    invenio_publishable: ValidationResult
    # has_readme: ValidationResult
    # has_license: ValidationResult


class ValidationResult(BaseModel):
    is_valid: bool
    messages: list[str]


class IsaInvestigation(BaseModel):
    correct_sheet_name: ValidationResult
    required_fields: dict[str, bool]
    addtional_fields: dict[str, bool]
    contacts: list[dict[str, bool]]
    messages: list[str]


class Assay(BaseModel):
    name: str
    structure: ValidationResult
    isa_file_has_second_sheet: ValidationResult
    # all_registered: ValidationResult


class Study(BaseModel):
    name: str
    structure: ValidationResult
    isa_file_has_second_sheet: ValidationResult
    # all_registered: ValidationResult


class IsaFileType(Enum):
    INVESTIGATION = "isa.investigation.xlsx"
    ASSAY = "isa.assay.xlsx"
    STUDY = "isa.study.xlsx"


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
        "submission_date": "Investigation Submission Date",
        "release_date": "Investigation Public Release Date",
    }
    INVESTIGATION_CONTACT_FIELDS: dict[str, str] = {
        "last_name": "Investigation Person Last Name",
        "first_name": "Investigation Person First Name",
        "email": "Investigation Person Email",
        "affiliation": "Investigation Person Affiliation",
        "orcid": "Comment[ORCID]",
    }

    def __init__(self, arc_project_id: int, cookie: str) -> None:
        self.project_id: int = arc_project_id
        self.cookie: str = cookie
        self.full_tree: list[str] = self._fetch_full_repo_tree(
            arc_project_id, cookie, "", "main"
        )

    def validate_repo_structure(self) -> ValidationResult:
        """Check if the ARC repository contains all required top-level directories
        and files.

        Returns:
            The result of the repository structure validation.
        """
        top_level_entries = [x.split("/", maxsplit=1)[0] for x in self.full_tree]
        messages: list[str] = []
        is_valid = True
        for entry in self.REQUIRED_TOP_LEVEL_CONTENT:
            if entry not in top_level_entries:
                is_valid = False
                messages += f"{entry} is missing in the ARC"

        return ValidationResult(is_valid=is_valid, messages=messages)

    def validate_assays(self) -> list[Assay]:
        """Validation of assays.

        Checks if each assay contains the required content and if the
        isa.assay.xlsx file contains a second sheet.

        Returns:
            Validation results of assays.
        """
        assays = self._get_dir_contents("assays")
        validation_assays: list[Assay] = []

        for assay_name, assay_content in assays.items():
            structure = self._check_sub_dir_structure(
                assay_name, assay_content, self.REQUIRED_ASSAY_CONTENT
            )
            isa_file_has_second_sheet = self._check_isa_file_second_sheet(
                assay_name, assay_content, IsaFileType.ASSAY
            )

            validation_assays.append(
                Assay(
                    name=assay_name,
                    structure=structure,
                    isa_file_has_second_sheet=isa_file_has_second_sheet,
                )
            )

        return validation_assays

    def validate_studies(self) -> list[Study]:
        """Validation of studies.

        Checks if each study contains the required content and if the
        isa.study.xlsx file contains a second sheet.

        Returns:
            Validation results of assays.
        """
        studies = self._get_dir_contents("studies")
        validation_studies: list[Study] = []

        for study_name, study_content in studies.items():
            structure = self._check_sub_dir_structure(
                study_name, study_content, self.REQUIRED_STUDY_CONTENT
            )
            isa_file_has_second_sheet = self._check_isa_file_second_sheet(
                study_name, study_content, IsaFileType.STUDY
            )

            validation_studies.append(
                Study(
                    name=study_name,
                    structure=structure,
                    isa_file_has_second_sheet=isa_file_has_second_sheet,
                )
            )

        return validation_studies

    def _check_sub_dir_structure(
        self, sub_dir_name: str, sub_dir_content: list[str], required_content: list[str]
    ) -> ValidationResult:
        """Check an arbitrary sub directory structure, e.g., a certain assay in
        `assays` folder.


        Args:
            sub_dir_name: Name of directory to check (e.g., name of an assay).
            sub_dir_content: Paths of the content of `sub_dir_name`.
            required_content: Names of files/directories required to be
                contained in `sub_dir_name`.

        Returns:
            Result of directory structure validation.
        """
        messages: list[str] = []
        valid_structure = True
        dir_entries = [x.split("/", maxsplit=1)[0] for x in sub_dir_content]
        for required_entry in required_content:
            if required_entry not in dir_entries:
                messages += f"{required_entry} is missing in {sub_dir_name}"
                valid_structure = False

        return ValidationResult(is_valid=valid_structure, messages=messages)

    def _check_isa_file_second_sheet(
        self, sub_dir_name: str, sub_dir_content: list[str], isa_file_type: IsaFileType
    ) -> ValidationResult:
        """Check if an isa.xxx.xlsx file contains a second excel sheet.

        Args:
            sub_dir_name: Name of the directory to check (e.g., name of an assay).
            sub_dir_content: Paths of the content of `sub_dir_name`.
            isa_file_type: Against which kind of isa file to check.

        Returns:
            Result of the validation containing information if a second sheet
            exists or not.
        """
        match isa_file_type:
            case IsaFileType.ASSAY:
                sub_dir_path = f"assays/{sub_dir_name}/"
            case IsaFileType.STUDY:
                sub_dir_path = f"studies/{sub_dir_name}/"
            case IsaFileType.INVESTIGATION:
                sub_dir_path = ""

        messages: list[str] = []
        has_second_sheet = False
        for entry in sub_dir_content:
            if entry.endswith(isa_file_type.value):
                full_name = f"{sub_dir_path}{entry}"
                isa_file_bytes = self._fetch_raw_file(
                    self.project_id, self.cookie, full_name
                )
                sheets = pd.read_excel(isa_file_bytes, index_col=0, sheet_name=None)
                has_second_sheet = len(sheets) > 1
                if not has_second_sheet:
                    messages.append(f"No second sheet in '{full_name}'")

        return ValidationResult(is_valid=has_second_sheet, messages=messages)

    def validate_isa_investigation_file(self) -> IsaInvestigation:
        """Validation of a `isa.investigation.xlsx` file.

        Returns:
            Result of the validation as `IsaInvestigation`.
        """
        isa_investigation_file = IsaFileType.INVESTIGATION.value
        if isa_investigation_file not in self.full_tree:
            raise ValueError(f"`{isa_investigation_file}` missing in ARC")

        excel_bytes = self._fetch_raw_file(
            self.project_id, self.cookie, isa_investigation_file
        )
        sheet_name = "isa_investigation"
        try:
            sheets = pd.read_excel(excel_bytes, index_col=0, sheet_name=None)
            sheet = sheets[sheet_name]
            correct_sheet_name = ValidationResult(is_valid=True, messages=[])
        except KeyError:
            correct_sheet_name = ValidationResult(
                is_valid=False,
                messages=[f"Sheet of 'isa.investigation.xlsx not named {sheet_name}"],
            )
            sheet = pd.read_excel(excel_bytes, index_col=0, sheet_name=0)

        messages: list[str] = list()
        required_fields_results = self._check_isa_investigation_required(
            sheet, messages
        )
        additional_fields_results = self._check_isa_investigation_addtional(
            sheet, messages
        )
        contact_fields_result = self._check_isa_investigation_contacts(sheet, messages)

        return IsaInvestigation(
            correct_sheet_name=correct_sheet_name,
            required_fields=required_fields_results,
            addtional_fields=additional_fields_results,
            contacts=contact_fields_result,
            messages=messages,
        )

    def _check_isa_investigation_required(
        self, sheet: pd.DataFrame, messages: list[str]
    ) -> dict[str, bool]:
        """Check of required fields in an `isa.investigation.xlsx` file.

        Args:
            sheet: Spreadsheet name inside the excel file.
            messages: List of messages about validation status of fields.
                (Gets mutated inside function)

        Returns:
            Dictionary in the form {"<column name>": <validation status>},
            e.g., `{"title": True}`. Mutates messages: Info message(s)
            about negative validation get appended.

        """
        results: dict[str, bool] = dict()
        for key, value in self.REQUIRED_INVESTIGATION_COLUMNS.items():
            try:
                to_validate = [x for x in sheet.loc[value]][0]
            except KeyError:
                messages.append(f"Row '{value}' not found in 'isa.investigation.xlsx'")
                continue

            if not isinstance(to_validate, str) or to_validate == "":
                is_valid = False
                messages.append(
                    f"No entry found for '{value}' in 'isa.investigation.xlsx'"
                )
            else:
                is_valid = True

            results[key] = is_valid

        return results

    def _check_isa_investigation_addtional(
        self, sheet: pd.DataFrame, messages: list[str]
    ) -> dict[str, bool]:
        """Check of additional fields in an `isa.investigation.xlsx` file.

        Args:
            sheet: Spreadsheet name inside the excel file.
            messages: List of messages about validation status of fields.
                (Gets mutated inside function)

        Returns:
            Dictionary in the form {"<column name>": <validation status>},
            e.g., `{"release_date": True}`. Mutates messages: Info message(s)
            about negative validation get appended.
        """
        results: dict[str, bool] = dict()
        for key, value in self.ADDITIONAL_INVESTIGATION_COLUMNS.items():
            try:
                to_validate = sheet.loc[value]
            except KeyError:
                messages.append(f"Row '{value}' not found in 'isa.investigation.xlsx'.")
                continue

            # TODO: valiDate should only return boolean
            if "date" in key and not valiDate(to_validate):
                is_valid = False
                messages.append(
                    f"Entry '{to_validate}' for '{value}' is not a valid date."
                )
            elif not isinstance(to_validate, str) or to_validate == "":
                is_valid = False
                messages.append(
                    f"No entry found for '{value}' in 'isa.investigation.xlsx'."
                )
            else:
                is_valid = True

            results[key] = is_valid

        return results

    def _check_isa_investigation_contacts(
        self, sheet: pd.DataFrame, messages: list[str]
    ) -> list[dict[str, bool]]:
        """Check of additional fields in an `isa.investigation.xlsx` file.

        Args:
            sheet: Spreadsheet name inside the excel file.
            messages: List of messages about validation status of fields.
                (Gets mutated inside function)

        Returns:
            Dictionary in the form {"<column name>": <validation status>},
            e.g., `{"last_name": True}`. Mutates messages: Info message(s)
            about negative validation get appended.
        """
        validation_contacts: list[dict[str, bool]] = []
        for key, field_name in self.INVESTIGATION_CONTACT_FIELDS.items():
            try:
                column_to_validate = sheet.loc[field_name]
            except KeyError:
                messages.append(
                    f"Row '{field_name}' not found in 'isa.investigation.xlsx'"
                )
                continue

            contact: dict[str, bool] = dict()
            contacts_columns: list[Any] = [x for x in sheet.loc[field_name]]
            for i, column_to_validate in enumerate(contacts_columns):
                is_valid = self._check_contact_fields(key, column_to_validate)
                contact[key] = is_valid

                if not is_valid:
                    messages.append(
                        f"Contact {i + 1}: No valid value for '{field_name}' found in 'isa.investigation.xlsx'"
                    )

            validation_contacts.append(contact)

        return validation_contacts

    def _check_contact_fields(self, field_key: str, contact_column: Any) -> bool:
        """Check of contact fields (which is represented as a column).

        Args:
            field_key: Key of `INVESTIGATION_CONTACT_FIELDS` to check against.
            contact_column: Column of an xlsx-file which represents the fields
                of a contact.

        Returns:
            `True` is the contact field is valid, `False` otherwise.
        """
        match field_key:
            case "last_name" | "first_name" | "affiliation":
                is_valid = isinstance(contact_column, str) and contact_column != ""
            case "email":
                is_valid = validMail(contact_column)
            case "orcid":
                is_valid = validORCID(contact_column)
            case _:
                raise NotImplementedError(
                    f"No validation implemented for `{field_key}`."
                )

        return is_valid

    def validate_invenio_publishable(
        self, isa_investigation_file: IsaInvestigation
    ) -> ValidationResult:
        """Validation of an ARC if it can be published to Invenio.

        Args:
            isa_investigation_file: Validation result of an
                `isa.investigation.xlsx` file.

        Returns:
            Result if ARC is publishable to Invenio.
        """
        is_valid = True
        messages: list[str] = []
        try:
            _ = isa_investigation_file.required_fields["title"]
        except KeyError:
            is_valid = False
            messages.append("Title is missing for publishing to invenio.")

        try:
            _ = isa_investigation_file.contacts[0]["last_name"]
        except (KeyError, IndexError):
            is_valid = False
            messages.append("Last name is missing for publishing to invenio.")

        try:
            _ = isa_investigation_file.contacts[0]["first_name"]
        except (KeyError, IndexError):
            is_valid = False
            messages.append("First name is missing for publishing to invenio.")

        return ValidationResult(is_valid=is_valid, messages=messages)

    def _get_dir_contents(self, dirname: str) -> dict[str, list[str]]:
        """Receive paths contained in a directory of an ARC.

        Args:
            dirname: Name of the directory to search inside.

        Returns:
            A dictionary that maps the directory name (str) to the paths
            contained (list[str]) inside of it.
        """
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

    def _fetch_full_repo_tree(
        self, project_id: int, cookie: str, path: str = "", ref: str = "main"
    ) -> list[str]:
        """Fetch the entire tree of the Gitlab repository.

        Args:
            project_id: ID of the ARC.
            cookie: Authorization cookie.
            path: Path to start fetching. Default: "" for starting at the root.
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
                    # End of a tree branch
                    tree.append(item["path"])

            page += 1

        return tree

    def _fetch_raw_file(
        self, project_id: int, cookie: str, filepath: str, ref: str = "main"
    ) -> BytesIO:
        """Fetch the bytes of a file contained in a Gitlab repository.

        Args:
            project_id: ID of the ARC.
            cookie: Authorization cookie.
            filepath: Path to of the file to be fetched.
            ref: Branch for fetching. Default: 'main' branch

        Returns:
            Bytes of the fetched file.
        """
        token = getData(cookie)
        target = getTarget(token["target"])
        domain = os.environ.get(target)
        headers = {"Authorization": f"Bearer {token['gitlab']}"}
        encoded_path = urllib.parse.quote_plus(filepath)
        url = f"{domain}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw?ref={ref}"

        response = requests.get(url, headers=headers)
        return BytesIO(response.content)
