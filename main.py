import os
import time
import re
import json
import requests

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
    print(f"🌐 KOCA NOTAM API 프록시 수집 시작... ({time.strftime('%H:%M:%S')})")
    
    url = "https://aim.koca.go.kr/xNotam/searchList.do"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://aim.koca.go.kr/xNotam/index.do?type=search2&language=ko_KR",
        "X-Requested-With": "XMLHttpRequest"
    }

    # 💡 [해외 IP 차단 우회 핵심] 웹에 공개된 한국 퍼블릭 프록시 중 하나를 경유하도록 세팅합니다.
    # 만약 아래 프록시가 만료되어 작동하지 않으면 다른 한국 proxy IP로 교체해야 합니다.
    proxies = {
        "http": "http://221.168.172.241:8080",
        "https": "http://221.168.172.241:8080"
    }

    notam_list = []
    unique_ids = set()

    for p in range(1, 11):
        print(f"📄 {p}페이지 API 프록시 요청 중...")
        
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
            # proxies 옵션을 추가하고, 프록시 서버 지연을 감안해 timeout을 15초로 설정합니다.
            response = requests.post(url, data=payload, headers=headers, proxies=proxies, timeout=15)
            
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
                
            time.sleep(0.5)
            
        except Exception as e:
            print(f"   ❌ {p}페이지 통신 중 에러 발생 (다른 프록시 IP 필요할 수 있음): {e}")
            break

    print(f"✅ 최종 데이터 통합: 총 {len(notam_list)}건 (중복 제거 완료)")

    if notam_list:
        try:
            json_output = [
                {
                    "lat": item.get("lat"), "lng": item.get("lng"),
                    "content": item.get("content", ""), "notam_id": item.get("notam_id", "")
                }
                for item in notam_list
            ]

            with open("notam-latest.json", "w", encoding="utf-8") as f:
                json.dump(json_output, f, ensure_ascii=False, indent=2)

            print(f"💾 JSON 저장 완료: notam-latest.json ({len(json_output)}건)")
        except Exception as e:
            print(f"⚠️ JSON 저장 실패: {e}")
            raise e
    else:
        raise Exception("수집된 NOTAM 데이터가 0건입니다. 워크플로우를 실패 처리합니다.")

if __name__ == "__main__":
    run_scraper()
