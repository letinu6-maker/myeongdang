"""계산 모듈 (B 담당) — 가이드 v4 6-1. API(api.py)와 화면(app.py)이 둘 다 이 파일을 쓴다.

- 경쟁 지표는 객실 수가 아니라 영업 중 업소 수(active_listings)
- 업소가 min_listings(기본 50) 미만인 구는 '검증 부족 시장'으로 순위에서 빼고 excluded로 돌려준다
- z점수는 필터를 적용한 뒤 남은 구만으로 계산한다 (극단값이 다른 구 점수를 왜곡하지 않게)
- 손익분기는 사용자가 입력한 월세·기타 비용으로만 계산한다
"""
import math
from typing import Iterable, Optional

import pandas as pd

DEFAULT_NIGHT_WEIGHT = 0.7
DEFAULT_MIN_LISTINGS = 50
W_PER_LISTING = 0.6
W_DEMAND = 0.4
CAUTION_QUANTILE = 0.75   # 주간 외국인 25개 구 중 상위 25% → 미등록 숙소 주의

MSG_NO_RESULT = "조건에 맞는 자치구가 없습니다. 경쟁 업소 수 상한을 높여 보세요."
MSG_MIN_GT_MAX = "최소 업소 수가 최대 업소 수보다 클 수 없습니다."
MSG_OVER_MONTH = "한 달 내내 차도 적자입니다. 1박 요금을 올리거나 비용을 줄여야 합니다."

RESULT_COLUMNS = ["rank", "sgg_code", "sgg_name", "score", "demand", "demand_per_listing",
                  "night_foreigners", "day_foreigners", "active_listings", "no_competition", "caution"]
EXCLUDED_COLUMNS = ["sgg_code", "sgg_name", "active_listings", "demand_per_listing"]


def zscore(s: pd.Series) -> pd.Series:
    """모표준편차(ddof=0)로 표준화. 남은 구가 1개이거나 표준편차 0이면 0."""
    if len(s) < 2:
        return pd.Series(0.0, index=s.index)
    std = s.std(ddof=0)
    if not std or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def add_metrics(df: pd.DataFrame, night_weight: float = DEFAULT_NIGHT_WEIGHT) -> pd.DataFrame:
    """수요·업소당 수요·주의 표시를 붙인다. caution은 25개 구 전체 기준."""
    out = df.copy()
    w = min(max(float(night_weight), 0.0), 1.0)
    night = out["night_foreigners"].fillna(0)
    day = out["day_foreigners"].fillna(0)
    listings = out["active_listings"].fillna(0)

    out["demand"] = w * night + (1 - w) * day
    out["no_competition"] = listings <= 0
    out["demand_per_listing"] = out["demand"] / listings.where(listings > 0, 1)  # 0곳이면 ÷1
    out["caution"] = day >= day.quantile(CAUTION_QUANTILE)
    return out


def listing_range_error(min_listings: Optional[int], max_listings: Optional[int]) -> Optional[str]:
    """최소 업소 수 > 최대 업소 수이면 안내 문구, 아니면 None."""
    if min_listings is not None and max_listings is not None and min_listings > max_listings:
        return MSG_MIN_GT_MAX
    return None


def rank(df: pd.DataFrame, night_weight: float = DEFAULT_NIGHT_WEIGHT,
         min_listings: int = DEFAULT_MIN_LISTINGS, max_listings: Optional[int] = None,
         districts: Optional[Iterable[str]] = None, top_n: int = 5):
    """반환: (순위 DataFrame, 검증 부족 시장 DataFrame). 0건이면 빈 DataFrame."""
    m = add_metrics(df, night_weight)
    if districts:
        m = m[m["sgg_code"].isin([str(c) for c in districts])].copy()

    min_listings = 0 if min_listings is None else int(min_listings)
    m["thin_market"] = m["active_listings"] < min_listings
    excluded = m[m["thin_market"]].sort_values("demand_per_listing", ascending=False)

    pool = m[~m["thin_market"]].copy()
    if max_listings is not None:
        pool = pool[pool["active_listings"] <= max_listings].copy()

    # 필터 후 남은 구만으로 z점수
    pool["score"] = W_PER_LISTING * zscore(pool["demand_per_listing"]) + W_DEMAND * zscore(pool["demand"])
    pool = pool.sort_values("score", ascending=False).head(max(int(top_n), 0))
    pool.insert(0, "rank", range(1, len(pool) + 1))

    ranked = pool[RESULT_COLUMNS].round({"score": 3, "demand": 1, "demand_per_listing": 1})
    excluded = excluded[EXCLUDED_COLUMNS].round({"demand_per_listing": 1})
    return ranked.reset_index(drop=True), excluded.reset_index(drop=True)


def simulate(price: float, occupancy_pct: float, monthly_rent: float, other_cost: float = 0) -> dict:
    """1객실 손익분기.
    monthly_cost     = 월세 + 기타 비용
    breakeven_nights = ceil(monthly_cost ÷ 1박 요금). 30 초과면 '한 달 내내 차도 적자'
    expected_profit  = 1박 요금 × 30 × (가동률 ÷ 100) − monthly_cost
    """
    if price is None or price <= 0:
        raise ValueError("1박 요금은 1~2,000,000원 사이로 입력해 주세요.")
    occ = min(max(float(occupancy_pct), 0.0), 100.0)
    monthly_cost = float(monthly_rent) + float(other_cost)
    breakeven_nights = math.ceil(monthly_cost / price)
    revenue = price * 30 * occ / 100
    profit = revenue - monthly_cost
    return {
        "monthly_cost": round(monthly_cost),
        "breakeven_nights": breakeven_nights,
        "breakeven_occupancy_pct": round(breakeven_nights / 30 * 100, 1),
        "over_month": breakeven_nights > 30,
        "expected_nights": round(30 * occ / 100, 1),
        "expected_revenue": round(revenue),
        "expected_profit": round(profit),
        "is_loss": profit < 0,
    }


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def district_info(df: pd.DataFrame, sgg_code: str, night_weight: float = DEFAULT_NIGHT_WEIGHT) -> Optional[dict]:
    """선택한 구의 수요·경쟁 정보. 객실 수·월세는 참고값(없으면 None)."""
    m = add_metrics(df, night_weight)
    row = m[m["sgg_code"] == str(sgg_code)]
    if row.empty:
        return None
    r = row.iloc[0]
    rooms_known = _num(r.get("rooms_known_listings"))
    rooms_sum = _num(r.get("rooms_known_sum"))
    rent = _num(r.get("median_monthly_rent"))
    return {
        "sgg_code": r["sgg_code"],
        "sgg_name": r["sgg_name"],
        "night_foreigners": round(float(r["night_foreigners"]), 1),
        "day_foreigners": round(float(r["day_foreigners"]), 1),
        "active_listings": int(r["active_listings"]),
        "demand_per_listing": round(float(r["demand_per_listing"]), 1),
        "rooms_known_listings": None if rooms_known is None else int(rooms_known),
        "rooms_known_sum": None if rooms_sum is None else int(rooms_sum),
        "median_monthly_rent": None if rent is None else int(rent),
        "caution": bool(r["caution"]),
    }
