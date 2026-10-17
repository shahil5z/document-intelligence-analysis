from fastapi import APIRouter

from app.api.routes import admin, audit_logs, auth, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(audit_logs.router)
api_router.include_router(admin.router)
