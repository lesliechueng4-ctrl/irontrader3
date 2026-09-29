"""
统一的 API 响应格式。

成功：{"success": true, "data": <任意>, "meta": {...可选：as_of / stale / cached / count ...}}
失败：{"success": false, "error": "<可读中文>", "error_code": "<可选机器码>"}

与 exceptions.py 里 IronTraderError.to_dict() 的失败格式一致。
数据时效等附加信息一律放在 meta 里；个别旧接口为兼容旧版界面仍在顶层保留同名字段（见各路由注释）。
"""

from typing import Any, Optional

from flask import jsonify


def ok(data: Any = None, *, status: int = 200, meta: Optional[dict] = None, **legacy_top_level: Any):
    body = {"success": True, "data": data}
    if meta:
        body["meta"] = meta
    # 仅供过渡期兼容旧版前端：顶层重复一份字段，新代码请读 meta
    body.update(legacy_top_level)
    return jsonify(body), status


def fail(error: Any, *, status: int = 400, code: Optional[str] = None, **extra: Any):
    body = {"success": False, "error": str(error)}
    if code:
        body["error_code"] = code
    body.update(extra)
    return jsonify(body), status
