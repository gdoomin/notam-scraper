import os
import time
import re
import shutil
import json
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    options = Options()
    # 💡 [최적화 핵심] DOM 구조만 생성되면 즉시 다음 단계로 넘어가 속도 극대화
    options.page_load_strategy = 'eager'
    
    # 백그라운드 자동 가동을 위한 최신 헤드리스 모드 유지
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome=120.0.0.0 Safari/537.36")
    
    prefs = {
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1,
        "download.prompt_for_download": False
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)
    
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    wait = WebDriverWait(driver, 60)

    try:
        print(f"🌐 KOCA 원클릭 전체 수집 가동... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        
        print("⏳ 테이블 데이터 초기 로딩 대기...")
        wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="notamSheet-table"]')))
        time.sleep(5)  # 내부 스크립트 안정화 마진

        # --- 🛠️ [개편 구조] 페이지 이동 루프 없이 곧바로 엑셀 단건 다운로드 타격 ---
        try:
            excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
            excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
            driver.execute_script("arguments[0].click();", excel_btn)
            print("📡 전체 목록 엑셀 다운로드 요청 전송 완료")
            
            # 윈도우 파일 스트림 전송 완료 상태 체크
            downloaded_file = None
            for _ in range(60): 
                time.sleep(1)
                all_files = os.listdir(download_dir)
                # 다운로드가 완료된 순수 엑셀 파일 수집
                valid_files = [f for f in all_files if (f.endswith('.xls') or f.endswith('.xlsx')) and not f.startswith('full_')]
                # 크롬 다운로드 중 생성되는 임시 확장자 체크
                temp_files = [f for f in all_files if f.endswith('.crdownload') or f.endswith('.tmp')]
                
                if valid_files and not temp_files:
                    time.sleep(2)  # 입출력 스트림 마감 여유 시간
                    old_path = os.path.join(download_dir, valid_files[0])
                    downloaded_file = os.path.join(download_dir, "full_notam.xls")
                    os.rename(old_path, downloaded_file)
                    print(f"✅ 통파일 확보 성공: full_notam.xls ({os.path.getsize(downloaded_file)} bytes)")
                    break
                    
            if not downloaded_file:
                print("❌ 에러: 전체 파일 다운로드 응답 타임아웃 종료")
                return
                
        except Exception as e:
            print(f"❌ 다운로드 과정 중 예외 발생: {e}")
            return

        # --- 단건 데이터 파싱 및 DOO GPX JSON 빌드 ---
        try:
            full_df = pd.read_excel(downloaded_file, engine='xlrd')
            full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
            print(f"✅ 최종 데이터 통합: 총 {len(full_df)}건 로드 완료")
        except Exception as e:
            print(f"❌ 엑셀 로드 오류: {e}")
            return

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

        # 최신 NOTAM snapshot JSON 매핑
        try:
            json_output = [
                {
                    "lat": item.get("lat"),
                    "lng": item.get("lng"),
                    "content": item.get("content", ""),
                    "notam_id": item.get("notam_id", "")
                }
                for item in notam_list
            ]

            with open("notam-latest.json", "w", encoding="utf-8") as f:
                json.dump(json_output, f, ensure_ascii=False, indent=2)

            print(f"💾 로컬 JSON 스냅샷 저장 성공: notam-latest.json ({len(json_output)}건)")
        except Exception as e:
            print(f"⚠️ JSON 변환 및 저장 실패: {e}")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
