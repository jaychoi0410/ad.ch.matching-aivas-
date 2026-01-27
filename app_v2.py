import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 방송 시간(24시제) 및 날짜 처리 함수 (24시~29시 대응)
def handle_24h_time(date_str, time_str):
    try:
        if pd.isna(time_str) or str(time_str).strip() == "": return pd.NaT
        # 시간 문자열 분리 (HH:MM:SS)
        parts = str(time_str).strip().split(':')
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        
        # 날짜 정리 (YYYY-MM-DD)
        clean_date = str(date_str).replace('.', '-').split(' ')[0]
        if len(clean_date) == 8: # YYYYMMDD
            date_dt = datetime.strptime(clean_date, '%Y%m%d')
        else:
            date_dt = pd.to_datetime(clean_date)
            
        if h >= 24:
            days_to_add = h // 24
            actual_h = h % 24
            actual_date = date_dt + timedelta(days=days_to_add)
            return pd.to_datetime(f"{actual_date.strftime('%Y-%m-%d')} {actual_h:02d}:{m:02d}:{s:02d}")
        return pd.to_datetime(f"{date_dt.strftime('%Y-%m-%d')} {h:02d}:{m:02d}:{s:02d}")
    except:
        return pd.NaT

# 2. 파일 로더 및 분류 기능 강화
def smart_load_and_classify(uploaded_files):
    ad_data_list = []
    df_incl = None
    df_excl = None

    for file in uploaded_files:
        # 확장자에 따라 읽기
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            # 엑셀의 경우 헤더 위치 탐색 (0~5행)
            df = None
            for skip in range(6):
                temp = pd.read_excel(file, skiprows=skip)
                if not temp.empty:
                    df = temp
                    break
        
        if df is None: continue
        cols = df.columns.tolist()

        # [분류 A] 광고 탐지/영상 분석 파일
        # 광고소재ID(영상분석) 또는 Advertiser(광고탐지결과) 컬럼 확인
        if any(c in cols for c in ['광고소재ID', 'Advertiser', '광고명', 'Product']):
            ad_data_list.append((file.name, df))
        
        # [분류 B] 편성표 파일
        elif '프로그램' in cols:
            if '제외' in file.name or 'excl' in file.name.lower():
                df_excl = df
            else:
                df_incl = df
                
    return ad_data_list, df_incl, df_excl

# UI 설정
st.set_page_config(page_title="통합 광고-편성 매칭 시스템", layout="wide")
st.title("🕒 시간 기반 광고 포지션 판정 (최종 버전)")
st.markdown("영상분석/광고탐지 파일과 편성표를 모두 업로드하세요. **기존 리포트 양식**으로 자동 변환됩니다.")

uploaded_files = st.file_uploader(
    "📂 파일들을 한꺼번에 업로드 (영상분석, 광고탐지, 포함편성, 제외편성)", 
    type=['xlsx', 'csv'], 
    accept_multiple_files=True
)

if uploaded_files:
    ad_files, df_incl, df_excl = smart_load_and_classify(uploaded_files)

    # 상태 표시
    c1, c2, c3 = st.columns(3)
    c1.metric("광고/영상분석 파일", f"{len(ad_files)}개")
    c2.metric("포함 편성표", "✅ 로드됨" if df_incl is not None else "❌ 미확인")
    c3.metric("제외 편성표", "✅ 로드됨" if df_excl is not None else "❌ 미확인")

    if ad_files and df_incl is not None and df_excl is not None:
        if st.button("🚀 매칭 및 리포트 생성"):
            final_report = []
            
            for file_name, df_ad in ad_files:
                # 1. 광고 파일 컬럼 표준화
                # 날짜/시간 컬럼명 매핑 (다양한 양식 대응)
                col_date = '일자' if '일자' in df_ad.columns else '기준일자'
                col_start = '시작시간' if '시작시간' in df_ad.columns else '시작일시'
                col_end = '종료시간' if '종료시간' in df_ad.columns else '종료일시'
                col_prod = '상품명' if '상품명' in df_ad.columns else ('Product' if 'Product' in df_ad.columns else '광고명')
                col_adv = '광고주' if '광고주' in df_ad.columns else 'Advertiser'

                ref_date_raw = df_ad[col_date].iloc[0]
                # 시간 전처리
                df_ad['dt_start'] = df_ad.apply(lambda r: handle_24h_time(r[col_date], r[col_start]), axis=1)
                
                # 2. 편성표 시간 전처리
                tmp_incl = df_incl.dropna(subset=['프로그램', '시작시간']).copy()
                tmp_excl = df_excl.dropna(subset=['프로그램', '시작시간']).copy()
                
                for target in [tmp_incl, tmp_excl]:
                    target['dt_start'] = target.apply(lambda r: handle_24h_time(ref_date_raw, r['시작시간']), axis=1)
                    target['dt_end'] = target.apply(lambda r: handle_24h_time(ref_date_raw, r['종료시간']), axis=1)

                # 3. 매칭 루프
                for _, ad in df_ad.iterrows():
                    # "광고아님" 제외
                    if str(ad.get('광고소재ID', '')) == "광고아님" or str(ad.get(col_prod, '')) == "광고없음":
                        continue
                    
                    ad_t = ad['dt_start']
                    if pd.isna(ad_t): continue

                    # 프로그램 찾기
                    match = tmp_incl[(tmp_incl['dt_start'] <= ad_t) & (tmp_incl['dt_end'] > ad_t)]
                    
                    if not match.empty:
                        prog = match.iloc[0]['프로그램']
                        p_s, p_e = match.iloc[0]['시작시간'], match.iloc[0]['종료시간']
                        
                        # 포지션 판정
                        excl_info = tmp_excl[tmp_excl['프로그램'] == prog]
                        prog_section = ""
                        pos = "판정불가"
                        
                        if not excl_info.empty:
                            ex_s, ex_e = excl_info.iloc[0]['dt_start'], excl_info.iloc[0]['dt_end']
                            if ad_t >= ex_s and ad_t < ex_e:
                                pos = "중광고"
                                prog_section = f"● 프로그램 진행 중({p_s}~{p_e}) ●"
                            elif ad_t < ex_s:
                                pos = "전광고"
                            else:
                                pos = "후광고"

                        # 광고주 추출 로직
                        adv = str(ad.get(col_adv, "-"))
                        if adv == "nan" or adv == "-":
                            p_name = str(ad.get(col_prod, ""))
                            adv = p_name.split('_')[0] if '_' in p_name else "-"

                        final_report.append({
                            '일자': pd.to_datetime(str(ad[col_date]).split(' ')[0]).strftime('%Y-%m-%d'),
                            '시작시간': ad[col_start],
                            '종료시간': ad[col_end],
                            '광고주': adv,
                            '상품명': ad[col_prod],
                            '광고유형': ad.get('광고유형', 'PR'), # 기본값 PR
                            '[프로그램 구간]': prog_section,
                            '매칭 프로그램명': prog,
                            '최종 판정 위치': pos,
                            '사유': "정상 매칭"
                        })

            if final_report:
                res_df = pd.DataFrame(final_report)
                st.subheader("📊 매칭 결과 (기존 에이전트 양식 일치)")
                st.dataframe(res_df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Result')
                
                st.download_button(
                    label="📥 통합 매칭결과 다운로드 (Excel)", 
                    data=output.getvalue(), 
                    file_name=f"광고-프로그램_매칭_결과_{datetime.now().strftime('%m%d')}.xlsx",
                    mime="application/vnd.ms-excel"
                )
    else:
        st.warning("분석을 위해 3종류의 파일이 모두 필요합니다. (파일명에 '제외' 포함 및 광고 데이터 확인)")
