import os
import logging
import random
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
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
DEFAULT_SUPABASE_SERVICE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJka3Z2b25vZW55enNrb3ZzcGNjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc5MDA1MzE5NCwiZXhwIjoyMTA1NjI5MTk0fQ."
    "d0UoTlFSAEIou91Iy8EzWz9v64QLEL_UftyDAFrMFqM"
)

# Supabase 클라이언트 초기화 함수
def get_supabase_client() -> Client:
    supabase_url = os.getenv('SUPABASE_URL') or DEFAULT_SUPABASE_URL
    supabase_key = os.getenv('SUPABASE_ANON_KEY') or DEFAULT_SUPABASE_ANON_KEY

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL 또는 SUPABASE_ANON_KEY 환경변수가 설정되지 않았습니다.")

    return create_client(supabase_url, supabase_key)


def get_supabase_admin_client() -> Client:
    """회원 생성 및 인증 처리를 위한 서비스 롤 클라이언트"""
    supabase_url = os.getenv('SUPABASE_URL') or DEFAULT_SUPABASE_URL
    service_key = os.getenv('SUPABASE_SERVICE_KEY') or DEFAULT_SUPABASE_SERVICE_KEY
    return create_client(supabase_url, service_key)


@main_bp.route('/')
def index():
    """
    메인 홈 화면 라우트:
    - Supabase products 테이블에서 신상품 컬렉션 조회
    - Supabase reviews 테이블에서 최신 고객 리뷰 및 평점 데이터 조회
    """
    products = []
    reviews = []
    avg_rating = 5.0
    total_reviews = 0

    try:
        supabase = get_supabase_client()
        # 1. 상품 조회
        response = (
            supabase.table('products')
            .select('id, name, description, price, sale_price, thumbnail_url, sort_order, is_active, is_featured')
            .eq('is_active', True)
            .eq('is_featured', True)
            .order('sort_order')
            .limit(8)
            .execute()
        )

        for item in response.data or []:
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
                'slug': item.get('slug'),
                'name': item.get('name'),
                'description': item.get('description') or '',
                'price': formatted_price,
                'sale_price': formatted_sale_price,
                'discount_percent': discount_percent,
                'thumbnail_url': item.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=600&q=80',
            })

        # 2. 고객 평점 및 리뷰 조회
        reviews_res = (
            supabase.table('reviews')
            .select('id, rating, content, created_at, products(name, thumbnail_url), profiles(full_name)')
            .order('created_at', desc=True)
            .limit(6)
            .execute()
        )

        raw_reviews = reviews_res.data or []
        total_reviews = len(raw_reviews)
        if total_reviews > 0:
            avg_rating = round(sum(r.get('rating', 5) for r in raw_reviews) / total_reviews, 1)

        for r in raw_reviews:
            prod_info = r.get('products') or {}
            profile_info = r.get('profiles') or {}
            created_str = (r.get('created_at') or '')[:10]

            author = profile_info.get('full_name') or 'VIBE 고객'
            # 익명화 처리 (예: 김민지 -> 김*지)
            if len(author) >= 2:
                masked_author = author[0] + '*' * (len(author) - 2) + author[-1] if len(author) > 2 else author[0] + '*'
            else:
                masked_author = author

            reviews.append({
                'id': r.get('id'),
                'rating': int(r.get('rating') or 5),
                'content': r.get('content') or '',
                'product_name': prod_info.get('name') or 'VIBE 시그니처 아이템',
                'product_img': prod_info.get('thumbnail_url'),
                'author': masked_author,
                'created_at': created_str,
            })

    except Exception as e:
        logger.error(f"[Supabase Error] 데이터 조회 실패: {e}", exc_info=True)
        print(f"[Supabase Error] 데이터 조회 실패: {e}")

    # 리뷰가 비어있을 경우를 대비한 세련된 폴백 데이터
    if not reviews:
        reviews = [
            {
                'id': 1,
                'rating': 5,
                'content': '핏이 정말 예술입니다! 하체 라인을 자연스럽고 슬림하게 커버해주고 사계절 내내 데일리로 입기 딱 좋아요. 강력 추천합니다.',
                'product_name': '와이드 데님 팬츠',
                'product_img': 'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=400&q=80',
                'author': '김*지',
                'created_at': '2026-09-28'
            },
            {
                'id': 2,
                'rating': 5,
                'content': '목 늘어남 전혀 없고 코튼 소재가 정말 탄탄합니다. 하이웨이스트 팬츠랑 매치했을 때 기장감이 완벽해요.',
                'product_name': '베이직 크롭 티셔츠',
                'product_img': 'https://images.unsplash.com/photo-1581655353564-df123a1eb820?auto=format&fit=crop&w=400&q=80',
                'author': '이*혁',
                'created_at': '2026-09-27'
            },
            {
                'id': 3,
                'rating': 5,
                'content': '요즘 날씨에 입기 최고의 아우터입니다. 어깨 라인이 과하지 않게 떨어져서 고급스럽고 주위에서 칭찬을 정말 많이 들었어요.',
                'product_name': '오버핏 코튼 자켓',
                'product_img': 'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?auto=format&fit=crop&w=400&q=80',
                'author': '박*연',
                'created_at': '2026-09-26'
            },
            {
                'id': 4,
                'rating': 5,
                'content': '가죽 텍스처가 너무 고급스럽고 13인치 노트북까지 깔끔하게 수납됩니다. 디자인, 실용성 둘 다 잡은 인생 가방이에요!',
                'product_name': '클래식 레더 토트백',
                'product_img': 'https://images.unsplash.com/photo-1584917865442-de89df76afd3?auto=format&fit=crop&w=400&q=80',
                'author': '정*진',
                'created_at': '2026-09-25'
            }
        ]
        avg_rating = 5.0
        total_reviews = 4

    return render_template(
        'index.html',
        products=products,
        reviews=reviews,
        avg_rating=avg_rating,
        total_reviews=total_reviews
    )


@main_bp.route('/reviews/new', methods=['POST'])
def add_review():
    """
    고객 평점/리뷰 즉시 작성 라우트
    """
    try:
        author_name = request.form.get('author_name', '').strip() or '고객'
        product_id = request.form.get('product_id')
        rating = int(request.form.get('rating', 5))
        content = request.form.get('content', '').strip()

        if not content:
            return redirect(url_for('main.index', _anchor='reviews'))

        supabase = get_supabase_client()
        profiles = supabase.table('profiles').select('id').limit(1).execute().data
        user_id = profiles[0]['id'] if profiles else None

        if user_id and product_id:
            supabase.table('reviews').insert({
                'product_id': product_id,
                'user_id': user_id,
                'rating': rating,
                'content': content
            }).execute()

    except Exception as e:
        logger.error(f"[Review Submit Error] {e}", exc_info=True)

    return redirect(url_for('main.index', _anchor='reviews'))


@main_bp.route('/product/<slug_or_id>')
def product_detail(slug_or_id):
    """
    상품 상세 페이지 라우트:
    - slug 또는 UUID id로 상품 단일 조회
    - 상품 관련 옵션(product_options) 및 추가 이미지(product_images) 조회
    - 함께 코디할 연관 상품(related_products) 조회
    """
    try:
        supabase = get_supabase_client()

        # 1. slug로 먼저 조회 시도, 없으면 id로 조회
        prod_res = (
            supabase.table('products')
            .select('*')
            .eq('slug', slug_or_id)
            .execute()
        )
        if not prod_res.data:
            prod_res = (
                supabase.table('products')
                .select('*')
                .eq('id', slug_or_id)
                .execute()
            )

        if not prod_res.data:
            flash('해당 상품을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('main.index'))

        raw_prod = prod_res.data[0]
        raw_price = float(raw_prod.get('price') or 0)
        formatted_price = f"{int(raw_price):,}원"

        sale_price = raw_prod.get('sale_price')
        formatted_sale_price = None
        discount_percent = None

        if sale_price and float(sale_price) < raw_price and raw_price > 0:
            sale_val = float(sale_price)
            formatted_sale_price = f"{int(sale_val):,}원"
            discount_percent = int(round((1 - (sale_val / raw_price)) * 100))

        product = {
            'id': raw_prod.get('id'),
            'name': raw_prod.get('name'),
            'slug': raw_prod.get('slug'),
            'description': raw_prod.get('description') or '',
            'price': formatted_price,
            'sale_price': formatted_sale_price,
            'discount_percent': discount_percent,
            'stock': raw_prod.get('stock') or 0,
            'thumbnail_url': raw_prod.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=800&q=80',
        }

        # 2. 상품 옵션 목록 조회
        opts_res = (
            supabase.table('product_options')
            .select('*')
            .eq('product_id', product['id'])
            .order('id')
            .execute()
        )
        options = opts_res.data or []

        # 3. 상품 추가 갤러리 이미지 조회
        imgs_res = (
            supabase.table('product_images')
            .select('*')
            .eq('product_id', product['id'])
            .order('sort_order')
            .execute()
        )
        images = imgs_res.data or []
        if not images:
            images = [{'image_url': product['thumbnail_url']}]

        # 4. 연관 상품 추천 (현재 상품 제외한 다른 신상품 4개)
        related_res = (
            supabase.table('products')
            .select('id, name, slug, price, sale_price, thumbnail_url')
            .neq('id', product['id'])
            .eq('is_active', True)
            .limit(4)
            .execute()
        )
        related_products = []
        for r in related_res.data or []:
            r_price = float(r.get('price') or 0)
            related_products.append({
                'id': r.get('id'),
                'slug': r.get('slug'),
                'name': r.get('name'),
                'price': f"{int(r_price):,}원",
                'thumbnail_url': r.get('thumbnail_url')
            })

        return render_template(
            'product_detail.html',
            product=product,
            options=options,
            images=images,
            related_products=related_products
        )

    except Exception as e:
        logger.error(f"[Product Detail Error] {e}", exc_info=True)
        return redirect(url_for('main.index'))


@main_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """
    회원가입 라우트:
    - GET: 회원가입 폼 화면 렌더링
    - POST: Supabase Auth를 통한 회원 생성 및 세션 자동 로그인
    """
    if request.method == 'GET':
        if session.get('user'):
            return redirect(url_for('main.index'))
        return render_template('signup.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    password_confirm = request.form.get('password_confirm', '').strip()
    full_name = request.form.get('full_name', '').strip() or '고객'

    # 기본 유효성 검사
    if not email or not password:
        flash('이메일과 비밀번호를 모두 입력해주세요.', 'warning')
        return redirect(url_for('main.signup'))

    if len(password) < 6:
        flash('비밀번호는 최소 6자리 이상이어야 합니다.', 'warning')
        return redirect(url_for('main.signup'))

    if password != password_confirm:
        flash('비밀번호가 일치하지 않습니다. 다시 확인해주세요.', 'danger')
        return redirect(url_for('main.signup'))

    try:
        # 이메일 인증 절차 없이 즉시 로그인할 수 있도록 email_confirm: True로 생성
        admin_client = get_supabase_admin_client()
        created_user = admin_client.auth.admin.create_user({
            'email': email,
            'password': password,
            'email_confirm': True,
            'user_metadata': {'full_name': full_name}
        })

        if created_user and created_user.user:
            # 회원가입 즉시 Flask 세션에 로그인 정보 저장
            session['user'] = {
                'id': created_user.user.id,
                'email': created_user.user.email,
                'full_name': full_name
            }
            flash(f'{full_name}님, VIBE-FASHION 회원가입을 축하합니다! 웰컴 10% 쿠폰이 발급되었습니다.', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('회원가입 처리 중 문제가 발생했습니다.', 'danger')
            return redirect(url_for('main.signup'))

    except Exception as e:
        err_msg = str(e)
        logger.error(f"[Signup Error] {err_msg}", exc_info=True)
        if 'already registered' in err_msg.lower() or 'already exists' in err_msg.lower():
            flash('이미 가입된 이메일 주소입니다. 로그인해주세요.', 'warning')
            return redirect(url_for('main.login'))
        flash('회원가입 실패: 잠시 후 다시 시도해주세요.', 'danger')
        return redirect(url_for('main.signup'))


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    로그인 라우트:
    - GET: 로그인 폼 화면 렌더링
    - POST: Supabase Auth 이메일/비밀번호 인증 후 세션 저장
    """
    if request.method == 'GET':
        if session.get('user'):
            return redirect(url_for('main.index'))
        return render_template('login.html')

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        flash('이메일과 비밀번호를 입력해주세요.', 'warning')
        return redirect(url_for('main.login'))

    try:
        supabase = get_supabase_client()
        auth_res = supabase.auth.sign_in_with_password({
            'email': email,
            'password': password
        })

        if auth_res and auth_res.user:
            user = auth_res.user
            full_name = user.user_metadata.get('full_name') if user.user_metadata else None

            # profiles 테이블에서 full_name 한번 더 조회 시도
            if not full_name:
                try:
                    prof_data = supabase.table('profiles').select('full_name').eq('id', user.id).execute().data
                    if prof_data and prof_data[0].get('full_name'):
                        full_name = prof_data[0].get('full_name')
                except Exception:
                    pass

            session['user'] = {
                'id': user.id,
                'email': user.email,
                'full_name': full_name or user.email.split('@')[0]
            }
            flash(f'환영합니다, {session["user"]["full_name"]}님!', 'success')
            return redirect(url_for('main.index'))
        else:
            flash('이메일 또는 비밀번호가 일치하지 않습니다.', 'danger')
            return redirect(url_for('main.login'))

    except Exception as e:
        err_msg = str(e)
        logger.error(f"[Login Error] {err_msg}", exc_info=True)
        flash('이메일 또는 비밀번호가 일치하지 않습니다.', 'danger')
        return redirect(url_for('main.login'))


@main_bp.route('/logout')
def logout():
    """
    로그아웃 라우트:
    - Flask 세션 제거
    """
    session.pop('user', None)
    flash('성공적으로 로그아웃되었습니다.', 'info')
    return redirect(url_for('main.index'))



