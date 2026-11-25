"""실제 데이터 검증 (가이드 v4 6-5, 10절). data/processed/district_summary.csv가 있을 때만 실행."""
import pandas as pd
import pytest

from src import data_loader, scoring

if not data_loader.PROCESSED_PATH.exists():
    pytest.skip("실제 CSV(data/processed)가 없어 건너뜁니다. git pull 후 다시 실행하세요.",
                allow_module_level=True)

df = data_loader.load_data().df


def test_25_rows_and_total_listings():
    assert len(df) == 25
    assert int(df["active_listings"].sum()) == 7833


def test_default_geumcheon_excluded():
    ranked, excluded = scoring.rank(df)
    assert "11545" not in set(ranked["sgg_code"])
    assert "11545" in set(excluded["sgg_code"])


def test_default_first_is_seocho():
    ranked, _ = scoring.rank(df)
    assert ranked.iloc[0]["sgg_code"] == "11650"


def test_min_listings_0_geumcheon_first():
    ranked, _ = scoring.rank(df, min_listings=0)
    assert ranked.iloc[0]["sgg_code"] == "11545"


def test_sample_equals_processed():
    if not data_loader.SAMPLE_PATH.exists():
        pytest.fail("data/sample/district_summary.csv가 없습니다. processed 파일을 복사해 주세요.")
    sample = pd.read_csv(data_loader.SAMPLE_PATH, dtype={"sgg_code": str})
    processed = pd.read_csv(data_loader.PROCESSED_PATH, dtype={"sgg_code": str})
    pd.testing.assert_frame_equal(sample, processed)
