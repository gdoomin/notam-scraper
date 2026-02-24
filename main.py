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
    # 1. Supabase 설정
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    # 2. 다운로드 디렉토리 정리
    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    # 3. 브라우저 옵션 설정 (타임아웃 방어)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 페이지 로드 전략 설정 (DOM 구성까지만 기다림)
    options.page_load_strategy = 'eager'
    
    # 이미지 로딩 차단하여 속도 향상
    prefs = {
        "download.default_directory": download_dir,
        "safebrowsing.enabled": True,
        "profile.managed_default_content_settings.images": 2 
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    # 드라이버 수준 타임아웃 확장 (3분)
    driver.set_page_load_timeout(180)
    driver.set_script_timeout(180)
    wait = WebDriverWait(driver, 40)

    try:
        print("🌐 KOCA 페이지 접속 중 (타임아웃 대폭 확장)...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(30) # JS 완전 로딩 대기

        # 4. 전체 페이지 수 확인
        try:
            page_elements = driver.find_elements(By.CSS_SELECTOR, ".pagination a, .paging a, .page_num a")
            page_numbers = [int(el.text) for el in page_elements if el.text.strip().isdigit()]
            total_pages = max(page_numbers) if page_numbers else 1
        except:
            total_pages = 1
        
        print(f"📊 총 {total_pages}개 페이지 수집 시작")

        for p in range(1, total_pages + 1):
            print(f"📄 {p} / {total_pages} 페이지 작업 중...")
            
            if p > 1:
                # 다음 페이지 클릭 (숫자 텍스트 기준)
                page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, f"//a[text()='{p}']")))
                driver.execute_script("arguments[0].click();", page_btn)
                time.sleep(12) # 페이지 전환 및 테이블 갱신 대기

            # 5. 엑셀 다운로드 (정밀 XPath 사용)
            target_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
            excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", excel_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", excel_btn)
            
            # 다운로드 간격 유지
            time.sleep(15)

        print("⏳ 모든 파일 다운로드 대기 중...")
        time.sleep(10)

        # 6. 다운로드된 파일 병합
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 파일을 찾을 수 없습니다.")
            return

        print(f"📂 수집된 {len(files)}개 파일 병합 및 중복 제거 중...")
        all_dfs = []
        for f in files:
            try:
                # xlrd는 .xls 파일을 읽을 때 필요합니다.
                all_dfs.append(pd.read_excel(f, engine='xlrd'))
            except: continue

        if not all_dfs: return
        
        df = pd.concat(all_dfs, ignore_index=True)
        df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 유효 노탐 데이터 {len(df)}건 확보")

        # 7. 데이터 가공 및 Supabase 저장
        notam_list = []
        for _, row in df.iterrows():
            notam_id = str(row.get('Notam#', ''))
            full_text = str(row.get('Full Text', ''))
            lat, lng = extract_coords(full_text)
            
            notam_list.append({
                "notam_id": notam_id,
                "content": full_text,
                "lat": lat,
                "lng": lng,
                "series": notam_id[0] if notam_id else "U",
                "start_date": str(row.get('Start Date UTC', '')),
                "end_date": str(row.get('End Date UTC', ''))
            })

        if notam_list:
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"🚀 최종 성공: {len(notam_list)}개의 전체 노탐이 Supabase에 업데이트되었습니다.")

    except Exception as e:
        print(f"🚨 런타임 에러: {e}")
        driver.save_screenshot("timeout_debug.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
