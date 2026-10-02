import os
from supabase import create_client, Client

# 공개 프로젝트 URL/anon key 기본값. 서비스 롤 키는 환경변수만 사용합니다.
DEFAULT_SUPABASE_URL = "https://rdkvvonoenyzskovspcc.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJka3Z2b25vZW55enNrb3ZzcGNjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwNTMxOTQsImV4cCI6MjEwNTYyOTE5NH0."
    "yihCagU115cYIXlST52YeobVBePfiNRxw719RoWH4M4"
)
def get_supabase_client() -> Client:
    """일반 조회 및 사용자 세션용 Supabase 클라이언트"""
    supabase_url = os.getenv('SUPABASE_URL') or DEFAULT_SUPABASE_URL
    supabase_key = os.getenv('SUPABASE_ANON_KEY') or DEFAULT_SUPABASE_ANON_KEY

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL 또는 SUPABASE_ANON_KEY 환경변수가 설정되지 않았습니다.")

    return create_client(supabase_url, supabase_key)


def get_supabase_admin_client() -> Client:
    """회원 생성/인증/주문/삭제 등 관리자 권한용 Supabase 서비스 롤 클라이언트"""
    supabase_url = os.getenv('SUPABASE_URL') or DEFAULT_SUPABASE_URL
    service_key = os.getenv('SUPABASE_SERVICE_KEY')

    if not supabase_url or not service_key:
        raise ValueError("SUPABASE_URL 또는 SUPABASE_SERVICE_KEY 환경변수가 설정되지 않았습니다.")

    return create_client(supabase_url, service_key)
