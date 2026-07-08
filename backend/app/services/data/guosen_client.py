"""国信 HTTP client — 从 skill get_data.py 移植的请求封装.

调 https://dgzt.guosen.com.cn/skills/{endpoint},带 apiKey + softName.
注意: 国信历史行情接口 queryPastHQInfo 只能取"近N个交易日"(非日期范围),
且 setCode 标识市场. 因此国信作为 secondary 源,适合指数/ETF 近端补数,
不适合全量历史回填(全量回填由 akshare 主导).

异常策略: 鉴权失败/限免过期/网络异常 → 抛 GuosenError,供 registry 切回主源.
"""
from __future__ import annotations

import ssl
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from app.config import settings

SOFT_NAME = "agent_skills"
TIMEOUT_SECONDS = 15

# 市场代码 (来自 skill SET_CODE_MAP)
SET_CODE = {
    "SZ": 0,   # 深圳
    "SH": 1,   # 上海
    "BJ": 2,   # 北交所
    "HK": -1,  # 港股
    "US": 74,  # 美股
}


class GuosenError(RuntimeError):
    """国信源不可用 (鉴权失败/限免过期/网络异常)."""


def _ssl_context() -> ssl.SSLContext | None:
    """旧服务器兼容 (skill 同款): 允许 legacy renegotiation + 弱密码套件."""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("ALL:@SECLEVEL=0")
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        except Exception:
            pass
        return ctx
    except Exception:
        return None


def _make_request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    if not settings.gs_api_key:
        raise GuosenError("GS_API_KEY 未配置,国信备用源不可用")
    url = f"{settings.gs_api_base}/{endpoint.lstrip('/')}"
    full = f"{url}?{urllib_parse.urlencode(params)}"
    ctx = _ssl_context()
    try:
        req = urllib_request.Request(full)
        opener_kwargs = {"context": ctx, "timeout": TIMEOUT_SECONDS} if ctx else {"timeout": TIMEOUT_SECONDS}
        with urllib_request.urlopen(req, **opener_kwargs) as resp:
            import json
            return json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as e:
        raise GuosenError(f"国信 HTTP {e.code}: 鉴权/限免可能失效") from e
    except (urllib_error.URLError, TimeoutError) as e:
        raise GuosenError(f"国信网络异常: {e}") from e


def query_past_hq(code: str, set_code: int, want_nums: int, target: int = 0, mas: str | None = None) -> dict[str, Any]:
    """近 N 个交易日日行情."""
    params: dict[str, Any] = {
        "code": code,
        "setCode": str(set_code),
        "wantNums": str(want_nums),
        "target": target,
        "softName": SOFT_NAME,
        "apiKey": settings.gs_api_key,
    }
    if mas:
        params["mas"] = mas
    return _make_request("gsnews/market/agentbot/queryPastHQInfo/1.0", params)
