import hashlib
import hmac
import re
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()
SECRET = Path("/run/secrets/warning_integration")
WARNING_URL = "http://warning:3000"
PUBLIC_API = {
    "GET": re.compile(r"me|alerts(?:/[0-9]+)?"),
    "POST": re.compile(r"alerts/[0-9]+/read|notifications/claim"),
}
ADMIN_API = re.compile(r"admin/(?:overview|jobs(?:/[0-9]+)?|news(?:/[0-9]+/retry)?|failures(?:/[0-9]+/retry)?|collect|alerts(?:/[0-9]+/withdraw)?|config|model/test)")
ADMIN_VIEWS = {"overview", "news", "alerts", "settings"}


async def forward(request: Request, path: str):
    try:
        secret = SECRET.read_bytes().strip()
    except OSError:
        raise HTTPException(503, "预警服务尚未配置。") from None
    if len(secret) < 32:
        raise HTTPException(503, "预警服务尚未配置。")
    user = request.state.user
    identity = f"{user['id']}:{user['role']}:{int(time.time())}"
    signature = hmac.new(secret, identity.encode(), hashlib.sha256).hexdigest()
    headers = {"X-Warning-Identity": identity, "X-Warning-Signature": signature}
    if "content-type" in request.headers:
        headers["Content-Type"] = request.headers["content-type"]
    try:
        async with httpx.AsyncClient(timeout=105, trust_env=False) as client:
            upstream = await client.request(
                request.method, WARNING_URL + path, headers=headers,
                params=request.query_params.multi_items(), content=await request.body(),
            )
    except httpx.RequestError:
        raise HTTPException(502, "预警服务暂时不可用。") from None
    response_headers = {
        key: value for key, value in upstream.headers.items()
        if key in {"content-type", "content-security-policy", "x-frame-options", "x-content-type-options"}
    }
    response_headers["cache-control"] = "no-store"
    return Response(upstream.content, status_code=upstream.status_code, headers=response_headers)


@router.api_route("/api/warning/{path:path}", methods=["GET", "POST", "PUT"])
async def warning_api(path: str, request: Request):
    public = PUBLIC_API.get(request.method)
    if ADMIN_API.fullmatch(path):
        if request.state.user["role"] != "admin":
            raise HTTPException(403, "需要管理员权限。")
    elif not public or not public.fullmatch(path):
        raise HTTPException(404, "预警接口不存在。")
    return await forward(request, "/api/" + path)


@router.get("/api/warning-ui/{asset:path}")
async def warning_ui(asset: str, request: Request):
    if not asset:
        view = request.query_params.get("view", "dashboard")
        if view in ADMIN_VIEWS and request.state.user["role"] != "admin":
            raise HTTPException(403, "需要管理员权限。")
        if view != "dashboard" and view not in ADMIN_VIEWS:
            raise HTTPException(404, "预警页面不存在。")
    elif not re.fullmatch(r"assets/[a-zA-Z0-9_.-]+", asset):
        raise HTTPException(404, "预警资源不存在。")
    return await forward(request, "/" + asset)
