import io
import pandas as pd
import streamlit as st

# ---------------- Password Gate ----------------
def require_password():
    app_pw = st.secrets.get("APP_PASSWORD", None)
    if app_pw is None:
        st.error("APP_PASSWORD가 설정되어 있지 않습니다.")
        st.stop()

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("HR Headcount Analyzer")
        pw = st.text_input("비밀번호", type="password")
        if st.button("로그인"):
            if pw == app_pw:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 틀렸습니다.")
        st.stop()

require_password()

# ---------------- Main App ----------------

st.title("월말 인원 변동 분석")

AUTO_MAP = {
    "법인": "회사",
    "그룹사번": "그룹사번",
    "고용형태": "분류구분",
    "부서명": "부서",
    "입사일": "그룹입사일",
    "성명": "이름",
}

EMP_TYPE_STANDARD = ["월급직", "시급직", "계약직"]

def to_year_month(x):
    if pd.isna(x):
        return ""
    dt = pd.to_datetime(x, errors="coerce")
    if pd.isna(dt):
        return ""
    return dt.strftime("%Y-%m")

def normalize_emp_type(x):
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if "월" in s or "정규" in s:
        return "월급직"
    if "시" in s or "파트" in s:
        return "시급직"
    if "계약" in s:
        return "계약직"
    return s

def build_std(df_raw):
    for v in AUTO_MAP.values():
        if v not in df_raw.columns:
            st.error(f"필수 컬럼 누락: {v}")
            st.stop()

    df = pd.DataFrame()
    for k, v in AUTO_MAP.items():
        df[k] = df_raw[v]

    df["그룹사번"] = df["그룹사번"].astype(str).str.strip()
    df["법인"] = df["법인"].astype(str).str.strip()
    df["고용형태"] = df["고용형태"].apply(normalize_emp_type)
    df["부서명"] = df["부서명"].astype(str).str.strip()
    df["입사년월"] = df["입사일"].apply(to_year_month)

    return df[["법인","그룹사번","성명","고용형태","부서명","입사년월"]]

col1, col2 = st.columns(2)
with col1:
    prev_file = st.file_uploader("전월 파일", type=["xlsx"])
with col2:
    curr_file = st.file_uploader("당월 파일", type=["xlsx"])

if st.button("분석 실행"):

    if not prev_file or not curr_file:
        st.warning("파일 2개 모두 업로드하세요.")
        st.stop()

    prev_raw = pd.read_excel(prev_file, engine="openpyxl")
    curr_raw = pd.read_excel(curr_file, engine="openpyxl")

    prev = build_std(prev_raw)
    curr = build_std(curr_raw)

    prev_ids = set(prev["그룹사번"])
    curr_ids = set(curr["그룹사번"])

    join_ids = curr_ids - prev_ids
    leave_ids = prev_ids - curr_ids

    joiners = curr[curr["그룹사번"].isin(join_ids)]
    leavers = prev[prev["그룹사번"].isin(leave_ids)]

    headcount = curr.groupby(["법인","고용형태"]).size().unstack(fill_value=0)
    for t in EMP_TYPE_STANDARD:
        if t not in headcount.columns:
            headcount[t] = 0
    headcount["총원"] = headcount[EMP_TYPE_STANDARD].sum(axis=1)
    headcount = headcount.reset_index()

    st.subheader("당월 집계")
    st.dataframe(headcount)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        headcount.to_excel(writer, index=False, sheet_name="집계")
        joiners.to_excel(writer, index=False, sheet_name="입사자")
        leavers.to_excel(writer, index=False, sheet_name="퇴사자")

    st.download_button(
        "엑셀 다운로드",
        data=output.getvalue(),
        file_name="월말_인원변동.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
