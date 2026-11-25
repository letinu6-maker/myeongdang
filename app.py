"""Streamlit 화면 (B 담당) — 가이드 v4 6-4.

실행(저장소 최상위 폴더에서):  streamlit run app.py
- API 서버(API_URL, 기본 http://localhost:8000)를 먼저 호출하고,
  연결이 안 되거나 3초 안에 답이 없으면 CSV를 직접 읽어 scoring.py로 같은 계산을 한다.
"""
import os

import pandas as pd
import requests
import streamlit as st

from src import data_loader, scoring

try:  # .env가 있으면 API_URL을 읽는다 (없어도 동작)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 3
FOOTER = ("1박 요금, 가동률, 월세는 사용자가 입력한 가정입니다. 경쟁 숙소는 등록 업소 기준 최소치이며, "
          "⚠ 표시 구는 미등록 숙소가 많을 수 있습니다.")


def call_api(path: str, params: dict):
    """API 응답 dict. 연결 실패·타임아웃·서버 오류면 None (→ 직접 계산)."""
    try:
        r = requests.get(f"{API_URL}{path}", params=params, timeout=TIMEOUT)
        payload = r.json()
    except (requests.RequestException, ValueError):
        return None
    if r.status_code >= 500:
        return None
    return payload


def records(df: pd.DataFrame) -> list:
    return df.to_dict(orient="records")


def local_rank(night_weight, min_listings, max_listings, codes, top_n) -> dict:
    """API와 같은 형식으로 직접 계산 (API 서버가 꺼져 있을 때)."""
    err = scoring.listing_range_error(min_listings, max_listings)
    if err:
        return {"ok": False, "message": err, "results": []}
    ranked, excluded = scoring.rank(loaded.df, night_weight, min_listings, max_listings, codes, top_n)
    return {"ok": True, "message": scoring.MSG_NO_RESULT if ranked.empty else "",
            "results": records(ranked), "excluded": records(excluded)}


def local_simulate(price, occupancy, monthly_rent, other_cost, code) -> dict:
    result = scoring.simulate(price, occupancy, monthly_rent, other_cost)
    result["district"] = scoring.district_info(loaded.df, code) if code else None
    return {"ok": True, "message": scoring.MSG_OVER_MONTH if result["over_month"] else "", "results": [result]}


def won(x) -> str:
    return f"{int(round(x)):,}원"


st.set_page_config(page_title="명당발견 — 외국인 관광객 숙소 입지·손익분기", page_icon="🏠", layout="wide")
st.title("🏠 명당발견")
st.caption("외국인 관광객 숙소, 서울 어느 구에서 시작해야 본전을 찾을까? — 예비 에어비앤비 호스트용 가이드")

loaded = data_loader.load_data()
if loaded.df is None:
    st.error("데이터 파일을 찾을 수 없습니다. README의 실행 방법을 확인해 주세요.")
    for w in loaded.warnings:
        st.caption(w)
    st.stop()

names = dict(zip(loaded.df["sgg_code"], loaded.df["sgg_name"]))
api_alive = True   # 한 번 실패하면 이번 실행에서는 바로 직접 계산 (3초씩 두 번 기다리지 않게)


def fetch(path, params, local_fn, *local_args):
    global api_alive
    if api_alive:
        res = call_api(path, params)
        if res is not None:
            return res
        api_alive = False
    return local_fn(*local_args)


# ---------------- 상단 안내 ----------------
header = st.container()

tab1, tab2 = st.tabs(["① 입지 비교", "② 손익분기 계산"])

# ---------------- 탭 1: 입지 비교 ----------------
with tab1:
    c1, c2, c3 = st.columns(3)
    with c1:
        selected = st.multiselect("검토할 자치구 (비우면 전체)", options=list(names),
                                  format_func=lambda c: names.get(c, c))
        night_weight = st.slider("수요 기준: 주간 관광(0) ↔ 야간 숙박(1)", 0.0, 1.0, 0.7, 0.05)
    with c2:
        min_listings = st.number_input("최소 업소 수 (미만이면 검증 부족 시장)", min_value=0,
                                       value=scoring.DEFAULT_MIN_LISTINGS, step=10)
        use_max = st.checkbox("경쟁 업소 수 상한 적용")
        max_input = st.number_input("경쟁 업소 수 상한(곳)", min_value=0, value=500, step=50, disabled=not use_max)
    with c3:
        top_n = st.slider("보여 줄 자치구 수", 1, 25, 5)
        chart_metric = st.radio("그래프 기준", ["점수", "업소당 수요"], horizontal=True)

    max_listings = int(max_input) if use_max else None
    params = {"night_weight": night_weight, "min_listings": int(min_listings), "top_n": top_n}
    if max_listings is not None:
        params["max_listings"] = max_listings
    if selected:
        params["districts"] = ",".join(selected)

    res = fetch("/rank", params, local_rank, night_weight, int(min_listings), max_listings, selected, top_n)
    rank_df = pd.DataFrame(res.get("results", []))
    excluded_df = pd.DataFrame(res.get("excluded", []))

    if not res.get("ok", False):
        st.warning(res.get("message") or "입력값을 확인해 주세요.")
    elif rank_df.empty:
        st.info(res.get("message") or scoring.MSG_NO_RESULT)
    else:
        table = pd.DataFrame({
            "순위": rank_df["rank"],
            "자치구": rank_df["sgg_name"],
            "점수": rank_df["score"],
            "업소당 수요": rank_df["demand_per_listing"],
            "수요(가중 평균)": rank_df["demand"],
            "영업 중 업소": rank_df["active_listings"],
            "비고": [("⚠ 미등록 숙소 주의 " if c else "") + ("경쟁 없음" if n else "")
                   for c, n in zip(rank_df["caution"], rank_df["no_competition"])],
        })
        st.dataframe(table, hide_index=True, use_container_width=True)
        try:
            import altair as alt
            chart = alt.Chart(table).mark_bar().encode(
                x=alt.X(f"{chart_metric}:Q", title=chart_metric),
                y=alt.Y("자치구:N", sort="-x", title=None),
                tooltip=["순위", "자치구", "점수", "업소당 수요", "영업 중 업소"],
            )
            st.altair_chart(chart, use_container_width=True)
        except Exception:
            st.bar_chart(table.set_index("자치구")[chart_metric])

    if res.get("ok", False) and not excluded_df.empty:
        with st.expander(f"검증 부족 시장 (업소 {int(min_listings)}곳 미만) — {len(excluded_df)}개 구"):
            st.caption("업소가 적어 업소당 수요가 크게 나오지만, 수요가 숙박으로 이어지는지 검증되지 않았습니다.")
            st.dataframe(pd.DataFrame({
                "자치구": excluded_df["sgg_name"],
                "영업 중 업소": excluded_df["active_listings"],
                "업소당 수요": excluded_df["demand_per_listing"],
            }), hide_index=True, use_container_width=True)

# ---------------- 탭 2: 손익분기 계산 ----------------
with tab2:
    c1, c2 = st.columns(2)
    with c1:
        code = st.selectbox("자치구 (선택)", [""] + list(names),
                            format_func=lambda c: "선택 안 함" if c == "" else names.get(c, c))
        price = st.number_input("1박 요금(원)", min_value=1, max_value=2_000_000, value=80_000, step=10_000)
        occupancy = st.slider("예상 가동률(%)", 0, 100, 60)
    with c2:
        monthly_rent = st.number_input("월세(원)", min_value=0, max_value=10_000_000, value=900_000, step=50_000)
        other_cost = st.number_input("월 기타 비용(원) — 관리비·청소·소모품 등", min_value=0,
                                     value=300_000, step=50_000)

    params = {"price": int(price), "occupancy_pct": occupancy, "monthly_rent": int(monthly_rent),
              "other_cost": int(other_cost)}
    if code:
        params["sgg_code"] = code
    sim = fetch("/simulate", params, local_simulate, int(price), occupancy, int(monthly_rent), int(other_cost), code)

    if not sim.get("ok", False) or not sim.get("results"):
        st.warning(sim.get("message") or "입력값을 확인해 주세요.")
    else:
        s = sim["results"][0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("월 비용 (월세+기타)", won(s["monthly_cost"]))
        m2.metric("손익분기 예약일수", f"{s['breakeven_nights']}일 / 30일")
        m3.metric("손익분기 가동률", f"{s['breakeven_occupancy_pct']}%")
        m4.metric("예상 월 손익", won(s["expected_profit"]))
        if s["over_month"]:
            st.error(f"한 달 내내 차도 적자입니다 (필요 {s['breakeven_nights']}일 > 30일). 1박 요금을 올리거나 비용을 줄여야 합니다.")
        elif s["is_loss"]:
            st.markdown(f"### :red[적자 {won(s['expected_profit'])}]")
            st.caption(f"가동률 {occupancy}%로는 손익분기 가동률 {s['breakeven_occupancy_pct']}%에 못 미칩니다.")
        else:
            st.markdown(f"### :green[흑자 +{won(s['expected_profit'])}]")
            st.caption(f"예상 예약 {s['expected_nights']}일, 예상 매출 {won(s['expected_revenue'])}")
        st.caption("계산식: 손익분기 예약일수 = (월세 + 기타 비용) ÷ 1박 요금(올림) · "
                   "예상 월 손익 = 1박 요금 × 30 × 가동률 − (월세 + 기타 비용)")

        d = s.get("district")
        if d:
            st.subheader(f"{d['sgg_name']} 정보")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("야간 단기외국인(숙박 수요)", f"{d['night_foreigners']:,.0f}명")
            d2.metric("주간 단기외국인(관광 수요)", f"{d['day_foreigners']:,.0f}명")
            d3.metric("영업 중 업소", f"{d['active_listings']:,}곳")
            d4.metric("업소당 수요", f"{d['demand_per_listing']:,}")
            if d.get("rooms_known_sum") is not None and d.get("rooms_known_listings"):
                st.caption(f"객실 수(참고값): 객실 정보가 있는 업소 {d['rooms_known_listings']:,}곳 기준 "
                           f"{d['rooms_known_sum']:,}실")
            if d.get("median_monthly_rent") is not None:
                st.caption(f"이 구의 평균 월세 참고값: {won(d['median_monthly_rent'])}")
            if d.get("caution"):
                st.warning("⚠ 주간 관광객이 많은 구(상위 25%)라 미등록 숙소가 많을 수 있습니다. 실제 경쟁은 더 클 수 있습니다.")
        if sim.get("message") and not s["over_month"]:
            st.info(sim["message"])

# ---------------- 상단 안내 (탭 계산 후 채움) ----------------
with header:
    st.caption(f"데이터 출처: 서울 열린데이터광장(외국인관광 도시민박업 인허가, 단기체류 외국인 생활인구) · "
               f"기준 시점: {loaded.data_as_of}")
    if "DUMMY" in str(loaded.data_as_of).upper():
        st.error("⚠ DUMMY 데이터입니다. 실제 데이터가 아니므로 숫자를 발표·판단에 쓰지 마세요.")
    if loaded.source == "sample":
        st.info("샘플 데이터로 실행 중입니다 (data/sample).")
    if not api_alive:
        st.warning(f"API 서버 없이 실행 중 — 화면이 CSV를 직접 읽어 계산했습니다. (API_URL: {API_URL})")
    for w in loaded.warnings:
        st.warning(w)

# ---------------- 하단 고정 문구 ----------------
st.divider()
st.caption(FOOTER)
