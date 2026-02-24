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
from selenium.webdriver.common.action_chains import ActionChains
from supabase import create_client, Client

# 1. 노탐 ID 추출용 정규표현식
def find_notam_id_in_source(source):
    match = re.search(r'[A-Z]\d{4}/\d{2}', source)
    return match.group(0) if match else None

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
    
    prefs = {
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    wait = WebDriverWait(driver, 60)

    try:
        print(f"🌐 KOCA 전수 수집 및 DB 동기화 작전... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(50) 

        last_page_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            current_id = find_notam_id_in_source(driver.page_source)
            
            if p == 1:
                last_page_id = current_id
                print(f"   -> 1페이지 ID 확보: {last_page_id}")
            else:
                try:
                    # [핵심] 숫자 인자 기반 JS 함수 타격
                    target_xpath = f"//td[contains(@onclick, \"'{p}'\")]"
                    page_btn = wait.until(EC.presence_of_element_located((By.XPATH, target_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(3)
                    
                    ActionChains(driver).move_to_element(page_btn).click().perform()
                    print(f"   -> {p}페이지 정밀 클릭 완료. 교체 대기...")
                    
                    updated = False
                    for _ in range(60):
                        time.sleep(1)
                        new_id = find_notam_id_in_source(driver.page_source)
                        if new_id and new_id != last_page_id:
                            print(f"   -> [확인] 데이터 교체 완료: {last_page_id} -> {new_id}")
                            last_page_id = new_id
                            updated = True
                            break
                    
                    if not updated:
                        print(f"   ⚠️ 갱신 실패. JS 강제 실행 시도...")
                        driver.execute_script("arguments[0].click();", page_btn)
                        time.sleep(10)
                except:
                    print(f"   -> {p}페이지 탐색 종료")
                    break

            # 엑셀 다운로드
            try:
                excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]')))
                driver.execute_script("arguments[0].click();", excel_btn)
                
                renamed = False
                for _ in range(60): 
                    time.sleep(1)
                    files = [f for f in os.listdir(download_dir) if not f.startswith('page_') and not f.endswith('.crdownload')]
                    if files:
                        time.sleep(5)
                        old_path = os.path.join(download_dir, files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [확보] {new_filename} ({os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
                        renamed = True
                        break
            except: pass

        # --- 데이터 병합 및 DB 동기화 ---
        all_files = sorted([os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')])
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                all_dfs.append(df_temp)
            except: continue

        if all_dfs:
            full_df = pd.concat(all_dfs, ignore_index=True)
            full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
            print(f"✅ 최종 통합 완료: 총 {len(full_df)}건")

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

            # --- [핵심 추가] 기존 데이터 완전 삭제 로직 ---
            print("🧹 만료된 노탐 청소 중 (Truncate)...")
            # notam_id가 "0"이 아닌 모든 행 삭제 (전체 삭제와 동일한 효과)
            supabase.table("notams").delete().neq("notam_id", "0").execute()
            print("✨ DB가 깨끗하게 비워졌습니다.")

            # 최신 데이터 업로드
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"🚀 [동기화 성공] 현재 유효한 {len(notam_list)}건의 데이터만 DB에 유지됩니다!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
