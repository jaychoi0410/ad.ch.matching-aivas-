import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io

# 1. 방송 시간(24시제) 처리 함수
def handle_24h_time(date_str, time_str):
    try:
        h, m, s = map(int, str(time_str).split(':'))
        date_str = str(date_str).replace('-', '').replace('.', '')
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
st.title("🕒 통합 시간 기반 광고 포지션 판정 시스템")
st.markdown("모든 파일(영상분석, 포함편성, 제외편성)을 **한 번에 업로드** 하세요. 시스템이 자동으로 분류합니다.")

# 2. 통합 파일 업로드
uploaded_files = st.file_uploader(
    "📂 관련 파일을 모두 선택하여 끌어다 놓으세요 (XLSX, CSV)", 
    type=['xlsx', 'csv'], 
    accept_multiple_files=True
)

if uploaded_files:
    ad_files = []
    df_incl = None
    df_excl = None

    # 파일 자동 분류 로직
    for file in uploaded_files:
        # 편성표는 보통 위쪽 3행이 타이틀이므로 4행(skiprows=3)부터 읽어 확인
        try:
            # 우선 헤더 없이 읽어서 판단
            sample_df = pd.read_excel(file, nrows=10)
            
            # 영상분석 파일 판별: '광고소재ID'나 '광고명' 컬럼이 있는 경우
            if any(col in sample_df.columns for col in ['광고소재ID', '광고명', '시작일시']):
                ad_files.append(file)
            else:
                # 편성표 판별 (3행 건너뛰고 '프로그램' 컬럼 확인)
                sched_df = pd.read_excel(file, skiprows=3)
                if '프로그램' in sched_df.columns:
                    if '제외' in file.name:
                        df_excl = sched_df
                    else:
                        df_incl = sched_df
        except Exception as e:
            st.error(f"파일 분석 중 오류 발생 ({file.name}): {e}")

    # 분류 상태 표시
    c1, c2, c3 = st.columns(3)
    c1.metric("영상분석 파일", f"{len(ad_files)}개")
    c2.metric("포함 편성표", "✅ 로드됨" if df_incl is not None else "❌ 미확인")
    c3.metric("제외 편성표", "✅ 로드됨" if df_excl is not None else "❌ 미확인")

    if ad_files and df_incl is not None and df_excl is not None:
        if st.button("🚀 통합 분석 시작"):
            all_reports = []
            
            for ad_file in ad_files:
                df_ad = pd.read_excel(ad_file)
                if df_ad.empty: continue
                
                # 기준일자 설정
                ref_date = str(df_ad['기준일자'].iloc[0])
                
                # 시간 데이터 전처리
                df_ad['start_dt'] = df_ad.apply(lambda r: handle_24h_time(r['기준일자'], r['시작일시']), axis=1)
                
                # 편성표 시간 변환 (사본 사용)
                tmp_incl = df_incl.copy()
                tmp_excl = df_excl.copy()
                
                for df in [tmp_incl, tmp_excl]:
                    df['start_dt'] = df.apply(lambda r: handle_24h_time(ref_date, r['시작시간']), axis=1)
                    df['end_dt'] = df.apply(lambda r: handle_24h_time(ref_date, r['종료시간']), axis=1)

                # 매칭 루프
                for _, ad in df_ad.iterrows():
                    if ad['광고소재ID'] == "광고아님": continue
                    
                    ad_start = ad['start_dt']
                    matched_incl = tmp_incl[(tmp_incl['start_dt'] <= ad_start) & (tmp_incl['end_dt'] > ad_start)]
                    
                    if not matched_incl.empty:
                        target_prog = matched_incl.iloc[0]['프로그램']
                        prog_times = f"{matched_incl.iloc[0]['시작시간']}~{matched_incl.iloc[0]['종료시간']}"
                        
                        target_excl = tmp_excl[tmp_excl['프로그램'] == target_prog]
                        
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
                            final_pos = "판정불가(제외편성미매칭)"
                            
                        all_reports.append({
                            '파일명': ad_file.name,
                            '일자': ad['기준일자'],
                            '시작시간': ad['시작일시'],
                            '종료시간': ad['종료일시'],
                            '상품명': ad['광고명'],
                            '[프로그램 구간]': f"● {target_prog} ({prog_times}) ●",
                            '매칭 프로그램명': target_prog,
                            '최종 판정 위치': final_pos,
                            '비고': "자동매칭완료"
                        })

            if all_reports:
                result_df = pd.DataFrame(all_reports)
                st.subheader("📊 통합 분석 결과")
                st.dataframe(result_df, use_container_width=True)

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    result_df.to_excel(writer, index=False)
                
                st.download_button(
                    label="📥 통합 결과 리포트 다운로드 (Excel)",
                    data=output.getvalue(),
                    file_name=f"통합_분석결과_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.ms-excel"
                )
    else:
        st.warning("분석에 필요한 모든 파일이 감지되지 않았습니다. 파일명에 '제외'가 포함되어 있는지 확인해주세요.")
else:
    st.info("파일들을 업로드창에 한꺼번에 올려주세요.")
