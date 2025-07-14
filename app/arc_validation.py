from __future__ import annotations

import datetime
import os
import re
import urllib
from abc import ABC, abstractmethod
from enum import Enum
from io import BytesIO
from typing import Annotated, Any, override

from fastapi import Depends
import pandas as pd
import requests
from pydantic import BaseModel, Field

from app.api.endpoints.projects import getData, getTarget


commonToken = Annotated[str, Depends(getData)]


class ArcValidationResponse(BaseModel):
    structure: ValidationResult
    isa_investigation: IsaInvestigation = Field(
        ..., serialization_alias="isaInvestigation"
    )
    assays: list[Assay]
    studies: list[Study]
    invenio_publishable: ValidationResult = Field(
        ..., serialization_alias="invenioPublishable"
    )


class ValidationResult(BaseModel):
    is_valid: bool = Field(..., serialization_alias="isValid")
    messages: list[str]


class IsaInvestigation(BaseModel):
    correct_sheet_name: ValidationResult = Field(
        ..., serialization_alias="correctSheetName"
    )
    required_fields: dict[str, bool] = Field(..., serialization_alias="requiredFields")
    additional_fields: dict[str, bool] = Field(
        ..., serialization_alias="additionalFields"
    )
    contacts: list[dict[str, bool]]
    messages: list[str]


class Assay(BaseModel):
    name: str
    structure: ValidationResult
    isa_file_has_second_sheet: ValidationResult = Field(
        ..., serialization_alias="isaFileHasSecondSheet"
    )


class Study(BaseModel):
    name: str
    structure: ValidationResult
    isa_file_has_second_sheet: ValidationResult = Field(
        ..., serialization_alias="isaFileHasSecondSheet"
    )


class IsaFileType(Enum):
    """Types of ISA spreadsheet files."""

    INVESTIGATION = "isa.investigation.xlsx"
    ASSAY = "isa.assay.xlsx"
    STUDY = "isa.study.xlsx"


class ClientInterface(ABC):
    """Interface for a client used by `ArcValidator`."""

    @abstractmethod
    def fetch_full_repo_tree(
        self, project_id: int, path: str = "", ref: str = "main"
    ) -> list[str]:
        pass

    @abstractmethod
    def fetch_raw_file(
        self, project_id: int, filepath: str, ref: str = "main"
    ) -> BytesIO:
        pass


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
        "submissionDate": "Investigation Submission Date",
        "releaseDate": "Investigation Public Release Date",
    }
    INVESTIGATION_CONTACT_FIELDS: dict[str, str] = {
        "lastName": "Investigation Person Last Name",
        "firstName": "Investigation Person First Name",
        "email": "Investigation Person Email",
        "affiliation": "Investigation Person Affiliation",
        "orcid": "Comment[ORCID]",
    }

    def __init__(self, arc_project_id: int, client: ClientInterface) -> None:
        self.project_id: int = arc_project_id
        self.client: ClientInterface = client
        self.full_tree: list[str] = self.client.fetch_full_repo_tree(
            arc_project_id, "", "main"
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
                messages.append(f"{entry} is missing in the ARC")

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
                messages.append(f"{required_entry} is missing in {sub_dir_name}")
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
                isa_file_bytes = self.client.fetch_raw_file(self.project_id, full_name)
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

        excel_bytes = self.client.fetch_raw_file(
            self.project_id, isa_investigation_file
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
        additional_fields_results = self._check_isa_investigation_additional(
            sheet, messages
        )
        contact_fields_result = self._check_isa_investigation_contacts(sheet, messages)

        return IsaInvestigation(
            correct_sheet_name=correct_sheet_name,
            required_fields=required_fields_results,
            additional_fields=additional_fields_results,
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
                messages.append(f"No entry found for '{value}'")
            else:
                is_valid = True

            results[key] = is_valid

        return results

    def _check_isa_investigation_additional(
        self, sheet: pd.DataFrame, messages: list[str]
    ) -> dict[str, bool]:
        """Check of additional fields in an `isa.investigation.xlsx` file.

        Args:
            sheet: Spreadsheet name inside the excel file.
            messages: List of messages about validation status of fields.
                (Gets mutated inside function)

        Returns:
            Dictionary in the form {"<column name>": <validation status>},
            e.g., `{"releaseDate": True}`. Mutates messages: Info message(s)
            about negative validation get appended.
        """
        results: dict[str, bool] = dict()
        for key, value in self.ADDITIONAL_INVESTIGATION_COLUMNS.items():
            try:
                to_validate = sheet.loc[value]
            except KeyError:
                messages.append(f"Row '{value}' not found in 'isa.investigation.xlsx'.")
                continue

            if "date" in key.lower() and not _validate_date(to_validate):
                is_valid = False
                messages.append(
                    f"No valid value for '{value}' found in 'isa.investigation.xlsx'."
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
            e.g., `{"lastName": True}`. Mutates messages: Info message(s)
            about negative validation get appended.
        """
        validation_contacts: list[dict[str, bool]] = [
            dict() for _ in sheet.loc[self.INVESTIGATION_CONTACT_FIELDS["lastName"]]
        ]
        for key, field_name in self.INVESTIGATION_CONTACT_FIELDS.items():
            try:
                column_to_validate = sheet.loc[field_name]
            except KeyError:
                messages.append(
                    f"Row '{field_name}' not found in 'isa.investigation.xlsx'"
                )
                continue

            contacts_columns: list[Any] = [x for x in sheet.loc[field_name]]
            for i, column_to_validate in enumerate(contacts_columns):
                is_valid = self._check_contact_fields(key, column_to_validate)
                validation_contacts[i][key] = is_valid

                if not is_valid:
                    messages.append(
                        f"Contact {i + 1}: No valid value for '{field_name}'"
                    )

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
            case "lastName" | "firstName" | "affiliation":
                is_valid = isinstance(contact_column, str) and contact_column != ""
            case "email":
                is_valid = _validate_mail(contact_column)
            case "orcid":
                is_valid = _validate_orcid(contact_column)
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


class GitlabClient(ClientInterface):
    def __init__(self, token: commonToken) -> None:
        self.token = token
        self.target = getTarget(self.token["target"])
        self.domain = os.environ.get(self.target)
        self.headers = {"Authorization": f"Bearer {self.token['gitlab']}"}

    @override
    def fetch_full_repo_tree(
        self, project_id: int, path: str = "", ref: str = "main"
    ) -> list[str]:
        """Fetch the entire tree of the Gitlab repository.

        Args:
            project_id: ID of the ARC.
            cookie: Authorization cookie.
            path: Path to start fetching. Default: "" for starting at the root.
            ref: Branch for fetching. Default: 'main' branch

        Returns:
            List of all full paths (str) files and directories in the Gitlab repo.

        Raises:
            requests.HTTPError: If request to Gitlab API fails.
        """
        url = f"{self.domain}/api/v4/projects/{project_id}/repository/tree"

        tree: list[str] = []
        page = 1

        while True:
            params = {"ref": ref, "path": path, "per_page": 100, "page": page}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            items = response.json()
            if not items:
                break

            for item in items:
                if item["type"] == "tree":
                    # Recurse into subdirectory
                    tree.extend(
                        self.fetch_full_repo_tree(project_id, item["path"], ref)
                    )
                elif item["type"] == "blob":
                    # End of a tree branch
                    tree.append(item["path"])

            page += 1

        return tree

    @override
    def fetch_raw_file(
        self, project_id: int, filepath: str, ref: str = "main"
    ) -> BytesIO:
        """Fetch the bytes of a file contained in a Gitlab repository.

        Args:
            project_id: ID of the ARC.
            cookie: Authorization cookie.
            filepath: Path to of the file to be fetched.
            ref: Branch for fetching. Default: 'main' branch

        Returns:
            Bytes of the fetched file.

        Raises:
            requests.HTTPError: If request to Gitlab API fails.
        """
        encoded_path = urllib.parse.quote_plus(filepath)
        url = f"{self.domain}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw"
        params = {"ref": ref}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        return BytesIO(response.content)

    # TODO: check if there's a better way to do that
    def is_file_tracked_by_lfs(
        self, project_id: int, filepath: str, ref: str = "main"
    ) -> bool:
        """Check if a file is tracked via Git LFS by looking for a
        Git LFS pointer file.

        Args:
            filepath: Path to the file in the repo.
            ref: Branch or tag name (default: "main").

        Returns:
            True if the file is an LFS pointer, False otherwise.

        Raises:
            requests.HTTPError: If request to Gitlab API fails.
        """
        encoded_path = urllib.parse.quote_plus(filepath)
        url = f"{self.domain}/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw"
        params = {"ref": ref}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()

        content = response.content
        return content.startswith(b"version https://git-lfs.github.com/spec/v1")


def _validate_date(date: str) -> bool:
    """Validation of a date value."""
    try:
        _ = datetime.datetime.fromisoformat(date)
    except Exception:
        return False
    return True


def _validate_mail(email: str) -> bool:
    """Validation of an e-mail address"""
    try:
        return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None
    except Exception:
        return False


# TODO: Check an actual ORCID db --> Could lead to performance drop
def _validate_orcid(orcid: str) -> bool:
    """Basic validation of an ORCID by number of digits and dashes."""
    try:
        return re.match(r"\d{4}-\d{4}-\d{4}-\d{4}", orcid) is not None
    except Exception:
        return False
