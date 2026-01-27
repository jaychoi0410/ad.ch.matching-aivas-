import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 방송 시간(24시제) 처리
def handle_24h_time(date_str, time_str):
    try:
        if pd.isna(time_str) or str(time_str).strip() == "": return pd.NaT
        parts = str(time_str).strip().split(':')
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        
        # 날짜가 NaT인 경우 대비
        if pd.isna(date_str): return pd.NaT
        
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

# 2. 스마트 로더 (병합된 날짜 셀 복구 기능 추가)
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
                if not temp.empty and ('프로그램' in temp.columns or '시작시간' in temp.columns):
                    df = temp
                    break
        
        if df is None: continue
        
        # [핵심 수정] 날짜 컬럼이 비어있으면 위에서 아래로 채워줌 (Forward Fill)
        for col in ['일자', '기준일자']:
            if col in df.columns:
                df[col] = df[col].ffill()

        cols = df.columns.tolist()
        if any(c in cols for c in ['광고소재ID', 'Advertiser', '광고명', 'Product']):
            ad_data_list.append((file.name, df))
        elif '프로그램' in cols:
            if '제외' in file.name or 'excl' in file.name.lower():
                df_excl = df
            else:
                df_incl = df
                
    return ad_data_list, df_incl, df_excl

st.set_page_config(page_title="통합 광고 매칭 시스템", layout="wide")
st.title("🕒 시간 기반 광고 포지션 판정 (누락 해결 버전)")

uploaded_files = st.file_uploader("📂 파일 3개를 한꺼번에 업로드", type=['xlsx', 'csv'], accept_multiple_files=True)

if uploaded_files:
    ad_files, df_incl, df_excl = smart_load_and_classify(uploaded_files)

    if ad_files and df_incl is not None and df_excl is not None:
        if st.button("🚀 전체 데이터 분석 시작"):
            final_report = []
            
            for f_name, df_ad in ad_files:
                col_date = '일자' if '일자' in df_ad.columns else '기준일자'
                col_start = '시작시간' if '시작시간' in df_ad.columns else '시작일시'
                col_end = '종료시간' if '종료시간' in df_ad.columns else '종료일시'
                col_prod = '상품명' if '상품명' in df_ad.columns else ('Product' if 'Product' in df_ad.columns else '광고명')
                col_adv = '광고주' if '광고주' in df_ad.columns else 'Advertiser'

                # 편성표 전처리 (기준일자는 광고파일의 첫 행 활용)
                ref_date = df_ad[col_date].dropna().iloc[0]
                
                tmp_incl = df_incl.dropna(subset=['프로그램', '시작시간']).copy()
                tmp_excl = df_excl.dropna(subset=['프로그램', '시작시간']).copy()
                
                for target in [tmp_incl, tmp_excl]:
                    target['dt_start'] = target.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                    target['dt_end'] = target.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

                # 광고 데이터 시간 변환
                df_ad['dt_start'] = df_ad.apply(lambda r: handle_24h_time(r[col_date], r[col_start]), axis=1)

                for _, ad in df_ad.iterrows():
                    # 필터링 (광고없음 등 제외)
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
                st.success(f"총 {len(res_df)}건의 매칭 데이터를 찾았습니다!")
                st.dataframe(res_df, use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Result')
                st.download_button("📥 통합 결과 다운로드", output.getvalue(), f"매칭결과_{datetime.now().strftime('%H%M')}.xlsx")
    else:
        st.warning("파일 분류 실패. 영상분석/광고탐지 파일과 포함/제외 편성표 3종이 모두 필요합니다.")
