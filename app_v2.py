import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 방송 시간(24시제) 처리 함수
def handle_24h_time(date_str, time_str):
    try:
        if pd.isna(time_str) or time_str == "": return pd.NaT
        h, m, s = map(int, str(time_str).split(':'))
        date_str = str(date_str).replace('-', '').replace('.', '').split(' ')[0]
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

# 2. 파일 로더 함수 (Excel/CSV 대응 및 헤더 자동 찾기)
def smart_load_df(file):
    if file.name.endswith('.csv'):
        df = pd.read_csv(file)
    else:
        # 편성표의 경우 헤더가 0~3행 사이에 있을 수 있으므로 탐색
        df = pd.read_excel(file)
        if '프로그램' not in df.columns:
            for i in range(1, 5):
                df_retry = pd.read_excel(file, skiprows=i)
                if '프로그램' in df_retry.columns:
                    return df_retry
    return df

# UI 설정
st.set_page_config(page_title="AI 영상분석 매칭 시스템", layout="wide")
st.title("🕒 통합 광고 포지션 판정 시스템 (v2.1)")

uploaded_files = st.file_uploader(
    "📂 파일 3개를 한꺼번에 드래그하세요 (영상분석, 포함편성, 제외편성)", 
    type=['xlsx', 'csv'], 
    accept_multiple_files=True
)

if uploaded_files:
    ad_files = []
    df_incl = None
    df_excl = None

    for file in uploaded_files:
        df = smart_load_df(file)
        cols = df.columns.tolist()

        # 분류 로직 강화
        if any(c in cols for c in ['광고소재ID', '광고명']):
            ad_files.append((file.name, df))
        elif '프로그램' in cols:
            if '제외' in file.name or 'excl' in file.name.lower():
                df_excl = df
            else:
                df_incl = df

    # 분류 상태 시각화
    c1, c2, c3 = st.columns(3)
    c1.metric("영상분석 파일", f"{len(ad_files)}개")
    c2.metric("포함 편성표", "✅ 로드됨" if df_incl is not None else "❌ 미확인")
    c3.metric("제외 편성표", "✅ 로드됨" if df_excl is not None else "❌ 미확인")

    if ad_files and df_incl is not None and df_excl is not None:
        if st.button("🚀 통합 분석 시작"):
            all_reports = []
            
            for file_name, df_ad in ad_files:
                # 첫 번째 행의 기준일자 확보
                ref_date = str(df_ad['기준일자'].iloc[0])
                
                # 전처리
                df_ad['start_dt'] = df_ad.apply(lambda r: handle_24h_time(r['기준일자'], r['시작일시']), axis=1)
                
                tmp_incl = df_incl.copy()
                tmp_excl = df_excl.copy()
                
                # 편성표 시간 처리 (프로그램이 비어있지 않은 행만)
                tmp_incl = tmp_incl.dropna(subset=['프로그램', '시작시간'])
                tmp_excl = tmp_excl.dropna(subset=['프로그램', '시작시간'])
                
                tmp_incl['start_dt'] = tmp_incl.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                tmp_incl['end_dt'] = tmp_incl.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)
                tmp_excl['start_dt'] = tmp_excl.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                tmp_excl['end_dt'] = tmp_excl.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

                for _, ad in df_ad.iterrows():
                    if str(ad.get('광고소재ID', '')) == "광고아님": continue
                    
                    ad_start = ad['start_dt']
                    if pd.isna(ad_start): continue

                    # 1단계: 포함 편성표 매칭
                    matched = tmp_incl[(tmp_incl['start_dt'] <= ad_start) & (tmp_incl['end_dt'] > ad_start)]
                    
                    if not matched.empty:
                        prog_name = matched.iloc[0]['프로그램']
                        prog_time = f"{matched.iloc[0]['시작시간']}~{matched.iloc[0]['종료시간']}"
                        
                        # 2단계: 제외 편성표 대조
                        excl_match = tmp_excl[tmp_excl['프로그램'] == prog_name]
                        
                        if not excl_match.empty:
                            excl_start = excl_match.iloc[0]['start_dt']
                            excl_end = excl_match.iloc[0]['end_dt']
                            
                            if ad_start >= excl_start and ad_start < excl_end:
                                final_pos = "중광고"
                            elif ad_start < excl_start:
                                final_pos = "전광고"
                            else:
                                final_pos = "후광고"
                        else:
                            final_pos = "판정불가(편성명칭미일치)"
                            
                        all_reports.append({
                            '파일명': file_name,
                            '일자': ad['기준일자'],
                            '시작시간': ad['시작일시'],
                            '종료시간': ad['종료일시'],
                            '상품명': ad['광고명'],
                            '[프로그램 구간]': f"● {prog_name} ({prog_time}) ●",
                            '최종 판정 위치': final_pos
                        })

            if all_reports:
                res_df = pd.DataFrame(all_reports)
                st.dataframe(res_df, use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False)
                st.download_button("📥 결과 리포트 다운로드", output.getvalue(), "분석결과.xlsx")
    else:
        st.error("파일 매칭 실패: 파일명에 '제외' 단어가 포함된 편성표와 '광고소재ID'가 포함된 영상분석 파일이 모두 필요합니다.")
