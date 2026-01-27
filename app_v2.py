import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 방송 시간(24시제) 처리 함수
def handle_24h_time(date_str, time_str):
    try:
        h, m, s = map(int, str(time_str).split(':'))
        # 기준 일자 처리 (YYYYMMDD 형식 대응)
        date_str = str(date_str)
        if len(date_str) == 8:
            date_dt = datetime.strptime(date_str, '%Y%m%d')
        else:
            date_dt = pd.to_datetime(date_str)
            
        if h >= 24:
            days_to_add = h // 24
            actual_h = h % 24
            actual_date = date_dt + timedelta(days=days_to_add)
            return pd.to_datetime(f"{actual_date.strftime('%Y-%m-%d')} {actual_h:02d}:{m:02d}:{s:02d}")
        return pd.to_datetime(f"{date_dt.strftime('%Y-%m-%d')} {time_str}")
    except:
        return pd.NaT

# UI 설정
st.set_page_config(page_title="AI 영상분석-편성 매칭 에이전트", layout="wide")
st.title("🕒 AI 영상분석 기반 광고 포지션 판정 시스템")
st.markdown("영상분석 탐지 기록(프로그램명 없음)과 편성표를 **시간 기반**으로 매칭합니다.")

# 2. 파일 업로드
with st.sidebar:
    st.header("파일 업로드")
    ad_file = st.file_uploader("1. 영상분석 탐지 파일", type=['xlsx', 'csv'])
    incl_file = st.file_uploader("2. 프로그램 편성(광고포함)", type=['xlsx', 'csv'])
    excl_file = st.file_uploader("3. 프로그램 편성(광고제외)", type=['xlsx', 'csv'])
    
    if st.button("🔄 데이터 리셋"):
        st.rerun()

if ad_file and incl_file and excl_file:
    # 데이터 로드 (헤더 위치는 파일 특성에 맞춰 조정)
    df_ad = pd.read_excel(ad_file) # 영상분석 파일은 보통 헤더가 0번행
    df_incl = pd.read_excel(incl_file, skiprows=3)
    df_excl = pd.read_excel(excl_file, skiprows=3)

    st.success("✅ 모든 파일 로드 완료. 분석을 시작합니다.")

    # 3. 전처리: 시간 데이터 변환
    # 영상분석 파일 컬럼 매핑: 기준일자, 시작일시, 종료일시
    df_ad['start_dt'] = df_ad.apply(lambda r: handle_24h_time(r['기준일자'], r['시작일시']), axis=1)
    df_ad['end_dt'] = df_ad.apply(lambda r: handle_24h_time(r['기준일자'], r['종료일시']), axis=1)

    # 편성표 날짜 기준 설정 (광고 파일의 첫 행 날짜 기준)
    ref_date = str(df_ad['기준일자'].iloc[0])
    df_incl['start_dt'] = df_incl.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
    df_incl['end_dt'] = df_incl.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)
    df_excl['start_dt'] = df_excl.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
    df_excl['end_dt'] = df_excl.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

    # 4. 시간 기반 매칭 루프
    report_data = []
    
    for _, ad in df_ad.iterrows():
        if ad['광고소재ID'] == "광고아님": continue # 광고가 아닌 구간 제외
        
        ad_start = ad['start_dt']
        
        # [Step 1] 광고 포함 편성표에서 해당 시간이 포함된 프로그램 찾기
        matched_incl = df_incl[(df_incl['start_dt'] <= ad_start) & (df_incl['end_dt'] > ad_start)]
        
        if not matched_incl.empty:
            target_prog = matched_incl.iloc[0]['프로그램']
            prog_start_str = matched_incl.iloc[0]['시작시간']
            prog_end_str = matched_incl.iloc[0]['종료시간']
            
            # [Step 2] 포지션 판정 (광고제외 편성표 기준)
            target_excl = df_excl[df_excl['프로그램'] == target_prog]
            
            if not target_excl.empty:
                excl_start = target_excl.iloc[0]['start_dt']
                excl_end = target_excl.iloc[0]['end_dt']
                
                if ad_start >= excl_start and ad_start < excl_end:
                    final_pos = "중광고"
                elif ad_start < excl_start:
                    final_pos = "전광고"
                else:
                    final_pos = "후광고"
            else:
                final_pos = "판정불가(편성미매칭)"
                
            report_data.append({
                '일자': ad['기준일자'],
                '시작시간': ad['시작일시'],
                '종료시간': ad['종료일시'],
                '광고주': "-", # 영상분석 데이터에는 광고주 정보가 없음
                '상품명': ad['광고명'],
                '광고유형': "영상분석",
                '[프로그램 구간]': f"● {target_prog} ({prog_start_str}~{prog_end_str}) ●",
                '매칭 프로그램명': target_prog,
                '최종 판정 위치': final_pos,
                '매칭 신뢰도': "100% (시간기반)",
                '사유': f"방영시간 {ad['시작일시']} 기준 자동 매칭"
            })

    # 결과 표시
    result_df = pd.DataFrame(report_data)
    st.subheader("📊 매칭 분석 결과")
    st.dataframe(result_df, use_container_width=True)

    # 엑셀 다운로드
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        result_df.to_excel(writer, index=False)
    
    st.download_button(
        label="📥 결과 리포트 다운로드 (Excel)",
        data=output.getvalue(),
        file_name=f"영상분석_매칭결과_{ref_date}.xlsx",
        mime="application/vnd.ms-excel"
    )
else:
    st.warning("왼쪽 사이드바에서 파일 3종을 모두 업로드해 주세요.")