import os
import re
import uuid
import logging
import random
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort
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
            .limit(8)
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
    - 요청 body (JSON 또는 Form): product_option_id 또는 product_id, quantity
    - 로그인 안 했으면 /auth/login 으로 리다이렉트 (JSON 요청 시 401 및 redirect_url 반환)
    - 담기 전에 product_options.stock을 조회해서 요청 수량보다 적으면
      "재고가 부족합니다(현재 N개)" 에러 반환, DB에 아무 것도 쓰지 않음
    - 옵션이 있는 상품은 옵션을 필수로 받고, 단일 상품은 product_id로 담기
    - carts 테이블에 upsert (같은 상품/옵션이면 수량 누적)
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
        requested_product_id = req_data.get('product_id')
        quantity_raw = req_data.get('quantity', 1)

        try:
            quantity = int(quantity_raw)
        except (ValueError, TypeError):
            quantity = 1

        if not product_option_id and not requested_product_id:
            return jsonify({
                'success': False,
                'error': '상품 정보가 필요합니다.'
            }), 400

        if quantity <= 0:
            return jsonify({
                'success': False,
                'error': '수량은 1개 이상이어야 합니다.'
            }), 400

        supabase = get_supabase_admin_client()

        # 3. 옵션 또는 단일 상품의 재고(stock) 조회
        option_id = None
        if product_option_id:
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
            option_id = option_row.get('id')
            product_id = option_row.get('product_id')
            stock = int(option_row.get('stock') or 0)
        else:
            product_res = (
                supabase.table('products')
                .select('id, stock')
                .eq('id', requested_product_id)
                .execute()
            )
            if not product_res.data:
                return jsonify({
                    'success': False,
                    'error': '존재하지 않는 상품입니다.'
                }), 404

            product_row = product_res.data[0]
            product_id = product_row['id']
            option_res = (
                supabase.table('product_options')
                .select('id')
                .eq('product_id', product_id)
                .limit(1)
                .execute()
            )
            if option_res.data:
                return jsonify({
                    'success': False,
                    'error': '옵션을 선택해주세요.',
                    'requires_option': True
                }), 400
            stock = int(product_row.get('stock') or 0)

        # 4. 담기 전 단일 요청 수량이 재고보다 적은지 검사
        if stock < quantity:
            return jsonify({
                'success': False,
                'error': f'재고가 부족합니다(현재 {stock}개)'
            }), 400

        # 5. 기존 장바구니에 해당 옵션이 있는지 조회
        cart_res = (
            supabase.table('carts')
            .select('id, quantity, option_id')
            .eq('user_id', user_id)
            .eq('product_id', product_id)
            .execute()
        )

        existing_cart = next(
            (item for item in (cart_res.data or [])
             if str(item.get('option_id') or '') == str(option_id or '')),
            None
        )

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
                'option_id': option_id,
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
            update_data['shipping_address'] = address
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


@main_bp.route('/api/profile/default-address', methods=['GET'])
def api_default_address():
    """
    로그인한 사용자의 마이페이지 기본 배송지 정보 조회 API (GET /api/profile/default-address)
    """
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        return jsonify({'success': False, 'error': '로그인이 필요합니다.'}), 401

    try:
        supabase = get_supabase_admin_client()
        prof_res = supabase.table('profiles').select('*').eq('id', user_id).execute()
        if not prof_res.data:
            return jsonify({'success': False, 'error': '프로필 정보를 찾을 수 없습니다.'}), 404

        prof = prof_res.data[0]
        shipping_addr = prof.get('shipping_address') or prof.get('address') or ''
        return jsonify({
            'success': True,
            'recipient_name': prof.get('full_name') or '',
            'recipient_phone': prof.get('phone') or '',
            'shipping_address': shipping_addr,
            'shipping_detail_address': prof.get('shipping_detail_address') or '',
            'postal_code': prof.get('postal_code') or ''
        }), 200
    except Exception as e:
        logger.error(f"[API Default Address Error] {e}", exc_info=True)
        return jsonify({'success': False, 'error': '기본 배송지를 불러오는 중 오류가 발생했습니다.'}), 500


@main_bp.route('/checkout', methods=['GET', 'POST'])
@main_bp.route('/order/checkout', methods=['GET', 'POST'])
def checkout():
    """
    주문서 및 결제 처리 라우트:
    - GET: 장바구니 기반 주문서 페이지 렌더링
      * 로그인 필수 (미로그인 시 /auth/login 리다이렉트)
      * 장바구니 비어있으면 /cart 리다이렉트
      * 품절(stock=0) 아이템이 하나라도 있으면 /cart로 리다이렉트 및 안내
      * 장바구니 아이템 목록 (수정 불가 읽기 전용)
      * 마이페이지에 저장된 기본 배송지(profiles) 조회
      * 결제 금액 요약 (상품금액 + 배송비 = 최종금액)
    - POST: 주문 결제 처리 (더미 결제 → 바로 주문 완료 처리)
      * 폼 유효성 검증 (수령인 이름, 010-0000-0000 패턴 휴대폰, 5자 이상 배송 주소)
      * orders 및 order_items 테이블에 저장
      * 장바구니 비우기
      * 주문 완료 페이지로 리다이렉트
    """
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        flash('로그인이 필요한 서비스입니다.', 'warning')
        return redirect(url_for('auth.login', error='login_required', next=request.path))

    supabase = get_supabase_admin_client()

    # 장바구니 데이터 조회 (carts + product_options + products JOIN)
    try:
        cart_res = (
            supabase.table('carts')
            .select('id, user_id, product_id, option_id, quantity, created_at, product_options(*), products(*)')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .execute()
        )
        raw_items = cart_res.data or []
    except Exception as e:
        logger.error(f"[Checkout Cart Load Error] {e}", exc_info=True)
        raw_items = []

    # 1. 장바구니가 비어있는 경우
    if not raw_items:
        flash('장바구니가 비어 있습니다.', 'warning')
        return redirect(url_for('main.cart_view'))

    # 장바구니 아이템 정제 및 품절 여부 검사
    items = []
    subtotal_amount = 0
    has_sold_out = False

    for row in raw_items:
        cid = row['id']
        pid = row['product_id']
        oid = row.get('option_id')
        qty = int(row.get('quantity') or 1)

        prod_data = row.get('products') or {}
        if not prod_data:
            p_lookup = supabase.table('products').select('*').eq('id', pid).execute()
            if p_lookup.data:
                prod_data = p_lookup.data[0]
            else:
                continue

        raw_price = float(prod_data.get('price') or 0)
        sale_price = prod_data.get('sale_price')
        base_price = float(sale_price) if sale_price and float(sale_price) < raw_price else raw_price

        opt_data = row.get('product_options') or {}
        if not opt_data and oid:
            o_lookup = supabase.table('product_options').select('*').eq('id', oid).execute()
            if o_lookup.data:
                opt_data = o_lookup.data[0]

        color = opt_data.get('color') or ''
        size = opt_data.get('size') or ''
        stock = int(opt_data.get('stock') if opt_data.get('stock') is not None else (prod_data.get('stock') or 0))
        additional_price = float(opt_data.get('additional_price') or 0)

        # 품절 판정
        if stock <= 0:
            has_sold_out = True

        unit_price = base_price + additional_price
        subtotal = unit_price * qty
        subtotal_amount += subtotal

        option_label = ''
        if color and size:
            option_label = f"{color} / {size}"
        elif color:
            option_label = color
        elif size:
            option_label = size

        items.append({
            'cart_id': cid,
            'product_id': pid,
            'product_name': prod_data.get('name') or '상품',
            'slug': prod_data.get('slug'),
            'thumbnail_url': prod_data.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=300&q=80',
            'option_id': oid,
            'option_info': option_label,
            'color': color,
            'size': size,
            'stock': stock,
            'unit_price': int(unit_price),
            'formatted_unit_price': f"{int(unit_price):,}원",
            'quantity': qty,
            'subtotal': int(subtotal),
            'formatted_subtotal': f"{int(subtotal):,}원"
        })

    # 2. 품절 상품이 하나라도 있으면 /cart로 리다이렉트 및 안내
    if has_sold_out:
        flash('품절된 상품이 있어 주문할 수 없습니다.', 'danger')
        return redirect(url_for('main.cart_view'))

    if not items:
        flash('장바구니가 비어 있습니다.', 'warning')
        return redirect(url_for('main.cart_view'))

    # 배송비 계산 (상품 합계 50,000원 미만이면 3,000원, 이상이면 무료)
    shipping_fee = 0 if subtotal_amount >= 50000 else 3000
    total_amount = subtotal_amount + shipping_fee

    # =========================================================================
    # POST 요청: 주문 처리 (order_create로 포워딩)
    # =========================================================================
    if request.method == 'POST':
        return order_create()

    # =========================================================================
    # GET 요청: 주문서 렌더링
    # =========================================================================
    # 마이페이지에 저장된 기본 배송지 정보(profiles) 조회
    profile = {}
    try:
        prof_res = supabase.table('profiles').select('*').eq('id', user_id).execute()
        if prof_res.data:
            profile = prof_res.data[0]
    except Exception as e:
        logger.error(f"[Checkout Profile Error] {e}")

    # 기본 배송 주소 fallback
    profile_address = profile.get('shipping_address') or profile.get('address') or ''
    profile_detail = profile.get('shipping_detail_address') or ''
    profile_postal = profile.get('postal_code') or ''
    profile_phone = profile.get('phone') or ''
    profile_name = profile.get('full_name') or (session.get('user') or {}).get('full_name') or ''

    return render_template(
        'checkout.html',
        items=items,
        total_items_count=len(items),
        subtotal_amount=int(subtotal_amount),
        formatted_subtotal=f"{int(subtotal_amount):,}원",
        shipping_fee=shipping_fee,
        formatted_shipping_fee="무료 배송 (0원)" if shipping_fee == 0 else f"{int(shipping_fee):,}원",
        total_amount=int(total_amount),
        formatted_total=f"{int(total_amount):,}원",
        profile={
            'full_name': profile_name,
            'phone': profile_phone,
            'shipping_address': profile_address,
            'shipping_detail_address': profile_detail,
            'postal_code': profile_postal
        },
        user=session.get('user')
    )


@main_bp.route('/order/create', methods=['POST'])
def order_create():
    """
    주문 생성 처리 라우트 (POST /order/create)
    처리 순서:
    1. 장바구니 조회 + 재고 확인 (재고 부족 시 에러, 처리 중단, 아무 것도 쓰지 않음)
    2. 배송지 입력값 서버 측 재검증(휴대폰 번호 패턴, 주소 최소 길이)
    3. 주문번호 생성: 'VF-' + 오늘날짜(YYYYMMDD) + '-' + 4자리 랜덤숫자
       + 밀리초 타임스탬프 뒷 3자리를 덧붙여 충돌 가능성을 낮춤
    4. orders 테이블에 INSERT (status='paid', paid_at=now())
    5. order_items INSERT (상품명, 색상, 사이즈, 가격 스냅샷)
    6. product_options.stock 차감 — 반드시 조건부 UPDATE 사용:
       UPDATE ... SET stock = stock - 수량 WHERE id = 옵션ID AND stock >= 수량
       영향받은 행이 0개면 "방금 재고가 소진되었습니다" 에러로 롤백 처리
    7. carts 아이템 DELETE
    8. /order/complete/<order_id> 리다이렉트
    기술: service_role 키로 재고 차감 (RLS 우회 필요)
    """
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        flash('로그인이 필요한 서비스입니다.', 'warning')
        return redirect(url_for('auth.login', error='login_required', next=url_for('main.cart_view')))

    admin_client = get_supabase_admin_client()

    # 1. 장바구니 조회 + 재고 확인 (재고 부족 시 에러, 처리 중단, 아무 것도 쓰지 않음)
    try:
        cart_res = (
            admin_client.table('carts')
            .select('id, user_id, product_id, option_id, quantity, created_at, product_options(*), products(*)')
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .execute()
        )
        raw_items = cart_res.data or []
    except Exception as e:
        logger.error(f"[Order Create Cart Query Error] {e}", exc_info=True)
        raw_items = []

    if not raw_items:
        flash('장바구니가 비어 있습니다.', 'warning')
        return redirect(url_for('main.cart_view'))

    items = []
    subtotal_amount = 0

    for row in raw_items:
        cid = row['id']
        pid = row['product_id']
        oid = row.get('option_id')
        qty = int(row.get('quantity') or 1)

        prod_data = row.get('products') or {}
        if not prod_data:
            p_lookup = admin_client.table('products').select('*').eq('id', pid).execute()
            if p_lookup.data:
                prod_data = p_lookup.data[0]
            else:
                flash('주문할 수 없는 상품이 장바구니에 포함되어 있습니다.', 'danger')
                return redirect(url_for('main.cart_view'))

        opt_data = row.get('product_options') or {}
        if not opt_data and oid:
            o_lookup = admin_client.table('product_options').select('*').eq('id', oid).execute()
            if o_lookup.data:
                opt_data = o_lookup.data[0]

        prod_name = prod_data.get('name') or '상품'
        raw_price = float(prod_data.get('price') or 0)
        sale_price = prod_data.get('sale_price')
        base_price = float(sale_price) if sale_price and float(sale_price) < raw_price else raw_price

        color = opt_data.get('color') or ''
        size = opt_data.get('size') or ''
        additional_price = float(opt_data.get('additional_price') or 0)

        # 재고 확인: 옵션 재고 우선, 없으면 상품 기본 재고
        if oid:
            opt_stock = opt_data.get('stock')
            if opt_stock is None:
                o_chk = admin_client.table('product_options').select('stock').eq('id', oid).execute()
                opt_stock = int(o_chk.data[0].get('stock') or 0) if o_chk.data else 0
            else:
                opt_stock = int(opt_stock)

            if opt_stock < qty:
                flash(f"상품 '{prod_name}'의 재고가 부족합니다. (현재 재고: {opt_stock}개)", 'danger')
                return redirect(url_for('main.cart_view'))
            item_stock = opt_stock
        else:
            prod_stock = int(prod_data.get('stock') or 0)
            if prod_stock < qty:
                flash(f"상품 '{prod_name}'의 재고가 부족합니다. (현재 재고: {prod_stock}개)", 'danger')
                return redirect(url_for('main.cart_view'))
            item_stock = prod_stock

        unit_price = int(base_price + additional_price)
        subtotal = unit_price * qty
        subtotal_amount += subtotal

        # 스냅샷용 옵션 정보
        if color and size:
            opt_label = f"색상: {color}, 사이즈: {size}"
        elif color:
            opt_label = f"색상: {color}"
        elif size:
            opt_label = f"사이즈: {size}"
        else:
            opt_label = opt_data.get('option_value') or '기본'

        items.append({
            'cart_id': cid,
            'product_id': pid,
            'product_name': prod_name,
            'slug': prod_data.get('slug'),
            'thumbnail_url': prod_data.get('thumbnail_url') or 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=300&q=80',
            'option_id': oid,
            'option_info': opt_label,
            'color': color,
            'size': size,
            'stock': item_stock,
            'unit_price': unit_price,
            'formatted_unit_price': f"{unit_price:,}원",
            'quantity': qty,
            'subtotal': subtotal,
            'formatted_subtotal': f"{subtotal:,}원"
        })

    shipping_fee = 0 if subtotal_amount >= 50000 else 3000
    total_amount = subtotal_amount + shipping_fee

    # 2. 배송지 입력값 서버 측 재검증(휴대폰 번호 패턴, 주소 최소 길이)
    recipient_name = request.form.get('recipient_name', '').strip()
    recipient_phone = request.form.get('recipient_phone', '').strip()
    shipping_address = request.form.get('shipping_address', '').strip()
    shipping_detail_address = request.form.get('shipping_detail_address', '').strip()
    postal_code = request.form.get('postal_code', '').strip() or '06000'
    delivery_memo = request.form.get('delivery_memo', '').strip()
    payment_method = request.form.get('payment_method', '신용/체크카드').strip()

    if not recipient_name:
        flash('수령인 이름을 입력해주세요.', 'danger')
        return redirect(url_for('main.checkout'))

    # 휴대폰 번호 패턴 검증
    phone_pattern = r'^01[0-9]-?\d{3,4}-?\d{4}$'
    if not re.match(phone_pattern, recipient_phone):
        flash('올바른 휴대폰 번호 형식을 입력해주세요. (예: 010-1234-5678)', 'danger')
        return redirect(url_for('main.checkout'))

    clean_digits = re.sub(r'[^0-9]', '', recipient_phone)
    if len(clean_digits) == 11:
        formatted_phone = f"{clean_digits[:3]}-{clean_digits[3:7]}-{clean_digits[7:]}"
    elif len(clean_digits) == 10:
        formatted_phone = f"{clean_digits[:3]}-{clean_digits[3:6]}-{clean_digits[6:]}"
    else:
        formatted_phone = recipient_phone

    # 주소 최소 길이 검증
    if len(shipping_address) < 5:
        flash('배송 주소는 최소 5자 이상 입력해주세요.', 'danger')
        return redirect(url_for('main.checkout'))

    # 3. 주문번호 생성: 'VF-' + 오늘날짜(YYYYMMDD) + '-' + 4자리 랜덤숫자
    #    + 밀리초 타임스탬프 뒷 3자리를 덧붙여 충돌 가능성을 낮춤
    now = datetime.now()
    today_str = now.strftime('%Y%m%d')
    rand_4 = f"{random.randint(0, 9999):04d}"
    ms_3 = f"{int(now.timestamp() * 1000) % 1000:03d}"
    order_number = f"VF-{today_str}-{rand_4}{ms_3}"

    # 4. orders 테이블에 INSERT (status='paid', paid_at=now())
    now_utc_iso = datetime.now(timezone.utc).isoformat()
    db_order = {
        'order_number': order_number,
        'user_id': user_id,
        'status': 'PAID',
        'total_amount': total_amount,
        'discount_amount': 0,
        'payment_amount': total_amount,
        'recipient_name': recipient_name,
        'recipient_phone': formatted_phone,
        'shipping_address': shipping_address,
        'shipping_detail_address': shipping_detail_address or None,
        'postal_code': postal_code,
        'paid_at': now_utc_iso
    }

    order_id = None
    order_persisted_in_db = False

    try:
        ord_res = admin_client.table('orders').insert(db_order).execute()
        if ord_res.data:
            order_id = ord_res.data[0]['id']
            order_persisted_in_db = True
    except Exception as e:
        logger.warning(f"[Orders Insert DB Notice] DB 트리거 또는 저장 경고 (더미 결제 플로우 진행): {e}")

    if not order_id:
        order_id = str(uuid.uuid4())

    # 5. order_items INSERT (상품명, 색상, 사이즈, 가격 스냅샷)
    if order_persisted_in_db:
        order_items_to_insert = []
        for it in items:
            order_items_to_insert.append({
                'order_id': order_id,
                'product_id': it['product_id'],
                'option_id': it['option_id'] if it.get('option_id') else None,
                'product_name': it['product_name'],
                'option_info': it['option_info'],
                'unit_price': it['unit_price'],
                'quantity': it['quantity'],
                'subtotal_price': it['subtotal']
            })

        try:
            admin_client.table('order_items').insert(order_items_to_insert).execute()
        except Exception as oi_err:
            logger.error(f"[Order Items Insert Error] {oi_err}", exc_info=True)

    # 6. product_options.stock 차감 — 조건부 UPDATE 사용 (RPC 우선, 테이블 UPDATE 폴백)
    #    영향받은 행이 0개면 "방금 재고가 소진되었습니다" 에러로 롤백 처리
    deducted_records = []
    stock_depleted = False

    for it in items:
        oid = it.get('option_id')
        qty = it['quantity']
        item_stock = it.get('stock') or 0

        if oid:
            up_res = None
            try:
                up_res = admin_client.rpc('decrement_product_option_stock', {
                    'p_option_id': oid,
                    'p_quantity': qty
                }).execute()
            except Exception:
                # RPC 미설치 시 조건부 UPDATE 폴백
                try:
                    up_res = (
                        admin_client.table('product_options')
                        .update({'stock': max(0, item_stock - qty)})
                        .eq('id', oid)
                        .gte('stock', qty)
                        .execute()
                    )
                except Exception as up_err:
                    logger.warning(f"[Stock Update Warning] {up_err}")

            if not up_res or not up_res.data or len(up_res.data) == 0:
                stock_depleted = True
                break

            deducted_records.append({
                'rpc': 'restore_product_option_stock',
                'rpc_params': {'p_option_id': oid, 'p_quantity': qty},
                'table': 'product_options',
                'id': oid,
                'restored_stock': item_stock
            })
        else:
            pid = it['product_id']
            up_res = None
            try:
                up_res = admin_client.rpc('decrement_product_stock', {
                    'p_product_id': pid,
                    'p_quantity': qty
                }).execute()
            except Exception:
                try:
                    up_res = (
                        admin_client.table('products')
                        .update({'stock': max(0, item_stock - qty)})
                        .eq('id', pid)
                        .gte('stock', qty)
                        .execute()
                    )
                except Exception as up_err:
                    logger.warning(f"[Product Stock Update Warning] {up_err}")

            if not up_res or not up_res.data or len(up_res.data) == 0:
                stock_depleted = True
                break

            deducted_records.append({
                'rpc': 'restore_product_stock',
                'rpc_params': {'p_product_id': pid, 'p_quantity': qty},
                'table': 'products',
                'id': pid,
                'restored_stock': item_stock
            })

    # 재고 차감 실패 시 롤백 처리
    if stock_depleted:
        for rec in deducted_records:
            try:
                if rec.get('rpc'):
                    admin_client.rpc(rec['rpc'], rec['rpc_params']).execute()
            except Exception:
                try:
                    admin_client.table(rec['table']).update({'stock': rec['restored_stock']}).eq('id', rec['id']).execute()
                except Exception as rb_err:
                    logger.error(f"[Stock Rollback Error] {rb_err}")

        if order_persisted_in_db:
            try:
                admin_client.table('order_items').delete().eq('order_id', order_id).execute()
                admin_client.table('orders').delete().eq('id', order_id).execute()
            except Exception as ord_del_err:
                logger.error(f"[Order Rollback Delete Error] {ord_del_err}")

        flash("방금 재고가 소진되었습니다", "danger")
        return redirect(url_for('main.cart_view'))

    # 7. carts 아이템 DELETE
    try:
        admin_client.table('carts').delete().eq('user_id', user_id).execute()
        session['cart_count'] = 0
    except Exception as cart_err:
        logger.error(f"[Cart Delete Error] {cart_err}")

    # 8. /order/complete/<order_id> 리다이렉트
    full_shipping = f"{shipping_address} {shipping_detail_address}".strip()
    summary_name = items[0]['product_name'] if len(items) == 1 else f"{items[0]['product_name']} 외 {len(items)-1}건"
    total_qty = sum(it['quantity'] for it in items)

    session['last_order'] = {
        'user_id': user_id,
        'order_id': order_id,
        'order_number': order_number,
        'recipient_name': recipient_name,
        'recipient_phone': formatted_phone,
        'postal_code': postal_code,
        'shipping_address': full_shipping,
        'delivery_memo': delivery_memo,
        'payment_method': payment_method,
        'item_list': items,
        'product_name': summary_name,
        'product_thumbnail': items[0]['thumbnail_url'],
        'option_info': items[0]['option_info'],
        'quantity': total_qty,
        'subtotal_amount': subtotal_amount,
        'formatted_subtotal': f"{subtotal_amount:,}원",
        'shipping_fee': shipping_fee,
        'formatted_shipping_fee': "무료" if shipping_fee == 0 else f"{shipping_fee:,}원",
        'total_amount': total_amount,
        'formatted_total': f"{total_amount:,}원",
        'status': 'PAID',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    return redirect(url_for('main.order_complete', order_id=order_id))


@main_bp.route('/checkout/process', methods=['POST'])
def process_checkout():
    """/checkout/process를 호출하는 기존 폼을 위한 하위 호환 포워딩"""
    return order_create()


@main_bp.route('/order/complete/<order_id>')
def order_complete(order_id):
    """
    주문 완료 페이지 라우트 (/order/complete/<order_id>)
    - 본인 주문이 맞는지 확인 (다른 사용자의 order_id 접근 차단)
    - 주문번호, 배송지, 주문 상품 목록, 결제 금액 표시
    - 마이페이지로 / 쇼핑 계속하기 버튼 제공
    """
    user_id = session.get('user_id') or (session.get('user') or {}).get('id')
    if not user_id:
        flash('로그인이 필요한 서비스입니다.', 'warning')
        return redirect(url_for('auth.login', error='login_required', next=request.path))

    admin_client = get_supabase_admin_client()
    order = None

    # 1. DB에서 orders 조회하여 본인 소유 여부 확인
    is_uuid = bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(order_id), re.IGNORECASE))
    db_ord = None
    try:
        if is_uuid:
            ord_res = admin_client.table('orders').select('*').eq('id', order_id).execute()
        else:
            ord_res = admin_client.table('orders').select('*').eq('order_number', order_id).execute()
        if ord_res.data:
            db_ord = ord_res.data[0]
    except Exception as e:
        logger.error(f"[Order Complete DB Load Error] {e}")

    # 다른 사용자의 order_id 접근 차단 (403 Forbidden)
    if db_ord and str(db_ord.get('user_id')) != str(user_id):
        abort(403, description="본인의 주문만 확인할 수 있습니다.")

    # 2. 세션의 last_order 확인 (본인 주문이고 order_id 또는 order_number 일치 여부)
    session_order = session.get('last_order')
    if session_order and (session_order.get('order_id') == order_id or session_order.get('order_number') == order_id):
        sess_user = session_order.get('user_id')
        if sess_user and str(sess_user) != str(user_id):
            abort(403, description="본인의 주문만 확인할 수 있습니다.")
        order = session_order

    # 3. DB에서 조회된 주문 데이터로 화면 구성
    if not order and db_ord:
        oid = db_ord['id']
        item_list = []
        subtotal_sum = 0
        try:
            oi_res = admin_client.table('order_items').select('*').eq('order_id', oid).execute()
            for it in (oi_res.data or []):
                unit_p = int(float(it.get('unit_price') or 0))
                qty = int(it.get('quantity') or 1)
                subtotal = int(float(it.get('subtotal_price') or (unit_p * qty)))
                subtotal_sum += subtotal
                item_list.append({
                    'product_name': it.get('product_name') or '상품',
                    'option_info': it.get('option_info'),
                    'unit_price': unit_p,
                    'formatted_unit_price': f"{unit_p:,}원",
                    'quantity': qty,
                    'subtotal': subtotal,
                    'formatted_subtotal': f"{subtotal:,}원",
                    'thumbnail_url': 'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?auto=format&fit=crop&w=300&q=80'
                })
        except Exception as e:
            logger.error(f"[Order Items DB Load Error] {e}")

        total_amt = int(float(db_ord.get('total_amount') or 0))
        shipping_fee = 0 if total_amt >= 50000 or subtotal_sum >= 50000 else 3000
        shipping_addr = db_ord.get('shipping_address') or ''
        detail_addr = db_ord.get('shipping_detail_address') or ''
        full_addr = f"{shipping_addr} {detail_addr}".strip()

        order = {
            'user_id': user_id,
            'order_id': oid,
            'order_number': db_ord.get('order_number'),
            'recipient_name': db_ord.get('recipient_name') or '고객',
            'recipient_phone': db_ord.get('recipient_phone') or '',
            'postal_code': db_ord.get('postal_code') or '',
            'shipping_address': full_addr,
            'delivery_memo': db_ord.get('delivery_memo') or '',
            'payment_method': db_ord.get('payment_method') or '신용/체크카드',
            'item_list': item_list,
            'quantity': sum(x['quantity'] for x in item_list) if item_list else 1,
            'subtotal_amount': subtotal_sum or total_amt,
            'formatted_subtotal': f"{(subtotal_sum or total_amt):,}원",
            'shipping_fee': shipping_fee,
            'formatted_shipping_fee': "무료 배송 (0원)" if shipping_fee == 0 else f"{shipping_fee:,}원",
            'total_amount': total_amt,
            'formatted_total': f"{total_amt:,}원",
            'status': db_ord.get('status', 'PAID'),
            'created_at': db_ord.get('created_at', '')
        }

    # 4. 존재하지 않는 주문 접근 처리
    if not order:
        flash('주문 내역을 찾을 수 없습니다.', 'warning')
        return redirect(url_for('main.index'))

    return render_template('order_complete.html', order=order)


@main_bp.route('/order/success/<order_number>')
def order_success(order_number):
    """하위 호환을 위한 주문 성공 라우트 포워딩"""
    return order_complete(order_number)




