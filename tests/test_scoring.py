"""scoring.py 테스트 — 발표에서 '계산이 맞는지 이렇게 확인했다'의 근거."""
import pytest

from src import scoring


def test_hand_calc_breakeven():
    # 손계산 (가이드 10절): 1박 80,000원, 가동률 60%, 월세 900,000원, 기타 300,000원
    # 월 비용 1,200,000 ÷ 80,000 = 15일 / 80,000 × 30 × 0.6 − 1,200,000 = 240,000원
    s = scoring.simulate(price=80_000, occupancy_pct=60, monthly_rent=900_000, other_cost=300_000)
    assert s["monthly_cost"] == 1_200_000
    assert s["breakeven_nights"] == 15
    assert s["expected_profit"] == 240_000


def test_hand_calc_location(small_df):
    # 손계산 (가이드 10절): 야간 1,200, 주간 3,000, 업소 60곳, 가중치 0.7
    # 수요 = 0.7×1,200 + 0.3×3,000 = 1,740 / 업소당 수요 = 1,740 ÷ 60 = 29.0
    m = scoring.add_metrics(small_df, 0.7)
    r = m[m["sgg_code"] == "11110"].iloc[0]
    assert r["demand"] == pytest.approx(1740)
    assert r["demand_per_listing"] == pytest.approx(29.0)


def test_zero_listings_no_error(small_df):
    m = scoring.add_metrics(small_df)
    zero = m[m["active_listings"] == 0].iloc[0]
    assert zero["no_competition"]
    assert zero["demand_per_listing"] == zero["demand"]   # ÷1로 계산
    ranked, _ = scoring.rank(small_df, min_listings=0)
    assert ranked["score"].notna().all()


def test_weight_0_and_1(small_df):
    w0 = scoring.add_metrics(small_df, 0)
    w1 = scoring.add_metrics(small_df, 1)
    assert (w0["demand"] == small_df["day_foreigners"]).all()
    assert (w1["demand"] == small_df["night_foreigners"]).all()


def test_one_district_left_z_safe(small_df):
    ranked, _ = scoring.rank(small_df, districts=["11140"], min_listings=0)
    assert len(ranked) == 1 and ranked.iloc[0]["score"] == 0


def test_min_listings_excludes_thin_market(small_df):
    ranked, excluded = scoring.rank(small_df, min_listings=50)
    assert "11545" not in set(ranked["sgg_code"])     # 업소 0곳 → 검증 부족 시장
    assert "11545" in set(excluded["sgg_code"])


def test_z_after_filter(small_df):
    # 필터 후 남은 구만으로 z → 남은 구들의 점수 평균은 0
    ranked, _ = scoring.rank(small_df, min_listings=50, top_n=25)
    assert ranked["score"].mean() == pytest.approx(0, abs=1e-3)


def test_min_greater_than_max():
    assert scoring.listing_range_error(60, 50) == scoring.MSG_MIN_GT_MAX
    assert scoring.listing_range_error(50, 60) is None
    assert scoring.listing_range_error(50, None) is None


def test_zero_result(small_df):
    ranked, _ = scoring.rank(small_df, min_listings=0, max_listings=-1)
    assert ranked.empty


def test_breakeven_rounds_up_and_over_month():
    s = scoring.simulate(price=30_000, occupancy_pct=100, monthly_rent=1_000_000)
    assert s["breakeven_nights"] == 34 and s["over_month"] and s["is_loss"]


def test_price_0_raises():
    with pytest.raises(ValueError):
        scoring.simulate(price=0, occupancy_pct=60, monthly_rent=900_000)
