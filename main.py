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


# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────

def find_notam_id_in_source(source):
    """페이지 소스에서 NOTAM ID 추출 (페이지 전환 감지용)"""
    match = re.search(r'[A-Z]\d{4}/\d{2}', source)
    return match.group(0) if match else None


def extract_coords(full_text):
    """NOTAM 본문에서 위/경도 추출"""
    try:
        match = re.search(r'(\d{4}[NS])(\d{5}[EW])', full_text)
        if match:
            lat_str, lng_str = match.groups()
            lat = int(lat_str[:2]) + int(lat_str[2:4]) / 60
            if 'S' in lat_str:
                lat = -lat
            lng = int(lng_str[:3]) + int(lng_str[3:5]) / 60
            if 'W' in lng_str:
                lng = -lng
            return lat, lng
    except:
        pass
    return 37.5665, 126.9780


def find_page_button(driver, page_num):
    """
    페이지 번호 버튼을 텍스트 기반으로 찾는다.
    여러 XPath 전략을 순서대로 시도한다.
    """
    strategies = [
        # 전략 1: 텍스트가 정확히 페이지 번호인 td
        f"//table//td[normalize-space(text())='{page_num}']",
        # 전략 2: a 태그 텍스트 기반
        f"//table//a[normalize-space(text())='{page_num}']",
        # 전략 3: 절대경로 (기존 방식, fallback)
        f"/html/body/div[2]/div[3]/div[2]/div/div/div[2]/div[3]/div[2]/div/div/div/div/div/table/tbody/tr[5]/td/div/table/tbody/tr/td[{page_num + 3}]",
    ]

    for xpath in strategies:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for el in elements:
                if el.is_displayed() and el.is_enabled():
                    return el
        except:
            continue
    return None


def get_total_pages(driver):
    """
    페이지 네비게이션에서 총 페이지 수를 파악한다.
    감지 실패 시 기본값 10 반환.
    """
    try:
        # 페이지 버튼 영역에서 숫자 텍스트만 추출
        candidates = driver.find_elements(
            By.XPATH,
            "//table//td[string-length(normalize-space(text()))<=2 and normalize-space(text())!='']"
        )
        nums = []
        for el in candidates:
            t = el.text.strip()
            if t.isdigit():
                nums.append(int(t))
        if nums:
            total = max(nums)
            print(f"   -> 총 {total}페이지 자동 감지")
            return total
    except:
        pass
    print("   -> 페이지 수 감지 실패, 기본값 10 사용")
    return 10


def wait_for_page_update(driver, old_id, timeout=60):
    """
    페이지 소스가 old_id와 다른 NOTAM ID를 포함할 때까지 기다린다.
    반환: (성공 여부, 새 ID)
    """
    for _ in range(timeout):
        time.sleep(1)
        new_id = find_notam_id_in_source(driver.page_source)
        if new_id and new_id != old_id:
            return True, new_id
    return False, old_id


def click_page_button(driver, btn):
    """버튼 스크롤 → ActionChains 클릭 → 실패 시 JS 클릭"""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
        time.sleep(2)
        ActionChains(driver).move_to_element(btn).click().perform()
        return True
    except:
        pass
    try:
        driver.execute_script("arguments[0].click();", btn)
        return True
    except:
        return False


def download_excel(driver, wait, download_dir, page_num, timeout=90):
    """
    현재 페이지의 엑셀을 다운로드하고 page_N_notam.xls 로 저장.
    반환: 저장된 파일 경로 or None
    """
    try:
        excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'
        excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
        driver.execute_script("arguments[0].click();", excel_btn)
        print(f"   -> {page_num}페이지 다운로드 버튼 클릭")
    except Exception as e:
        print(f"   ⚠️ 다운로드 버튼 클릭 실패: {e}")
        return None

    for _ in range(timeout):
        time.sleep(1)
        files = [
            f for f in os.listdir(download_dir)
            if not f.startswith('page_') and not f.endswith('.crdownload')
        ]
        if files:
            time.sleep(3)  # 파일 쓰기 완료 대기
            old_path = os.path.join(download_dir, files[0])
            new_filename = f"page_{page_num}_notam.xls"
            new_path = os.path.join(download_dir, new_filename)
            os.rename(old_path, new_path)
            size = os.path.getsize(new_path)
            print(f"   -> [확보] {new_filename} ({size} bytes)")
            return new_path

    print(f"   ⚠️ {page_num}페이지 다운로드 타임아웃")
    return None


# ─────────────────────────────────────────────
# 메인 스크래퍼
# ─────────────────────────────────────────────

def run_scraper():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    supabase: Client = create_client(url, key)

    # 다운로드 폴더 초기화
    download_dir = os.path.join(os.getcwd(), "downloads")
    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)
    os.makedirs(download_dir)

    # Chrome 옵션
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    prefs = {
        "download.default_directory": download_dir,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1,
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.execute_cdp_cmd(
        'Page.setDownloadBehavior',
        {'behavior': 'allow', 'downloadPath': download_dir}
    )
    wait = WebDriverWait(driver, 60)

    try:
        print(f"🌐 KOCA NOTAM 수집 시작... ({time.strftime('%H:%M:%S')})")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        print("   -> 초기 페이지 로딩 대기 (55초)...")
        time.sleep(55)

        # ── 1페이지 처리 ──
        print("📄 1페이지 수집 작업 시작...")
        last_id = find_notam_id_in_source(driver.page_source)
        print(f"   -> 1페이지 ID 확보: {last_id}")
        download_excel(driver, wait, download_dir, 1)

        # ── 총 페이지 수 파악 ──
        total_pages = get_total_pages(driver)

        # ── 2페이지 이후 처리 ──
        for p in range(2, total_pages + 1):
            print(f"📄 {p}페이지 수집 작업 시작...")

            # 1) 페이지 버튼 탐색 (최대 30초)
            page_btn = None
            for attempt in range(30):
                page_btn = find_page_button(driver, p)
                if page_btn:
                    break
                time.sleep(1)

            if not page_btn:
                print(f"   -> {p}페이지 버튼을 찾지 못했습니다. 수집 종료.")
                break

            # 2) 버튼 클릭
            clicked = click_page_button(driver, page_btn)
            if not clicked:
                print(f"   -> {p}페이지 클릭 실패. 건너뜁니다.")
                continue

            print(f"   -> {p}페이지 클릭 완료. 갱신 확인 중...")

            # 3) 페이지 갱신 대기 (최대 60초)
            updated, new_id = wait_for_page_update(driver, last_id, timeout=60)

            if updated:
                print(f"   -> [성공] 데이터 교체 확인: {last_id} -> {new_id}")
                last_id = new_id
            else:
                # JS 강제 클릭 재시도
                print(f"   ⚠️ 갱신 미확인. JS 강제 클릭 재시도...")
                try:
                    page_btn = find_page_button(driver, p)
                    if page_btn:
                        driver.execute_script("arguments[0].click();", page_btn)
                except:
                    pass

                updated, new_id = wait_for_page_update(driver, last_id, timeout=30)

                if updated:
                    print(f"   -> [JS 재시도 성공] {last_id} -> {new_id}")
                    last_id = new_id
                else:
                    print(f"   ⚠️ {p}페이지 갱신 최종 실패. 다운로드 스킵.")
                    continue  # 같은 데이터 중복 저장 방지를 위해 건너뜀

            # 4) 엑셀 다운로드
            download_excel(driver, wait, download_dir, p)

        # ── 데이터 병합 ──
        all_files = sorted([
            os.path.join(download_dir, f)
            for f in os.listdir(download_dir)
            if f.startswith('page_')
        ])
        print(f"\n📂 병합 파일 목록: {[os.path.basename(f) for f in all_files]}")

        all_dfs = []
        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine='xlrd')
                all_dfs.append(df_temp)
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}행 추가")
            except Exception as e:
                print(f"   ⚠️ {os.path.basename(f)} 읽기 실패: {e}")
                continue

        if not all_dfs:
            print("❌ 수집된 파일이 없습니다.")
            return

        full_df = pd.concat(all_dfs, ignore_index=True)
        full_df.drop_duplicates(subset=['Notam#'], keep='first', inplace=True)
        print(f"✅ 최종 데이터 확보: 총 {len(full_df)}건")

        # ── Supabase 동기화 ──
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
                "end_date": str(row.get('End Date UTC', '')),
            })

        print("🧹 이전 노탐 청소 중...")
        supabase.table("notams").delete().neq("notam_id", "0").execute()

        # 대량 upsert 시 배치 처리 (안정성 향상)
        BATCH_SIZE = 100
        for i in range(0, len(notam_list), BATCH_SIZE):
            batch = notam_list[i:i + BATCH_SIZE]
            supabase.table("notams").upsert(batch, on_conflict="notam_id").execute()
            print(f"   -> {i + len(batch)}/{len(notam_list)}건 업로드 완료")

        print(f"🚀 [최종 성공] {len(notam_list)}건의 데이터를 DB에 반영했습니다!")

    finally:
        driver.quit()


if __name__ == "__main__":
    run_scraper()
