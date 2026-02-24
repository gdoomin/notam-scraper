import os
import time
import re
import shutil
import pandas as pd
from selenium import webdriver
# ... (상단 import 생략) ...

def run_scraper():
    # ... (Supabase 설정 및 브라우저 옵션 생략) ...

    try:
        print("🌐 KOCA 접속 및 초기화...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(30) 

        print("📊 멀티 페이지 수집 시작 (파일 이름 변경 로직 추가)...")
        
        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 중...")
            
            if p > 1:
                try:
                    td_idx = p + 3 
                    page_xpath = f'//*[@id="notamSheet-table"]/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 이동 성공")
                    time.sleep(15) 
                except:
                    print(f"   -> {p}페이지 버튼 없음 (종료)")
                    break

            # 1. 엑셀 다운로드 클릭
            excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
            excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, excel_xpath)))
            driver.execute_script("arguments[0].click();", excel_btn)
            print(f"   -> {p}페이지 다운로드 요청")
            
            # 2. 파일이 생성될 때까지 감시 및 이름 변경 (핵심!)
            downloaded = False
            for _ in range(30): # 최대 30초 대기
                time.sleep(1)
                files = [f for f in os.listdir(download_dir) if not f.endswith('.crdownload')]
                if files:
                    # 방금 다운로드된 파일을 'page_p.xls' 형태로 변경
                    for f in files:
                        if not f.startswith("page_"):
                            old_path = os.path.join(download_dir, f)
                            new_path = os.path.join(download_dir, f"page_{p}_{f}")
                            os.rename(old_path, new_path)
                            print(f"   -> 파일 저장 완료: page_{p}_{f}")
                            downloaded = True
                            break
                if downloaded: break
            
        # 3. 모든 파일 병합
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith("page_")]
        print(f"📂 총 {len(files)}개 파일 통합 시작...")
        
        all_dfs = []
        for f in files:
            try:
                all_dfs.append(pd.read_excel(f, engine='xlrd'))
            except Exception as e:
                print(f"⚠️ {f} 읽기 실패: {e}")

        if not all_dfs: return
        
        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 중복 제거 후 최종 {len(full_df)}건 확보!")

        # ... (이후 Supabase 업로드 로직 동일) ...

        notam_list = []
        for _, row in full_df.iterrows():
            notam_id = str(row.get('Notam#', ''))
            full_text = str(row.get('Full Text', ''))
            lat, lng = extract_coords(full_text)
            notam_list.append({
                "notam_id": notam_id, "content": full_text, "lat": lat, "lng": lng,
                "series": notam_id[0] if notam_id else "U",
                "start_date": str(row.get('Start Date UTC', '')),
                "end_date": str(row.get('End Date UTC', ''))
            })

        if notam_list:
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"🚀 [성공] 총 {len(notam_list)}개의 노탐이 Supabase에 업데이트되었습니다!")

    except Exception as e:
        print(f"🚨 치명적 에러: {e}")
        driver.save_screenshot("pagination_error.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
