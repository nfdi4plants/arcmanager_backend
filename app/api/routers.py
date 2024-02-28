from fastapi import APIRouter


from app.api.endpoints import projects, authentication, validation


api_router = APIRouter(prefix="/arcmanager/api/v1")


api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(
    authentication.router, prefix="/auth", tags=["Authentication"]
)
api_router.include_router(validation.router, prefix="/validate", tags=["Validation"])
