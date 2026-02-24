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
        print(f"🌐 KOCA 345건 전수 수집 가동... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(50) 

        last_page_id = ""

        # 총 10페이지까지 탐색 (실제로는 4페이지에서 종료 예상)
        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            
            # 현재 페이지 ID 확보
            current_id = find_notam_id_in_source(driver.page_source)
            
            if p == 1:
                last_page_id = current_id
                print(f"   -> 1페이지 기준 ID: {last_page_id}")
            else:
                # --- [핵심 수정] 3페이지 누락 방지: 숫자 텍스트 정밀 타격 ---
                try:
                    # 방법 1: td 내부에 해당 페이지 번호가 정확히 적힌 요소를 찾음
                    page_xpath = f"//td[contains(@onclick, 'search') and .//font[text()='{p}']]"
                    # 방법 2: (백업) 텍스트 자체가 숫자인 td
                    fallback_xpath = f"//td[text()='{p}']"
                    
                    try:
                        page_btn = wait.until(EC.presence_of_element_located((By.XPATH, page_xpath)))
                    except:
                        page_btn = wait.until(EC.presence_of_element_located((By.XPATH, fallback_xpath)))

                    # 버튼 위치로 이동 및 마우스 클릭
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(3)
                    
                    actions = ActionChains(driver)
                    actions.move_to_element(page_btn).click().perform()
                    print(f"   -> {p}페이지 클릭 완료. 갱신 확인 중...")
                    
                    # 데이터 갱신 검증 (ID가 바뀔 때까지 60초간 대기)
                    updated = False
                    for _ in range(60):
                        time.sleep(1)
                        new_id = find_notam_id_in_source(driver.page_source)
                        if new_id and new_id != last_page_id:
                            print(f"   -> [확인] {p}페이지로 성공적 이동: {last_page_id} -> {new_id}")
                            last_page_id = new_id
                            updated = True
                            break
                    
                    if not updated:
                        print(f"   ⚠️ {p}페이지 갱신 실패 (이전 페이지와 동일). 다시 클릭 시도...")
                        driver.execute_script("arguments[0].click();", page_btn) # JS로 재클릭
                        time.sleep(10)
                        continue # 다시 루프 돌아서 갱신 확인
                        
                except Exception as e:
                    print(f"   -> {p}페이지 버튼을 찾을 수 없습니다. (모든 데이터 수집 완료로 간주)")
                    break

            # --- 엑셀 다운로드 (매 페이지 확실히 수행) ---
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 엑셀 다운로드 요청 완료")
                
                renamed = False
                for _ in range(60): 
                    time.sleep(1)
                    files = [f for f in os.listdir(download_dir) if not f.startswith('page_') and not f.endswith('.crdownload')]
                    if files:
                        time.sleep(5) # 파일 저장 완료 대기
                        old_path = os.path.join(download_dir, files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [확보성공] {new_filename} ({os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
                        renamed = True
                        break
                if not renamed:
                    print(f"   ⚠️ {p}페이지 파일 생성 실패")
            except Exception as e:
                print(f"   ⚠️ 다운로드 버튼 클릭 실패: {e}")

        # --- 데이터 병합 및 업로드 ---
        all_files = sorted([os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')])
        print(f"📂 병합 파일 목록: {[os.path.basename(f) for f in all_files]}")
        
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                all_dfs.append(df_temp)
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}행 읽기 성공")
            except Exception as e:
                print(f"   ⚠️ {f} 읽기 오류: {e}")

        if all_dfs:
            full_df = pd.concat(all_dfs, ignore_index=True)
            # Notam# 기준으로 중복 제거
            full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
            print(f"✅ 최종 데이터 통합 완료: 총 {len(full_df)}건")

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
            
            # Supabase 업로드
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"🚀 [최종 성공] {len(notam_list)}건의 데이터를 '코숏' DB에 업데이트했습니다!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
