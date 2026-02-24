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
    
    prefs = {
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    wait = WebDriverWait(driver, 60)

    try:
        print(f"🌐 KOCA 접속 및 데이터 로딩 대기... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        
        # 표가 나타날 때까지 대기
        wait.until(EC.presence_of_element_located((By.ID, "notamSheet-table")))
        time.sleep(40) # 그리드 내부 데이터 렌더링 시간

        last_first_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 데이터 수집 시도...")
            
            # --- [핵심] 현재 페이지의 첫 번째 노탐 ID 확실히 잡기 ---
            current_id = ""
            for _ in range(20): # ID가 로딩될 때까지 20초간 재시도
                try:
                    # 표의 1행 2열 혹은 특정 패턴을 가진 셀 찾기
                    cell = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]//tr[1]/td[2]')
                    temp_id = cell.get_attribute("textContent").strip()
                    if temp_id and "/" in temp_id: # A1234/26 같은 형식이 잡히면 성공
                        current_id = temp_id
                        break
                except: pass
                time.sleep(1)

            if p == 1:
                last_first_id = current_id
                print(f"   -> 1페이지 기준 ID 확보: {last_first_id if last_first_id else '실패(공백)'}")
            else:
                # 페이지 이동 클릭 (보내주신 정밀 XPath)
                try:
                    td_idx = p + 3
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 클릭 완료. 데이터 교체 검증 중...")
                    
                    # --- [핵심] 데이터가 실제로 바뀌었는지 확인 ---
                    updated = False
                    for _ in range(40):
                        time.sleep(1)
                        try:
                            check_id = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]//tr[1]/td[2]').get_attribute("textContent").strip()
                            if check_id and check_id != last_first_id:
                                print(f"   -> [성공] 데이터 갱신 확인: {last_first_id} -> {check_id}")
                                last_first_id = check_id
                                updated = True
                                break
                        except: pass
                    
                    if not updated:
                        print(f"   ⚠️ 데이터 갱신 미확인. (이전 페이지와 동일한 데이터를 받을 위험이 있습니다.)")
                    time.sleep(5)
                except Exception as e:
                    print(f"   -> 더 이상 페이지가 없거나 이동 실패: {e}")
                    break

            # 엑셀 다운로드
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                
                # 파일 이름 변경
                renamed = False
                for _ in range(60): 
                    time.sleep(1)
                    files = [f for f in os.listdir(download_dir) if not f.startswith('page_') and not f.endswith('.crdownload')]
                    if files:
                        time.sleep(4)
                        old_path = os.path.join(download_dir, files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [파일확보] {new_filename} ({os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
                        renamed = True
                        break
            except Exception as e:
                print(f"   ⚠️ 다운로드 오류: {e}")

        # --- 데이터 병합 및 업로드 ---
        all_files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')]
        print(f"📂 병합 파일 수: {len(all_files)}")
        
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                all_dfs.append(df_temp)
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}개 행")
            except: continue

        if all_dfs:
            full_df = pd.concat(all_dfs, ignore_index=True)
            full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
            print(f"✅ 중복 제거 후 최종 데이터: {len(full_df)}건")

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
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"🚀 [최종성공] {len(notam_list)}건 '코숏' DB 업데이트 완료!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
