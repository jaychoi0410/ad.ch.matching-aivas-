import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import re

# 1. 방송 시간(24시제) 처리 함수 (24시~29시 대응)
def handle_24h_time(date_str, time_str):
    try:
        if pd.isna(time_str) or str(time_str).strip() == "": return pd.NaT
        parts = str(time_str).strip().split(':')
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        
        if pd.isna(date_str): return pd.NaT
        
        # 날짜 정리
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

# 2. 파일 로더 및 날짜/채널 정보 추출 강화
def smart_load_and_classify(uploaded_files):
    ad_data_list = []
    df_incl, df_excl = None, None

    for file in uploaded_files:
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = None
            for skip in range(6):
                temp = pd.read_excel(file, skiprows=skip)
                if not temp.empty and ('프로그램' in temp.columns or '시작시간' in temp.columns or 'Advertiser' in temp.columns):
                    df = temp
                    break
        
        if df is None: continue
        
        # [핵심] 병합된 날짜 및 채널 셀 복구 (Forward Fill)
        for col in ['일자', '기준일자', '채널']:
            if col in df.columns:
                df[col] = df[col].ffill()

        cols = df.columns.tolist()
        # 광고 탐지 파일 판별
        if any(c in cols for c in ['광고소재ID', 'Advertiser', '광고명', 'Product']):
            ad_data_list.append((file.name, df))
        # 편성표 파일 판별
        elif '프로그램' in cols:
            if '제외' in file.name or 'excl' in file.name.lower():
                df_excl = df
            else:
                df_incl = df
                
    return ad_data_list, df_incl, df_excl

# UI 설정
st.set_page_config(page_title="AIVAS 광고-편성 매칭 시스템", layout="wide")
st.title("🕒 (AIVAS)TV광고-프로그램 편성 정보 매칭 시스템")

uploaded_files = st.file_uploader("📂 광고 탐지 및 편성표 파일들을 모두 업로드하세요", type=['xlsx', 'csv'], accept_multiple_files=True)

if uploaded_files:
    ad_files, df_incl, df_excl = smart_load_and_classify(uploaded_files)

    if ad_files and df_incl is not None and df_excl is not None:
        if st.button("🚀 매칭 분석 및 리포트 생성"):
            final_report = []
            output_channel = "채널미확인"
            output_mmdd = datetime.now().strftime('%m%d')
            
            for f_name, df_ad in ad_files:
                # 컬럼 매핑
                col_date = '일자' if '일자' in df_ad.columns else '기준일자'
                col_start = '시작시간' if '시작시간' in df_ad.columns else '시작일시'
                col_end = '종료시간' if '종료시간' in df_ad.columns else '종료일시'
                col_prod = '상품명' if '상품명' in df_ad.columns else ('Product' if 'Product' in df_ad.columns else '광고명')
                col_adv = '광고주' if '광고주' in df_ad.columns else 'Advertiser'
                
                # 채널명 및 날짜 정보 추출 (파일명 생성용)
                if '채널' in df_ad.columns:
                    output_channel = str(df_ad['채널'].dropna().iloc[0])
                
                first_date = df_ad[col_date].dropna().iloc[0]
                dt_obj = pd.to_datetime(str(first_date).replace('.', '-').split(' ')[0])
                output_mmdd = dt_obj.strftime('%m%d')

                # 편성표 전처리
                tmp_incl = df_incl.dropna(subset=['프로그램', '시작시간']).copy()
                tmp_excl = df_excl.dropna(subset=['프로그램', '시작시간']).copy()
                
                for target in [tmp_incl, tmp_excl]:
                    target['dt_start'] = target.apply(lambda r: handle_24h_time(first_date, r['시작시간']), axis=1)
                    target['dt_end'] = target.apply(lambda r: handle_24h_time(first_date, r['종료시간']), axis=1)

                # 광고 데이터 전처리
                df_ad['dt_start'] = df_ad.apply(lambda r: handle_24h_time(r[col_date], r[col_start]), axis=1)

                for _, ad in df_ad.iterrows():
                    p_name = str(ad.get(col_prod, ''))
                    if "광고없음" in p_name or "광고아님" in str(ad.get('광고소재ID', '')): continue
                    
                    ad_t = ad['dt_start']
                    if pd.isna(ad_t): continue

                    match = tmp_incl[(tmp_incl['dt_start'] <= ad_t) & (tmp_incl['dt_end'] > ad_t)]
                    
                    if not match.empty:
                        prog = match.iloc[0]['프로그램']
                        p_s, p_e = match.iloc[0]['시작시간'], match.iloc[0]['종료시간']
                        excl_info = tmp_excl[tmp_excl['프로그램'] == prog]
                        
                        prog_section, pos = "", "판정불가"
                        if not excl_info.empty:
                            ex_s, ex_e = excl_info.iloc[0]['dt_start'], excl_info.iloc[0]['dt_end']
                            if ad_t >= ex_s and ad_t < ex_e:
                                pos, prog_section = "중광고", f"● 프로그램 진행 중({p_s}~{p_e}) ●"
                            elif ad_t < ex_s: pos = "전광고"
                            else: pos = "후광고"

                        adv = str(ad.get(col_adv, "-"))
                        if adv in ["nan", "-", "None"]:
                            adv = p_name.split('_')[0] if '_' in p_name else "-"

                        final_report.append({
                            '일자': pd.to_datetime(str(ad[col_date])).strftime('%Y-%m-%d'),
                            '시작시간': ad[col_start],
                            '종료시간': ad[col_end],
                            '광고주': adv,
                            '상품명': p_name,
                            '광고유형': ad.get('광고유형', 'PR'),
                            '[프로그램 구간]': prog_section,
                            '매칭 프로그램명': prog,
                            '최종 판정 위치': pos,
                            '사유': "정상 매칭"
                        })

            if final_report:
                res_df = pd.DataFrame(final_report)
                st.success(f"✅ 분석 완료! 총 {len(res_df)}건의 데이터를 매칭했습니다.")
                st.dataframe(res_df, use_container_width=True)
                
                # 파일명 생성: (AIVAS)광고-프로그램_매칭_결과_MMDD(채널명).xlsx
                final_filename = f"(AIVAS)광고-프로그램_매칭_결과_{output_mmdd}({output_channel}).xlsx"
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Result')
                
                st.download_button(
                    label=f"📥 {final_filename} 다운로드", 
                    data=output.getvalue(), 
                    file_name=final_filename,
                    mime="application/vnd.ms-excel"
                )
    else:
        st.warning("분석을 위해 3종류의 파일(광고데이터, 포함편성표, 제외편성표)이 필요합니다.")

