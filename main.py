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
        print(f"🌐 KOCA 346건 완전 정복 작전 개시... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(50) 

        last_page_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 수집 시도 중...")
            
            # 현재 페이지 ID 확보
            current_id = find_notam_id_in_source(driver.page_source)
            
            if p == 1:
                last_page_id = current_id
                print(f"   -> 1페이지 기준 ID: {last_page_id}")
            else:
                # --- [핵심] 페이지 이동 (JS 직접 호출) ---
                try:
                    # KOCA 내부 함수인 notamSearch(p) 또는 movePage(p)를 직접 쏩니다.
                    # td[idx]를 찾는 대신 버튼에 심긴 스크립트를 추출해 실행합니다.
                    td_idx = p + 3
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    target_btn = driver.find_element(By.XPATH, page_xpath)
                    # onclick 속성에 있는 "notamSearch('4')" 같은 스크립트 추출
                    js_func = target_btn.get_attribute("onclick") or target_btn.find_element(By.TAG_NAME, "a").get_attribute("href")
                    
                    if js_func:
                        clean_js = js_func.replace("javascript:", "")
                        driver.execute_script(clean_js)
                        print(f"   -> [JS 호출] {clean_js}")
                    else:
                        # 스크립트가 안 잡히면 강제 클릭
                        driver.execute_script("arguments[0].click();", target_btn)
                    
                    # 데이터 갱신 검증 (시간을 더 넉넉히!)
                    updated = False
                    for _ in range(60): 
                        time.sleep(1)
                        new_id = find_notam_id_in_source(driver.page_source)
                        if new_id and new_id != last_page_id:
                            print(f"   -> [성공] {p}페이지 데이터 갱신 완료: {last_page_id} -> {new_id}")
                            last_page_id = new_id
                            updated = True
                            break
                    
                    if not updated:
                        print(f"   ⚠️ {p}페이지 갱신 실패. (이전 페이지와 동일 데이터 방지 위해 skip)")
                        continue
                except Exception as e:
                    print(f"   -> {p}페이지 이동 불가 (종료): {e}")
                    break

            # --- 엑셀 다운로드 (데이터가 완전히 렌더링될 때까지 추가 대기) ---
            try:
                time.sleep(5) 
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 다운로드 요청 완료")
                
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
                if not renamed: print(f"   ⚠️ {p}페이지 파일 확보 실패")
            except Exception as e:
                print(f"   ⚠️ {p}페이지 다운로드 에러: {e}")

        # --- 데이터 병합 및 업로드 ---
        all_files = sorted([os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')])
        print(f"📂 병합 대상 파일 수: {len(all_files)}")
        
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                all_dfs.append(df_temp)
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}개 행 추가")
            except: continue

        if all_dfs:
            full_df = pd.concat(all_dfs, ignore_index=True)
            full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
            print(f"✅ 최종 중복 제거 결과: {len(full_df)}건 확보!")

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
            print(f"🚀 [최종 성공] 총 {len(notam_list)}건 'Doo GPX' 데이터 업데이트 완료!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
