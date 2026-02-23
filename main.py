import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def run_scraper():
    # 1. 서버용 크롬 브라우저 설정
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
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
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(10) # 페이지 로딩 대기

        print("2. [KML] 버튼 클릭 시도...")
        # 아까 성공했던 KML 클릭 로직
        kml_xpath = "//*[contains(text(), 'KML')] | //*[contains(@onclick, 'kml')] | //*[@id='btn_kml']"
        kml_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, kml_xpath))
        )
        driver.execute_script("arguments[0].click();", kml_btn)
        print("   ✅ KML 버튼 클릭 성공!")

        print("3. 파일 다운로드 대기 중 (20초)...")
        time.sleep(20)
        
        # 4. 결과 확인 및 내용 출력
        files = os.listdir(download_dir)
        if files:
            file_path = os.path.join(download_dir, files[0])
            print(f"✅ 다운로드 성공: {files[0]}")
            
            # --- KML 내부 데이터 구조 확인을 위한 출력 ---
            print("\n--- [데이터 분석용] KML 내용 시작 ---")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                print(content[:1500]) # 앞부분 1500자 출력
            print("--- KML 내용 끝 ---\n")
            
        else:
            print("❌ 파일이 다운로드되지 않았습니다.")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    run_scraper()
