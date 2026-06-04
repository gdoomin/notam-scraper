import os
import time
import re
import shutil
import json
import glob
import pandas as pd

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)


KOCA_URL = "https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR"


def find_notam_id_in_source(source):
    match = re.search(r"[A-Z]\d{4}/\d{2}", source or "")
    return match.group(0) if match else None


def extract_coords(full_text):
    try:
        match = re.search(r"(\d{4}[NS])(\d{5}[EW])", full_text or "")
        if match:
            lat_str, lng_str = match.groups()

            lat = int(lat_str[:2]) + int(lat_str[2:4]) / 60
            if "S" in lat_str:
                lat = -lat

            lng = int(lng_str[:3]) + int(lng_str[3:5]) / 60
            if "W" in lng_str:
                lng = -lng

            return lat, lng
    except Exception:
        pass

    return 37.5665, 126.9780


def make_driver(download_dir):
    options = Options()

    # GitHub Actions 안정화 옵션
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")

    # 페이지 전체 리소스를 끝까지 기다리지 않음
    options.page_load_strategy = "eager"

    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_setting_values.multiple_automatic_downloads": 1,
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )

    driver.set_page_load_timeout(45)
    driver.set_script_timeout(45)

    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": download_dir},
        )
    except Exception as e:
        print(f"⚠️ 다운로드 설정 CDP 실패, 계속 진행: {e}")

    return driver


def safe_get(driver, url, wait_seconds=45, max_retry=3):
    for attempt in range(1, max_retry + 1):
        try:
            print(f"🌐 페이지 접속 시도 {attempt}/{max_retry}")
            driver.get(url)
            return True

        except TimeoutException:
            print("⚠️ driver.get() 타임아웃. window.stop() 후 DOM 확인")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

            time.sleep(3)

            try:
                if "notam" in driver.page_source.lower() or "Notam" in driver.page_source:
                    print("✅ 타임아웃이지만 페이지 일부 로드 확인. 계속 진행")
                    return True
            except Exception:
                pass

        except WebDriverException as e:
            print(f"⚠️ WebDriver 오류: {e}")

        time.sleep(5)

    return False


def wait_table(driver, timeout=60):
    wait = WebDriverWait(driver, timeout)

    candidates = [
        (By.ID, "notamSheet-table"),
        (By.XPATH, '//*[@id="notamSheet-table"]'),
        (By.XPATH, "//table[contains(@id, 'notam')]"),
    ]

    for by, value in candidates:
        try:
            wait.until(EC.presence_of_element_located((by, value)))
            print("✅ 테이블 확인")
            return True
        except TimeoutException:
            continue

    print("⚠️ 테이블을 찾지 못함")
    return False


def click_excel_download(driver, wait):
    excel_xpath = '//*[@id="realContents"]/div[3]/div[1]/div/div/a[3]'

    for attempt in range(1, 4):
        try:
            excel_btn = wait.until(EC.element_to_be_clickable((By.XPATH, excel_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", excel_btn)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", excel_btn)
            return True

        except Exception as e:
            print(f"   ⚠️ 엑셀 버튼 클릭 실패 {attempt}/3: {e}")
            time.sleep(3)

    return False


def wait_and_rename_download(download_dir, page_num, timeout=90):
    end_time = time.time() + timeout

    while time.time() < end_time:
        time.sleep(1)

        partials = glob.glob(os.path.join(download_dir, "*.crdownload"))
        if partials:
            continue

        files = [
            f for f in os.listdir(download_dir)
            if (f.endswith(".xls") or f.endswith(".xlsx"))
            and not f.startswith("page_")
        ]

        if files:
            old_path = os.path.join(download_dir, files[0])

            if os.path.getsize(old_path) <= 0:
                continue

            new_filename = f"page_{page_num}_notam.xls"
            new_path = os.path.join(download_dir, new_filename)

            if os.path.exists(new_path):
                os.remove(new_path)

            os.rename(old_path, new_path)
            print(f"   -> [확보성공] {new_filename} ({os.path.getsize(new_path)} bytes)")
            return True

    return False


def go_next_page(driver, wait, last_page_id):
    next_xpath = '//*[@id="notamSheet-table"]/tbody/tr[5]/td/div/table/tbody/tr/td[5]'

    for attempt in range(1, 4):
        try:
            next_btn = wait.until(EC.element_to_be_clickable((By.XPATH, next_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btn)
            time.sleep(1)

            try:
                ActionChains(driver).move_to_element(next_btn).click().perform()
            except Exception:
                driver.execute_script("arguments[0].click();", next_btn)

            print("   -> 다음 페이지 클릭 완료. 데이터 갱신 확인 중...")

            for _ in range(60):
                time.sleep(1)
                new_id = find_notam_id_in_source(driver.page_source)

                if new_id and new_id != last_page_id:
                    print(f"   -> [성공] 데이터 갱신: {last_page_id} -> {new_id}")
                    return new_id

            print(f"   ⚠️ 다음 페이지 갱신 미확인 {attempt}/3")

        except (TimeoutException, StaleElementReferenceException, WebDriverException) as e:
            print(f"   ⚠️ 다음 페이지 클릭 실패 {attempt}/3: {e}")
            time.sleep(3)

    return None


def save_empty_json():
    with open("notam-latest.json", "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=2)
    print("⚠️ 수집 데이터 없음. 빈 notam-latest.json 저장")


def run_scraper():
    download_dir = os.path.join(os.getcwd(), "downloads")

    if os.path.exists(download_dir):
        shutil.rmtree(download_dir)

    os.makedirs(download_dir, exist_ok=True)

    driver = None

    try:
        driver = make_driver(download_dir)
        wait = WebDriverWait(driver, 60)

        print(f"🌐 KOCA NOTAM 수집 시작... ({time.strftime('%H:%M:%S')})")

        if not safe_get(driver, KOCA_URL):
            print("❌ KOCA 페이지 접속 실패")
            save_empty_json()
            return

        print("⏳ 테이블 로딩 대기 중...")
        if not wait_table(driver, timeout=60):
            save_empty_json()
            return

        time.sleep(5)

        last_page_id = find_notam_id_in_source(driver.page_source)

        if not last_page_id:
            print("⚠️ 첫 페이지 NOTAM ID를 찾지 못했지만 다운로드는 시도")
        else:
            print(f"   -> 1페이지 기준 ID: {last_page_id}")

        for p in range(1, 11):
            print(f"📄 {p}페이지 작업 시작...")

            if p > 1:
                new_id = go_next_page(driver, wait, last_page_id)

                if not new_id:
                    print("   ⚠️ 다음 페이지 없음 또는 갱신 실패. 페이지 반복 종료")
                    break

                last_page_id = new_id
                time.sleep(3)

            try:
                if click_excel_download(driver, wait):
                    print(f"   -> {p}페이지 엑셀 다운로드 요청")

                    if not wait_and_rename_download(download_dir, p):
                        print(f"   ⚠️ {p}페이지 파일 확보 실패")
                else:
                    print(f"   ⚠️ {p}페이지 엑셀 버튼 클릭 실패")

            except Exception as e:
                print(f"   ⚠️ {p}페이지 다운로드 처리 오류: {e}")

        all_files = sorted(
            [
                os.path.join(download_dir, f)
                for f in os.listdir(download_dir)
                if f.startswith("page_") and (f.endswith(".xls") or f.endswith(".xlsx"))
            ]
        )

        print(f"📂 병합 파일 목록: {[os.path.basename(f) for f in all_files]}")

        all_dfs = []

        for f in all_files:
            try:
                df_temp = pd.read_excel(f, engine="xlrd")
                print(f"   -> {os.path.basename(f)}: {len(df_temp)}행 읽기 완료")
                all_dfs.append(df_temp)

            except Exception as e:
                print(f"   ⚠️ {os.path.basename(f)} 읽기 오류: {e}")

        if not all_dfs:
            save_empty_json()
            return

        full_df = pd.concat(all_dfs, ignore_index=True)

        if "Notam#" in full_df.columns:
            full_df.drop_duplicates(subset=["Notam#"], keep="first", inplace=True)
        else:
            print("⚠️ 'Notam#' 컬럼 없음. 중복 제거 생략")

        print(f"✅ 최종 데이터 통합: 총 {len(full_df)}건")

        notam_list = []

        for _, row in full_df.iterrows():
            notam_id = str(row.get("Notam#", "")).strip()
            full_text = str(row.get("Full Text", "")).strip()
            lat, lng = extract_coords(full_text)

            notam_list.append(
                {
                    "notam_id": notam_id,
                    "content": full_text,
                    "lat": lat,
                    "lng": lng,
                    "series": notam_id[0] if notam_id else "U",
                    "start_date": str(row.get("Start Date UTC", "")),
                    "end_date": str(row.get("End Date UTC", "")),
                }
            )

        json_output = [
            {
                "lat": item["lat"],
                "lng": item["lng"],
                "content": item["content"],
                "notam_id": item["notam_id"],
            }
            for item in notam_list
        ]

        with open("notam-latest.json", "w", encoding="utf-8") as f:
            json.dump(json_output, f, ensure_ascii=False, indent=2)

        print(f"💾 JSON 저장 완료: notam-latest.json ({len(json_output)}건)")

    except Exception as e:
        print(f"❌ 치명적 오류 발생: {e}")
        save_empty_json()

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    run_scraper()
