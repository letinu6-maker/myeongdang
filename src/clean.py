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


def read_population_file(path: Path) -> pd.DataFrame:
    """단기외국인 생활인구 일별 CSV 읽기.
    같은 달 파일인데도 형식이 두 가지로 섞여 있다.
      - 일반형: 쉼표 구분
      - 혼합형: 머리글은 쉼표, 데이터 줄은 세미콜론 구분 + 행정동코드 뒤 공백 + 끝에 빈 칸
    줄마다 구분자를 판단해 머리글 개수만큼만 잘라 읽는다."""
    import csv, io
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"인코딩을 알 수 없습니다: {path}")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = [h.strip() for h in next(csv.reader([lines[0]]))]
    rows = []
    for ln in lines[1:]:
        sep = ";" if ";" in ln else ","
        vals = [v.strip() for v in next(csv.reader(io.StringIO(ln), delimiter=sep))]
        rows.append((vals + [""] * len(header))[: len(header)])
    df = pd.DataFrame(rows, columns=header)
    df["_format"] = "세미콜론" if lines[1:] and ";" in lines[1] else "쉼표"
    return df


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

    # 중복 제거: 관리번호는 구청마다 따로 매겨져 서울 전체에서 겹치므로
    # 반드시 구청코드(OPNSFTEAMCODE)와 함께 고유키로 사용한다.
    id_col = pick(df.columns, "MGTNO", "관리번호")
    org_col = pick(df.columns, "OPNSFTEAMCODE", "개방자치단체코드")
    if id_col:
        keys = [c for c in (org_col, id_col) if c]
        before = len(df)
        df = df.drop_duplicates(subset=keys)
        note("도시민박업", "중복 제거", before - len(df),
             f"{'+'.join(keys)} 기준 (관리번호만으로는 구청 간 번호가 겹침)")

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

    # 객실 수: 구청마다 입력 여부가 달라 결측이 많으므로 채우지 않고 참고용으로만 집계
    room_col = pick(df.columns, "STROOMCNT", "객실")
    df["rooms"] = pd.to_numeric(df[room_col], errors="coerce") if room_col else float("nan")
    note("도시민박업", "객실수 결측(영업 중)", int(df["rooms"].isna().sum()),
         "구청별 입력 여부가 달라 채우지 않음. 경쟁 지표는 업소 수 사용")

    g = df.groupby("sgg_code").agg(
        active_listings=("sgg_code", "size"),
        rooms_known_listings=("rooms", "count"),
        rooms_known_sum=("rooms", "sum"),
    ).reset_index()
    return g


# ---------------------------------------------------------------- 생활인구
def clean_population() -> pd.DataFrame:
    files = sorted((RAW / "population").glob("*.csv"))
    if not files:
        sys.exit(f"{RAW / 'population'} 에 생활인구 CSV가 없습니다. 월별 zip을 풀어 넣어 주세요.")
    parts = [read_population_file(f) for f in files]
    df = pd.concat(parts, ignore_index=True)
    n_semi = sum(p["_format"].iat[0] == "세미콜론" for p in parts if len(p))
    note("생활인구", "원본 행 수", len(df), f"일별 파일 {len(files)}개 (세미콜론 형식 {n_semi}개 포함, 줄별로 구분자 판단)")
    print("생활인구 컬럼:", [c for c in df.columns if c != "_format"])

    dong_col = pick(df.columns, "행정동코드", "ADSTRD")
    hour_col = pick(df.columns, "시간대", "TMZON", "시간")
    val_col = pick(df.columns, "생활인구합계", "총생활인구", "TOT_LVPOP", "생활인구")
    date_col = pick(df.columns, "기준일", "STDR_DE", "일자")
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
    cnt_cols = ["active_listings", "rooms_known_listings", "rooms_known_sum"]
    out[cnt_cols] = out[cnt_cols].fillna(0).astype(int)
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
