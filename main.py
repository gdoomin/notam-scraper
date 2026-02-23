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
        
        # 페이지 로딩 대기
        time.sleep(5)

        print("2. [조회] 버튼 클릭 시도...")
        # KOCA 사이트의 '조회' 버튼 XPath (일반적인 버튼 텍스트 기준)
        search_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., '조회')] | //a[contains(., '조회')]"))
        )
        search_btn.click()
        print("   - 조회 버튼 클릭 완료 (데이터 로딩 대기)")
        time.sleep(5)

        print("3. [KML] 다운로드 버튼 클릭 시도...")
        # KML 버튼 XPath
        kml_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'KML')] | //a[contains(., 'KML')]"))
        )
        kml_btn.click()
        print("   - KML 버튼 클릭 성공!")

        # 다운로드 대기 (15초)
        print("4. 파일 다운로드 대기 중 (15초)...")
        time.sleep(15)
        
        # 결과 확인
        files = os.listdir(download_dir)
        if files:
            print(f"✅ 성공! 다운로드된 파일 목록: {files}")
        else:
            print("❌ 실패: 다운로드 폴더가 비어 있습니다.")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
        # 에러 발생 시 현재 화면의 텍스트 일부 출력 (디버깅용)
        print("현재 페이지 요약:", driver.title)
    finally:
        driver.quit()

if __name__ == "__main__":
    test_koca_download()
