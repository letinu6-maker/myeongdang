"""api.py 테스트 (FastAPI TestClient) — 가이드 v4 6-5."""
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src import data_loader  # noqa: E402
from src.api import app  # noqa: E402

NOWHERE = Path(__file__).resolve().parent / "없는파일.csv"
client = TestClient(app)


@pytest.fixture(autouse=True)
def use_test_csv(monkeypatch, test_csv):
    # processed는 없고 sample만 있는 상황으로 테스트 (실제 데이터와 무관하게 항상 같은 결과)
    monkeypatch.setattr(data_loader, "PROCESSED_PATH", NOWHERE)
    monkeypatch.setattr(data_loader, "SAMPLE_PATH", test_csv)


def test_health_sample():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["data_source"] == "sample"


def test_rank_ok_has_excluded():
    body = client.get("/rank").json()
    assert body["ok"] is True and len(body["results"]) == 5
    assert all(e["active_listings"] < 50 for e in body["excluded"])


@pytest.mark.parametrize("params", [{"top_n": 0}, {"top_n": 99}, {"night_weight": 1.5},
                                    {"min_listings": -1}, {"max_listings": -1}, {"top_n": "abc"}])
def test_rank_out_of_range_400(params):
    r = client.get("/rank", params=params)
    body = r.json()
    assert r.status_code == 400 and body["ok"] is False and body["results"] == [] and body["message"]


def test_unknown_district_400():
    r = client.get("/rank", params={"districts": "99999"})
    assert r.status_code == 400 and "서울 자치구 코드가 아닙니다: 99999" in r.json()["message"]


def test_min_greater_than_max_400():
    r = client.get("/rank", params={"min_listings": 60, "max_listings": 50})
    assert r.status_code == 400 and "최소 업소 수가 최대 업소 수보다" in r.json()["message"]


def test_zero_result_200():
    # 업소 0곳인 구가 없을 때 max_listings=0 → 0건 (min_listings도 0으로 넣어야 400이 안 남)
    r = client.get("/rank", params={"min_listings": 0, "max_listings": 0})
    body = r.json()
    assert r.status_code == 200 and body["results"] == [] and "조건에 맞는 자치구가 없습니다" in body["message"]


def test_simulate_hand_calc():
    r = client.get("/simulate", params={"price": 80000, "occupancy_pct": 60,
                                        "monthly_rent": 900000, "other_cost": 300000})
    s = r.json()["results"][0]
    assert s["breakeven_nights"] == 15 and s["expected_profit"] == 240000


def test_simulate_with_district():
    r = client.get("/simulate", params={"price": 80000, "occupancy_pct": 60,
                                        "monthly_rent": 900000, "sgg_code": "11440"})
    d = r.json()["results"][0]["district"]
    assert d["sgg_name"] == "마포구" and d["median_monthly_rent"] is None


@pytest.mark.parametrize("params,text", [
    ({"price": 80000, "occupancy_pct": 150, "monthly_rent": 900000}, "가동률은 0~100"),
    ({"price": 0, "occupancy_pct": 60, "monthly_rent": 900000}, "1박 요금"),
    ({"price": 80000, "occupancy_pct": 60, "monthly_rent": -1}, "월세는"),
])
def test_simulate_out_of_range_400(params, text):
    r = client.get("/simulate", params=params)
    assert r.status_code == 400 and text in r.json()["message"]


def test_no_data_file_503(monkeypatch):
    monkeypatch.setattr(data_loader, "SAMPLE_PATH", NOWHERE)
    r = client.get("/rank")
    assert r.status_code == 503 and r.json()["ok"] is False
