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
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

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

        print("📊 멀티 페이지 수집 시작 (XPath 정밀 인덱싱)...")
        
        # p=1(100건), p=2(200건), p=3(300건), p=4(346건)
        # 2페이지가 td[5]라면, p페이지의 XPath는 td[p+3]이 됩니다.
        for p in range(1, 11): 
            print(f"📄 {p}페이지 데이터 수집 중...")
            
            if p > 1:
                try:
                    # 주신 XPath 규칙 적용: 2페이지=td[5], 3페이지=td[6]...
                    td_idx = p + 3 
                    page_xpath = f'//*[@id="notamSheet-table"]/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 이동 성공 (td[{td_idx}])")
                    time.sleep(15) # KOCA 서버 응답 대기
                except Exception as e:
                    print(f"   -> {p}페이지 버튼을 더 이상 찾을 수 없습니다. (종료)")
                    break

            # 엑셀 다운로드 (성공했던 XPath)
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 엑셀 다운로드 요청 완료")
                time.sleep(15) 
            except Exception as e:
                print(f"   -> {p}페이지 다운로드 중 에러: {e}")

        # 모든 파일 병합
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.endswith(('.xls', '.xlsx'))]
        if not files:
            print("🚨 수집된 파일이 없습니다.")
            return

        print(f"📂 {len(files)}개 파일 통합 및 중복 제거...")
        all_dfs = []
        for f in files:
            try:
                all_dfs.append(pd.read_excel(f, engine='xlrd'))
            except: continue

        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 최종 유효 데이터 {len(full_df)}건 확보")

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
