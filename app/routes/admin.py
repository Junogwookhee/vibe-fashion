"""VIBE-FASHION Admin Blueprint and Access Control
Manages administrative dashboard, products, and order management.
Strictly enforced by server-side role check (profiles.role == 'admin') and CSRF protection.
"""

import math
import logging
import re
import secrets
from datetime import datetime, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from app.utils.supabase_client import get_supabase_admin_client

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ==============================================================================
# CSRF 토큰 생성 및 검증 헬퍼
# ==============================================================================
def get_or_create_csrf_token():
    """세션에 안전한 CSRF 토큰을 생성 또는 반환합니다."""
    token = session.get('admin_csrf_token')
    if not token:
        token = secrets.token_hex(32)
        session['admin_csrf_token'] = token
    return token


def validate_csrf():
    """POST 등 변경 요청에 대해 CSRF 토큰을 검증합니다."""
    expected_token = session.get('admin_csrf_token')
    sent_token = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token')
    if not expected_token or not sent_token or not secrets.compare_digest(expected_token, sent_token):
        abort(400, description="CSRF 토큰이 유효하지 않거나 만료되었습니다. 페이지를 새로고침 후 다시 시도해주세요.")


@admin_bp.context_processor
def inject_admin_context():
    """관리자 템플릿에 공통으로 필요한 변수를 주입합니다."""
    return {
        'admin_csrf_token': get_or_create_csrf_token(),
        'current_admin': getattr(g, 'admin_user', session.get('user', {})),
        'now': datetime.now()
    }


# ==============================================================================
# 관리자 권한 검증 미들웨어 / 데코레이터
# ==============================================================================
def admin_required(f):
    """
    서버 측 관리자 권한 검증:
    1. 로그인 여부 확인 -> 미로그인 시 로그인 페이지로 리다이렉트
    2. Supabase DB의 profiles 테이블에서 role 조회 -> 'admin' 여부 직접 확인
    3. 일반 회원인 경우 403 Forbidden 응답 및 비인가 안내 화면 표시
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash('관리자 페이지 접근을 위해 로그인이 필요합니다.', 'warning')
            return redirect(url_for('auth.login', next=request.full_path if request.method == 'GET' else url_for('admin.dashboard'), error='login_required'))

        # Supabase service_role 클라이언트로 최신 프로필 role 검증 (세션 조작 방지)
        admin_client = get_supabase_admin_client()
        try:
            prof_res = admin_client.table('profiles').select('id, email, full_name, role').eq('id', user_id).execute()
            if not prof_res.data:
                logger.warning(f"[Admin Security] 프로필 없는 사용자의 관리자 접근 차단: {user_id}")
                return render_template('admin/unauthorized.html', user_email=(session.get('user') or {}).get('email')), 403

            profile = prof_res.data[0]
            if profile.get('role') != 'admin':
                logger.warning(f"[Admin Security] 권한 없는 사용자의 관리자 접근 시도 (role={profile.get('role')}): {user_id}")
                return render_template('admin/unauthorized.html', user_email=profile.get('email')), 403

            # 유효한 관리자 정보 컨텍스트 저장
            g.admin_user = profile

        except Exception as e:
            logger.error(f"[Admin Auth Check Error] {e}", exc_info=True)
            return render_template('admin/unauthorized.html', error_detail="권한 확인 중 오류가 발생했습니다."), 500

        # 변경 요청(POST)의 경우 CSRF 검증 필수 적용
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            validate_csrf()

        return f(*args, **kwargs)
    return decorated_function


# ==============================================================================
# [1] 관리자 대시보드 (GET /admin, GET /admin/dashboard)
# ==============================================================================
@admin_bp.route('', methods=['GET'])
@admin_bp.route('/dashboard', methods=['GET'])
@admin_required
def dashboard():
    """
    실제 조회 가능한 데이터 기반 관리자 대시보드:
    - 전체 상품 수, 판매 중 상품 수, 품절/재고부족 상품 수
    - 전체 주문 수, 결제완료(PAID/PREPARING/SHIPPING/DELIVERED) 누적 매출액
    - 상태별 주문 카운트 (PAID, PREPARING, SHIPPING, DELIVERED, CANCELLED)
    - 최근 주문 내역 (최신 5건)
    """
    admin_client = get_supabase_admin_client()

    metrics = {
        'total_products': 0,
        'active_products': 0,
        'out_of_stock_products': 0,
        'total_orders': 0,
        'total_revenue': 0,
        'orders_by_status': {
            'PAID': 0,
            'PREPARING': 0,
            'SHIPPING': 0,
            'DELIVERED': 0,
            'CANCELLED': 0,
            'PENDING_PAYMENT': 0
        }
    }
    recent_orders = []
    recent_products = []
    db_error = None

    try:
        # 1. 상품 통계 조회
        prods_res = admin_client.table('products').select('id, name, price, stock, is_active, created_at').execute()
        prods_data = prods_res.data or []
        metrics['total_products'] = len(prods_data)
        metrics['active_products'] = sum(1 for p in prods_data if p.get('is_active') is True)
        metrics['out_of_stock_products'] = sum(1 for p in prods_data if (p.get('stock') or 0) <= 0 or p.get('is_active') is False)

        # 최근 등록 상품 5개
        sorted_prods = sorted(prods_data, key=lambda x: x.get('created_at') or '', reverse=True)
        recent_products = sorted_prods[:5]

        # 2. 주문 통계 조회
        orders_res = admin_client.table('orders').select('*').order('created_at', desc=True).execute()
        orders_data = orders_res.data or []
        metrics['total_orders'] = len(orders_data)

        # 매출 집계 기준: 결제 완료 상태인 PAID, PREPARING, SHIPPING, DELIVERED 실결제액(payment_amount or total_amount) 합산
        revenue_statuses = {'PAID', 'PREPARING', 'SHIPPING', 'DELIVERED'}
        for o in orders_data:
            st = str(o.get('status') or '').upper()
            if st in metrics['orders_by_status']:
                metrics['orders_by_status'][st] += 1
            else:
                metrics['orders_by_status'][st] = 1

            if st in revenue_statuses:
                amt = float(o.get('payment_amount') or o.get('total_amount') or 0)
                metrics['total_revenue'] += amt

        metrics['total_revenue'] = int(metrics['total_revenue'])
        recent_orders = orders_data[:5]

    except Exception as e:
        logger.error(f"[Admin Dashboard Error] {e}", exc_info=True)
        db_error = "데이터베이스 조회 중 오류가 발생하여 최신 통계를 불러오지 못했습니다."

    return render_template(
        'admin/dashboard.html',
        active_menu='dashboard',
        metrics=metrics,
        recent_orders=recent_orders,
        recent_products=recent_products,
        db_error=db_error
    )


# ==============================================================================
# [2] 상품 관리: 목록 및 검색/필터 (GET /admin/products)
# ==============================================================================
@admin_bp.route('/products', methods=['GET'])
@admin_required
def product_list():
    """
    상품 목록 조회, 검색(상품명/슬러그), 카테고리 필터, 판매상태 필터, 페이지네이션
    """
    admin_client = get_supabase_admin_client()

    query_text = request.args.get('q', '').strip()
    category_id = request.args.get('category', '').strip()
    status_filter = request.args.get('status', '').strip()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 10

    categories = []
    products = []
    total_count = 0
    total_pages = 1
    db_error = None

    try:
        # 카테고리 목록 조회
        cat_res = admin_client.table('categories').select('id, name, slug').order('sort_order').execute()
        categories = cat_res.data or []

        # 상품 전체 조회 (옵션 수 포함)
        prods_res = admin_client.table('products').select(
            'id, category_id, name, slug, price, sale_price, stock, is_active, is_featured, thumbnail_url, created_at, categories(name)'
        ).order('created_at', desc=True).execute()
        all_prods = prods_res.data or []

        # 검색 및 필터링
        filtered = []
        for p in all_prods:
            # 검색어 필터
            if query_text:
                q_lower = query_text.lower()
                name_match = q_lower in (p.get('name') or '').lower()
                slug_match = q_lower in (p.get('slug') or '').lower()
                if not (name_match or slug_match):
                    continue

            # 카테고리 필터
            if category_id:
                if str(p.get('category_id')) != str(category_id):
                    continue

            # 상태 필터
            if status_filter == 'active' and not p.get('is_active'):
                continue
            if status_filter == 'inactive' and p.get('is_active'):
                continue
            if status_filter == 'out_of_stock' and (p.get('stock') or 0) > 0:
                continue

            filtered.append(p)

        total_count = len(filtered)
        total_pages = max(1, math.ceil(total_count / per_page))
        start_idx = (page - 1) * per_page
        products = filtered[start_idx:start_idx + per_page]

        # 각 상품별 옵션 개수 조회
        prod_ids = [p['id'] for p in products]
        if prod_ids:
            opts_res = admin_client.table('product_options').select('product_id').in_('product_id', prod_ids).execute()
            opt_counts = {}
            for opt in (opts_res.data or []):
                pid = opt['product_id']
                opt_counts[pid] = opt_counts.get(pid, 0) + 1
            for p in products:
                p['options_count'] = opt_counts.get(p['id'], 0)

    except Exception as e:
        logger.error(f"[Admin Products List Error] {e}", exc_info=True)
        db_error = "상품 목록을 불러오는 중 오류가 발생했습니다."

    return render_template(
        'admin/products.html',
        active_menu='products',
        products=products,
        categories=categories,
        query_text=query_text,
        category_id=category_id,
        status_filter=status_filter,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        db_error=db_error
    )


# ==============================================================================
# [3] 상품 등록 (GET /admin/products/new, POST /admin/products/new)
# ==============================================================================
@admin_bp.route('/products/new', methods=['GET', 'POST'])
@admin_required
def product_new():
    admin_client = get_supabase_admin_client()

    if request.method == 'GET':
        categories = []
        try:
            cat_res = admin_client.table('categories').select('id, name').order('sort_order').execute()
            categories = cat_res.data or []
        except Exception as e:
            logger.error(f"[Admin Cat Fetch Error] {e}")

        return render_template(
            'admin/product_form.html',
            active_menu='products',
            is_edit=False,
            product={},
            options=[],
            categories=categories
        )

    # 1. 폼 데이터 검증
    name = request.form.get('name', '').strip()
    slug = request.form.get('slug', '').strip()
    category_id_raw = request.form.get('category_id', '').strip()
    price_raw = request.form.get('price', '').strip()
    sale_price_raw = request.form.get('sale_price', '').strip()
    stock_raw = request.form.get('stock', '0').strip()
    thumbnail_url = request.form.get('thumbnail_url', '').strip()
    summary = request.form.get('summary', '').strip()
    description = request.form.get('description', '').strip()
    is_active = request.form.get('is_active') == 'true'
    is_featured = request.form.get('is_featured') == 'true'

    if not name:
        flash('상품명은 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.product_new'))

    try:
        price = float(price_raw)
        if price < 0:
            raise ValueError()
    except (ValueError, TypeError):
        flash('정가는 0원 이상의 올바른 숫자를 입력해주세요.', 'danger')
        return redirect(url_for('admin.product_new'))

    sale_price = None
    if sale_price_raw:
        try:
            sale_price = float(sale_price_raw)
            if sale_price < 0:
                raise ValueError()
        except (ValueError, TypeError):
            flash('판매가(할인가)는 0원 이상의 숫자를 입력해주세요.', 'danger')
            return redirect(url_for('admin.product_new'))

    try:
        stock = max(0, int(stock_raw))
    except (ValueError, TypeError):
        stock = 0

    category_id = int(category_id_raw) if category_id_raw and category_id_raw.isdigit() else None

    # 이미지 URL 검증
    if thumbnail_url:
        parsed_url = urlparse(thumbnail_url)
        if parsed_url.scheme not in ('http', 'https') or not parsed_url.netloc:
            flash('올바른 이미지 URL(http:// 또는 https://)을 입력해주세요.', 'danger')
            return redirect(url_for('admin.product_new'))

    # 슬러그 생성 및 정제
    if not slug:
        # 영문/숫자/하이픈 기반 자동 슬러그
        slug_base = re.sub(r'[^a-zA-Z0-9]+', '-', name).strip('-').lower()
        slug = slug_base or f"prod-{int(datetime.now().timestamp())}"
    else:
        slug = re.sub(r'[^a-zA-Z0-9\-_]+', '-', slug).strip('-').lower()

    # 슬러그 중복 확인
    try:
        dup = admin_client.table('products').select('id').eq('slug', slug).execute()
        if dup.data:
            slug = f"{slug}-{int(datetime.now().timestamp()) % 10000}"
    except Exception as e:
        logger.warning(f"[Slug Dup Check Warning] {e}")

    try:
        product_insert_data = {
            'name': name,
            'slug': slug,
            'category_id': category_id,
            'price': price,
            'sale_price': sale_price,
            'stock': stock,
            'thumbnail_url': thumbnail_url or None,
            'summary': summary or None,
            'description': description or None,
            'is_active': is_active,
            'is_featured': is_featured,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        res = admin_client.table('products').insert(product_insert_data).execute()
        if not res.data:
            raise RuntimeError("상품 등록 결과 행이 반환되지 않았습니다.")

        new_product_id = res.data[0]['id']

        # 옵션 저장 처리 (색상/사이즈/추가금/재고)
        colors = request.form.getlist('option_color[]')
        sizes = request.form.getlist('option_size[]')
        add_prices = request.form.getlist('option_additional_price[]')
        opt_stocks = request.form.getlist('option_stock[]')

        options_to_insert = []
        for i in range(len(colors)):
            c = colors[i].strip() if i < len(colors) else ''
            s = sizes[i].strip() if i < len(sizes) else ''
            if not c and not s:
                continue
            ap = float(add_prices[i]) if i < len(add_prices) and add_prices[i].replace('.', '', 1).isdigit() else 0.0
            stk = int(opt_stocks[i]) if i < len(opt_stocks) and opt_stocks[i].isdigit() else 0

            opt_name = f"{c}/{s}" if c and s else (c or s)
            options_to_insert.append({
                'product_id': new_product_id,
                'color': c or None,
                'size': s or None,
                'additional_price': ap,
                'stock': stk,
                'option_name': '색상/사이즈' if c and s else ('색상' if c else '사이즈'),
                'option_value': opt_name
            })

        if options_to_insert:
            admin_client.table('product_options').insert(options_to_insert).execute()

        flash(f"상품 '{name}'이(가) 성공적으로 등록되었습니다.", 'success')
        return redirect(url_for('admin.product_list'))

    except Exception as e:
        logger.error(f"[Admin Product Create Error] {e}", exc_info=True)
        flash(f"상품 등록 중 오류가 발생했습니다: {e}", 'danger')
        return redirect(url_for('admin.product_new'))


# ==============================================================================
# [4] 상품 수정 (GET /admin/products/<id>/edit, POST /admin/products/<id>/edit)
# ==============================================================================
@admin_bp.route('/products/<product_id>/edit', methods=['GET', 'POST'])
@admin_required
def product_edit(product_id):
    admin_client = get_supabase_admin_client()

    # 상품 조회
    try:
        p_res = admin_client.table('products').select('*').eq('id', product_id).execute()
        if not p_res.data:
            flash('수정할 상품을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.product_list'))
        product = p_res.data[0]
    except Exception as e:
        logger.error(f"[Admin Product Fetch Error] {e}")
        flash('상품 정보를 불러오는 중 오류가 발생했습니다.', 'danger')
        return redirect(url_for('admin.product_list'))

    categories = []
    try:
        cat_res = admin_client.table('categories').select('id, name').order('sort_order').execute()
        categories = cat_res.data or []
    except Exception as e:
        logger.error(f"[Admin Cat Fetch Error] {e}")

    if request.method == 'GET':
        options = []
        try:
            opts_res = admin_client.table('product_options').select('*').eq('product_id', product_id).order('id').execute()
            options = opts_res.data or []
        except Exception as e:
            logger.error(f"[Admin Options Fetch Error] {e}")

        return render_template(
            'admin/product_form.html',
            active_menu='products',
            is_edit=True,
            product=product,
            options=options,
            categories=categories
        )

    # POST: 상품 정보 수정
    name = request.form.get('name', '').strip()
    slug = request.form.get('slug', '').strip()
    category_id_raw = request.form.get('category_id', '').strip()
    price_raw = request.form.get('price', '').strip()
    sale_price_raw = request.form.get('sale_price', '').strip()
    stock_raw = request.form.get('stock', '0').strip()
    thumbnail_url = request.form.get('thumbnail_url', '').strip()
    summary = request.form.get('summary', '').strip()
    description = request.form.get('description', '').strip()
    is_active = request.form.get('is_active') == 'true'
    is_featured = request.form.get('is_featured') == 'true'

    if not name:
        flash('상품명은 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.product_edit', product_id=product_id))

    try:
        price = float(price_raw)
        if price < 0:
            raise ValueError()
    except (ValueError, TypeError):
        flash('정가는 0원 이상의 올바른 숫자를 입력해주세요.', 'danger')
        return redirect(url_for('admin.product_edit', product_id=product_id))

    sale_price = None
    if sale_price_raw:
        try:
            sale_price = float(sale_price_raw)
            if sale_price < 0:
                raise ValueError()
        except (ValueError, TypeError):
            flash('판매가(할인가)는 0원 이상의 숫자를 입력해주세요.', 'danger')
            return redirect(url_for('admin.product_edit', product_id=product_id))

    try:
        stock = max(0, int(stock_raw))
    except (ValueError, TypeError):
        stock = 0

    category_id = int(category_id_raw) if category_id_raw and category_id_raw.isdigit() else None

    if thumbnail_url:
        parsed_url = urlparse(thumbnail_url)
        if parsed_url.scheme not in ('http', 'https') or not parsed_url.netloc:
            flash('올바른 이미지 URL을 입력해주세요.', 'danger')
            return redirect(url_for('admin.product_edit', product_id=product_id))

    if not slug:
        slug = product.get('slug') or f"prod-{int(datetime.now().timestamp())}"

    try:
        update_data = {
            'name': name,
            'slug': slug,
            'category_id': category_id,
            'price': price,
            'sale_price': sale_price,
            'stock': stock,
            'thumbnail_url': thumbnail_url or None,
            'summary': summary or None,
            'description': description or None,
            'is_active': is_active,
            'is_featured': is_featured,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        admin_client.table('products').update(update_data).eq('id', product_id).execute()

        # 옵션 동기화 (기존 옵션 확인 후 신규 추가 또는 업데이트)
        colors = request.form.getlist('option_color[]')
        sizes = request.form.getlist('option_size[]')
        add_prices = request.form.getlist('option_additional_price[]')
        opt_stocks = request.form.getlist('option_stock[]')
        opt_ids = request.form.getlist('option_id[]')

        # 기존 옵션 목록
        existing_opts_res = admin_client.table('product_options').select('id').eq('product_id', product_id).execute()
        existing_opt_ids = {str(o['id']) for o in (existing_opts_res.data or [])}
        submitted_opt_ids = set()

        for i in range(len(colors)):
            c = colors[i].strip() if i < len(colors) else ''
            s = sizes[i].strip() if i < len(sizes) else ''
            if not c and not s:
                continue
            ap = float(add_prices[i]) if i < len(add_prices) and add_prices[i].replace('.', '', 1).isdigit() else 0.0
            stk = int(opt_stocks[i]) if i < len(opt_stocks) and opt_stocks[i].isdigit() else 0
            cur_oid = opt_ids[i].strip() if i < len(opt_ids) else ''

            opt_name = f"{c}/{s}" if c and s else (c or s)
            opt_payload = {
                'color': c or None,
                'size': s or None,
                'additional_price': ap,
                'stock': stk,
                'option_name': '색상/사이즈' if c and s else ('색상' if c else '사이즈'),
                'option_value': opt_name
            }

            if cur_oid and cur_oid in existing_opt_ids:
                submitted_opt_ids.add(cur_oid)
                admin_client.table('product_options').update(opt_payload).eq('id', cur_oid).execute()
            else:
                opt_payload['product_id'] = product_id
                ins_res = admin_client.table('product_options').insert(opt_payload).execute()
                if ins_res.data:
                    submitted_opt_ids.add(str(ins_res.data[0]['id']))

        # 삭제된 옵션 처리 (주문 이력 없는 경우에만 안전 삭제, 주문 이력 있으면 stock=0으로 보관)
        to_remove = existing_opt_ids - submitted_opt_ids
        for rem_id in to_remove:
            try:
                oi_check = admin_client.table('order_items').select('id').eq('option_id', rem_id).limit(1).execute()
                if oi_check.data:
                    admin_client.table('product_options').update({'stock': 0}).eq('id', rem_id).execute()
                else:
                    admin_client.table('product_options').delete().eq('id', rem_id).execute()
            except Exception as rem_err:
                logger.warning(f"[Option Cleanup Error] {rem_err}")

        flash(f"상품 '{name}' 정보가 성공적으로 수정되었습니다.", 'success')
        return redirect(url_for('admin.product_list'))

    except Exception as e:
        logger.error(f"[Admin Product Update Error] {e}", exc_info=True)
        flash(f"상품 수정 중 오류가 발생했습니다: {e}", 'danger')
        return redirect(url_for('admin.product_edit', product_id=product_id))


# ==============================================================================
# [5] 상품 상태 토글 및 보관 삭제 (POST /admin/products/<id>/toggle-status)
# ==============================================================================
@admin_bp.route('/products/<product_id>/toggle-status', methods=['POST'])
@admin_required
def product_toggle_status(product_id):
    """판매 중 <-> 판매 중지 상태 원클릭 토글 (POST 전용, CSRF 검증)"""
    admin_client = get_supabase_admin_client()
    try:
        cur = admin_client.table('products').select('id, name, is_active').eq('id', product_id).execute()
        if not cur.data:
            flash('상품을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.product_list'))

        prod = cur.data[0]
        new_status = not prod.get('is_active')
        admin_client.table('products').update({
            'is_active': new_status,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', product_id).execute()

        msg = "판매 중" if new_status else "판매 중지"
        flash(f"'{prod.get('name')}' 상품 상태가 [{msg}]으로 변경되었습니다.", 'success')

    except Exception as e:
        logger.error(f"[Product Toggle Status Error] {e}", exc_info=True)
        flash('상품 상태 변경 중 오류가 발생했습니다.', 'danger')

    return redirect(request.referrer or url_for('admin.product_list'))


@admin_bp.route('/products/<product_id>/delete', methods=['POST'])
@admin_required
def product_delete(product_id):
    """
    주문 이력이 연결된 상품은 삭제로 이력이 훼손되지 않도록 [판매 중지(보관)] 처리,
    연결된 주문이 없는 상품만 안전하게 삭제 처리
    """
    admin_client = get_supabase_admin_client()
    try:
        cur = admin_client.table('products').select('id, name').eq('id', product_id).execute()
        if not cur.data:
            flash('상품을 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.product_list'))
        p_name = cur.data[0].get('name')

        # 주문 이력 존재 여부 확인
        order_check = admin_client.table('order_items').select('id').eq('product_id', product_id).limit(1).execute()
        if order_check.data:
            # 주문 이력이 있으므로 이력 보존을 위해 판매 중지(보관)로 처리
            admin_client.table('products').update({
                'is_active': False,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', product_id).execute()
            flash(f"'{p_name}' 상품은 기존 주문 이력이 존재하여 데이터를 영구 삭제하지 않고 [판매 중지(보관)] 상태로 전환했습니다.", 'info')
        else:
            # 주문 이력이 없으므로 옵션 정리 후 안전 삭제
            admin_client.table('product_options').delete().eq('product_id', product_id).execute()
            admin_client.table('products').delete().eq('id', product_id).execute()
            flash(f"'{p_name}' 상품이 안전하게 삭제되었습니다.", 'success')

    except Exception as e:
        logger.error(f"[Product Delete Error] {e}", exc_info=True)
        flash('상품 삭제 처리 중 오류가 발생했습니다.', 'danger')

    return redirect(url_for('admin.product_list'))


# ==============================================================================
# [6] 주문 관리: 목록 및 검색/필터 (GET /admin/orders)
# ==============================================================================
@admin_bp.route('/orders', methods=['GET'])
@admin_required
def order_list():
    """
    주문 목록, 주문번호/수령인 검색, 주문상태 필터, 페이지네이션
    """
    admin_client = get_supabase_admin_client()

    query_text = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip().upper()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 10

    orders = []
    total_count = 0
    total_pages = 1
    db_error = None

    try:
        ord_res = admin_client.table('orders').select('*').order('created_at', desc=True).execute()
        all_orders = ord_res.data or []

        filtered = []
        for o in all_orders:
            # 검색어 필터
            if query_text:
                q_lower = query_text.lower()
                num_match = q_lower in (o.get('order_number') or '').lower()
                name_match = q_lower in (o.get('recipient_name') or '').lower()
                phone_match = q_lower in (o.get('recipient_phone') or '').lower()
                if not (num_match or name_match or phone_match):
                    continue

            # 상태 필터
            if status_filter and status_filter != 'ALL':
                if str(o.get('status') or '').upper() != status_filter:
                    continue

            filtered.append(o)

        total_count = len(filtered)
        total_pages = max(1, math.ceil(total_count / per_page))
        start_idx = (page - 1) * per_page
        orders = filtered[start_idx:start_idx + per_page]

        # 각 주문별 주문 상품 대표명 및 항목 수 요약 연결
        order_ids = [o['id'] for o in orders]
        if order_ids:
            items_res = admin_client.table('order_items').select('order_id, product_name, quantity').in_('order_id', order_ids).execute()
            items_by_order = {}
            for it in (items_res.data or []):
                oid = it['order_id']
                items_by_order.setdefault(oid, []).append(it)

            for o in orders:
                its = items_by_order.get(o['id'], [])
                if its:
                    first_name = its[0]['product_name']
                    extra = len(its) - 1
                    o['summary_title'] = f"{first_name} 외 {extra}건" if extra > 0 else first_name
                    o['total_item_count'] = sum(x.get('quantity') or 1 for x in its)
                else:
                    o['summary_title'] = "주문 상품 1건"
                    o['total_item_count'] = 1

    except Exception as e:
        logger.error(f"[Admin Order List Error] {e}", exc_info=True)
        db_error = "주문 목록을 불러오는 중 오류가 발생했습니다."

    return render_template(
        'admin/orders.html',
        active_menu='orders',
        orders=orders,
        query_text=query_text,
        status_filter=status_filter,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        db_error=db_error
    )


# ==============================================================================
# [7] 주문 상세 및 배송/상태 관리 (GET /admin/orders/<id>)
# ==============================================================================
# 유효한 상태 전환 규칙 (임의 결제완료/임의 환불 차단)
ALLOWED_TRANSITIONS = {
    'PAID': ['PREPARING', 'CANCELLED'],
    'PREPARING': ['SHIPPING', 'CANCELLED'],
    'SHIPPING': ['DELIVERED'],
    'DELIVERED': [],
    'CANCELLED': [],
    'PENDING_PAYMENT': ['CANCELLED']
}

STATUS_LABELS = {
    'PENDING_PAYMENT': '입금 대기',
    'PAID': '결제 완료',
    'PREPARING': '배송 준비 중',
    'SHIPPING': '배송 중',
    'DELIVERED': '배송 완료',
    'CANCELLED': '주문 취소'
}


@admin_bp.route('/orders/<order_id>', methods=['GET'])
@admin_required
def order_detail(order_id):
    admin_client = get_supabase_admin_client()

    try:
        ord_res = admin_client.table('orders').select('*').eq('id', order_id).execute()
        if not ord_res.data:
            flash('주문 정보를 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.order_list'))

        order = ord_res.data[0]
        cur_status = str(order.get('status') or '').upper()

        # 주문 상품 상세 조회
        items_res = admin_client.table('order_items').select('*').eq('order_id', order_id).order('id').execute()
        order_items = items_res.data or []

        # 허용되는 전환 상태 목록
        allowed_next_statuses = ALLOWED_TRANSITIONS.get(cur_status, [])

        return render_template(
            'admin/order_detail.html',
            active_menu='orders',
            order=order,
            order_items=order_items,
            cur_status=cur_status,
            allowed_next_statuses=allowed_next_statuses,
            status_labels=STATUS_LABELS
        )

    except Exception as e:
        logger.error(f"[Admin Order Detail Error] {e}", exc_info=True)
        flash('주문 상세 정보를 불러오는 중 오류가 발생했습니다.', 'danger')
        return redirect(url_for('admin.order_list'))


@admin_bp.route('/orders/<order_id>/status', methods=['POST'])
@admin_required
def order_update_status(order_id):
    """
    주문 상태 변경 (POST 전용, CSRF 검증)
    - 허용된 단계별 배송 상태 전환만 지원
    - 실제 PG 연동 없는 임의 결제완료/환불 차단
    - 운송장 번호(tracking_number) 저장 지원
    """
    admin_client = get_supabase_admin_client()
    new_status = request.form.get('status', '').strip().upper()
    tracking_number = request.form.get('tracking_number', '').strip()

    try:
        ord_res = admin_client.table('orders').select('id, status, order_number').eq('id', order_id).execute()
        if not ord_res.data:
            flash('주문 정보를 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.order_list'))

        order = ord_res.data[0]
        cur_status = str(order.get('status') or '').upper()

        allowed = ALLOWED_TRANSITIONS.get(cur_status, [])
        if new_status != cur_status and new_status not in allowed:
            flash(f"현재 상태({STATUS_LABELS.get(cur_status, cur_status)})에서는 선택하신 상태({STATUS_LABELS.get(new_status, new_status)})로 전환할 수 없습니다.", 'danger')
            return redirect(url_for('admin.order_detail', order_id=order_id))

        update_payload = {
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        if new_status and new_status != cur_status:
            update_payload['status'] = new_status

        if tracking_number:
            update_payload['tracking_number'] = tracking_number

        admin_client.table('orders').update(update_payload).eq('id', order_id).execute()
        flash(f"주문({order.get('order_number')}) 상태가 정상적으로 갱신되었습니다.", 'success')

    except Exception as e:
        logger.error(f"[Admin Order Status Update Error] {e}", exc_info=True)
        flash(f"주문 상태 갱신 중 오류가 발생했습니다: {e}", 'danger')

    return redirect(url_for('admin.order_detail', order_id=order_id))
