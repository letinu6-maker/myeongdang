"""data_loader.py 테스트."""
from pathlib import Path

from src import data_loader

NOWHERE = Path(__file__).resolve().parent / "없는파일.csv"


def test_processed_missing_uses_sample(test_csv):
    loaded = data_loader.load_data(processed_path=NOWHERE, sample_path=test_csv)
    assert loaded.source == "sample" and len(loaded.df) == 25
    assert loaded.df["sgg_code"].map(type).eq(str).all()


def test_no_file_does_not_crash():
    loaded = data_loader.load_data(processed_path=NOWHERE, sample_path=NOWHERE)
    assert loaded.df is None and loaded.source == "none" and loaded.warnings


def test_missing_column_falls_back(tmp_path, test_csv):
    bad = tmp_path / "bad.csv"
    bad.write_text("sgg_code,sgg_name\n11440,마포구\n", encoding="utf-8")
    loaded = data_loader.load_data(processed_path=bad, sample_path=test_csv)
    assert loaded.source == "sample"
    assert any("필수 컬럼" in w for w in loaded.warnings)


def test_works_without_median_monthly_rent(test_csv):
    loaded = data_loader.load_data(processed_path=test_csv)
    assert loaded.source == "processed"
    assert loaded.df["median_monthly_rent"].isna().all()   # 컬럼이 없어도 동작
