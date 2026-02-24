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

# --- 좌표 파싱 함수 (Q라인에서 좌표 추출) ---
def extract_coords(full_text):
    try:
        # Q) 라인에서 3726N12706E 형태의 패턴 검색
        match = re.search(r'(\d{4}[NS])(\d{5}[EW])', full_text)
        if match:
            lat_str, lng_str = match.groups()
            # 위도 변환
            lat = int(lat_str[:2]) + int(lat_str[2:4])/60
            if 'S' in lat_str: lat = -lat
            # 경도 변환
            lng = int(lng_str[:3]) + int(lng_str[3:5])/60
            if 'W' in lng_str: lng = -lng
            return lat, lng
    except:
        pass
    return 37.5665, 126.9780 # 실패 시 기본값 (서울)

def run_scraper():
    # 1. 환경 설정 (Supabase)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("🚨 환경 변수가 설정되지 않았습니다.")
        return
    supabase: Client = create_client(url, key)

    # 2. 브라우저 및 다운로드 설정
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # 3. KOCA 사이트 접속
        print("🌐 KOCA 접속 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        
        # 페이지 로딩을 위해 충분히 대기
        wait = WebDriverWait(driver, 30)
        time.sleep(15) 

        # 4. EXCEL 버튼 찾기 및 클릭
        print("🖱 EXCEL 버튼 검색 중...")
        excel_btn = None
        try:
            # 시도 1: ID로 찾기
            excel_btn = wait.until(EC.presence_of_element_located((By.ID, "btn_excel")))
            print("✅ 버튼 ID('btn_excel') 발견")
        except:
            # 시도 2: 텍스트로 찾기
            try:
                excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(.,'EXCEL')]")))
                print("✅ 버튼 텍스트('EXCEL') 기반 발견")
            except Exception as e:
                print(f"🚨 버튼을 찾을 수 없습니다: {e}")
                driver.save_screenshot("button_error.png")
                return

        # 강제 클릭 실행
        driver.execute_script("arguments[0].scrollIntoView(true);", excel_btn)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", excel_btn)
        
        print("⏳ 다운로드 대기 중 (30초)...")
        time.sleep(30)

        # 5. 다운로드된 파일 확인
        files = [f for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 엑셀 파일을 찾지 못했습니다. 목록:", os.listdir(download_dir))
            driver.save_screenshot("download_error.png")
            return

        file_path = os.path.join(download_dir, files[-1])
        print(f"📖 파일 파싱 중: {file_path}")
        
        # 6. 데이터 가공 (Pandas)
        df = pd.read_excel(file_path, engine='xlrd')
        
        notam_list = []
        for _, row in df.iterrows():
            notam_id = str(row.get('Notam#', ''))
            full_text = str(row.get('Full Text', ''))
            
            # 좌표 추출 로직 실행
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

        # 7. Supabase Upsert (중복 시 업데이트)
        if notam_list:
            # 10분마다 실행되므로, 기존 데이터를 지우고 새로 넣거나 upsert를 사용합니다.
            # 여기서는 편의상 upsert(notam_id 기준)를 사용합니다.
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"✅ 성공: {len(notam_list)}개의 노탐 정보가 Supabase에 저장되었습니다.")

    except Exception as e:
        print(f"🚨 런타임 에러: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
