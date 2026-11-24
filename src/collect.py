"""
서울 열린데이터광장 OpenAPI로 외국인관광 도시민박업 인허가 정보를 수집해
data/raw/minbak_raw.csv 로 저장합니다.

실행:  python src/collect.py
필요:  .env 에 SEOUL_OPENAPI_KEY, SEOUL_MINBAK_SERVICE 값
       (SEOUL_MINBAK_SERVICE 는 데이터셋 페이지 'Open API' 탭의 샘플 URL에 있는 서비스명)
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = RAW_DIR / "minbak_raw.csv"
PAGE_SIZE = 1000  # 서울 열린데이터광장은 한 번에 최대 1,000건


def fetch_page(key: str, service: str, start: int, end: int) -> dict:
    url = f"http://openapi.seoul.go.kr:8088/{key}/json/{service}/{start}/{end}/"
    for attempt in range(3):
        try:
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            return res.json()
        except (requests.RequestException, ValueError) as e:
            print(f"  요청 실패({attempt + 1}/3): {e}")
            time.sleep(2)
    raise RuntimeError(f"{start}~{end} 구간을 3번 시도했지만 받지 못했습니다.")


def main() -> None:
    load_dotenv(ROOT / ".env")
    key = os.getenv("SEOUL_OPENAPI_KEY", "").strip()
    service = os.getenv("SEOUL_MINBAK_SERVICE", "").strip()
    if not key or not service:
        print("SEOUL_OPENAPI_KEY 또는 SEOUL_MINBAK_SERVICE 가 .env 에 없습니다.")
        print("키 없이 실행하려면 data/sample 의 샘플 데이터를 사용하세요.")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows, start, total = [], 1, None

    while True:
        end = start + PAGE_SIZE - 1
        data = fetch_page(key, service, start, end)
        body = data.get(service)
        if body is None:  # 키 오류, 서비스명 오류 등은 RESULT 로만 돌아옴
            print("API 응답에 데이터가 없습니다:", data.get("RESULT", data))
            sys.exit(1)
        if total is None:
            total = int(body.get("list_total_count", 0))
            print(f"전체 {total}건 수집 시작")
        page_rows = body.get("row", [])
        rows.extend(page_rows)
        print(f"  {start}~{min(end, total)} 수집 ({len(rows)}/{total})")
        if not page_rows or end >= total:
            break
        start = end + 1
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUT_PATH} ({len(df)}행, API 전체 {total}건)")
    if len(df) != total:
        print("주의: 받은 행 수와 API 전체 건수가 다릅니다. 건수 검증표에 기록하세요.")


if __name__ == "__main__":
    main()
