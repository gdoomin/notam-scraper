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
    # 실행 전 다운로드 디렉토리 정리 (이전 파일 섞임 방지)
    if os.path.exists(download_dir):
        import shutil
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    prefs = {"download.default_directory": download_dir, "safebrowsing.enabled": True}
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 30)

    try:
        print("🌐 KOCA 페이지 접속 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(20) 

        # 1. 전체 페이지 수 파악 (페이지네이션 분석)
        # 보통 'a' 태그 중 숫자로 된 마지막 요소를 찾습니다.
        page_elements = driver.find_elements(By.CSS_SELECTOR, ".pagination a, .paging a")
        page_numbers = [int(el.text) for el in page_elements if el.text.isdigit()]
        total_pages = max(page_numbers) if page_numbers else 1
        print(f"📊 탐색된 총 페이지 수: {total_pages}")

        for p in range(1, total_pages + 1):
            print(f"📄 {p} / {total_pages} 페이지 처리 중...")
            
            if p > 1:
                # 페이지 번호 클릭
                page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, f"//a[text()='{p}']")))
                driver.execute_script("arguments[0].click();", page_btn)
                time.sleep(10) # 테이블 갱신 대기

            # 2. 엑셀 버튼 클릭 (제공된 XPath 사용)
            target_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
            excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", excel_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", excel_btn)
            
            # 각 페이지 다운로드 대기
            time.sleep(15)

        print("⏳ 모든 파일 다운로드 완료 대기...")
        time.sleep(10)

        # 3. 다운로드된 모든 파일 읽기 및 병합
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 다운로드된 파일이 없습니다.")
            return

        print(f"📂 총 {len(files)}개의 파일 병합 중...")
        all_dfs = []
        for f in files:
            try:
                temp_df = pd.read_excel(f, engine='xlrd')
                all_dfs.append(temp_df)
            except Exception as e:
                print(f"⚠️ 파일 읽기 실패({f}): {e}")

        df = pd.concat(all_dfs, ignore_index=True)
        
        # 중복 데이터 제거 (Notam# 기준)
        df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 중복 제거 후 총 {len(df)}개의 노탐 데이터 확보")

        # 4. 데이터 가공 및 Supabase 업로드
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
            print(f"🚀 최종 성공: {len(notam_list)}개의 전체 노탐 업데이트 완료!")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
        driver.save_screenshot("multi_page_error.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
