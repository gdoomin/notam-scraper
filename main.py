import os
import time
import re
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client

# --- 좌표 파싱 함수 ---
def extract_coords(full_text):
    """Q) 라인에서 도분(DMS) 형태의 좌표를 소수점(Decimal)으로 변환"""
    try:
        # Q) 라인에서 좌표 패턴 찾기 (예: 3726N12706E)
        match = re.search(r'(\d{4}[NS])(\d{5}[EW])', full_text)
        if match:
            lat_str, lng_str = match.groups()
            lat = int(lat_str[:2]) + int(lat_str[2:4])/60
            if 'S' in lat_str: lat = -lat
            lng = int(lng_str[:3]) + int(lng_str[3:5])/60
            if 'W' in lng_str: lng = -lng
            return lat, lng
    except:
        pass
    return 37.5665, 126.9780 # 기본값: 서울

def run_scraper():
    # 1. 환경 변수 및 브라우저 설정
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "directory_upgrade": True
    }
    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("🌐 KOCA 접속 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(10)

        # 2. EXCEL 버튼 클릭
        print("🖱 EXCEL 다운로드 시도...")
        excel_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'EXCEL')] | //*[@id='btn_excel']"))
        )
        driver.execute_script("arguments[0].click();", excel_btn)
        
        # 다운로드 대기 (넉넉히 30초)
        time.sleep(30)

        # 3. 파일 읽기 및 데이터 가공
        files = [f for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 엑셀 파일을 찾을 수 없습니다.")
            return

        file_path = os.path.join(download_dir, files[-1]) # 가장 최근 파일
        print(f"📖 파일 파싱 중: {file_path}")
        
        # xlrd 엔진을 사용하여 .xls 파일 읽기
        df = pd.read_excel(file_path, engine='xlrd')

        update_data = []
        for _, row in df.iterrows():
            notam_id = str(row.get('Notam#', ''))
            full_text = str(row.get('Full Text', ''))
            
            lat, lng = extract_coords(full_text)
            
            update_data.append({
                "notam_id": notam_id,
                "content": full_text,
                "lat": lat,
                "lng": lng,
                "series": notam_id[0] if notam_id else "U",
                "start_date": str(row.get('Start Date UTC', '')),
                "end_date": str(row.get('End Date UTC', ''))
            })

        # 4. Supabase 저장 (Upsert 방식: 중복은 덮어쓰고 새것은 추가)
        if update_data:
            supabase.table("notams_excel").upsert(update_data, on_conflict="notam_id").execute()
            print(f"✅ 성공: {len(update_data)}개의 노탐 데이터를 저장했습니다.")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
