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

    # 3. 브라우저 옵션 설정 (최적화 버전)
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
    driver.set_script_timeout(180)
    wait = WebDriverWait(driver, 40)

    try:
        print("🌐 KOCA 페이지 접속 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(30) 

        # 4. 무한 루프 탐색 (페이지가 없을 때까지)
        print("📊 멀티 페이지 데이터 수집 시작...")
        
        for p in range(1, 21): # 최대 20페이지까지 안전장치
            print(f"📄 {p}페이지 시도 중...")
            
            if p > 1:
                try:
                    # 'p'라는 텍스트를 가진 페이지 번호 클릭
                    page_btn = driver.find_element(By.XPATH, f"//a[text()='{p}']")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(2)
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 이동 성공")
                    time.sleep(12) # 테이블 로딩 대기
                except:
                    print(f"   -> {p}페이지 버튼을 찾을 수 없습니다. 수집을 종료합니다.")
                    break

            # 5. 엑셀 다운로드 (정밀 XPath)
            try:
                target_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 엑셀 다운로드 클릭 완료")
                time.sleep(15) # 파일 다운로드 시간 확보
            except Exception as e:
                print(f"   -> {p}페이지 다운로드 중 오류 발생: {e}")
                continue

        print("⏳ 모든 파일 병합 준비 중...")
        time.sleep(10)

        # 6. 다운로드된 모든 파일 병합
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 수집된 파일이 없습니다.")
            return

        print(f"📂 총 {len(files)}개 파일 병합 및 중복 제거 시작...")
        all_dfs = []
        for f in files:
            try:
                all_dfs.append(pd.read_excel(f, engine='xlrd'))
            except: continue

        if not all_dfs: return
        
        full_df = pd.concat(all_dfs, ignore_index=True)
        # Notam# 컬럼 기준으로 중복 제거
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 최종 유효 데이터 {len(full_df)}건 확보")

        # 7. Supabase 업로드 데이터 생성
        notam_list = []
        for _, row in full_df.iterrows():
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
            print(f"🚀 [완료] 총 {len(notam_list)}개의 노탐 데이터가 업데이트되었습니다.")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
        driver.save_screenshot("final_multi_debug.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
