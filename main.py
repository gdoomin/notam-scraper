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
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    prefs = {"download.default_directory": download_dir, "safebrowsing.enabled": True}
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("🌐 KOCA 페이지 접속 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        
        # 1. 충분한 초기 로딩 대기
        wait = WebDriverWait(driver, 30)
        time.sleep(20) 

        print("🎯 제공된 XPath로 엑셀 버튼 정밀 조준...")
        target_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
        
        try:
            # 2. 요소가 나타날 때까지 대기 후 가져오기
            excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
            
            # 3. 화면 중앙으로 스크롤 (클릭 미스 방지)
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", excel_btn)
            time.sleep(2)
            
            # 4. 일반 클릭 시도 후 안되면 JS 클릭
            try:
                excel_btn.click()
                print("✅ 일반 클릭 성공")
            except:
                driver.execute_script("arguments[0].click();", excel_btn)
                print("✅ 자바스크립트 강제 클릭 성공")
                
        except Exception as e:
            print(f"🚨 XPath로 버튼을 찾지 못했습니다: {e}")
            driver.save_screenshot("xpath_error.png")
            # 디버깅을 위해 페이지 내 모든 'a' 태그 갯수 출력
            links = driver.find_elements(By.TAG_NAME, "a")
            print(f"💡 현재 페이지 내 총 {len(links)}개의 링크가 존재합니다.")
            return

        print("⏳ 다운로드 대기 (40초)...")
        time.sleep(40)

        # 5. 파일 확인 및 처리
        files = [f for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 파일 다운로드 실패. 목록:", os.listdir(download_dir))
            return

        file_path = os.path.join(download_dir, files[-1])
        df = pd.read_excel(file_path, engine='xlrd')
        
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
            print(f"✅ 성공: {len(notam_list)}개의 엑셀 데이터 업데이트 완료!")

    except Exception as e:
        print(f"🚨 에러: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
