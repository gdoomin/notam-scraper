import os
import time
import re
import json
import requests
from github import Github

# 1. 좌표 추출 함수 (Doo GPX 지도 표시용)
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
    print(f"🌐 KOCA NOTAM API 로컬 수집 시작... ({time.strftime('%H:%M:%S')})")
    
    # 💡 [설정] 본인의 GitHub 환경에 맞게 입력하세요.
    # 안전을 위해 토큰은 OS 환경변수(NOTAM_JSON_REPO_PAT)에 등록해 쓰거나, 테스트 시 아래 따옴표 안에 직접 넣으셔도 됩니다.
    GITHUB_TOKEN = os.getenv("NOTAM_JSON_REPO_PAT") or "아까_발급받은_ghp_로_시작하는_토큰_입력"
    TARGET_REPO = "gdoomin/notam-json"
    TARGET_BRANCH = "main"
    FILE_PATH = "notam-latest.json"

    url = "https://aim.koca.go.kr/xNotam/searchList.do"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR",
        "X-Requested-With": "XMLHttpRequest"
    }

    notam_list = []
    unique_ids = set()

    # 최대 10페이지까지 데이터를 API로 당겨옵니다 (한국 IP이므로 차단 없음)
    for p in range(1, 11):
        print(f"📄 {p}페이지 API 요청 중...")
        
        payload = {
            "pageIndex": str(p),
            "pageSize": "10",
            "searchType": "search2",
            "language": "ko_KR",
            "sortingField": "NOTAM_ID",
            "sortingOrder": "DESC",
            "notamNo": "", "fir": "", "aeroCode": "", "series": "", "qCode": "",
            "startDttm": "", "endDttm": "", "scopeA": "Y", "scopeE": "Y", "scopeW": "Y",
            "chkInternational": "Y", "chkDomestic": "Y", "chkMilitary": "Y"
        }

        try:
            response = requests.post(url, data=payload, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"   ⚠️ {p}페이지 요청 실패 (Status Code: {response.status_code})")
                break
                
            data = response.json()
            result_list = data.get("resultList", [])
            
            if not result_list:
                print("   -> 더 이상 가져올 데이터가 없습니다. 루프를 종료합니다.")
                break
                
            print(f"   -> {len(result_list)}건 확보 완료")
            
            for item in result_list:
                notam_id = item.get("notamId", "").strip()
                if notam_id in unique_ids:
                    continue
                unique_ids.add(notam_id)
                
                full_text = item.get("fullTxt", "").strip()
                start_date = item.get("effDttm", "").strip()
                end_date = item.get("estDttm", "").strip()
                
                lat, lng = extract_coords(full_text)
                
                notam_list.append({
                    "notam_id": notam_id, "content": full_text, "lat": lat, "lng": lng,
                    "series": notam_id[0] if notam_id else "U", "start_date": start_date, "end_date": end_date
                })
            time.sleep(0.3)
            
        except Exception as e:
            print(f"   ❌ {p}페이지 통신 중 에러 발생: {e}")
            break

    print(f"✅ 최종 데이터 통합: 총 {len(notam_list)}건 (중복 제거 완료)")

    if not notam_list:
        print("❌ 수집된 NOTAM 데이터가 없어 종료합니다.")
        return

    # DOO GPX 구조에 맞게 JSON 스트링 생성
    json_output = [
        {
            "lat": item.get("lat"),
            "lng": item.get("lng"),
            "content": item.get("content", ""),
            "notam_id": item.get("notam_id", "")
        }
        for item in notam_list
    ]
    new_json_content = json.dumps(json_output, ensure_ascii=False, indent=2)

    # 💡 [로컬 우회 핵심] PyGithub 라이브러리를 사용해 gdoomin/notam-json 레포지토리로 바로 업데이트 깃 커밋 날리기
    try:
        print(f"🚀 GitHub {TARGET_REPO} 레포지토리로 푸시 시도 중...")
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(TARGET_REPO)
        
        try:
            # 기존 파일 정보 가져오기 (SHA 값이 필요합니다)
            contents = repo.get_contents(FILE_PATH, ref=TARGET_BRANCH)
            old_json_content = contents.decoded_content.decode("utf-8")
            
            # 갱신된 내용이 완전히 똑같다면 커밋 생략하고 종료
            if old_json_content == new_json_content:
                print("✨ 기존 snapshot 파일과 내용이 동일합니다. 업데이트를 건너뜁니다.")
                return
                
            repo.update_file(
                path=FILE_PATH,
                message="Update NOTAM snapshot (Local Auto Update)",
                content=new_json_content,
                sha=contents.sha,
                branch=TARGET_BRANCH
            )
            print("💾 [성공] 기존 snapshot 파일이 업데이트되어 커밋/푸시되었습니다.")
            
        except Exception as file_not_found:
            # 레포지토리에 파일이 아예 없을 경우 새로 생성
            repo.create_file(
                path=FILE_PATH,
                message="Initial NOTAM snapshot (Local Auto Update)",
                content=new_json_content,
                branch=TARGET_BRANCH
            )
            print("💾 [성공] 새로운 snapshot 파일이 생성되어 커밋/푸시되었습니다.")
            
    except Exception as github_error:
        print(f"❌ GitHub 푸시 실패 (토큰 권한 또는 레포지토리 주소를 확인하세요): {github_error}")

if __name__ == "__main__":
    run_scraper()
