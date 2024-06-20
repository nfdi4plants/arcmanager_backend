from fastapi import APIRouter


from app.api.endpoints import (
    projects,
    authentication,
    termsntemplates,
    user,
    validation,
    arcsearch,
)


api_router = APIRouter(prefix="/arcmanager/api/v1")


api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(
    termsntemplates.router, prefix="/tnt", tags=["Terms and Templates"]
)
api_router.include_router(user.router, prefix="/user", tags=["User"])
api_router.include_router(
    authentication.router, prefix="/auth", tags=["Authentication"]
)
api_router.include_router(validation.router, prefix="/validate", tags=["Validation"])
api_router.include_router(arcsearch.router, prefix="/search", tags=["Search"])
