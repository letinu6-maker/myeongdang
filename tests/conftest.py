import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import data_loader  # noqa: E402


@pytest.fixture
def small_df():
    """3~4행짜리 작은 표 (가이드 v4 6-5: 0 나누기 테스트는 테스트 안에서 작은 표로)."""
    return pd.DataFrame({
        "sgg_code": ["11110", "11140", "11545", "11650"],
        "sgg_name": ["종로구", "중구", "금천구", "서초구"],
        "night_foreigners": [1200.0, 3000.0, 500.0, 2000.0],
        "day_foreigners": [3000.0, 8000.0, 900.0, 4000.0],
        "active_listings": [60, 200, 0, 80],
        "data_as_of": ["TEST"] * 4,
    })


@pytest.fixture
def test_csv(tmp_path):
    """API 테스트용 25행 CSV (모든 구 업소 1곳 이상). 실제 데이터 아님, 저장소에 올리지 않음."""
    rows = []
    for i, (code, name) in enumerate(data_loader.SEOUL_DISTRICTS.items()):
        rows.append({
            "sgg_code": code, "sgg_name": name,
            "night_foreigners": 500 + i * 100, "day_foreigners": 1000 + i * 150,
            "active_listings": 10 + i * 20, "rooms_known_listings": 5 + i,
            "rooms_known_sum": 20 + i * 3, "data_as_of": "TEST - 테스트용",
        })
    path = tmp_path / "district_summary.csv"
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    return path
