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
        print(f"🌐 KOCA 접속 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(40) 

        last_first_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            
            # --- 페이지 이동 로직 ---
            if p > 1:
                try:
                    td_idx = p + 3
                    # td 내부의 a 태그를 직접 조준
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    page_td = wait.until(EC.presence_of_element_located((By.XPATH, page_xpath)))
                    # td 안의 a 태그가 있으면 그것을, 없으면 td 자체를 클릭
                    try:
                        click_target = page_td.find_element(By.TAG_NAME, "a")
                    except:
                        click_target = page_td
                    
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", click_target)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", click_target)
                    print(f"   -> {p}페이지 클릭 명령 전송 완료")
                    
                    # --- [핵심] 데이터 갱신 검증 로직 ---
                    updated = False
                    for _ in range(40):
                        time.sleep(1)
                        try:
                            # .text 대신 textContent 사용하여 그리드 내부 텍스트 강제 추출
                            current_first_id = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]/tbody/tr[1]/td[2]').get_attribute("textContent").strip()
                            if current_first_id and current_first_id != last_first_id:
                                print(f"   -> [확인] 데이터 갱신됨: {last_first_id} -> {current_first_id}")
                                last_first_id = current_first_id
                                updated = True
                                break
                        except: pass
                    
                    if not updated:
                        print(f"   ⚠️ {p}페이지 데이터 갱신 확인 실패. (강제 10초 대기 후 진행)")
                        time.sleep(10)
                except Exception as e:
                    print(f"   -> 이동 에러: {e}")
                    break
            else:
                # 1페이지 초기 ID 확보 (textContent 사용)
                time.sleep(5)
                try:
                    last_first_id = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]/tbody/tr[1]/td[2]').get_attribute("textContent").strip()
                    print(f"   -> 1페이지 기준 ID: {last_first_id}")
                except: print("   ⚠️ 1페이지 ID 확보 실패")

            # --- 엑셀 다운로드 클릭 ---
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                
                # 파일 확보 및 이름 변경
                renamed = False
                for _ in range(60): 
                    time.sleep(1)
                    new_files = [f for f in os.listdir(download_dir) if not f.startswith('page_') and not f.endswith('.crdownload')]
                    if new_files:
                        time.sleep(4)
                        old_path = os.path.join(download_dir, new_files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [확보성공] {new_filename} ({os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
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
            print(f"✅ 최종 데이터 확보: {len(full_df)}건")

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
            print(f"🚀 [최종완료] {len(notam_list)}건 '코숏' DB 업데이트 성공!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
