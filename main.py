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
    # CDP 명령어로 헤드리스 다운로드 허용
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    wait = WebDriverWait(driver, 45)

    try:
        print(f"🌐 KOCA 접속 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(35) 

        last_first_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            
            # --- 1페이지가 아닐 때만 페이지 이동 로직 실행 ---
            if p > 1:
                try:
                    td_idx = p + 3 
                    # td 내부의 모든 클릭 가능한 요소를 포함하는 정밀 XPath
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    # 버튼이 나타날 때까지 기다린 후 클릭
                    page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(2)
                    
                    # td 안의 a 태그가 있다면 그것을 클릭, 없으면 td 클릭
                    try:
                        inner_link = page_btn.find_element(By.TAG_NAME, "a")
                        driver.execute_script("arguments[0].click();", inner_link)
                    except:
                        driver.execute_script("arguments[0].click();", page_btn)
                    
                    print(f"   -> {p}페이지 버튼 클릭 완료. 데이터 갱신 대기 중...")
                    
                    # --- [핵심] 데이터 갱신 검증 로직 ---
                    updated = False
                    for _ in range(30): # 최대 30초 대기
                        time.sleep(1)
                        try:
                            # 첫 번째 행의 ID 추출 (ID 위치가 td[2]라고 가정)
                            current_first_id = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]/tbody/tr[1]/td[2]').text
                            if current_first_id and current_first_id != last_first_id:
                                print(f"   -> [확인] 데이터 갱신됨: {last_first_id} -> {current_first_id}")
                                last_first_id = current_first_id
                                updated = True
                                break
                        except: pass
                    
                    if not updated:
                        print(f"   ⚠️ {p}페이지 데이터 갱신 확인 실패. (스크린샷 저장)")
                        driver.save_screenshot(f"debug_page_{p}.png")
                    
                    time.sleep(5) # 안정적인 엑셀 생성을 위한 추가 대기
                except Exception as e:
                    print(f"   -> 페이지 이동 실패 또는 종료: {e}")
                    break
            else:
                # 1페이지 첫 번째 ID 미리 저장
                try:
                    last_first_id = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]/tbody/tr[1]/td[2]').text
                    print(f"   -> 1페이지 첫 ID: {last_first_id}")
                except: pass

            # --- 엑셀 다운로드 클릭 ---
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                
                # --- 파일 이름 즉시 변경 ---
                renamed = False
                for _ in range(60): 
                    time.sleep(1)
                    new_files = [f for f in os.listdir(download_dir) if not f.startswith('page_') and not f.endswith('.crdownload')]
                    if new_files:
                        time.sleep(3)
                        old_path = os.path.join(download_dir, new_files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [확보 성공] {new_filename} (크기: {os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
                        renamed = True
                        break
                if not renamed: print(f"   ⚠️ {p}페이지 파일 다운로드 확인 실패")
            except Exception as e:
                print(f"   ⚠️ {p}페이지 엑셀 작업 오류: {e}")

        # --- 병합 및 업로드 ---
        all_files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')]
        print(f"📂 총 {len(all_files)}개 파일 병합 시작...")
        
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}개 행 확보")
                all_dfs.append(df_temp)
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
            print(f"🚀 [최종 완료] {len(notam_list)}건 '코숏' DB 업데이트 성공!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
