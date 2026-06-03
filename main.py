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
from selenium.webdriver.common.action_chains import ActionChains

# 1. 노탐 ID 추출용 정규표현식
def find_notam_id_in_source(source):
    match = re.search(r'[A-Z]\d{4}/\d{2}', source)
    return match.group(0) if match else None

# 2. 좌표 추출 함수 (Doo GPX 지도 표시용)
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
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")  # 리소스 부족으로 인한 크래시 방지
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    prefs = {
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    # [추가] 브라우저 자체의 타임아웃을 60초로 제한 (120초 동안 멍때리는 것 방지)
    driver.set_page_load_timeout(60)
    driver.set_script_timeout(60)
    
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {'behavior': 'allow', 'downloadPath': download_dir})
    wait = WebDriverWait(driver, 60)

    try:
        print(f"🌐 KOCA 345건 전수 수집 (td[5] 무조건 타격)... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        
        # [수정] 무조건 50초 쉬는 대신, 테이블 요소가 렌더링될 때까지만 대기 (맥시멈 60초)
        print("⏳ 테이블 로딩 대기 중...")
        wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="notamSheet-table"]')))
        time.sleep(5)  # 내부 JS 데이터가 완전히 안착할 수 있도록 약간의 여유만 제공

        last_page_id = ""

        # 최대 10페이지까지 반복 (갱신 안 될 때까지)
        for p in range(1, 11): 
            print(f"📄 {p}페이지 작업 시작...")
            
            # 현재 페이지 ID 확보
            current_id = find_notam_id_in_source(driver.page_source)
            
            if p == 1:
                last_page_id = current_id
                print(f"   -> 1페이지 기준 ID 확보: {last_page_id}")
            else:
                # --- [핵심 수정] 무조건 td[5] 클릭 ---
                try:
                    next_xpath = '//*[@id="notamSheet-table"]/tbody/tr[5]/td/div/table/tbody/tr/td[5]'
                    next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, next_xpath)))
                    
                    # 화면 중앙으로 이동 후 안정화
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                    time.sleep(2)

                    # [마우스 클릭] ActionChains로 정밀 타격
                    ActionChains(driver).move_to_element(next_btn).click().perform()
                    print(f"   -> td[5] '다음' 클릭 완료. 페이지 교체 대기 중...")
                    
                    # 데이터 갱신 확인 (최대 60초)
                    updated = False
                    for _ in range(60):
                        time.sleep(1)
                        new_id = find_notam_id_in_source(driver.page_source)
                        if new_id and new_id != last_page_id:
                            print(f"   -> [성공] 데이터 갱신 확인: {last_page_id} -> {new_id}")
                            last_page_id = new_id
                            updated = True
                            break
                    
                    if not updated:
                        print(f"   ⚠️ 갱신 미확인. (더 이상 페이지가 없거나 클릭 실패)")
                        break # 데이터가 안 바뀌면 루프 종료
                        
                except Exception as e:
                    print(f"   -> 다음 페이지 버튼(td[5])을 찾을 수 없음: {e}")
                    break

            # --- 엑셀 다운로드 및 파일 이름 변경 ---
            try:
                excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
                excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> {p}페이지 엑셀 다운로드 요청")
                
                renamed = False
                for _ in range(60): 
                    time.sleep(1)
                    # 확장자가 .xls 또는 .xlsx인 진짜 다운로드 완료된 파일만 필터링
                    files = [f for f in os.listdir(download_dir) if (f.endswith('.xls') or f.endswith('.xlsx')) and not f.startswith('page_')]
                    if files:
                        time.sleep(2) # 파일 스트림이 완전히 닫힐 때까지 아주 잠깐 대기
                        old_path = os.path.join(download_dir, files[0])
                        new_filename = f"page_{p}_notam.xls"
                        os.rename(old_path, os.path.join(download_dir, new_filename))
                        print(f"   -> [확보성공] {new_filename} ({os.path.getsize(os.path.join(download_dir, new_filename))} bytes)")
                        renamed = True
                        break
                if not renamed:
                    print(f"   ⚠️ {p}페이지 파일 확보 실패")
            except Exception as e:
                print(f"   ⚠️ 다운로드 오류 발생: {e}")

        # --- 데이터 병합 ---
        all_files = sorted([os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith('page_')])
        print(f"📂 병합 파일 목록: {[os.path.basename(f) for f in all_files]}")
        
        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}행 읽기 완료")
                all_dfs.append(df_temp)
            except Exception as e:
                print(f"   ⚠️ {f} 읽기 오류: {e}")

        if all_dfs:
            full_df = pd.concat(all_dfs, ignore_index=True)
            full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
            print(f"✅ 최종 데이터 통합: 총 {len(full_df)}건")

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

            # 최신 NOTAM snapshot JSON 저장 (DOO GPX 호환용)
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

                print(f"💾 JSON 저장 완료: notam-latest.json ({len(json_output)}건)")
            except Exception as e:
                print(f"⚠️ JSON 저장 실패: {e}")

    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
