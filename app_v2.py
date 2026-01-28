import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 시간 처리 및 보정 함수 (-3초 기본 적용)
def handle_24h_time(date_str, time_str, offset_sec=0):
    try:
        if pd.isna(time_str) or str(time_str).strip() == "": return pd.NaT
        parts = str(time_str).strip().split(':')
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        
        clean_date = str(date_str).replace('.', '-').split(' ')[0]
        date_dt = pd.to_datetime(clean_date)
            
        base_dt = None
        if h >= 24:
            days_to_add = h // 24
            actual_h = h % 24
            actual_date = date_dt + timedelta(days=days_to_add)
            base_dt = pd.to_datetime(f"{actual_date.strftime('%Y-%m-%d')} {actual_h:02d}:{m:02d}:{s:02d}")
        else:
            base_dt = pd.to_datetime(f"{date_dt.strftime('%Y-%m-%d')} {h:02d}:{m:02d}:{s:02d}")
            
        if offset_sec != 0:
            return base_dt + timedelta(seconds=offset_sec)
        return base_dt
    except:
        return pd.NaT

# 2. 파일 로더 및 분류
def load_and_classify(uploaded_files):
    ad_df, incl_df, excl_df = None, None, None
    for file in uploaded_files:
        df_temp = None
        for skip in range(6):
            try:
                curr = pd.read_excel(file, skiprows=skip) if not file.name.endswith('.csv') else pd.read_csv(file)
                if not curr.empty and any(c in curr.columns for c in ['광고소재ID', '광고명', '프로그램']):
                    df_temp = curr
                    break
            except: continue
        
        if df_temp is None: continue

        cols = df_temp.columns
        if '광고소재ID' in cols or '광고명' in cols:
            ad_df = df_temp
            ad_df['기준일자'] = ad_df['기준일자'].ffill()
        elif '프로그램' in cols:
            if '제외' in file.name or 'excl' in file.name.lower():
                excl_df = df_temp
            else:
                incl_df = df_temp
            
    return ad_df, incl_df, excl_df

# UI 설정
st.set_page_config(page_title="AIVAS 정밀 매칭 에이전트 v4", layout="wide")
st.title("🕒 (AIVAS) 정밀 광고 포지션 판정 시스템")
st.markdown("엄격한 슬롯 매칭을 적용합니다. 편성표상의 공백 구간 광고는 '검토 필요'로 분류됩니다.")

with st.sidebar:
    st.header("⚙️ 시스템 설정")
    time_offset = st.number_input("AIVAS 시간 보정값 (초)", value=-3, help="AIVAS 실측 시간에서 이만큼 가감하여 편성표와 대조합니다.")

uploaded_files = st.file_uploader("📂 파일 3개를 한꺼번에 업로드", type=['xlsx', 'csv'], accept_multiple_files=True)

if uploaded_files:
    df_ad, df_incl, df_excl = load_and_classify(uploaded_files)
    
    if df_ad is not None and df_incl is not None and df_excl is not None:
        if st.button("🚀 정밀 매칭 시작"):
            ref_date = str(df_ad['기준일자'].iloc[0])
            channel_name = str(df_ad['채널'].iloc[0]) if '채널' in df_ad.columns else "채널미확인"
            
            # 편성표 시간 전처리
            for target in [df_incl, df_excl]:
                target['dt_start'] = target.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                target['dt_end'] = target.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

            results = []
            for _, row in df_ad.iterrows():
                if "광고없음" in str(row['광고명']) or str(row['광고소재ID']) == "광고아님": continue
                
                # AIVAS 실측 시각 보정 (-3초)
                ad_time_corr = handle_24h_time(row['기준일자'], row['시작일시'], offset_sec=time_offset)
                if pd.isna(ad_time_corr): continue
                
                # 1단계: 엄격한 슬롯 매칭 (df_incl 내에 존재해야 함)
                target_match = df_incl[(df_incl['dt_start'] <= ad_time_corr) & (df_incl['dt_end'] > ad_time_corr)]
                
                if not target_match.empty:
                    # [정상 매칭 케이스]
                    final_match = target_match.iloc[0]
                    prog_name = final_match['프로그램']
                    match_reason = "정상 매칭"
                    
                    # 2단계: 포지션 판정 (광고제외 시간 대조)
                    excl_info = df_excl[df_excl['프로그램'] == prog_name]
                    prog_section, pos = "", "판정불가"
                    
                    if not excl_info.empty:
                        ex_s_dt, ex_e_dt = excl_info.iloc[0]['dt_start'], excl_info.iloc[0]['dt_end']
                        ex_s_str, ex_e_str = excl_info.iloc[0]['시작시간'], excl_info.iloc[0]['종료시간']
                        
                        if ad_time_corr >= ex_s_dt and ad_time_corr < ex_e_dt:
                            pos, prog_section = "중광고", f"● 프로그램 진행 중({ex_s_str}~{ex_e_str}) ●"
                        elif ad_time_corr < ex_s_dt: pos = "전광고"
                        else: pos = "후광고"

                    results.append({
                        '일자': pd.to_datetime(ref_date).strftime('%Y-%m-%d'),
                        '시작시간': row['시작일시'],
                        '종료시간': row['종료일시'],
                        '광고주': str(row['광고명']).split('_')[0] if '_' in str(row['광고명']) else "-",
                        '상품명': row['광고명'],
                        '광고유형': "",
                        '[프로그램 구간]': prog_section,
                        '매칭 프로그램명': prog_name,
                        '최종 판정 위치': pos,
                        '사유': match_reason
                    })
                else:
                    # [공백 구간 등 매칭 실패 케이스]
                    results.append({
                        '일자': pd.to_datetime(ref_date).strftime('%Y-%m-%d'),
                        '시작시간': row['시작일시'],
                        '종료시간': row['종료일시'],
                        '광고주': str(row['광고명']).split('_')[0] if '_' in str(row['광고명']) else "-",
                        '상품명': row['광고명'],
                        '광고유형': "",
                        '[프로그램 구간]': "",
                        '매칭 프로그램명': "미매칭",
                        '최종 판정 위치': "판정불가",
                        '사유': "검토 필요(편성 공백 구간)"
                    })

            if results:
                res_df = pd.DataFrame(results)
                st.subheader("📊 매칭 결과 리포트")
                st.dataframe(res_df, use_container_width=True)
                
                mmdd = pd.to_datetime(ref_date).strftime('%m%d')
                filename = f"(AIVAS)광고-프로그램_매칭_결과_{mmdd}({channel_name}).xlsx"
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Result')
                st.download_button(f"📥 {filename} 다운로드", output.getvalue(), filename)
