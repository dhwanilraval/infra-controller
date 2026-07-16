import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth_routes, credentials, dashboard, discovery, events_ws,
    firmware, gpu, ipmi, machines, metrics, provisioning, tenants, tpm,
)
from app.config import settings
from app.database import init_db

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Bare-metal lifecycle management platform using Redfish",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(machines.router)
app.include_router(gpu.router)
app.include_router(ipmi.router)
app.include_router(tpm.router)
app.include_router(provisioning.router)
app.include_router(discovery.router)
app.include_router(dashboard.router)
app.include_router(credentials.router)
app.include_router(events_ws.router)
app.include_router(metrics.router)
app.include_router(tenants.router)
app.include_router(firmware.router)

if settings.ansible_enabled:
    from app.api import ansible

    app.include_router(ansible.router)


@app.on_event("startup")
async def startup():
    await init_db()
    logging.info("Infra Controller started")


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "machines": "/api/v1/machines",
            "discovery": "/api/v1/discovery",
            "dashboard": "/api/v1/dashboard/summary",
            "credentials": "/api/v1/credentials",
            "events_ws": "/ws/events",
            "events_history": "/api/v1/events/history",
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
