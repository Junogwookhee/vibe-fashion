import os
import logging
import random
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from dotenv import load_dotenv
from app.utils.supabase_client import get_supabase_client, get_supabase_admin_client
from .auth import login_required

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


@main_bp.route('/products/<product_id>')
@main_bp.route('/product/<slug_or_id>')
def product_detail(product_id=None, slug_or_id=None):
    """
    상품 상세 페이지 라우트: GET /products/<product_id> (및 GET /product/<slug_or_id>)
    - Supabase products 테이블에서 product_id(또는 slug)로 상품 정보 조회
    - 상품 이미지, 이름, 가격(할인가/정가), 설명 표시를 위한 데이터 포맷팅
    - product_options 테이블에서 해당 상품의 색상(color) 목록을 DISTINCT로 조회
    - 갤러리 이미지(product_images) 및 연관 상품 추천 목록 조회
    """
    try:
        supabase = get_supabase_client()
        target = product_id or slug_or_id

        # 1. Supabase에서 id(UUID) 또는 slug로 상품 정보 조회
        prod_res = (
            supabase.table('products')
            .select('*')
            .eq('id', target)
            .execute()
        )
        if not prod_res.data:
            prod_res = (
                supabase.table('products')
                .select('*')
                .eq('slug', target)
                .execute()
            )

        if not prod_res.data:
            flash('해당 상품을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('main.index'))

        raw_prod = prod_res.data[0]
        actual_product_id = raw_prod.get('id')

        # 가격 및 할인율 포맷팅 계산
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
            'id': actual_product_id,
            'name': raw_prod.get('name'),
            'slug': raw_prod.get('slug'),
            'description': raw_prod.get('description') or '',
            'price': formatted_price,
            'sale_price': formatted_sale_price,
            'discount_percent': discount_percent,
            'stock': raw_prod.get('stock') or 0,
            'thumbnail_url': raw_prod.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=800&q=80',
        }

        # 2. product_options 테이블에서 해당 상품의 색상(color) 목록을 DISTINCT로 조회
        # (color / size / stock 컬럼 사용)
        colors_res = (
            supabase.table('product_options')
            .select('color')
            .eq('product_id', actual_product_id)
            .not_.is_('color', 'null')
            .order('id')
            .execute()
        )

        # 중복 제거 (순서 보장)
        colors = []
        seen_colors = set()
        for row in (colors_res.data or []):
            c = (row.get('color') or '').strip()
            if c and c not in seen_colors:
                seen_colors.add(c)
                colors.append(c)

        # 3. 상품 추가 갤러리 이미지 조회
        imgs_res = (
            supabase.table('product_images')
            .select('*')
            .eq('product_id', actual_product_id)
            .order('sort_order')
            .execute()
        )
        images = imgs_res.data or []
        if not images:
            images = [{'image_url': product['thumbnail_url']}]

        # 4. 연관 상품 추천 (현재 상품 제외한 다른 활성 상품 4개)
        related_res = (
            supabase.table('products')
            .select('id, name, slug, price, sale_price, thumbnail_url')
            .neq('id', actual_product_id)
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
            colors=colors,
            images=images,
            related_products=related_products
        )

    except Exception as e:
        logger.error(f"[Product Detail Error] {e}", exc_info=True)
        return redirect(url_for('main.index'))


@main_bp.route('/api/products/<product_id>/sizes')
def product_sizes_api(product_id):
    """
    상품 상세 페이지에서 색상 선택 시 호출되는 사이즈 및 재고 조회 API:
    - GET /api/products/<product_id>/sizes?color=<선택한 색상>
    - product_options 테이블에서 product_id + color로 필터링
    - [{"size": "S", "stock": 3}, {"size": "M", "stock": 0}] 형태의 JSON 배열 반환
    """
    try:
        supabase = get_supabase_client()
        color = request.args.get('color', '').strip()

        # target_product_id 확인 (UUID 또는 slug 지원)
        target_product_id = product_id
        if len(product_id) != 36:
            prod_lookup = supabase.table('products').select('id').eq('slug', product_id).execute()
            if prod_lookup.data:
                target_product_id = prod_lookup.data[0]['id']

        # product_options에서 product_id + color로 필터링
        query = (
            supabase.table('product_options')
            .select('id, size, stock')
            .eq('product_id', target_product_id)
        )

        if color:
            query = query.eq('color', color)

        # 조회 실행 (id 순 정렬)
        res = query.order('id').execute()
        raw_options = res.data or []

        # size, stock 형태의 딕셔너리 리스트로 변환 (id 포함하여 프론트엔드 연동 지원)
        sizes = [
            {
                'id': item.get('id'),
                'size': item.get('size'),
                'stock': int(item.get('stock') or 0)
            }
            for item in raw_options
        ]

        # JSON 배열 반환 (HTTP 200)
        return sizes, 200

    except Exception as e:
        logger.error(f"[Product Sizes API Error] {e}", exc_info=True)
        return [], 500


@main_bp.route('/cart/add', methods=['POST'])
def add_to_cart():
    """
    장바구니 담기 라우트: POST /cart/add
    - 요청 body (JSON 또는 Form): product_option_id, quantity
    - 로그인 안 했으면 /auth/login 으로 리다이렉트 (JSON 요청 시 401 및 redirect_url 반환)
    - 담기 전에 product_options.stock을 조회해서 요청 수량보다 적으면
      "재고가 부족합니다(현재 N개)" 에러 반환, DB에 아무 것도 쓰지 않음
    - carts 테이블에 upsert (같은 옵션이면 수량 누적)
    - 누적 후 수량이 재고를 초과하게 되는 경우도 동일하게 에러 처리
    - 성공 시 JSON: {"success": true, "message": "장바구니에 담겼습니다"}
    """
    # 1. 로그인 여부 확인 (미로그인 시 /auth/login 으로 리다이렉트)
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        login_url = url_for('auth.login', error='login_required', next=request.referrer or url_for('main.index'))
        if request.is_json:
            return jsonify({
                'success': False,
                'error': '로그인이 필요한 서비스입니다.',
                'redirect_url': login_url
            }), 401
        return redirect(login_url)

    try:
        # 2. 요청 파라미터 파싱
        req_data = request.get_json(silent=True) or request.form
        product_option_id = req_data.get('product_option_id')
        quantity_raw = req_data.get('quantity', 1)

        try:
            quantity = int(quantity_raw)
        except (ValueError, TypeError):
            quantity = 1

        if not product_option_id:
            return jsonify({
                'success': False,
                'error': '상품 옵션을 선택해주세요.'
            }), 400

        if quantity <= 0:
            return jsonify({
                'success': False,
                'error': '수량은 1개 이상이어야 합니다.'
            }), 400

        supabase = get_supabase_admin_client()

        # 3. product_options에서 옵션 및 재고(stock) 조회
        opt_res = (
            supabase.table('product_options')
            .select('id, product_id, stock')
            .eq('id', product_option_id)
            .execute()
        )

        if not opt_res.data:
            return jsonify({
                'success': False,
                'error': '존재하지 않는 상품 옵션입니다.'
            }), 404

        option_row = opt_res.data[0]
        stock = int(option_row.get('stock') or 0)
        product_id = option_row.get('product_id')

        # 4. 담기 전 단일 요청 수량이 재고보다 적은지 검사
        if stock < quantity:
            return jsonify({
                'success': False,
                'error': f'재고가 부족합니다(현재 {stock}개)'
            }), 400

        # 5. 기존 장바구니에 해당 옵션이 있는지 조회
        cart_res = (
            supabase.table('carts')
            .select('id, quantity')
            .eq('user_id', user_id)
            .eq('product_id', product_id)
            .eq('option_id', product_option_id)
            .execute()
        )

        existing_cart = cart_res.data[0] if cart_res.data else None

        if existing_cart:
            # 기존 수량과 누적
            current_qty = int(existing_cart.get('quantity') or 0)
            new_qty = current_qty + quantity

            # 누적 후 수량이 재고를 초과하는지 검사
            if new_qty > stock:
                return jsonify({
                    'success': False,
                    'error': f'재고가 부족합니다(현재 {stock}개)'
                }), 400

            # carts 테이블 수량 업데이트 (누적)
            supabase.table('carts').update({
                'quantity': new_qty,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('id', existing_cart['id']).execute()
        else:
            # 신규 행 추가 (upsert / insert)
            supabase.table('carts').insert({
                'user_id': user_id,
                'product_id': product_id,
                'option_id': product_option_id,
                'quantity': quantity
            }).execute()

        # 6. 성공 JSON 반환
        return jsonify({
            'success': True,
            'message': '장바구니에 담겼습니다'
        }), 200

    except Exception as e:
        logger.error(f"[Add To Cart Error] {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': '장바구니에 담는 중 오류가 발생했습니다.'
        }), 500


@main_bp.route('/cart/<cart_id>', methods=['PATCH'])
def update_cart(cart_id):
    """
    장바구니 수량 변경 라우트: PATCH /cart/<cart_id>
    - 요청 body (JSON): quantity (변경할 새 수량)
    - 본인 소유의 장바구니 아이템인지 확인 (다른 사용자의 cart_id 접근 차단)
    - quantity가 1 미만이면 에러
    - 변경하려는 quantity가 해당 옵션의 stock을 초과하면
      "재고가 부족합니다(현재 N개)" 에러, 변경하지 않음
    - 성공 시 UPDATE 후 새 소계(subtotal) 반환
      소계 = (상품 가격 + 추가 옵션가격) * 변경된 수량
    """
    # 1. 로그인 확인
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        login_url = url_for('auth.login', error='login_required', next=request.referrer or url_for('main.index'))
        if request.is_json:
            return jsonify({
                'success': False,
                'error': '로그인이 필요한 서비스입니다.',
                'redirect_url': login_url
            }), 401
        return redirect(login_url)

    try:
        # 2. 요청 파라미터 파싱
        req_data = request.get_json(silent=True) or {}
        quantity_raw = req_data.get('quantity')

        if quantity_raw is None:
            return jsonify({
                'success': False,
                'error': '수량을 입력해주세요.'
            }), 400

        try:
            new_quantity = int(quantity_raw)
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'error': '수량은 숫자여야 합니다.'
            }), 400

        if new_quantity < 1:
            return jsonify({
                'success': False,
                'error': '수량은 1개 이상이어야 합니다.'
            }), 400

        supabase = get_supabase_admin_client()

        # 3. 장바구니 아이템 조회 (cart_id)
        cart_res = (
            supabase.table('carts')
            .select('id, user_id, product_id, option_id, quantity')
            .eq('id', cart_id)
            .execute()
        )

        if not cart_res.data:
            return jsonify({
                'success': False,
                'error': '해당 장바구니 항목을 찾을 수 없습니다.'
            }), 404

        cart_item = cart_res.data[0]

        # 4. 본인 소유 확인 (다른 사용자의 cart_id 접근 차단)
        if cart_item['user_id'] != user_id:
            return jsonify({
                'success': False,
                'error': '다른 사용자의 장바구니는 수정할 수 없습니다.'
            }), 403

        product_id = cart_item['product_id']
        option_id = cart_item['option_id']

        # 5. product_options에서 stock 및 additional_price 조회
        opt_res = (
            supabase.table('product_options')
            .select('id, product_id, stock, additional_price')
            .eq('id', option_id)
            .execute()
        )

        if not opt_res.data:
            return jsonify({
                'success': False,
                'error': '상품 옵션을 찾을 수 없습니다.'
            }), 404

        option_item = opt_res.data[0]
        stock = int(option_item.get('stock') or 0)
        additional_price = float(option_item.get('additional_price') or 0)

        # 6. 변경하려는 quantity가 stock을 초과하는지 확인
        if new_quantity > stock:
            return jsonify({
                'success': False,
                'error': f'재고가 부족합니다(현재 {stock}개)'
            }), 400

        # 7. products에서 판매가(sale_price) 또는 정가(price) 조회
        prod_res = (
            supabase.table('products')
            .select('id, price, sale_price')
            .eq('id', product_id)
            .execute()
        )

        if not prod_res.data:
            return jsonify({
                'success': False,
                'error': '상품을 찾을 수 없습니다.'
            }), 404

        product_item = prod_res.data[0]
        base_price = float(product_item.get('sale_price') or product_item.get('price') or 0)

        # 8. 소계(subtotal) 계산: (상품 가격 + 추가 옵션가격) * 변경된 수량
        unit_price = base_price + additional_price
        subtotal = unit_price * new_quantity

        # 9. carts 테이블 UPDATE (수량 변경)
        update_res = (
            supabase.table('carts')
            .update({
                'quantity': new_quantity,
                'updated_at': datetime.utcnow().isoformat()
            })
            .eq('id', cart_id)
            .eq('user_id', user_id)  # 이중 안전 장치: user_id로도 필터링
            .execute()
        )

        # 10. 성공 응답 (새 소계 포함)
        return jsonify({
            'success': True,
            'message': '장바구니 수량이 변경되었습니다.',
            'data': {
                'cart_id': cart_id,
                'quantity': new_quantity,
                'unit_price': unit_price,
                'subtotal': subtotal
            }
        }), 200

    except Exception as e:
        logger.error(f"[Update Cart Error] {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': '장바구니 수량을 변경하는 중 오류가 발생했습니다.'
        }), 500


@main_bp.route('/cart/<cart_id>', methods=['DELETE'])
def delete_cart_item(cart_id):
    """
    장바구니 아이템 삭제 라우트: DELETE /cart/<cart_id>
    - 본인 소유의 장바구니 아이템인지 확인 후 삭제
    - 미로그인 시 401
    - 다른 사용자의 cart_id 접근 시 403 차단
    - 성공 시 JSON: {"success": true, "message": "장바구니에서 상품이 삭제되었습니다."}
    """
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        login_url = url_for('auth.login', error='login_required', next=request.referrer or url_for('main.cart_view'))
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                'success': False,
                'error': '로그인이 필요한 서비스입니다.',
                'redirect_url': login_url
            }), 401
        return redirect(login_url)

    try:
        supabase = get_supabase_admin_client()

        # 1. 장바구니 아이템 조회
        cart_res = (
            supabase.table('carts')
            .select('id, user_id, product_id, option_id, quantity')
            .eq('id', cart_id)
            .execute()
        )

        if not cart_res.data:
            return jsonify({
                'success': False,
                'error': '해당 장바구니 항목을 찾을 수 없습니다.'
            }), 404

        cart_item = cart_res.data[0]

        # 2. 본인 소유 확인 (다른 사용자의 cart_id 삭제 차단)
        if str(cart_item.get('user_id')) != str(user_id):
            return jsonify({
                'success': False,
                'error': '다른 사용자의 장바구니는 삭제할 수 없습니다.'
            }), 403

        # 3. 삭제 수행
        supabase.table('carts').delete().eq('id', cart_id).eq('user_id', user_id).execute()

        return jsonify({
            'success': True,
            'message': '장바구니에서 상품이 삭제되었습니다.',
            'cart_id': cart_id
        }), 200

    except Exception as e:
        logger.error(f"[Delete Cart Error] {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': '장바구니 아이템을 삭제하는 중 오류가 발생했습니다.'
        }), 500


@main_bp.route('/cart/count', methods=['GET'])
def cart_count_api():
    """로그인한 사용자의 장바구니 총 수량을 반환합니다."""
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        return jsonify({'success': True, 'count': 0}), 200

    try:
        supabase = get_supabase_admin_client()
        response = (
            supabase.table('carts')
            .select('quantity')
            .eq('user_id', user_id)
            .execute()
        )
        count = sum(int(item.get('quantity') or 0) for item in (response.data or []))
        return jsonify({'success': True, 'count': count}), 200
    except Exception as e:
        logger.error(f"[Cart Count Error] {e}", exc_info=True)
        return jsonify({'success': False, 'count': 0}), 500


@main_bp.route('/cart', methods=['GET'])
def cart_view():
    """
    장바구니 목록 조회 페이지: GET /cart
    - carts + product_options + products JOIN 조회
    - 각 아이템: 상품명, 색상, 사이즈, 수량, 단가, 소계
    - 품절(stock=0) 아이템 식별: is_sold_out 플래그 전달
    - 전체 합계 + 배송비 (50,000원 미만이면 3,000원, 이상이면 무료)
    - 품절 아이템 존재 여부(has_sold_out) 전달
    """
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        return redirect(url_for('auth.login', error='login_required', next=url_for('main.cart_view')))

    try:
        supabase = get_supabase_admin_client()

        # carts + product_options + products JOIN 조회
        cart_res = (
            supabase.table('carts')
            .select('id, user_id, product_id, option_id, quantity, created_at, product_options(*), products(*)')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .execute()
        )
        raw_items = cart_res.data or []

        items = []
        subtotal_amount = 0
        has_sold_out = False

        for row in raw_items:
            cid = row['id']
            pid = row['product_id']
            oid = row.get('option_id')
            qty = int(row.get('quantity') or 1)

            # JOIN된 products 정보
            prod_data = row.get('products') or {}
            if not prod_data:
                # JOIN 데이터가 비어있을 경우 fallback 조회
                p_lookup = supabase.table('products').select('*').eq('id', pid).execute()
                if p_lookup.data:
                    prod_data = p_lookup.data[0]
                else:
                    continue

            raw_price = float(prod_data.get('price') or 0)
            sale_price = prod_data.get('sale_price')
            base_price = float(sale_price) if sale_price and float(sale_price) < raw_price else raw_price

            # JOIN된 product_options 정보
            opt_data = row.get('product_options') or {}
            if not opt_data and oid:
                o_lookup = supabase.table('product_options').select('*').eq('id', oid).execute()
                if o_lookup.data:
                    opt_data = o_lookup.data[0]

            color = opt_data.get('color') or ''
            size = opt_data.get('size') or ''
            stock = int(opt_data.get('stock') if opt_data.get('stock') is not None else (prod_data.get('stock') or 0))
            additional_price = float(opt_data.get('additional_price') or 0)

            # 품절(stock=0) 여부 판정
            is_sold_out = (stock <= 0)
            if is_sold_out:
                has_sold_out = True

            unit_price = base_price + additional_price
            subtotal = unit_price * qty
            subtotal_amount += subtotal

            items.append({
                'cart_id': cid,
                'product_id': pid,
                'product_name': prod_data.get('name') or '상품',
                'slug': prod_data.get('slug'),
                'thumbnail_url': prod_data.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=300&q=80',
                'option_id': oid,
                'color': color,
                'size': size,
                'stock': stock,
                'is_sold_out': is_sold_out,
                'unit_price': int(unit_price),
                'formatted_unit_price': f"{int(unit_price):,}원",
                'quantity': qty,
                'subtotal': int(subtotal),
                'formatted_subtotal': f"{int(subtotal):,}원"
            })

        # 배송비 계산 (상품 합계 50,000원 미만이면 3,000원, 이상이면 무료)
        if len(items) == 0:
            shipping_fee = 0
        else:
            shipping_fee = 0 if subtotal_amount >= 50000 else 3000

        total_amount = subtotal_amount + shipping_fee

        return render_template(
            'cart.html',
            cart_items=items,
            subtotal_amount=int(subtotal_amount),
            formatted_subtotal=f"{int(subtotal_amount):,}원",
            shipping_fee=shipping_fee,
            formatted_shipping_fee="무료" if shipping_fee == 0 else f"{int(shipping_fee):,}원",
            total_amount=int(total_amount),
            formatted_total=f"{int(total_amount):,}원",
            has_sold_out=has_sold_out
        )

    except Exception as e:
        logger.error(f"[Cart View Error] {e}", exc_info=True)
        return render_template(
            'cart.html',
            cart_items=[],
            subtotal_amount=0,
            formatted_subtotal="0원",
            shipping_fee=0,
            formatted_shipping_fee="0원",
            total_amount=0,
            formatted_total="0원",
            has_sold_out=False
        )


@main_bp.route('/order/checkout', methods=['GET', 'POST'])
def order_checkout_alias():
    """
    주문 결제 페이지 라우트 (/order/checkout):
    - 장바구니에서 [주문하기] 클릭 시 이동
    - /checkout 페이지로 내부 연결
    """
    return checkout()


@main_bp.route('/products/<product_id>/options')
@main_bp.route('/api/products/<product_id>/options')
def product_options_api(product_id):
    """
    선택된 상품 및 색상에 해당하는 사이즈와 재고 목록을 반환하는 API:
    - query parameter: color (선택 사항)
    - 같은 색상이라도 사이즈별 재고가 다름을 반영
    - JavaScript(fetch)로 호출되어 사이즈 드롭다운 동적 업데이트에 사용
    """
    try:
        supabase = get_supabase_client()
        color = request.args.get('color', '').strip()

        # target_product_id 찾기 (UUID가 아닌 slug가 전달된 경우 지원)
        target_product_id = product_id
        if len(product_id) != 36:
            prod_lookup = supabase.table('products').select('id').eq('slug', product_id).execute()
            if prod_lookup.data:
                target_product_id = prod_lookup.data[0]['id']

        query = (
            supabase.table('product_options')
            .select('id, product_id, color, size, stock, additional_price')
            .eq('product_id', target_product_id)
        )

        if color:
            query = query.eq('color', color)

        res = query.order('id').execute()
        options = res.data or []

        return {
            'success': True,
            'product_id': target_product_id,
            'color': color,
            'options': options
        }, 200

    except Exception as e:
        logger.error(f"[Product Options API Error] {e}", exc_info=True)
        return {
            'success': False,
            'error': '상품 옵션을 조회하는 중 오류가 발생했습니다.'
        }, 500

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


@main_bp.route('/mypage', methods=['GET', 'POST'])
@login_required
def mypage():
    """
    마이페이지 라우트:
    - login_required: 로그인 안 되어 있으면 /auth/login으로 이동
    - GET: 사용자 프로필 조회 (이름, 이메일, 기본 배송지) 및 탭 표시
    - POST: 내 정보 수정 (이름, 전화번호, 기본 배송지)
    """
    user_id = session.get('user_id')
    user = session.get('user', {})
    profile = {}
    total_spent = 0
    supabase = get_supabase_client()

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()

        update_data = {
            'full_name': full_name,
            'phone': phone,
        }
        update_succeeded = False
        try:
            update_data['address'] = address
            supabase.table('profiles').update(update_data).eq('id', user_id).execute()
            update_succeeded = True
            flash('회원 정보가 성공적으로 수정되었습니다.', 'success')
        except Exception as e:
            logger.error(f"[MyPage Update Error] {e}")
            flash('회원 정보 수정 중 오류가 발생했습니다.', 'danger')

        if update_succeeded and 'user' in session and isinstance(session['user'], dict):
            session['user']['full_name'] = full_name
            session.modified = True

        return redirect(url_for('main.mypage'))

    try:
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




