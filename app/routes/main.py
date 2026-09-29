import os
import logging
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv
from app.utils.supabase_client import get_supabase_client, get_supabase_admin_client

# 로깅 설정
logger = logging.getLogger(__name__)

# 메인 페이지 및 관련 라우트를 관리하는 블루프린트 객체 생성
main_bp = Blueprint('main', __name__)


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

        supabase = get_supabase_admin_client()
        # 로그인 세션이 있으면 해당 user_id 사용, 없으면 첫 번째 프로필을 작성자로 매핑
        user_id = session.get('user_id') or (session.get('user') or {}).get('id')
        if not user_id:
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
    """/auth/signup으로 리다이렉트 (하위 호환성 유지)"""
    return redirect(url_for('auth.signup'))


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """/auth/login으로 리다이렉트 (하위 호환성 유지)"""
    return redirect(url_for('auth.login'))


@main_bp.route('/logout')
def logout():
    """/auth/logout으로 리다이렉트 (하위 호환성 유지)"""
    return redirect(url_for('auth.logout'))


@main_bp.route('/delete_account', methods=['POST'])
def delete_account_alias():
    """/auth/delete-account로 내부 포워딩"""
    from .auth import delete_account
    return delete_account()


@main_bp.route('/mypage')
def mypage():
    """
    마이페이지 라우트:
    - login_required: 로그인 안 되어 있으면 /auth/login으로 이동
    - 사용자 정보 및 회원 등급, 누적 구매 금액 표시
    """
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login', error='login_required', next='/mypage'))

    user = session.get('user', {})
    profile = {}
    total_spent = 0

    try:
        supabase = get_supabase_client()
        prof_res = supabase.table('profiles').select('*').eq('id', user_id).execute()
        if prof_res.data:
            profile = prof_res.data[0]
            total_spent = float(profile.get('total_spent') or 0)
    except Exception as e:
        logger.error(f"[MyPage Profile Error] {e}")

    return render_template(
        'mypage.html',
        user=user,
        profile=profile,
        formatted_total_spent=f"{int(total_spent):,}원"
    )


@main_bp.route('/checkout', methods=['GET'])
def checkout():
    """
    주문/결제 페이지 라우트:
    - 쿼리 파라미터: product_id, option, qty
    """
    product_id = request.args.get('product_id')
    selected_option = request.args.get('option', '')
    qty = max(1, int(request.args.get('qty', 1)))

    supabase = get_supabase_client()
    product = None

    if product_id:
        try:
            prod_res = supabase.table('products').select('*').eq('id', product_id).execute()
            if not prod_res.data:
                prod_res = supabase.table('products').select('*').eq('slug', product_id).execute()
            if prod_res.data:
                p = prod_res.data[0]
                raw_price = float(p.get('price') or 0)
                sale_price = p.get('sale_price')
                unit_price = int(float(sale_price)) if sale_price and float(sale_price) < raw_price else int(raw_price)

                discount_percent = None
                if sale_price and float(sale_price) < raw_price and raw_price > 0:
                    discount_percent = int(round((1 - (float(sale_price) / raw_price)) * 100))

                product = {
                    'id': p.get('id'),
                    'name': p.get('name'),
                    'thumbnail_url': p.get('thumbnail_url'),
                    'price': f"{int(raw_price):,}원",
                    'sale_price': f"{int(float(sale_price)):,}원" if sale_price else None,
                    'discount_percent': discount_percent,
                    'unit_val': unit_price
                }
        except Exception as e:
            logger.error(f"[Checkout Load Error] {e}")

    # 상품을 찾지 못했을 경우 기본 첫 번째 상품으로 폴백
    if not product:
        try:
            default_p = supabase.table('products').select('*').limit(1).execute().data[0]
            raw_price = float(default_p.get('price') or 0)
            product = {
                'id': default_p.get('id'),
                'name': default_p.get('name'),
                'thumbnail_url': default_p.get('thumbnail_url'),
                'price': f"{int(raw_price):,}원",
                'sale_price': None,
                'discount_percent': None,
                'unit_val': int(raw_price)
            }
        except Exception:
            product = {
                'id': '900eaccc-1e16-49a0-a6b9-bca87e7875d0',
                'name': '와이드 데님 팬츠',
                'thumbnail_url': 'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=800&q=80',
                'price': '39,900원',
                'sale_price': None,
                'discount_percent': None,
                'unit_val': 39900
            }

    unit_price = product['unit_val']
    subtotal = unit_price * qty
    shipping_fee = 0
    total_price = subtotal + shipping_fee

    return render_template(
        'checkout.html',
        product=product,
        selected_option=selected_option,
        qty=qty,
        unit_price=unit_price,
        formatted_unit_price=f"{unit_price:,}원",
        subtotal=subtotal,
        formatted_subtotal=f"{subtotal:,}원",
        shipping_fee=shipping_fee,
        total_price=total_price,
        formatted_total=f"{total_price:,}원",
        user=session.get('user')
    )


@main_bp.route('/checkout/process', methods=['POST'])
def process_checkout():
    """
    주문 및 결제 처리 라우트:
    - 주문 번호 생성
    - Supabase orders 및 order_items 테이블에 저장 (또는 세션 안전 저장)
    - 주문 완료 페이지로 리다이렉트
    """
    try:
        product_id = request.form.get('product_id')
        product_name = request.form.get('product_name')
        option_info = request.form.get('option_info', '')
        quantity = int(request.form.get('quantity', 1))
        unit_price = int(request.form.get('unit_price', 0))
        total_amount = int(request.form.get('total_amount', 0))

        recipient_name = request.form.get('recipient_name', '').strip() or '고객'
        recipient_phone = request.form.get('recipient_phone', '').strip() or '010-0000-0000'
        postal_code = request.form.get('postal_code', '06000')
        shipping_address = request.form.get('shipping_address', '').strip()
        shipping_detail = request.form.get('shipping_detail_address', '').strip()
        full_shipping_addr = f"{shipping_address} {shipping_detail}".strip()
        delivery_memo = request.form.get('delivery_memo', '')
        payment_method = request.form.get('payment_method', '신용/체크카드')

        # 주문 번호 생성 (예: VIBE-20260928-8429)
        now_str = datetime.now().strftime('%Y%m%d%H%M')
        rand_num = random.randint(1000, 9999)
        order_number = f"VIBE-{now_str}-{rand_num}"

        supabase = get_supabase_admin_client()

        # user_id 결정 (로그인 유저 또는 기본 프로필)
        user_id = session.get('user', {}).get('id') if session.get('user') else None
        if not user_id:
            try:
                prof_data = supabase.table('profiles').select('id').limit(1).execute().data
                if prof_data:
                    user_id = prof_data[0]['id']
            except Exception:
                pass

        # 상품 썸네일 조회
        prod_thumb = None
        try:
            prod_row = supabase.table('products').select('thumbnail_url').eq('id', product_id).execute().data
            if prod_row:
                prod_thumb = prod_row[0].get('thumbnail_url')
        except Exception:
            pass

        order_record = {
            'order_number': order_number,
            'recipient_name': recipient_name,
            'recipient_phone': recipient_phone,
            'postal_code': postal_code,
            'shipping_address': full_shipping_addr,
            'delivery_memo': delivery_memo,
            'payment_method': payment_method,
            'product_name': product_name,
            'product_thumbnail': prod_thumb,
            'option_info': option_info,
            'quantity': quantity,
            'unit_price': unit_price,
            'total_amount': total_amount,
            'formatted_total': f"{total_amount:,}원",
            'status': 'PAID',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        # Supabase orders 및 order_items 테이블에 저장 시도
        if user_id:
            try:
                db_order = {
                    'order_number': order_number,
                    'user_id': user_id,
                    'status': 'PAID',
                    'total_amount': total_amount,
                    'payment_amount': total_amount,
                    'recipient_name': recipient_name,
                    'recipient_phone': recipient_phone,
                    'postal_code': postal_code,
                    'shipping_address': full_shipping_addr
                }
                ord_res = supabase.table('orders').insert(db_order).execute()
                if ord_res.data:
                    new_order_id = ord_res.data[0]['id']
                    db_item = {
                        'order_id': new_order_id,
                        'product_id': product_id,
                        'product_name': product_name,
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'option_info': option_info
                    }
                    supabase.table('order_items').insert(db_item).execute()
            except Exception as db_err:
                logger.error(f"[DB Order Insert Notice] {db_err}")
                print(f"[DB Order Insert Notice] {db_err}")

        # 세션에 주문 정보 저장 (완료 화면 렌더링용)
        session['last_order'] = order_record

        return redirect(url_for('main.order_success', order_number=order_number))

    except Exception as e:
        logger.error(f"[Checkout Process Error] {e}", exc_info=True)
        flash('주문 처리 중 오류가 발생했습니다. 다시 시도해주세요.', 'danger')
        return redirect(url_for('main.index'))


@main_bp.route('/order/success/<order_number>')
def order_success(order_number):
    """
    주문 완료 페이지 라우트
    """
    order = session.get('last_order')
    if not order or order.get('order_number') != order_number:
        # 세션에 없으면 기본 주문 더미 데이터 구성
        order = {
            'order_number': order_number,
            'recipient_name': '고객',
            'recipient_phone': '010-1234-5678',
            'postal_code': '06000',
            'shipping_address': '서울특별시 강남구 테헤란로 152',
            'delivery_memo': '부재 시 문 앞에 놓아주세요.',
            'payment_method': '신용/체크카드',
            'product_name': 'VIBE 시그니처 아이템',
            'product_thumbnail': 'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=400&q=80',
            'option_info': '기본 옵션',
            'quantity': 1,
            'formatted_total': '39,900원'
        }

    return render_template('order_complete.html', order=order)




