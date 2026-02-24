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
    # 1. Supabase 및 환경 설정
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    # 2. 브라우저 최적화 설정
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
    wait = WebDriverWait(driver, 45)

    try:
        print("🌐 KOCA 접속 및 페이지 로딩 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(30) 

        print("📊 멀티 페이지 데이터 수집 가동 (Full Data Mode)...")
        
        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            
            # --- 페이지 이동 로직 (보내주신 XPath 적용) ---
            if p > 1:
                try:
                    td_idx = p + 3 # 2페이지=td[5], 3페이지=td[6] 규칙
                    # 보내주신 전체 절대 경로 XPath 활용
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", page_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 이동 완료 (XPath 타격)")
                    time.sleep(15) # 테이블 데이터 갱신 대기
                except Exception as e:
                    print(f"   -> 페이지 버튼(td[{p+3}])이 없거나 클릭 불가 (탐색 종료)")
                    break

            # --- 엑셀 다운로드 클릭 (주신 XPath) ---
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 엑셀 다운로드 버튼 클릭")
                
                # --- 파일 이름 즉시 변경 (중복 방지 핵심) ---
                renamed = False
                for _ in range(45): # 최대 45초 대기
                    time.sleep(1)
                    current_files = [f for f in os.listdir(download_dir) 
                                    if not f.startswith('page_') and not f.endswith('.crdownload')]
                    
                    if current_files:
                        time.sleep(2) # 파일 기록 완료 대기
                        old_path = os.path.join(download_dir, current_files[0])
                        new_filename = f"page_{p}_notam.xls"
                        new_path = os.path.join(download_dir, new_filename)
                        os.rename(old_path, new_path)
                        print(f"   -> [확보] {new_filename} 저장 완료")
                        renamed = True
                        break
                
                if not renamed:
                    print(f"   ⚠️ {p}페이지 파일 다운로드 확인 실패")
                    
            except Exception as e:
                print(f"   ⚠️ {p}페이지 작업 중 오류 발생: {e}")

        # 3. 데이터 병합 처리
        all_files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')]
        print(f"📂 총 {len(all_files)}개 파일 병합을 시작합니다.")
        
        all_dfs = []
        for f in all_files:
            try:
                temp_df = pd.read_excel(f, engine='xlrd')
                all_dfs.append(temp_df)
                print(f"   -> {os.path.basename(f)} 읽기 완료: {len(temp_df)}행")
            except Exception as e:
                print(f"   ⚠️ {f} 파싱 실패: {e}")

        if not all_dfs:
            print("🚨 병합할 데이터가 없습니다.")
            return
        
        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 최종 유효 데이터 확보: {len(full_df)}건")

        # 4. Supabase Upsert
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
            print(f"🚀 [최종 성공] {len(notam_list)}개의 데이터가 '코숏' DB에 업데이트되었습니다!")

    except Exception as e:
        print(f"🚨 치명적 에러 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
