from io import BytesIO
from pathlib import Path
from typing import override
from app.api.endpoints.validation import (
    ArcValidator,
    Assay,
    ClientInterface,
    IsaInvestigation,
    Study,
    ValidationResult,
)


class MockClient(ClientInterface):
    @override
    def fetch_full_repo_tree(self, project_id: int, path: str = "", ref: str = "main"):
        return [
            ".arc/.gitkeep",
            "assays/test_assay1/dataset/.gitkeep",
            "assays/test_assay1/protocols/.gitkeep",
            "assays/test_assay1/README.md",
            "assays/test_assay1/isa.assay.xlsx",
            "assays/.gitkeep",
            "runs/.gitkeep",
            "studies/test_study1/protocols/.gitkeep",
            "studies/test_study1/resources/.gitkeep",
            "studies/test_study1/README.md",
            "studies/test_study1/isa.study.xlsx",
            "studies/.gitkeep",
            "workflows/.gitkeep",
            "README.md",
            "isa.investigation.xlsx",
        ]

    @override
    def fetch_raw_file(
        self, project_id: int, filepath: str, ref: str = "main"
    ) -> BytesIO:
        xlsx_file = Path(__file__).parent / "testdata" / "test_validation2" / filepath
        return BytesIO(xlsx_file.read_bytes())


def test_validate_repostructure() -> None:
    client = MockClient()
    arc_validator = ArcValidator(0, client)
    expected = ValidationResult(is_valid=True, messages=[])
    assert arc_validator.validate_repo_structure() == expected


def test_validate_assays() -> None:
    client = MockClient()
    arc_validator = ArcValidator(0, client)
    expected = [
        Assay(
            name="test_assay1",
            structure=ValidationResult(is_valid=True, messages=[]),
            isa_file_has_second_sheet=ValidationResult(
                is_valid=False,
                messages=["No second sheet in 'assays/test_assay1/isa.assay.xlsx'"],
            ),
        )
    ]
    assert arc_validator.validate_assays() == expected


def test_validate_studies() -> None:
    client = MockClient()
    arc_validator = ArcValidator(0, client)
    expected = [
        Study(
            name="test_study1",
            structure=ValidationResult(is_valid=True, messages=[]),
            isa_file_has_second_sheet=ValidationResult(
                is_valid=False,
                messages=["No second sheet in 'studies/test_study1/isa.study.xlsx'"],
            ),
        )
    ]
    assert arc_validator.validate_studies() == expected


def test_validate_isa_investigation_file() -> None:
    client = MockClient()
    arc_validator = ArcValidator(0, client)
    expected = IsaInvestigation(
        correct_sheet_name=ValidationResult(is_valid=True, messages=[]),
        required_fields={"identifier": True, "title": True, "description": True},
        addtional_fields={"submission_date": False, "release_date": False},
        contacts=[
            {"last_name": True},
            {"first_name": False},
            {"email": False},
            {"affiliation": False},
            {"orcid": False},
        ],
        messages=[
            "No entry found for 'Investigation Submission Date' in 'isa.investigation.xlsx'.",
            "No entry found for 'Investigation Public Release Date' in 'isa.investigation.xlsx'.",
            "Contact 1: No valid value for 'Investigation Person First Name' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Investigation Person First Name' found in 'isa.investigation.xlsx'",
            "Contact 1: No valid value for 'Investigation Person Email' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Investigation Person Email' found in 'isa.investigation.xlsx'",
            "Contact 1: No valid value for 'Investigation Person Affiliation' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Investigation Person Affiliation' found in 'isa.investigation.xlsx'",
            "Contact 1: No valid value for 'Comment[ORCID]' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Comment[ORCID]' found in 'isa.investigation.xlsx'",
        ],
    )
    assert arc_validator.validate_isa_investigation_file() == expected


def test_validate_invenio_publishable() -> None:
    client = MockClient()
    arc_validator = ArcValidator(0, client)
    isa_investigation = IsaInvestigation(
        correct_sheet_name=ValidationResult(is_valid=True, messages=[]),
        required_fields={"identifier": True, "title": True, "description": True},
        addtional_fields={"submission_date": False, "release_date": False},
        contacts=[
            {"last_name": True},
            {"first_name": False},
            {"email": False},
            {"affiliation": False},
            {"orcid": False},
        ],
        messages=[
            "No entry found for 'Investigation Submission Date' in 'isa.investigation.xlsx'.",
            "No entry found for 'Investigation Public Release Date' in 'isa.investigation.xlsx'.",
            "Contact 1: No valid value for 'Investigation Person First Name' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Investigation Person First Name' found in 'isa.investigation.xlsx'",
            "Contact 1: No valid value for 'Investigation Person Email' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Investigation Person Email' found in 'isa.investigation.xlsx'",
            "Contact 1: No valid value for 'Investigation Person Affiliation' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Investigation Person Affiliation' found in 'isa.investigation.xlsx'",
            "Contact 1: No valid value for 'Comment[ORCID]' found in 'isa.investigation.xlsx'",
            "Contact 2: No valid value for 'Comment[ORCID]' found in 'isa.investigation.xlsx'",
        ],
    )
    expected = ValidationResult(
        is_valid=False, messages=["First name is missing for publishing to invenio."]
    )
    assert arc_validator.validate_invenio_publishable(isa_investigation) == expected
