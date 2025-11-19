# src/pclink/api_server/control_api.py
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2025 AZHAR ZOUHIR / BYTEDz

from fastapi import FastAPI, APIRouter


def create_control_api(controller, shutdown_callback):
    """Creates the FastAPI application for the internal control API."""
    control_app = FastAPI()
    router = APIRouter()

    @router.get("/status")
    def get_status():
        return controller.get_status()

    @router.post("/stop")
    def stop_server():
        controller.shutdown()
        return {"message": "PCLink is shutting down."}

    @router.post("/restart")
    def restart_server():
        controller.restart()
        return {"message": "PCLink is restarting."}

    @router.get("/web-url")
    def get_web_url():
        return {"url": controller.get_web_ui_url()}

    @router.get("/qr-data")
    def get_qr_data():
        """Get QR code data for pairing."""
        qr_data = controller.get_qr_data()
        if qr_data:
            return {"qr_data": qr_data}
        return {"error": "QR data not available"}

    control_app.include_router(router)
    return control_app