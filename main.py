import os
import time
import re
import json
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from supabase import create_client, Client
import xml.etree.ElementTree as ET

def run_scraper():
    # 1. 환경 설정
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    prefs = {"download.default_directory": download_dir}
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # 2. KML 다운로드
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(10)
        kml_btn = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'KML')] | //*[@id='btn_kml']")))
        driver.execute_script("arguments[0].click();", kml_btn)
        time.sleep(20) # 다운로드 대기
        
        # 3. KML 파싱
        files = os.listdir(download_dir)
        if not files: return
        
        file_path = os.path.join(download_dir, files[0])
        tree = ET.parse(file_path)
        root = tree.getroot()
        # 네임스페이스 정의 (KML 태그 인식용)
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}

        notam_list = []
        for pm in root.findall('.//kml:Placemark', ns):
            notam_id = pm.get('id')
            desc = pm.find('kml:description', ns).text if pm.find('kml:description', ns) is not None else ""
            coords_text = pm.find('.//kml:coordinates', ns).text.strip()
            
            # 좌표 분리 (경도, 위도, 고도 순)
            lng, lat, _ = map(float, coords_text.split(','))
            
            notam_list.append({
                "notam_id": notam_id,
                "content": desc,
                "lat": lat,
                "lng": lng
            })

        # 4. Supabase DB에 저장 (중복 제거를 위해 기존 데이터 삭제 후 삽입 또는 Upsert)
        if notam_list:
            # 기존 노탐 데이터를 비우고 새 데이터를 넣거나, Upsert 로직 사용
            supabase.table("notams").delete().neq("id", 0).execute() # 전체 삭제 예시
            supabase.table("notams").insert(notam_list).execute()
            print(f"✅ {len(notam_list)}개의 노탐 정보를 DB에 업데이트했습니다!")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
