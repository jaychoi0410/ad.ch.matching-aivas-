import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 24시제 시간 처리 함수 (익일 새벽 대응)
def handle_24h_time(date_str, time_str):
    try:
        if pd.isna(time_str) or str(time_str).strip() == "": return pd.NaT
        parts = str(time_str).strip().split(':')
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        
        clean_date = str(date_str).replace('.', '-').split(' ')[0]
        date_dt = pd.to_datetime(clean_date)
            
        if h >= 24:
            days_to_add = h // 24
            actual_h = h % 24
            actual_date = date_dt + timedelta(days=days_to_add)
            return pd.to_datetime(f"{actual_date.strftime('%Y-%m-%d')} {actual_h:02d}:{m:02d}:{s:02d}")
        return pd.to_datetime(f"{date_dt.strftime('%Y-%m-%d')} {h:02d}:{m:02d}:{s:02d}")
    except:
        return pd.NaT

# 2. 스마트 파일 로더 (분류 로직 최적화)
def load_and_classify(uploaded_files):
    ad_df, incl_df, excl_df = None, None, None
    for file in uploaded_files:
        # 헤더 위치 자동 탐색 루프 (0~5행)
        df_temp = None
        for skip in range(6):
            try:
                curr = pd.read_excel(file, skiprows=skip) if not file.name.endswith('.csv') else pd.read_csv(file)
                if not curr.empty and any(c in curr.columns for c in ['광고소재ID', '광고명', '프로그램']):
                    df_temp = curr
                    break
            except: continue
        
        if df_temp is None: continue

        # 분류 로직
        cols = df_temp.columns
        if '광고소재ID' in cols or '광고명' in cols:
            ad_df = df_temp
            ad_df['기준일자'] = ad_df['기준일자'].ffill() # 병합된 날짜 보정
        elif '프로그램' in cols:
            if '제외' in file.name: excl_df = df_temp
            else: incl_df = df_temp
            
    return ad_df, incl_df, excl_df

# UI 설정
st.set_page_config(page_title="AIVAS-Nielsen 매칭 에이전트", layout="wide")
st.title("🕒 AIVAS 영상분석 기반 광고 매칭 시스템")
st.info("AIVAS 영상분석 파일(1개) + 닐슨 편성표(포함/제외 각 1개)를 업로드하세요.")

uploaded_files = st.file_uploader("📂 파일 3개를 한꺼번에 업로드", type=['xlsx', 'csv'], accept_multiple_files=True)

if uploaded_files:
    df_ad, df_incl, df_excl = load_and_classify(uploaded_files)
    
    # 로드 상태 체크
    c1, c2, c3 = st.columns(3)
    c1.metric("AIVAS 데이터", "✅ 로드됨" if df_ad is not None else "❌ 미확인")
    c2.metric("포함 편성표", "✅ 로드됨" if df_incl is not None else "❌ 미확인")
    c3.metric("제외 편성표", "✅ 로드됨" if df_excl is not None else "❌ 미확인")

    if df_ad is not None and df_incl is not None and df_excl is not None:
        if st.button("🚀 매칭 분석 시작"):
            # 기준일자 및 채널 정보
            ref_date = str(df_ad['기준일자'].iloc[0])
            channel_name = str(df_ad['채널'].iloc[0]) if '채널' in df_ad.columns else "MBN"
            
            # 편성표 시간 전처리
            for target in [df_incl, df_excl]:
                target['dt_start'] = target.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                target['dt_end'] = target.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

            results = []
            for _, row in df_ad.iterrows():
                # [중요] 광고가 아니거나 누락된 데이터 제외
                if "광고없음" in str(row['광고명']) or str(row['광고소재ID']) == "광고아님": continue
                
                ad_time = handle_24h_time(row['기준일자'], row['시작일시'])
                if pd.isna(ad_time): continue
                
                # 1단계: 프로그램 매칭
                match = df_incl[(df_incl['dt_start'] <= ad_time) & (df_incl['dt_end'] > ad_time)]
                
                if not match.empty:
                    prog = match.iloc[0]['프로그램']
                    p_s, p_e = match.iloc[0]['시작시간'], match.iloc[0]['종료시간']
                    
                    # 2단계: 포지션 판정
                    excl_info = df_excl[df_excl['프로그램'] == prog]
                    prog_section, pos = "", "판정불가"
                    
                    if not excl_info.empty:
                        ex_s, ex_e = excl_info.iloc[0]['dt_start'], excl_info.iloc[0]['dt_end']
                        if ad_time >= ex_s and ad_time < ex_e:
                            pos, prog_section = "중광고", f"● 프로그램 진행 중({p_s}~{p_e}) ●"
                        elif ad_time < ex_s: pos = "전광고"
                        else: pos = "후광고"

                    results.append({
                        '일자': pd.to_datetime(ref_date).strftime('%Y-%m-%d'),
                        '시작시간': row['시작일시'],
                        '종료시간': row['종료일시'],
                        '광고주': str(row['광고명']).split('_')[0] if '_' in str(row['광고명']) else "-",
                        '상품명': row['광고명'],
                        '광고유형': "영상분석",
                        '[프로그램 구간]': prog_section,
                        '매칭 프로그램명': prog,
                        '최종 판정 위치': pos,
                        '사유': "AIVAS 실측 매칭"
                    })

            if results:
                res_df = pd.DataFrame(results)
                st.dataframe(res_df, use_container_width=True)
                
                # 파일명: (AIVAS)광고-프로그램_매칭_결과_MMDD(채널명).xlsx
                mmdd = pd.to_datetime(ref_date).strftime('%m%d')
                filename = f"(AIVAS)광고-프로그램_매칭_결과_{mmdd}({channel_name}).xlsx"
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Result')
                st.download_button(f"📥 {filename} 다운로드", output.getvalue(), filename)
