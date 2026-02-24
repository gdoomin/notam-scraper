import os
import time
import re
import shutil
import glob
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

def wait_for_new_download(download_dir, existing_files, timeout=90):
    """기존 파일 목록과 비교해서 새 파일이 완전히 다운로드될 때까지 대기"""
    for _ in range(timeout):
        time.sleep(1)
        current_files = set(os.listdir(download_dir))
        new_files = [f for f in current_files - existing_files 
                     if not f.endswith('.crdownload') and not f.endswith('.tmp')]
        if new_files:
            time.sleep(2)  # 파일 쓰기 완료 대기
            return new_files[0]
    return None

def click_page(driver, wait, page_num):
    """페이지 버튼 클릭 - 여러 방식 시도"""
    try:
        # 방법 1: 텍스트로 페이지 버튼 찾기
        page_btns = driver.find_elements(By.XPATH, 
            f"//table//td[normalize-space(text())='{page_num}']")
        for btn in page_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                print(f"   -> {page_num}페이지 버튼 클릭 (텍스트 방식)")
                return True
    except: pass
    
    try:
        # 방법 2: a 태그로 찾기
        page_links = driver.find_elements(By.XPATH,
            f"//a[normalize-space(text())='{page_num}']")
        for link in page_links:
            if link.is_displayed():
                driver.execute_script("arguments[0].click();", link)
                print(f"   -> {page_num}페이지 링크 클릭")
                return True
    except: pass
    
    return False

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
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_cdp_cmd('Page.setDownloadBehavior', {
        'behavior': 'allow',
        'downloadPath': download_dir
    })
    driver.set_page_load_timeout(180)
    wait = WebDriverWait(driver, 60)

    try:
        print(f"🌐 KOCA 접속: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        
        print("⏳ 초기 로딩 대기 (40초)...")
        time.sleep(40)

        for p in range(1, 5):  # 1~4페이지
            print(f"\n{'='*40}")
            print(f"📄 {p}페이지 처리 시작")
            
            # 1페이지 제외하고 페이지 이동
            if p > 1:
                success = click_page(driver, wait, p)
                if not success:
                    print(f"   ⚠️ {p}페이지 버튼을 찾지 못함. 페이지네이션 구조 확인 필요")
                    # 디버깅: 현재 페이지네이션 영역 HTML 출력
                    try:
                        pagination = driver.find_element(By.XPATH, "//table[.//td[@class='paginate_button']]")
                        print(f"   [DEBUG] 페이지네이션 HTML:\n{pagination.get_attribute('outerHTML')[:500]}")
                    except:
                        print("   [DEBUG] 페이지네이션 요소를 찾을 수 없음")
                    break
                
                print(f"   ⏳ 페이지 로딩 대기...")
                time.sleep(25)

            # 현재 다운로드 폴더 상태 스냅샷
            existing_files = set(os.listdir(download_dir))
            
            # 엑셀 다운로드 버튼 클릭
            try:
                # 엑셀 버튼 - 여러 XPath/선택자 시도
                excel_btn = None
                selectors = [
                    '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]',
                    '//a[contains(@onclick, "excel") or contains(@href, "excel")]',
                    '//a[contains(text(), "엑셀") or contains(text(), "Excel") or contains(text(), "XLS")]',
                    '//img[contains(@src, "excel") or contains(@alt, "excel")]/parent::a',
                ]
                
                for sel in selectors:
                    try:
                        el = driver.find_element(By.XPATH, sel)
                        if el.is_displayed():
                            excel_btn = el
                            print(f"   -> 엑셀 버튼 발견: {sel[:50]}")
                            break
                    except: continue
                
                if not excel_btn:
                    print(f"   ⚠️ {p}페이지 엑셀 버튼 없음")
                    # 디버깅용 스크린샷
                    driver.save_screenshot(f"debug_page_{p}.png")
                    print(f"   [DEBUG] 스크린샷 저장: debug_page_{p}.png")
                    continue
                
                driver.execute_script("arguments[0].click();", excel_btn)
                print(f"   -> 엑셀 다운로드 클릭")
                
            except Exception as e:
                print(f"   ⚠️ 엑셀 버튼 클릭 실패: {e}")
                continue

            # 새 파일 대기
            print(f"   ⏳ 다운로드 완료 대기...")
            new_file = wait_for_new_download(download_dir, existing_files, timeout=90)
            
            if new_file:
                old_path = os.path.join(download_dir, new_file)
                new_filename = f"page_{p}_notam.xls"
                new_path = os.path.join(download_dir, new_filename)
                # 기존 동명 파일 있으면 삭제
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(old_path, new_path)
                file_size = os.path.getsize(new_path)
                print(f"   ✅ [{p}페이지] {new_filename} 저장 완료 ({file_size:,} bytes)")
            else:
                print(f"   ⚠️ [{p}페이지] 다운로드 감지 실패")
                driver.save_screenshot(f"debug_download_fail_p{p}.png")

        # 파일 병합
        all_files = sorted(glob.glob(os.path.join(download_dir, 'page_*.xls')))
        print(f"\n{'='*40}")
        print(f"📂 총 {len(all_files)}개 파일 병합 중...")

        if not all_files:
            print("🚨 파일 없음. debug_*.png 스크린샷 확인하세요.")
            return

        all_dfs = []
        for f in all_files:
            try:
                df = pd.read_excel(f, engine='xlrd')
                print(f"   -> {os.path.basename(f)}: {len(df)}건")
                all_dfs.append(df)
            except Exception as e:
                print(f"   ⚠️ {f} 읽기 실패: {e}")

        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 중복 제거 후 최종: {len(full_df)}건")

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
            print(f"🚀 [완료] {len(notam_list)}건 DB 업서트!")

    except Exception as e:
        import traceback
        print(f"🚨 에러: {e}")
        traceback.print_exc()
        driver.save_screenshot("debug_error.png")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
