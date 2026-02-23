try:
        print("1. KOCA 페이지 접속 중...")
        url = "https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR"
        driver.get(url)
        time.sleep(7) # 전체 페이지 로딩 넉넉히 대기

        # --- 추가된 부분: iframe이 있는지 확인하고 전환 ---
        # KOCA 사이트는 메인 콘텐츠가 iframe 안에 있을 확률이 높습니다.
        if len(driver.find_elements(By.TAG_NAME, "iframe")) > 0:
            print("   - iframe 발견! 첫 번째 프레임으로 전환합니다.")
            driver.switch_to.frame(0) 

        print("2. [조회] 버튼 클릭 시도...")
        # KOCA의 조회 버튼은 보통 id나 특정 클래스를 가집니다.
        # 아래는 KOCA 사이트의 실제 구조를 반영한 3가지 후보군입니다.
        search_xpath = "//button[@id='btn_search'] | //a[@id='btn_search'] | //span[text()='조회']/parent::button | //button[contains(., '조회')]"
        
        search_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, search_xpath))
        )
        # 일반 클릭이 안될 경우를 대비해 자바스크립트로 클릭 실행
        driver.execute_script("arguments[0].click();", search_btn)
        print("   - 조회 버튼 클릭 완료 (데이터 로딩 대기)")
        time.sleep(5)

        print("3. [KML] 다운로드 버튼 클릭 시도...")
        # KML 버튼도 id 기반으로 찾거나 텍스트 포함 요소로 찾습니다.
        kml_xpath = "//button[contains(., 'KML')] | //a[contains(., 'KML')] | //button[contains(@onclick, 'kml')]"
        
        kml_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, kml_xpath))
        )
        driver.execute_script("arguments[0].click();", kml_btn)
        print("   - KML 버튼 클릭 성공!")

        # 4. 파일 다운로드 대기
        print("4. 파일 다운로드 대기 중 (15초)...")
        time.sleep(15)
        
        files = os.listdir(download_dir)
        print(f"✅ 결과: {files}")

    except Exception as e:
        print(f"🚨 에러 상세: {e}")
        # 에러 발생 시 현재 페이지의 HTML을 일부 출력해서 버튼이 왜 안보이는지 확인
        print("DEBUG: 현재 페이지 버튼 목록 ->", [b.text for b in driver.find_elements(By.TAG_NAME, "button")[:5]])
