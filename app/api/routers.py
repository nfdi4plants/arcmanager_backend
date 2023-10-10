from fastapi import APIRouter


from app.api.endpoints import (
    projects,
    authentication,
    authentication_alt,
)



api_router = APIRouter(prefix="/arcmanager/api/v1")


api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(
    authentication.router, prefix="/auth", tags=["Authentication"]
)
api_router.include_router(
    authentication_alt.router, prefix="/auth_alt", tags=["Authentication_alt"]
)
