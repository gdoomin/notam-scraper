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
        print(f"🌐 KOCA 접속 및 프레임 탐색 시작...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(40) 

        # --- [핵심] iframe 찾기 및 전환 ---
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, frame in enumerate(iframes):
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            if len(driver.find_elements(By.ID, "notamSheet-table")) > 0:
                print(f"✅ 데이터 프레임 발견 및 전환 성공 (Index: {i})")
                break
        
        last_first_id = ""

        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            
            # 현재 프레임 안에서 ID 추출 시도
            try:
                current_id_el = driver.find_element(By.XPATH, '//*[@id="notamSheet-table"]/tbody/tr[1]/td[2]')
                current_id = current_id_el.get_attribute("textContent").strip()
                if not current_id: # 텍스트가 안 잡히면 JS로 시도
                    current_id = driver.execute_script("return arguments[0].innerText;", current_id_el).strip()
            except:
                current_id = ""

            if p == 1:
                last_first_id = current_id
                print(f"   -> 1페이지 기준 ID: {last_first_id}")
            else:
                # 페이지 이동 로직
                try:
                    td_idx = p + 3
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    # 프레임 안에서 버튼 찾기
                    page_btn = wait.until(EC.presence_of_element_located((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 클릭 완료. 갱신 대기...")
                    
                    # 데이터 갱신 확인
                    updated = False
                    for _ in range(30):
                        time.sleep(1)
                        new_id = driver.execute_script("return document.evaluate('//*[@id=\"notamSheet-table\"]/tbody/tr[1]/td[2]', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue.innerText;").strip()
                        if new_id and new_id != last_first_id:
                            print(f"   -> [확인] 데이터 갱신됨: {last_first_id} -> {new_id}")
                            last_first_id = new_id
                            updated = True
                            break
                    
                    if not updated:
                        print(f"   ⚠️ 데이터 갱신 확인 실패. (강제 진행)")
                    time.sleep(5)
                except Exception as e:
                    print(f"   -> 이동 에러: {e}")
                    break

            # 엑셀 다운로드 (부모 페이지에 버튼이 있을 경우를 대비해 필요시 전환)
            driver.switch_to.default_content()
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

            # 다음 페이지를 누르기 위해 다시 프레임으로 복귀
            driver.switch_to.frame(iframes[i]) 

        # --- 데이터 병합 및 업로드 ---
        driver.switch_to.default_content() # 최종 업로드 전 메인으로 복귀
        all_files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')]
        print(f"📂 병합 파일 수: {len(all_files)}")
        
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}개 행")
                all_dfs.append(df_temp)
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
            print(f"🚀 [임무 완수] {len(notam_list)}건 '코숏' DB 업데이트 성공!")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
