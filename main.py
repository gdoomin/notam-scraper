import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def test_koca_download():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # 다운로드 폴더 설정
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "directory_upgrade": True
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("1. KOCA 페이지 접속 중...")
        url = "https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR"
        driver.get(url)
        time.sleep(7)

        # iframe 처리
        if len(driver.find_elements(By.TAG_NAME, "iframe")) > 0:
            print("   - iframe 발견! 프레임으로 전환합니다.")
            driver.switch_to.frame(0)

        print("2. [조회] 버튼 클릭 시도...")
        search_xpath = "//button[contains(., '조회')] | //a[contains(., '조회')] | //span[text()='조회']/.."
        search_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, search_xpath))
        )
        driver.execute_script("arguments[0].click();", search_btn)
        print("   - 조회 클릭 성공")
        time.sleep(5)

        print("3. [KML] 다운로드 버튼 클릭 시도...")
        kml_xpath = "//button[contains(., 'KML')] | //a[contains(., 'KML')] | //*[contains(@onclick, 'kml')]"
        kml_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, kml_xpath))
        )
        driver.execute_script("arguments[0].click();", kml_btn)
        print("   - KML 클릭 성공!")

        print("4. 다운로드 대기 중...")
        time.sleep(15)
        
        files = os.listdir(download_dir)
        print(f"✅ 최종 파일 목록: {files}")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
        # 디버깅: 현재 페이지에 있는 버튼 텍스트들을 출력해봅니다.
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"현재 찾은 버튼 개수: {len(buttons)}")
        for b in buttons[:10]:
            print(f"버튼 텍스트: {b.text}")

    finally:
        driver.quit()

if __name__ == "__main__":
    test_koca_download()
