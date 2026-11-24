"""
수집한 원본을 정리·결합해 data/processed/district_summary.csv (자치구 25행)를 만들고,
단계별 건수를 reports/count_check_auto.md 에 기록합니다.

입력:
  data/raw/minbak_raw.csv              (collect.py 결과)
  data/raw/population/*.csv            ([단기외국인] 행정동별 서울 생활인구 월별 zip을 풀어 넣은 CSV)
실행:
  python src/clean.py
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "district_summary.csv"
REPORT = ROOT / "reports" / "count_check_auto.md"

NIGHT_HOURS = range(0, 6)    # 0~5시: 숙박 수요
DAY_HOURS = range(10, 18)    # 10~17시: 관광 수요

SGG = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}
NAME_TO_CODE = {v: k for k, v in SGG.items()}

log = []  # 건수 검증 기록


def note(stage, item, value, how=""):
    log.append((stage, item, value, how))
    print(f"[{stage}] {item}: {value} {('- ' + how) if how else ''}")


def read_csv_any(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 알 수 없습니다: {path}")


def pick(cols, *keywords):
    """컬럼 이름에 키워드가 들어 있는 첫 컬럼을 찾습니다 (대소문자 무시)."""
    for kw in keywords:
        for c in cols:
            if kw.lower() in c.lower():
                return c
    return None


# ---------------------------------------------------------------- 도시민박업
def clean_minbak() -> pd.DataFrame:
    path = RAW / "minbak_raw.csv"
    if not path.exists():
        sys.exit(f"{path} 가 없습니다. 먼저 python src/collect.py 를 실행하세요.")
    df = read_csv_any(path)
    note("도시민박업", "원본 행 수", len(df))

    # 중복 제거 (관리번호 기준)
    id_col = pick(df.columns, "MGTNO", "관리번호")
    if id_col:
        before = len(df)
        df = df.drop_duplicates(subset=id_col)
        note("도시민박업", "중복 제거", before - len(df), f"{id_col} 기준")

    # 영업 중만 남기기
    st_col = pick(df.columns, "TRDSTATENM", "영업상태명")
    if st_col is None:
        sys.exit(f"영업상태 컬럼을 찾지 못했습니다. 컬럼 목록: {list(df.columns)}")
    print("영업상태 값 분포:\n", df[st_col].value_counts(dropna=False).to_string())
    active_mask = df[st_col].fillna("").str.contains("영업|정상")
    note("도시민박업", "폐업·취소 등 제거", int((~active_mask).sum()), f"{st_col}에 '영업/정상'이 없는 행")
    df = df[active_mask].copy()
    note("도시민박업", "영업 중", len(df))

    # 주소에서 자치구 추출 (도로명 주소 우선, 없으면 지번 주소)
    road = pick(df.columns, "RDNWHLADDR", "도로명")
    jibun = pick(df.columns, "SITEWHLADDR", "지번", "소재지")
    addr = df[road].fillna("") if road else pd.Series("", index=df.index)
    if jibun:
        addr = addr.where(addr.str.strip() != "", df[jibun].fillna(""))
    df["sgg_name"] = addr.str.extract(r"서울특별시\s+(\S+?구)")[0]
    df["sgg_code"] = df["sgg_name"].map(NAME_TO_CODE)
    fail = df["sgg_code"].isna()
    note("도시민박업", "자치구 매칭 성공", int((~fail).sum()))
    note("도시민박업", "자치구 매칭 실패", int(fail.sum()), "주소가 비었거나 서울 자치구가 아님")
    if fail.any():
        df[fail].to_csv(RAW / "minbak_unmatched.csv", index=False, encoding="utf-8-sig")
        print(f"  매칭 실패 행은 {RAW / 'minbak_unmatched.csv'} 에 저장했습니다.")
    df = df[~fail]

    # 객실 수 (컬럼이 없으면 업소당 1실로 계산하고 기록)
    room_col = pick(df.columns, "객실", "ROOM")
    if room_col:
        df["rooms"] = pd.to_numeric(df[room_col], errors="coerce")
        miss = int(df["rooms"].isna().sum())
        note("도시민박업", "객실수 결측", miss, f"{room_col} 컬럼, 결측은 1실로 계산")
        df["rooms"] = df["rooms"].fillna(1)
    else:
        note("도시민박업", "객실수 컬럼 없음", "-", "업소당 1실로 계산")
        df["rooms"] = 1

    g = df.groupby("sgg_code").agg(active_listings=("sgg_code", "size"), active_rooms=("rooms", "sum")).reset_index()
    return g


# ---------------------------------------------------------------- 생활인구
def clean_population() -> pd.DataFrame:
    files = sorted((RAW / "population").glob("*.csv"))
    if not files:
        sys.exit(f"{RAW / 'population'} 에 생활인구 CSV가 없습니다. 월별 zip을 풀어 넣어 주세요.")
    df = pd.concat([read_csv_any(f) for f in files], ignore_index=True)
    note("생활인구", "원본 행 수", len(df), f"파일 {len(files)}개")
    print("생활인구 컬럼:", list(df.columns))

    dong_col = pick(df.columns, "행정동코드", "ADSTRD")
    hour_col = pick(df.columns, "시간대", "TMZON")
    val_col = pick(df.columns, "총생활인구", "TOT_LVPOP", "생활인구")
    date_col = pick(df.columns, "기준일", "STDR_DE")
    if not all([dong_col, hour_col, val_col]):
        sys.exit(f"필요한 컬럼(행정동코드/시간대/생활인구)을 찾지 못했습니다: {list(df.columns)}")

    df["val"] = pd.to_numeric(df[val_col].str.replace("*", "", regex=False), errors="coerce")
    masked = int(df["val"].isna().sum())
    note("생활인구", "값이 '*' 또는 비어 있는 칸", masked, "소수 인원 비공개 처리 칸. 0으로 계산")
    df["val"] = df["val"].fillna(0)

    df["hour"] = pd.to_numeric(df[hour_col], errors="coerce")
    df["sgg_code"] = df[dong_col].str.strip().str[:5]
    n_dong = df[dong_col].nunique()
    bad = ~df["sgg_code"].isin(SGG)
    note("생활인구", "행정동 수", n_dong)
    note("생활인구", "자치구 매칭 실패 행", int(bad.sum()), "행정동코드 앞 5자리가 서울 자치구 코드가 아님")
    df = df[~bad]

    keys = ["sgg_code", "hour"] + ([date_col] if date_col else [])
    by_hour = df.groupby(keys)["val"].sum().reset_index()  # 날짜·시간대별 자치구 합계
    night = by_hour[by_hour["hour"].isin(NIGHT_HOURS)].groupby("sgg_code")["val"].mean().rename("night_foreigners")
    day = by_hour[by_hour["hour"].isin(DAY_HOURS)].groupby("sgg_code")["val"].mean().rename("day_foreigners")
    g = pd.concat([night, day], axis=1).reset_index()
    if date_col:
        period = f"{df[date_col].min()}~{df[date_col].max()}"
        note("생활인구", "기간", period)
    return g


# ---------------------------------------------------------------- 결합
def main() -> None:
    minbak = clean_minbak()
    pop = clean_population()

    base = pd.DataFrame({"sgg_code": list(SGG), "sgg_name": list(SGG.values())})
    out = base.merge(pop, on="sgg_code", how="left").merge(minbak, on="sgg_code", how="left")
    no_pop = int(out["night_foreigners"].isna().sum())
    no_minbak = int(out["active_listings"].isna().sum())
    note("결합", "생활인구가 없는 자치구", no_pop)
    note("결합", "영업 중 도시민박업이 0곳인 자치구", no_minbak, "0으로 채움")
    out[["active_listings", "active_rooms"]] = out[["active_listings", "active_rooms"]].fillna(0).astype(int)
    out[["night_foreigners", "day_foreigners"]] = out[["night_foreigners", "day_foreigners"]].round(1)
    out["data_as_of"] = f"생활인구 {next((v for s, i, v, h in log if i == '기간'), '?')} / 인허가 수집일 {pd.Timestamp.today():%Y-%m-%d}"
    note("결합", "최종 행 수", len(out), "서울 자치구 25개여야 함")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {OUT}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 건수 검증 자동 기록 (clean.py 실행 결과)", "", "| 단계 | 항목 | 값 | 확인 방법 |", "|---|---|---|---|"]
    lines += [f"| {s} | {i} | {v} | {h} |" for s, i, v, h in log]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"건수 기록: {REPORT}")


if __name__ == "__main__":
    main()
