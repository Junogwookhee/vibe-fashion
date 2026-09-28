import os
import logging
from flask import Blueprint, render_template
from dotenv import load_dotenv
from supabase import create_client, Client

# 로깅 설정
logger = logging.getLogger(__name__)

# .env 파일에서 환경변수 로드
load_dotenv()

# 메인 페이지 및 관련 라우트를 관리하는 블루프린트 객체 생성
main_bp = Blueprint('main', __name__)

# Supabase 접속 기본값 설정 (Azure 등 클라우드 배포 환경에서 환경변수 누락 시 자동 대체)
DEFAULT_SUPABASE_URL = "https://rdkvvonoenyzskovspcc.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJka3Z2b25vZW55enNrb3ZzcGNjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwNTMxOTQsImV4cCI6MjEwNTYyOTE5NH0."
    "yihCagU115cYIXlST52YeobVBePfiNRxw719RoWH4M4"
)

# Supabase 클라이언트 초기화 함수
def get_supabase_client() -> Client:
    supabase_url = os.getenv('SUPABASE_URL') or DEFAULT_SUPABASE_URL
    supabase_key = os.getenv('SUPABASE_ANON_KEY') or DEFAULT_SUPABASE_ANON_KEY

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL 또는 SUPABASE_ANON_KEY 환경변수가 설정되지 않았습니다.")

    return create_client(supabase_url, supabase_key)


@main_bp.route('/')
def index():
    """
    메인 홈 화면 라우트:
    Supabase products 테이블에서 is_active=true, is_featured=true인 상품 최대 4개를 조회하여 템플릿에 전달합니다.
    연결 실패 시 빈 리스트로 대체하며 터미널에 에러 로그를 출력합니다.
    """
    products = []

    try:
        supabase = get_supabase_client()
        response = (
            supabase.table('products')
            .select('id, name, description, price, sale_price, thumbnail_url, sort_order, is_active, is_featured')
            .eq('is_active', True)
            .eq('is_featured', True)
            .order('sort_order')
            .limit(4)
            .execute()
        )

        for item in response.data or []:
            # 가격 포맷팅 ({:,}원 형태, sale_price가 있을 경우 활용 가능하도록 원가 및 할인가 처리)
            raw_price = float(item.get('price') or 0)
            formatted_price = f"{int(raw_price):,}원"

            sale_price = item.get('sale_price')
            formatted_sale_price = None
            discount_percent = None

            if sale_price and float(sale_price) < raw_price and raw_price > 0:
                sale_val = float(sale_price)
                formatted_sale_price = f"{int(sale_val):,}원"
                discount_percent = int(round((1 - (sale_val / raw_price)) * 100))

            products.append({
                'id': item.get('id'),
                'name': item.get('name'),
                'description': item.get('description') or '',
                'price': formatted_price,
                'sale_price': formatted_sale_price,
                'discount_percent': discount_percent,
                'thumbnail_url': item.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=600&q=80',
            })
    except Exception as e:
        logger.error(f"[Supabase Error] 상품 데이터 조회 실패: {e}", exc_info=True)
        print(f"[Supabase Error] 상품 데이터 조회 실패: {e}")
        products = []

    return render_template('index.html', products=products)
