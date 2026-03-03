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

    # 그룹사번 중복 체크(중복이면 비교가 깨짐)
    def validate_unique(df, key, label):
        dup = df[df[key].duplicated(keep=False)]
        if not dup.empty:
            st.error(f"[{label}] '{key}' 중복이 있습니다. 그룹사번은 고유해야 합니다.")
            st.dataframe(dup, use_container_width=True)
            st.stop()

    validate_unique(prev, "그룹사번", "전월")
    validate_unique(curr, "그룹사번", "당월")

    # ===== 1) 당월 법인별 인원 집계 =====
    headcount = curr.groupby(["법인", "고용형태"]).size().unstack(fill_value=0)
    for t in EMP_TYPE_STANDARD:
        if t not in headcount.columns:
            headcount[t] = 0
    headcount["총원"] = headcount[EMP_TYPE_STANDARD].sum(axis=1)
    headcount = headcount.reset_index()

    # ===== 2) 전월 대비 변동(입/퇴/전입/전출) =====
    prev_idx = prev.set_index("그룹사번")
    curr_idx = curr.set_index("그룹사번")

    prev_ids = set(prev_idx.index)
    curr_ids = set(curr_idx.index)

    join_ids = sorted(list(curr_ids - prev_ids))    # 입사(전월X, 당월O)
    leave_ids = sorted(list(prev_ids - curr_ids))   # 퇴사(전월O, 당월X)
    common_ids = sorted(list(prev_ids & curr_ids))  # 양쪽 모두 존재

    joiners = curr_idx.loc[join_ids].reset_index() if join_ids else pd.DataFrame(columns=["그룹사번"] + list(curr.columns))
    leavers  = prev_idx.loc[leave_ids].reset_index() if leave_ids else pd.DataFrame(columns=["그룹사번"] + list(prev.columns))

    # 전입/전출: 두 달 모두 존재 + 법인 변경
    merged = prev_idx.loc[common_ids].add_prefix("전월_").join(curr_idx.loc[common_ids].add_prefix("당월_"))
    moved = merged[merged["전월_법인"] != merged["당월_법인"]].reset_index()  # index가 그룹사번

    transfers_in = pd.DataFrame({
        "법인": moved["당월_법인"],            # 당월 법인 기준 전입
        "이전법인": moved["전월_법인"],
        "그룹사번": moved["그룹사번"],
        "이름": moved["당월_성명"],
        "부서명": moved["당월_부서명"],
        "입사년월": moved["당월_입사년월"],
        "고용형태": moved["당월_고용형태"],
    })

    transfers_out = pd.DataFrame({
        "법인": moved["전월_법인"],            # 전월 법인 기준 전출
        "현재법인": moved["당월_법인"],
        "그룹사번": moved["그룹사번"],
        "이름": moved["전월_성명"],
        "부서명": moved["전월_부서명"],
        "입사년월": moved["전월_입사년월"],
        "고용형태": moved["전월_고용형태"],
    })

    # ===== 3) 법인별 변동 요약 =====
    def count_by_entity(df, entity_col, name):
        if df.empty:
            return pd.DataFrame(columns=["법인", name])
        return df.groupby(entity_col).size().rename(name).reset_index().rename(columns={entity_col: "법인"})

    join_summary  = count_by_entity(joiners, "법인", "입사자")
    leave_summary = count_by_entity(leavers,  "법인", "퇴사자")
    in_summary    = count_by_entity(transfers_in,  "법인", "전입자")
    out_summary   = count_by_entity(transfers_out, "법인", "전출자")

    movement_summary = headcount[["법인"]].merge(join_summary, on="법인", how="left") \
                                         .merge(leave_summary, on="법인", how="left") \
                                         .merge(in_summary, on="법인", how="left") \
                                         .merge(out_summary, on="법인", how="left") \
                                         .fillna(0)

    for c in ["입사자", "퇴사자", "전입자", "전출자"]:
        movement_summary[c] = movement_summary[c].astype(int)

    # ===== 4) 화면 표시 =====
    st.subheader("당월 법인별 인원 집계")
    st.dataframe(headcount, use_container_width=True)

    st.subheader("전월 대비 변동 요약(법인별)")
    st.dataframe(movement_summary, use_container_width=True)

    st.subheader("상세 리스트")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### 입사자 상세")
        st.dataframe(joiners[["법인", "그룹사번", "성명", "부서명", "입사년월", "고용형태"]], use_container_width=True)
        st.markdown("### 전입자 상세(법인 변경)")
        st.dataframe(transfers_in[["법인", "이전법인", "그룹사번", "이름", "부서명", "입사년월", "고용형태"]], use_container_width=True)

    with c2:
        st.markdown("### 퇴사자 상세")
        st.dataframe(leavers[["법인", "그룹사번", "성명", "부서명", "입사년월", "고용형태"]], use_container_width=True)
        st.markdown("### 전출자 상세(법인 변경)")
        st.dataframe(transfers_out[["법인", "현재법인", "그룹사번", "이름", "부서명", "입사년월", "고용형태"]], use_container_width=True)

    # ===== 5) 엑셀 다운로드(시트 6개) =====
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        headcount.to_excel(writer, index=False, sheet_name="1_당월인원집계")
        movement_summary.to_excel(writer, index=False, sheet_name="2_변동요약")
        joiners[["법인","그룹사번","성명","고용형태","부서명","입사년월"]].to_excel(writer, index=False, sheet_name="3_입사자상세")
        leavers[["법인","그룹사번","성명","고용형태","부서명","입사년월"]].to_excel(writer, index=False, sheet_name="4_퇴사자상세")
        transfers_in.to_excel(writer, index=False, sheet_name="5_전입자상세")
        transfers_out.to_excel(writer, index=False, sheet_name="6_전출자상세")

    st.download_button(
        "엑셀 리포트 다운로드",
        data=output.getvalue(),
        file_name="월말_인원변동_리포트.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
