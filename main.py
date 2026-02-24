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

# 1. 노탐 ID 추출용 정규표현식 (Z0105/26 등)
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
    actions = ActionChains(driver)

    try:
        print(f"🌐 KOCA 접속 및 초기 렌더링 대기...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(45) 

        last_page_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 데이터 수집 시도...")
            
            # 현재 페이지 ID 확보
            current_id = find_notam_id_in_source(driver.page_source)
            
            if p == 1:
                last_page_id = current_id
                print(f"   -> 1페이지 기준 ID 확보: {last_page_id}")
            else:
                # --- 페이지 이동 (마우스 시뮬레이션 방식) ---
                try:
                    td_idx = p + 3
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    target_td = wait.until(EC.presence_of_element_located((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_td)
                    time.sleep(2)

                    # td 내부의 모든 자식 요소(a, span, div 등) 중 클릭 가능한 놈 찾기
                    try:
                        clickable_element = target_td.find_element(By.XPATH, ".//*[not(child::*)]") # 가장 하위 자식 요소
                        print(f"   -> [타격] 하위 요소 발견: {clickable_element.tag_name}")
                    except:
                        clickable_element = target_td

                    # ActionChains로 정밀 클릭
                    actions.move_to_element(clickable_element).click().perform()
                    print(f"   -> {p}페이지 마우스 클릭 실행 완료")
                    
                    # 데이터 갱신 검증
                    updated = False
                    for _ in range(40):
                        time.sleep(1)
                        new_id = find_notam_id_in_source(driver.page_source)
                        if new_id and new_id != last_page_id:
                            print(f"   -> [성공] 데이터 갱신 확인: {last_page_id} -> {new_id}")
                            last_page_id = new_id
                            updated = True
                            break
                    
                    if not updated:
                        print(f"   ⚠️ 데이터 갱신 실패. (현재 ID: {new_id if 'new_id' in locals() else 'N/A'})")
                        # 마지막 수단: 엔터키 입력 시뮬레이션
                        clickable_element.send_keys("\n")
                        print(f"   -> [재시도] 엔터키 입력 신호 전송")
                        time.sleep(5)
                    
                    time.sleep(5)
                except Exception as e:
                    print(f"   -> 페이지 이동 실패: {e}")
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
                        time.sleep(4)
                        old_path = os.path.join(download_dir, files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [파일확보] {new_filename} ({os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
                        renamed = True
                        break
            except Exception as e:
                print(f"   ⚠️ 다운로드 오류: {e}")

        # 병합 및 업로드
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
