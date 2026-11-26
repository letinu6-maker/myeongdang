"""CSV 로드 모듈 (B 담당) — 가이드 v4 6-2.

- data/processed/district_summary.csv(A가 만든 실제 데이터)가 있으면 그걸 읽고,
  없거나 쓸 수 없으면 data/sample/district_summary.csv를 읽는다.
- 어느 파일을 읽었는지(source)와 기준 시점(data_as_of)을 함께 돌려준다.
- 문제가 있어도 예외를 던지지 않고 warnings에 한국어 메시지를 담는다.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_PATH = ROOT / "data" / "processed" / "district_summary.csv"
SAMPLE_PATH = ROOT / "data" / "sample" / "district_summary.csv"

# 없으면 계산이 불가능한 컬럼
REQUIRED_COLUMNS = ["sgg_code", "sgg_name", "night_foreigners", "day_foreigners",
                    "active_listings", "data_as_of"]
# 참고용 컬럼: 없어도 동작 (rooms_known_*는 상세 화면 참고값, median_monthly_rent는 2차 전월세)
OPTIONAL_COLUMNS = ["rooms_known_listings", "rooms_known_sum", "median_monthly_rent"]
NUMERIC_COLUMNS = ["night_foreigners", "day_foreigners", "active_listings"]

SEOUL_DISTRICTS = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}


@dataclass
class LoadResult:
    df: Optional[pd.DataFrame]   # 못 읽었으면 None
    source: str                   # "processed" | "sample" | "none"
    data_as_of: str = ""
    warnings: list = field(default_factory=list)


def _read_one(path: Path):
    """파일 하나를 읽고 검사한다. 반환: (df 또는 None, 경고 목록)"""
    warnings = []
    try:
        df = pd.read_csv(path, dtype={"sgg_code": str}, encoding="utf-8")
    except Exception as e:
        return None, [f"{path.name}을(를) 읽지 못했습니다: {e}"]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return None, [f"{path.name}에 필수 컬럼이 없습니다: {', '.join(missing)}"]

    df["sgg_code"] = df["sgg_code"].astype(str).str.strip()
    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].isna().any():
            warnings.append(f"{col}에 빈 값이 있어 0으로 처리했습니다.")
        df[col] = df[col].fillna(0).clip(lower=0)
    for col in OPTIONAL_COLUMNS:  # 없으면 빈 칸으로 만들어 둔다 (계산에는 안 씀)
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df.columns else float("nan")

    if len(df) != 25:
        warnings.append(f"자치구 행 수가 25가 아닙니다 (현재 {len(df)}행).")
    unknown = sorted(set(df["sgg_code"]) - set(SEOUL_DISTRICTS))
    if unknown:
        warnings.append(f"서울 자치구 코드가 아닌 값이 있습니다: {', '.join(unknown)}")
    return df, warnings


def load_data(processed_path: Optional[Path] = None, sample_path: Optional[Path] = None) -> LoadResult:
    processed_path = Path(processed_path or PROCESSED_PATH)
    sample_path = Path(sample_path or SAMPLE_PATH)
    warnings = []

    if processed_path.exists():
        df, w = _read_one(processed_path)
        warnings += w
        if df is not None:
            return LoadResult(df, "processed", _as_of(df), warnings)
        warnings.append("정리된 데이터를 쓸 수 없어 샘플 데이터로 대체합니다.")

    if sample_path.exists():
        df, w = _read_one(sample_path)
        warnings += w
        if df is not None:
            return LoadResult(df, "sample", _as_of(df), warnings)

    warnings.append("데이터 파일이 없습니다. data/sample/district_summary.csv를 확인해 주세요.")
    return LoadResult(None, "none", "", warnings)


def _as_of(df: pd.DataFrame) -> str:
    values = df["data_as_of"].dropna().astype(str).unique()
    return values[0] if len(values) else ""
