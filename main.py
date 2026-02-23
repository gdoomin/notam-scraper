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
    options.add_argument("--window-size=1920,1080") # 창 크기를 크게 키워야 버튼이 잘 보입니다.
    
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir): os.makedirs(download_dir)
    
    prefs = {"download.default_directory": download_dir}
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("1. KOCA 페이지 접속 중...")
        driver.get("https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR")
        time.sleep(10) # 로딩 시간을 넉넉히 줍니다.

        # --- 모든 프레임을 순회하며 버튼 찾기 ---
        found = False
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"발견된 iframe 개수: {len(iframes)}")

        # 프레임 안으로 들어가는 시도
        for i, frame in enumerate(iframes):
            driver.switch_to.default_content() # 초기화
            driver.switch_to.frame(i)
            print(f"[{i}번 프레임] 탐색 중...")
            
            try:
                # '조회' 버튼 찾기 (텍스트가 없을 수 있으니 id와 class로도 시도)
                search_xpath = "//button[contains(., '조회')] | //a[contains(., '조회')] | //input[@value='조회'] | //*[@id='btn_search']"
                search_btn = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, search_xpath))
                )
                driver.execute_script("arguments[0].scrollIntoView();", search_btn)
                driver.execute_script("arguments[0].click();", search_btn)
                print(f"   ✅ {i}번 프레임에서 조회 버튼 클릭 성공!")
                found = True
                break # 찾았으면 프레임 순회 중환
            except:
                continue

        if not found:
            print("❌ 모든 프레임에서도 버튼을 찾지 못했습니다. 메인 컨텐츠에서 다시 시도합니다.")
            driver.switch_to.default_content()

        # 3. KML 다운로드 버튼 클릭
        print("3. [KML] 버튼 클릭 시도...")
        time.sleep(5) # 데이터 로딩 대기
        kml_xpath = "//*[contains(text(), 'KML')] | //*[contains(@onclick, 'kml')] | //*[@id='btn_kml']"
        kml_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, kml_xpath))
        )
        driver.execute_script("arguments[0].click();", kml_btn)
        print("   ✅ KML 버튼 클릭 성공!")

        print("4. 다운로드 대기 중...")
        time.sleep(20)
        
        files = os.listdir(download_dir)
        print(f"🚀 최종 결과: {files}")

    except Exception as e:
        print(f"🚨 최종 에러: {e}")
        # 실패 시 화면 캡처 대신 현재 HTML 구조를 조금 더 출력
        print("DEBUG: Page Source 일부", driver.page_source[:500])

    finally:
        driver.quit()

if __name__ == "__main__":
    test_koca_download()
