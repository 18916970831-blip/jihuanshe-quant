import os

from fastapi import Request

LOCAL_HOSTS = {"127.0.0.1", "::1"}


def share_enabled() -> bool:
    return os.environ.get("QUANT_SHARE") == "1"


def is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOCAL_HOSTS


def is_readonly(request: Request) -> bool:
    """Guests on the shared address can read. This computer can still edit."""
    if not share_enabled():
        return False
    token = os.environ.get("QUANT_API_TOKEN")
    if token and request.headers.get("authorization") == f"Bearer {token}":
        return False
    return not is_local(request)
