import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 시간 처리 및 보정 함수
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

# 2. 파일 로더
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
st.set_page_config(page_title="AIVAS 지능형 매칭 v13", layout="wide")
st.title("🕒 (AIVAS) 지능형 광고 매칭 및 자동 분류 시스템")
st.markdown("상품명 키워드 분석을 통해 **PR/Non-PR을 자동으로 구분**하고 리포트를 생성합니다.")

# 키워드 사전 설정
default_keywords = "국제구조위원회, 유니세프, 공익광고, 방송통신심의위원회, 캠페인, 정부혁신, 환경부, 보건복지부, 협찬"

with st.sidebar:
    st.header("⚙️ 시스템 설정")
    time_offset = st.number_input("AIVAS 시간 보정값 (초)", value=-3)
    buffer_val = st.slider("경계면 보호 버퍼 (초)", 0, 30, 15)
    st.divider()
    st.subheader("🔍 Non-PR 필터 키워드")
    kw_input = st.text_area("쉼표로 구분하여 입력", default_keywords)
    filter_keywords = [k.strip() for k in kw_input.split(',')]

uploaded_files = st.file_uploader("📂 파일 3개를 업로드하세요", type=['xlsx', 'csv'], accept_multiple_files=True)

if uploaded_files:
    df_ad, df_incl, df_excl = load_and_classify(uploaded_files)
    
    if df_ad is not None and df_incl is not None and df_excl is not None:
        if st.button("🚀 지능형 리포트 생성"):
            ref_date = str(df_ad['기준일자'].iloc[0])
            channel_name = str(df_ad['채널'].iloc[0]) if '채널' in df_ad.columns else "채널미확인"
            broadcast_start_dt = handle_24h_time(ref_date, "02:00:00")
            
            for target in [df_incl, df_excl]:
                target['dt_start'] = target.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                target['dt_end'] = target.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

            results = []
            df_ad = df_ad.sort_values(by='시작일시').reset_index(drop=True)

            for _, row in df_ad.iterrows():
                if "광고없음" in str(row['광고명']) or str(row['광고소재ID']) == "광고아님": continue
                
                ad_time_end = handle_24h_time(row['기준일자'], row['종료일시'])
                if ad_time_end < broadcast_start_dt: continue
                
                ad_time_corr = handle_24h_time(row['기준일자'], row['시작일시'], offset_sec=time_offset)
                if pd.isna(ad_time_corr): continue

                # [v13 핵심] Non-PR 키워드 검사
                is_non_pr = any(k in str(row['광고명']) for k in filter_keywords)
                ad_type = "Non-PR" if is_non_pr else "PR"
                
                match = df_incl[(df_incl['dt_start'] <= ad_time_corr) & (df_incl['dt_end'] > ad_time_corr)]
                
                if not match.empty:
                    prog_name = match.iloc[0]['프로그램']
                    excl_info = df_excl[df_excl['프로그램'] == prog_name]
                    prog_section, pos, reason = "", "판정불가", "정상 매칭"
                    
                    if is_non_pr:
                        reason = "공익광고 추정 - 미매칭 처리"
                    elif not excl_info.empty:
                        ex_s_dt, ex_e_dt = excl_info.iloc[0]['dt_start'], excl_info.iloc[0]['dt_end']
                        ex_s_str, ex_e_str = excl_info.iloc[0]['시작시간'], excl_info.iloc[0]['종료시간']
                        
                        if ad_time_corr >= ex_s_dt and ad_time_corr < ex_e_dt:
                            if ad_time_corr < (ex_s_dt + timedelta(seconds=buffer_val)):
                                pos, reason = "전광고", f"경계면 보정(시작+{buffer_val}s)"
                            elif ad_time_corr >= (ex_e_dt - timedelta(seconds=buffer_val)):
                                pos, reason = "후광고", f"경계면 보정(종료-{buffer_val}s)"
                            else:
                                pos = "중광고"
                                prog_section = f"● 프로그램 진행 중({ex_s_str}~{ex_e_str}) ●"
                        elif ad_time_corr < ex_s_dt: pos = "전광고"
                        else: pos = "후광고"

                    results.append({
                        '일자': pd.to_datetime(ref_date).strftime('%Y-%m-%d'),
                        '시작시간': row['시작일시'], '종료시간': row['종료일시'],
                        '광고주': str(row['광고명']).split('_')[0] if '_' in str(row['광고명']) else "-",
                        '상품명': row['광고명'], '광고유형': ad_type,
                        '[프로그램 구간]': prog_section, '매칭 프로그램명': prog_name,
                        '최종 판정 위치': pos, '사유': reason
                    })
                else:
                    results.append({
                        '일자': pd.to_datetime(ref_date).strftime('%Y-%m-%d'),
                        '시작시간': row['시작일시'], '종료시간': row['종료일시'],
                        '광고주': "-", '상품명': row['광고명'], '광고유형': ad_type,
                        '[프로그램 구간]': "", '매칭 프로그램명': "미매칭",
                        '최종 판정 위치': "판정불가", '사유': "검토 필요(편성 공백)"
                    })

            # 광고 없는 프로그램 블록 추가 (v12 유지)
            current_res_df = pd.DataFrame(results)
            day_progs = df_excl[df_excl['dt_end'] > broadcast_start_dt].copy()
            for _, p_row in day_progs.iterrows():
                p_name = p_row['프로그램']
                has_midroll = not current_res_df[(current_res_df['매칭 프로그램명'] == p_name) & 
                                                 (current_res_df['최종 판정 위치'] == '중광고')].empty
                if not has_midroll:
                    results.append({
                        '일자': pd.to_datetime(ref_date).strftime('%Y-%m-%d'),
                        '시작시간': p_row['시작시간'], '종료시간': p_row['종료시간'],
                        '광고주': "-", '상품명': "탐지된 광고 없음", '광고유형': "",
                        '[프로그램 구간]': f"● 프로그램 진행 중({p_row['시작시간']}~{p_row['종료시간']}) ●",
                        '매칭 프로그램명': p_name, '최종 판정 위치': "중광고", '사유': "탐지광고없음"
                    })

            final_df = pd.DataFrame(results)
            final_df['_sort_key'] = final_df['시작시간'].apply(lambda x: sum(int(a) * 60**i for i, a in enumerate(reversed(str(x).split(':')))))
            final_df = final_df.sort_values(by='_sort_key').drop(columns=['_sort_key']).reset_index(drop=True)

            st.dataframe(final_df, use_container_width=True)
            mmdd = pd.to_datetime(ref_date).strftime('%m%d')
            filename = f"(AIVAS)광고-프로그램_매칭_결과_{mmdd}({channel_name}).xlsx"
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False, sheet_name='Result')
            st.download_button(f"📥 {filename} 다운로드", output.getvalue(), filename)
