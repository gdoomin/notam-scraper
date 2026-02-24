import os
import time
import re
import shutil
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client

def extract_coords(full_text):
    try:
        match = re.search(r'(\d{4}[NS])(\d{5}[EW])', full_text)
        if match:
            lat_str, lng_str = match.groups()
            lat = int(lat_str[:2]) + int(lat_str[2:4])/60
            if 'S' in lat_str: lat = -lat
            lng = int(lng_str[:3]) + int(lng_str[3:5])/60
            if 'W' in lng_str: lng = -lng
            return lat, lng
    except: pass
    return 37.5665, 126.9780

def run_scraper():
    # 1. Supabase 및 디렉토리 설정
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    # 2. 브라우저 옵션 설정
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.page_load_strategy = 'eager'
    prefs = {
        "download.default_directory": download_dir,
        "safebrowsing.enabled": True,
        "profile.managed_default_content_settings.images": 2 
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(180)
    wait = WebDriverWait(driver, 40)

    try:
        print("🌐 KOCA 접속 및 초기화...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(30) 

        print("📊 멀티 페이지 수집 및 파일 충돌 방지 로직 가동...")
        
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
                    print(f"   -> 더 이상 페이지가 없습니다. (종료)")
                    break

            # A. 엑셀 다운로드 클릭
            excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
            excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, excel_xpath)))
            driver.execute_script("arguments[0].click();", excel_btn)
            print(f"   -> {p}페이지 다운로드 요청")
            
            # B. 파일 이름 즉시 변경 (중복 방지 핵심 로직)
            renamed = False
            for _ in range(30): # 최대 30초 대기
                time.sleep(1)
                # 다운로드 중인 임시 파일(.crdownload) 제외하고 실제 파일만 목록화
                current_files = [f for f in os.listdir(download_dir) if not f.endswith('.crdownload') and not f.startswith('page_')]
                if current_files:
                    target_file = current_files[0]
                    old_path = os.path.join(download_dir, target_file)
                    new_filename = f"page_{p}_{target_file}"
                    new_path = os.path.join(download_dir, new_filename)
                    
                    try:
                        os.rename(old_path, new_path)
                        print(f"   -> 파일 이름 변경 완료: {new_filename}")
                        renamed = True
                        break
                    except Exception as e:
                        print(f"   -> 이름 변경 대기 중... ({e})")
                
            if not renamed:
                print(f"   ⚠️ {p}페이지 파일 다운로드 확인 실패")

        # 3. 모든 개별 파일 병합
        all_files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith("page_")]
        print(f"📂 총 {len(all_files)}개 파일 병합 시작...")
        
        all_dfs = []
        for f in all_files:
            try:
                # KOCA 엑셀은 xlrd 엔진이 필요함
                temp_df = pd.read_excel(f, engine='xlrd')
                all_dfs.append(temp_df)
                print(f"   -> {os.path.basename(f)} 읽기 완료 ({len(temp_df)}행)")
            except Exception as e:
                print(f"   ⚠️ {f} 파싱 실패: {e}")

        if not all_dfs:
            print("🚨 병합할 데이터가 없습니다.")
            return
        
        full_df = pd.concat(all_dfs, ignore_index=True)
        # Notam# 컬럼 기준으로 중복 제거
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 중복 제거 후 최종 {len(full_df)}건의 노탐 데이터 확보")

        # 4. 가공 및 Supabase 업로드
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
            print(f"🚀 [최종 성공] {len(notam_list)}개의 노탐 데이터가 Supabase에 저장되었습니다!")

    except Exception as e:
        print(f"🚨 런타임 에러: {e}")
        driver.save_screenshot("file_collision_debug.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
