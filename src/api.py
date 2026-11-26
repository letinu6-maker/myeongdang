"""FastAPI 서버 (B 담당) — 가이드 v4 6-3.

실행(저장소 최상위 폴더에서):  uvicorn src.api:app --reload --port 8000
문서 화면:                     http://localhost:8000/docs
"""
import json
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src import data_loader, scoring

app = FastAPI(title="명당발견 API", description="외국인 관광객 숙소 입지·손익분기 가이드")

# 범위 밖 값 → FastAPI 기본 422(영어) 대신 400 + 한국어 안내
FIELD_MESSAGES = {
    "night_weight": "야간 가중치는 0~1 사이로 입력해 주세요.",
    "min_listings": "최소 업소 수는 0 이상의 정수로 입력해 주세요.",
    "max_listings": "경쟁 업소 수 상한은 0 이상의 정수로 입력해 주세요.",
    "top_n": "표시 개수는 1~25 사이로 입력해 주세요.",
    "price": "1박 요금은 1~2,000,000원 사이로 입력해 주세요.",
    "occupancy_pct": "가동률은 0~100 사이로 입력해 주세요.",
    "monthly_rent": "월세는 0~10,000,000원 사이로 입력해 주세요.",
    "other_cost": "월 기타 비용은 0 이상으로 입력해 주세요.",
}


def fail(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "message": message, "results": []})


def records(df) -> list:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def parse_districts(text: Optional[str]) -> list:
    """'11440,11140' → ['11440', '11140']"""
    return [c.strip() for c in (text or "").split(",") if c.strip()]


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    messages = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        name = str(loc[-1]) if loc else ""
        if err.get("type") == "missing":
            msg = f"필수 입력값이 빠졌습니다: {name}"
        else:
            msg = FIELD_MESSAGES.get(name, f"입력값을 확인해 주세요: {name}")
        if msg not in messages:
            messages.append(msg)
    return fail(400, " / ".join(messages))


@app.exception_handler(Exception)
async def unexpected_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"ok": False, "message": f"서버 내부 오류: {exc}", "results": []})


@app.get("/health")
def health():
    loaded = data_loader.load_data()
    return {
        "ok": loaded.df is not None,
        "data_source": loaded.source,
        "data_as_of": loaded.data_as_of,
        "rows": 0 if loaded.df is None else len(loaded.df),
        "warnings": loaded.warnings,
    }


@app.get("/districts")
def districts():
    results = [{"sgg_code": c, "sgg_name": n} for c, n in data_loader.SEOUL_DISTRICTS.items()]
    return {"ok": True, "message": "", "results": results}


@app.get("/rank")
def rank(
    night_weight: float = Query(0.7, ge=0, le=1, description="야간 가중치 0~1"),
    min_listings: int = Query(50, ge=0, description="최소 업소 수 (미만이면 검증 부족 시장)"),
    max_listings: Optional[int] = Query(None, ge=0, description="경쟁 업소 수 상한"),
    districts: Optional[str] = Query(None, description="자치구 코드, 쉼표 구분 (예: 11440,11650)"),
    top_n: int = Query(5, ge=1, le=25, description="표시 개수 1~25"),
):
    codes = parse_districts(districts)
    bad = [c for c in codes if c not in data_loader.SEOUL_DISTRICTS]
    if bad:
        return fail(400, f"서울 자치구 코드가 아닙니다: {', '.join(bad)}")
    range_error = scoring.listing_range_error(min_listings, max_listings)
    if range_error:
        return fail(400, range_error)

    loaded = data_loader.load_data()
    if loaded.df is None:
        return fail(503, "데이터 파일을 찾을 수 없습니다. 서버는 켜져 있으니 data/sample을 확인해 주세요.")

    ranked, excluded = scoring.rank(loaded.df, night_weight, min_listings, max_listings, codes, top_n)
    return {
        "ok": True,
        "message": scoring.MSG_NO_RESULT if ranked.empty else "",
        "data_source": loaded.source,
        "data_as_of": loaded.data_as_of,
        "results": records(ranked),
        "excluded": records(excluded),
    }


@app.get("/simulate")
def simulate(
    price: int = Query(..., ge=1, le=2_000_000, description="1박 요금(원)"),
    occupancy_pct: float = Query(..., ge=0, le=100, description="예상 가동률(%)"),
    monthly_rent: int = Query(..., ge=0, le=10_000_000, description="월세(원)"),
    other_cost: int = Query(0, ge=0, description="월 기타 비용(원)"),
    sgg_code: Optional[str] = Query(None, description="자치구 코드(선택)"),
):
    code = (sgg_code or "").strip()
    if code and code not in data_loader.SEOUL_DISTRICTS:
        return fail(400, f"서울 자치구 코드가 아닙니다: {code}")

    result = scoring.simulate(price, occupancy_pct, monthly_rent, other_cost)
    messages = [scoring.MSG_OVER_MONTH] if result["over_month"] else []

    loaded = data_loader.load_data()
    result["district"] = None
    if code:
        if loaded.df is None:
            messages.append("데이터 파일이 없어 자치구 정보는 보여 줄 수 없습니다.")
        else:
            result["district"] = scoring.district_info(loaded.df, code)

    return {
        "ok": True,
        "message": " ".join(messages),
        "data_source": loaded.source,
        "data_as_of": loaded.data_as_of,
        "results": [result],
    }
