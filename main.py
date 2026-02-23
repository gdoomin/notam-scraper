import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def run_koca_scraper():
    # 1. 서버용 크롬 설정
    options = Options()
    options.add_argument("--headless")  # 화면 없이 실행
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    # 다운로드 경로 설정 (GitHub 워크스페이스 내 temp 폴더)
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    
    prefs = {"download.default_directory": download_dir}
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        # 2. KOCA NOTAM 페이지 접속
        url = "https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR"
        driver.get(url)
        print("페이지 접속 성공")

        # 3. [조회] 버튼 클릭 (데이터를 먼저 불러와야 KML 버튼이 활성화될 수 있음)
        # KOCA 사이트 특성상 조회 버튼의 id나 class를 확인해야 합니다. 
        # 보통 'btn_search' 또는 '조회' 텍스트를 가진 버튼입니다.
        search_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), '조회')]"))
        )
        search_btn.click()
        time.sleep(3) # 결과 로딩 대기

        # 4. [KML] 다운로드 버튼 클릭
        # 화면에 보이는 'KML' 버튼을 찾습니다.
        kml_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'KML')]"))
        )
        kml_btn.click()
        print("KML 다운로드 클릭 완료")

        # 다운로드 완료 대기
        time.sleep(10)
        
        # 5. 다운로드된 파일 확인 및 가공
        files = os.listdir(download_dir)
        print(f"다운로드된 파일들: {files}")
        
        # 여기서 파싱 로직(KML -> JSON)을 추가하고 DB로 쏘면 됩니다!

    except Exception as e:
        print(f"에러 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_koca_scraper()
