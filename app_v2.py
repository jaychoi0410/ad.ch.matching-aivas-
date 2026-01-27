import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 방송 시간(24시제) 및 날짜 처리 함수
def handle_24h_time(date_str, time_str):
    try:
        if pd.isna(time_str) or str(time_str).strip() == "": return pd.NaT
        h, m, s = map(int, str(time_str).split(':'))
        # 날짜 포맷 정리
        clean_date = str(date_str).replace('-', '').replace('.', '').split(' ')[0]
        if len(clean_date) == 8:
            date_dt = datetime.strptime(clean_date, '%Y%m%d')
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

# 2. 파일 로더 함수 (Excel/CSV 및 헤더 자동 탐색)
def smart_load_df(file):
    try:
        if file.name.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        # '프로그램' 컬럼이 없으면 헤더 위치(skiprows)를 바꿔가며 재시도
        if '프로그램' not in df.columns and not any(c in df.columns for c in ['광고소재ID', '광고명']):
            for i in range(1, 6):
                df_retry = pd.read_excel(file, skiprows=i)
                if '프로그램' in df_retry.columns:
                    return df_retry
        return df
    except Exception as e:
        st.error(f"파일 로드 오류 ({file.name}): {e}")
        return None

# UI 설정
st.set_page_config(page_title="AI 영상분석 매칭 에이전트", layout="wide")
st.title("🕒 통합 광고 포지션 판정 시스템 (기존 양식 호환)")

uploaded_files = st.file_uploader(
    "📂 파일들을 한꺼번에 업로드하세요 (영상분석, 포함편성, 제외편성)", 
    type=['xlsx', 'csv'], 
    accept_multiple_files=True
)

if uploaded_files:
    ad_files = []
    df_incl = None
    df_excl = None

    for file in uploaded_files:
        df = smart_load_df(file)
        if df is None: continue
        
        cols = df.columns.tolist()
        if any(c in cols for c in ['광고소재ID', '광고명']):
            ad_files.append((file.name, df))
        elif '프로그램' in cols:
            if '제외' in file.name or 'excl' in file.name.lower():
                df_excl = df
            else:
                df_incl = df

    # 분류 상태 확인
    c1, c2, c3 = st.columns(3)
    c1.metric("영상분석 파일", f"{len(ad_files)}개")
    c2.metric("포함 편성표", "✅ 로드됨" if df_incl is not None else "❌ 미확인")
    c3.metric("제외 편성표", "✅ 로드됨" if df_excl is not None else "❌ 미확인")

    if ad_files and df_incl is not None and df_excl is not None:
        if st.button("🚀 분석 실행 및 리포트 생성"):
            all_reports = []
            
            for file_name, df_ad in ad_files:
                ref_date_raw = df_ad['기준일자'].iloc[0]
                # 날짜 형식 표준화 (YYYY-MM-DD)
                ref_date_dt = pd.to_datetime(str(ref_date_raw).split(' ')[0])
                ref_date_str = ref_date_dt.strftime('%Y-%m-%d')
                
                # 영상분석 데이터 전처리
                df_ad['start_dt'] = df_ad.apply(lambda r: handle_24h_time(r['기준일자'], r['시작일시']), axis=1)
                
                # 편성표 전처리
                tmp_incl = df_incl.dropna(subset=['프로그램', '시작시간']).copy()
                tmp_excl = df_excl.dropna(subset=['프로그램', '시작시간']).copy()
                
                for df_target in [tmp_incl, tmp_excl]:
                    df_target['start_dt'] = df_target.apply(lambda r: handle_24h_time(ref_date_str, r['시작시간']), axis=1)
                    df_target['end_dt'] = df_target.apply(lambda r: handle_24h_time(ref_date_str, r['종료시간']), axis=1)

                # 매칭 루프
                for _, ad in df_ad.iterrows():
                    if str(ad.get('광고소재ID', '')) == "광고아님": continue
                    
                    ad_start = ad['start_dt']
                    if pd.isna(ad_start): continue

                    # 1. 포함 편성표에서 프로그램 찾기
                    matched = tmp_incl[(tmp_incl['start_dt'] <= ad_start) & (tmp_incl['end_dt'] > ad_start)]
                    
                    if not matched.empty:
                        prog_name = matched.iloc[0]['프로그램']
                        prog_start = matched.iloc[0]['시작시간']
                        prog_end = matched.iloc[0]['종료시간']
                        
                        # 2. 제외 편성표로 포지션 판정
                        excl_match = tmp_excl[tmp_excl['프로그램'] == prog_name]
                        
                        prog_interval_str = "" # 기본값 (전/후광고 시 공란)
                        final_pos = "판정불가"
                        
                        if not excl_match.empty:
                            ex_s = excl_match.iloc[0]['start_dt']
                            ex_e = excl_match.iloc[0]['end_dt']
                            
                            if ad_start >= ex_s and ad_start < ex_e:
                                final_pos = "중광고"
                                prog_interval_str = f"● 프로그램 진행 중({prog_start}~{prog_end}) ●"
                            elif ad_start < ex_s:
                                final_pos = "전광고"
                            else:
                                final_pos = "후광고"
                        
                        # 광고주 추출 (상품명에서 '_' 앞부분)
                        ad_name = str(ad['광고명'])
                        advertiser = ad_name.split('_')[0] if '_' in ad_name else "-"

                        all_reports.append({
                            '일자': ref_date_str,
                            '시작시간': ad['시작일시'],
                            '종료시간': ad['종료일시'],
                            '광고주': advertiser,
                            '상품명': ad_name,
                            '광고유형': "영상분석",
                            '[프로그램 구간]': prog_interval_str,
                            '매칭 프로그램명': prog_name,
                            '최종 판정 위치': final_pos,
                            '사유': "정상 매칭(시간기반)"
                        })

            if all_reports:
                res_df = pd.DataFrame(all_reports)
                st.subheader("📊 매칭 결과 (기존 양식 동일)")
                st.dataframe(res_df, use_container_width=True)
                
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    res_df.to_excel(writer, index=False, sheet_name='Result')
                
                st.download_button(
                    label="📥 통합 결과 리포트 다운로드", 
                    data=output.getvalue(), 
                    file_name=f"광고-프로그램_매칭_결과_{datetime.now().strftime('%m%d')}.xlsx",
                    mime="application/vnd.ms-excel"
                )
    else:
        st.warning("분석을 위해 3종류의 파일이 모두 필요합니다. (파일명에 '제외' 포함 확인)")
