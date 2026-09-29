import os
from supabase import create_client, Client

# Supabase 접속 기본값 설정 (Azure 등 클라우드 배포 환경에서 환경변수 누락 시 자동 대체)
DEFAULT_SUPABASE_URL = "https://rdkvvonoenyzskovspcc.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJka3Z2b25vZW55enNrb3ZzcGNjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwNTMxOTQsImV4cCI6MjEwNTYyOTE5NH0."
    "yihCagU115cYIXlST52YeobVBePfiNRxw719RoWH4M4"
)
DEFAULT_SUPABASE_SERVICE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJka3Z2b25vZW55enNrb3ZzcGNjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MDA1MzE5NCwiZXhwIjoyMTA1NjI5MTk0fQ."
    "d0UoTlFSAEIou91Iy8EzWz9v64QLEL_UftyDAFrMFqM"
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
    service_key = os.getenv('SUPABASE_SERVICE_KEY') or DEFAULT_SUPABASE_SERVICE_KEY

    if not supabase_url or not service_key:
        raise ValueError("SUPABASE_URL 또는 SUPABASE_SERVICE_KEY 환경변수가 설정되지 않았습니다.")

    return create_client(supabase_url, service_key)
