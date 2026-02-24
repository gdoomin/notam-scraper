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

# 1. 좌표 추출 함수 (Doo GPX 지도 표시용)
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
    # 2. Supabase 및 환경 설정
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    # 3. 브라우저 옵션 설정 (보안 정책 해제 및 최적화)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    options.page_load_strategy = 'eager'
    
    # 핵심 수정: 다중 다운로드 자동 허용 및 이미지 로딩 차단
    prefs = {
        "download.default_directory": download_dir,
        "safebrowsing.enabled": True,
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1 
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.set_page_load_timeout(180)
    wait = WebDriverWait(driver, 45)

    try:
        print(f"🌐 KOCA 접속 시작: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(30) # 초기 로딩 대기

        print("📊 멀티 페이지 수집 가동 (다중 다운로드 권한 획득)...")
        
        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시도 중...")
            
            # --- 페이지 이동 (2페이지부터) ---
            if p > 1:
                try:
                    td_idx = p + 3 # 2페이지=td[5] 규칙
                    # 주신 절대 경로 XPath 활용
                    page_xpath = f'/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{td_idx}]'
                    
                    page_btn = wait.until(EC.element_to_be_clickable((By.XPATH, page_xpath)))
                    driver.execute_script("arguments[0].click();", page_btn)
                    print(f"   -> {p}페이지 이동 버튼 클릭 성공")
                    time.sleep(20) # 서버에서 엑셀 생성 데이터를 준비할 시간을 충분히 줌
                except:
                    print(f"   -> 더 이상의 페이지가 없습니다. 탐색 종료.")
                    break

            # --- 엑셀 다운로드 클릭 ---
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                # 페이지가 바뀌었으므로 요소를 새로 찾습니다.
                excel_btn = wait.until(EC.presence_of_element_located((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 엑셀 다운로드 요청 완료")
                
                # --- 파일 이름 즉시 변경 (충돌 및 유실 방지) ---
                renamed = False
                for i in range(60): # 깃허브 액션 속도 고려 (최대 60초)
                    time.sleep(1)
                    # page_로 시작하지 않는 실제 엑셀 파일 찾기
                    new_files = [f for f in os.listdir(download_dir) 
                                 if not f.startswith('page_') and not f.endswith('.crdownload') and f.endswith(('.xls', '.xlsx'))]
                    
                    if new_files:
                        time.sleep(3) # 파일 쓰기 완료를 위한 안전 대기
                        old_path = os.path.join(download_dir, new_files[0])
                        new_filename = f"page_{p}_notam.xls"
                        new_path = os.path.join(download_dir, new_filename)
                        os.rename(old_path, new_path)
                        print(f"   -> [확보 성공] {new_filename}")
                        renamed = True
                        break
                
                if not renamed:
                    print(f"   ⚠️ {p}페이지 다운로드 파일 감지 실패 (브라우저 차단 여부 확인 필요)")
                    
            except Exception as e:
                print(f"   ⚠️ {p}페이지 다운로드 버튼 클릭 실패: {e}")

        # 4. 모든 개별 파일 병합 로직
        all_files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')]
        print(f"📂 총 {len(all_files)}개의 파일을 병합합니다...")
        
        if len(all_files) == 0:
            print("🚨 수집된 파일이 하나도 없습니다.")
            return

        all_dfs = []
        for f in all_files:
            try:
                temp_df = pd.read_excel(f, engine='xlrd')
                all_dfs.append(temp_df)
                print(f"   -> {os.path.basename(f)} 읽기 완료: {len(temp_df)}행")
            except Exception as e:
                print(f"   ⚠️ {f} 읽기 오류: {e}")

        # 5. 중복 제거 및 최종 업로드 데이터 생성
        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 중복 제거 후 최종 유효 데이터: {len(full_df)}건")

        notam_list = []
        for _, row in full_df.iterrows():
            notam_id = str(row.get('Notam#', ''))
            full_text = str(row.get('Full Text', ''))
            lat, lng = extract_coords(full_text)
            
            notam_list.append({
                "notam_id": notam_id,
                "content": full_text,
                "lat": lat,
                "lng": lng,
                "series": notam_id[0] if notam_id else "U",
                "start_date": str(row.get('Start Date UTC', '')),
                "end_date": str(row.get('End Date UTC', ''))
            })

        if notam_list:
            # Supabase에 346건 이상의 전체 데이터 한 번에 업로드
            supabase.table("notams").upsert(notam_list, on_conflict="notam_id").execute()
            print(f"🚀 [축하합니다!] 총 {len(notam_list)}건의 데이터가 업데이트되었습니다.")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
        driver.save_screenshot("scraper_error.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
