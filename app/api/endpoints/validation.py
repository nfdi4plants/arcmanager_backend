from __future__ import annotations

import time
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)

from app.api.endpoints.projects import (
    getData,
    writeLogJson,
)
from app.arc_validation import ArcValidationResponse, ArcValidator, GitlabClient

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
    _request: Request, id: Annotated[int, Query(ge=1)], token: commonToken
) -> ArcValidationResponse:
    # this is for measuring the response time of the api
    startTime = time.time()

    client = GitlabClient(token)
    validator = ArcValidator(id, client)

    repo_structure = validator.validate_repo_structure()
    try:
        isa_investigation = validator.validate_isa_investigation_file()
    except ValueError as e:
        raise HTTPException(404, str(e))

    assays = validator.validate_assays()
    studies = validator.validate_studies()
    inventio_publishable = validator.validate_invenio_publishable(isa_investigation)

    response = ArcValidationResponse(
        structure=repo_structure,
        isa_investigation=isa_investigation,
        assays=assays,
        studies=studies,
        invenio_publishable=inventio_publishable,
        # has_readme=ValidationResult(is_valid=False, messages=[]),
        # has_license=ValidationResult(is_valid=False, messages=[]),
    )

    # save the response time and return the dict to the user
    writeLogJson("validateArc", 200, startTime)

    return response
