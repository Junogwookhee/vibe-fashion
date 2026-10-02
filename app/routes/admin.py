"""VIBE-FASHION Admin Blueprint and Access Control
Manages administrative dashboard, products, and order management.
Strictly enforced by server-side role check (profiles.role == 'admin') and CSRF protection.
"""

import math
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException
from app.utils.supabase_client import get_supabase_admin_client
from app.utils.admin_work_alerts import (
    LOW_STOCK_THRESHOLD,
    SEOUL_TIMEZONE,
    format_seoul_datetime,
    load_work_alerts,
)
from app.utils.admin_members import format_member_directory_row

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
                logger.warning('[Admin Security] 프로필이 없는 사용자의 관리자 접근을 차단했습니다.')
                return render_template('admin/unauthorized.html', user_email=(session.get('user') or {}).get('email')), 403

            profile = prof_res.data[0]
            if profile.get('role') != 'admin':
                logger.warning('[Admin Security] 관리자 권한이 없는 접근을 차단했습니다.')
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
    work_alerts = load_work_alerts(admin_client)
    last_work_alert_refresh = format_seoul_datetime(datetime.now(timezone.utc).isoformat())

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
        db_error=db_error,
        work_alerts=work_alerts,
        last_work_alert_refresh=last_work_alert_refresh,
        low_stock_threshold=LOW_STOCK_THRESHOLD
    )


@admin_bp.route('/api/work-alerts', methods=['GET'])
@admin_required
def work_alerts_api():
    """관리자 대시보드에서 수동 새로고침에 사용하는 업무 알림 API."""
    alerts = load_work_alerts(get_supabase_admin_client())
    refreshed_at = format_seoul_datetime(datetime.now(timezone.utc).isoformat())
    return jsonify({'alerts': alerts, 'refreshed_at': refreshed_at})


# ======================================================================
# 고객 문의 관리 (GET /admin/inquiries, 답변 등록/수정)
# ======================================================================
INQUIRY_TYPE_LABELS = {
    'product_size': '상품·사이즈',
    'delivery': '배송',
    'order_payment': '주문·결제',
    'cancel_exchange_return': '취소·교환·반품',
    'other': '기타',
}
INQUIRY_STATUS_LABELS = {'pending': '답변 대기', 'answered': '답변 완료'}
INQUIRY_PAGE_SIZE = 20
INQUIRY_REPLY_MAX_LENGTH = 5000
ADMIN_INQUIRY_LIST_COLUMNS = (
    'id, inquiry_number, user_id, user_id_text, author_name, author_nickname, '
    'inquiry_type, title, status, created_at'
)
ADMIN_INQUIRY_DETAIL_COLUMNS = (
    'id, inquiry_number, user_id, user_id_text, author_name, order_id, order_number, '
    'inquiry_type, title, content, status, reply_text, answered_by, answered_at, '
    'reply_updated_by, reply_updated_at, reply_version, created_at, updated_at'
)


def _inquiry_search_pattern(value):
    escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
    escaped = escaped.replace('%', r'\%').replace('_', r'\_')
    return f'%{escaped}%'


def _inquiry_return_params(args):
    try:
        page = max(1, int(args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    status = args.get('status', '')
    inquiry_type = args.get('inquiry_type', '')
    raw_member_id = args.get('member_id', '')
    member_id = _validated_member_id(raw_member_id) if raw_member_id else ''
    if raw_member_id and not member_id:
        abort(404)
    return {
        'q': args.get('q', '').strip()[:100],
        'author': args.get('author', '').strip()[:100],
        'inquiry_type': inquiry_type if inquiry_type in INQUIRY_TYPE_LABELS else '',
        'status': status if status in ('pending', 'answered') else '',
        'from_date': args.get('from_date', '').strip(),
        'to_date': args.get('to_date', '').strip(),
        'member_id': member_id,
        'page': page,
    }


def _format_admin_inquiry(row):
    item = dict(row)
    item['inquiry_type_label'] = INQUIRY_TYPE_LABELS.get(item.get('inquiry_type'), '기타')
    item['status_label'] = INQUIRY_STATUS_LABELS.get(item.get('status'), '확인 필요')
    item['created_at_display'] = format_seoul_datetime(item.get('created_at'))
    item['answered_at_display'] = format_seoul_datetime(item.get('answered_at'))
    item['reply_updated_at_display'] = format_seoul_datetime(item.get('reply_updated_at'))
    return item


def _load_admin_inquiry_detail(admin_client, inquiry_id):
    result = (
        admin_client.table('admin_customer_inquiries')
        .select(ADMIN_INQUIRY_DETAIL_COLUMNS)
        .eq('id', inquiry_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    inquiry = _format_admin_inquiry(result.data[0])
    history = []
    history_error = None
    try:
        history_result = (
            admin_client.table('customer_inquiry_reply_history')
            .select('reply_version, action, previous_reply, new_reply, changed_by, changed_at')
            .eq('inquiry_id', inquiry_id)
            .order('reply_version', desc=True)
            .execute()
        )
        for row in history_result.data or []:
            item = dict(row)
            item['changed_at_display'] = format_seoul_datetime(item.get('changed_at'))
            item['changed_by_display'] = f"관리자 · {str(item.get('changed_by') or '')[:8]}"
            item['action_label'] = '최초 답변' if item.get('action') == 'answered' else '답변 수정'
            history.append(item)
    except Exception:
        logger.error('[Admin Inquiries] 답변 변경 이력 조회에 실패했습니다.')
        history_error = '답변 변경 이력을 불러오지 못했습니다.'
    return {'inquiry': inquiry, 'history': history, 'history_error': history_error}


def _render_admin_inquiry_detail(detail, return_params, reply_draft='', reply_error=None, status=200):
    inquiry = detail['inquiry']
    order_detail_url = None
    if inquiry.get('order_id'):
        order_params = {'from_inquiry_id': inquiry['id']}
        for key in ('q', 'author', 'inquiry_type', 'status', 'from_date', 'to_date', 'member_id', 'page'):
            order_params[f'inquiry_{key}'] = return_params.get(key, '')
        order_detail_url = url_for('admin.order_detail', order_id=inquiry['order_id'], **order_params)
    return render_template(
        'admin/inquiry_detail.html',
        active_menu='inquiries',
        inquiry=inquiry,
        history=detail['history'],
        history_error=detail['history_error'],
        reply_draft=reply_draft if reply_draft else inquiry.get('reply_text') or '',
        reply_error=reply_error,
        return_params=return_params,
        return_url=url_for('admin.inquiry_list', **return_params),
        member_detail_url=url_for('admin.member_detail', member_id=inquiry['user_id']),
        order_detail_url=order_detail_url,
    ), status


@admin_bp.route('/inquiries', methods=['GET'])
@admin_required
def inquiry_list():
    admin_client = get_supabase_admin_client()
    return_params = _inquiry_return_params(request.args)
    query_text = return_params['q']
    author_text = return_params['author']
    inquiry_type = return_params['inquiry_type']
    status_filter = return_params['status']
    from_date = return_params['from_date']
    to_date = return_params['to_date']
    member_id = return_params['member_id']
    page = return_params['page']

    date_error = None
    start_utc = None
    end_exclusive_utc = None
    try:
        if from_date:
            start_utc = datetime.strptime(from_date, '%Y-%m-%d').replace(
                tzinfo=SEOUL_TIMEZONE
            ).astimezone(timezone.utc).isoformat()
        if to_date:
            end_exclusive_utc = (
                datetime.strptime(to_date, '%Y-%m-%d').replace(tzinfo=SEOUL_TIMEZONE)
                + timedelta(days=1)
            ).astimezone(timezone.utc).isoformat()
        if from_date and to_date and from_date > to_date:
            raise ValueError('기간 시작일은 종료일보다 늦을 수 없습니다.')
    except ValueError as exc:
        date_error = (
            str(exc) if str(exc) == '기간 시작일은 종료일보다 늦을 수 없습니다.'
            else '접수 기간을 확인해주세요.'
        )

    inquiries = []
    total_count = None
    total_pages = 1
    list_error = None

    def build_query():
        query = admin_client.table('admin_customer_inquiries').select(
            ADMIN_INQUIRY_LIST_COLUMNS, count='exact'
        )
        if query_text:
            pattern = _inquiry_search_pattern(query_text)
            query = query.or_(f'title.ilike."{pattern}",content.ilike."{pattern}"')
        if author_text:
            pattern = _inquiry_search_pattern(author_text)
            query = query.or_(
                f'author_name.ilike."{pattern}",author_nickname.ilike."{pattern}",'
                f'user_id_text.ilike."{pattern}"'
            )
        if inquiry_type:
            query = query.eq('inquiry_type', inquiry_type)
        if status_filter:
            query = query.eq('status', status_filter)
        if member_id:
            query = query.eq('user_id', member_id)
        if start_utc:
            query = query.gte('created_at', start_utc)
        if end_exclusive_utc:
            query = query.lt('created_at', end_exclusive_utc)
        return query.order('created_at', desc=status_filter != 'pending').order(
            'id', desc=status_filter != 'pending'
        )

    if not date_error:
        try:
            result = build_query().range(
                (page - 1) * INQUIRY_PAGE_SIZE,
                page * INQUIRY_PAGE_SIZE - 1
            ).execute()
            total_count = result.count
            if total_count is None:
                raise ValueError('정확한 문의 건수를 반환하지 않았습니다.')
            total_pages = max(1, math.ceil(total_count / INQUIRY_PAGE_SIZE))
            if page > total_pages:
                page = total_pages
                result = build_query().range(
                    (page - 1) * INQUIRY_PAGE_SIZE,
                    page * INQUIRY_PAGE_SIZE - 1
                ).execute()
            inquiries = [_format_admin_inquiry(row) for row in (result.data or [])]
        except Exception:
            logger.error('[Admin Inquiries] 문의 목록 조회에 실패했습니다.')
            list_error = '문의 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.'
            total_count = None

    return render_template(
        'admin/inquiries.html',
        active_menu='inquiries',
        inquiries=inquiries,
        query_text=query_text,
        author_text=author_text,
        inquiry_type=inquiry_type,
        inquiry_types=INQUIRY_TYPE_LABELS,
        status_filter=status_filter,
        from_date=from_date,
        to_date=to_date,
        member_id=member_id,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        date_error=date_error,
        list_error=list_error,
    ), 503 if list_error else 200


@admin_bp.route('/inquiries/<inquiry_id>', methods=['GET'])
@admin_required
def inquiry_detail(inquiry_id):
    inquiry_id = _validated_member_id(inquiry_id)
    if not inquiry_id:
        abort(404)
    return_params = _inquiry_return_params(request.args)
    try:
        detail = _load_admin_inquiry_detail(get_supabase_admin_client(), inquiry_id)
        if not detail:
            abort(404)
        return _render_admin_inquiry_detail(detail, return_params)
    except HTTPException:
        raise
    except Exception:
        logger.error('[Admin Inquiries] 문의 상세 조회에 실패했습니다.')
        return render_template(
            'admin/inquiry_detail.html',
            active_menu='inquiries', inquiry=None, history=[],
            history_error=None, reply_draft='', reply_error='문의 내용을 불러오지 못했습니다.',
            return_params=return_params,
            return_url=url_for('admin.inquiry_list', **return_params),
            member_detail_url=None, order_detail_url=None,
        ), 503


@admin_bp.route('/inquiries/<inquiry_id>/reply', methods=['POST'])
@admin_required
def inquiry_reply(inquiry_id):
    inquiry_id = _validated_member_id(inquiry_id)
    if not inquiry_id:
        abort(404)
    admin_client = get_supabase_admin_client()
    return_params = _inquiry_return_params(request.args)
    reply_text = request.form.get('reply_text', '').strip()
    reply_error = None
    response_status = 400
    expected_version = request.form.get('expected_version', '')

    if not reply_text:
        reply_error = '답변 내용을 입력해주세요.'
    elif len(reply_text) > INQUIRY_REPLY_MAX_LENGTH:
        reply_error = f'답변은 {INQUIRY_REPLY_MAX_LENGTH:,}자 이내로 입력해주세요.'
    try:
        expected_version = int(expected_version)
        if expected_version < 0:
            raise ValueError
    except (ValueError, TypeError):
        expected_version = None
        reply_error = '문의 화면을 새로고침한 뒤 답변을 다시 입력해주세요.'

    try:
        detail = _load_admin_inquiry_detail(admin_client, inquiry_id)
        if not detail:
            abort(404)
    except HTTPException:
        raise
    except Exception:
        logger.error('[Admin Inquiries] 답변 저장 전 문의 조회에 실패했습니다.')
        return render_template(
            'admin/inquiry_detail.html',
            active_menu='inquiries', inquiry=None, history=[], history_error=None,
            reply_draft=reply_text, reply_error='문의 정보를 불러오지 못했습니다. 입력한 답변은 유지했습니다.',
            return_params=return_params, return_url=url_for('admin.inquiry_list', **return_params),
            member_detail_url=None, order_detail_url=None,
        ), 503

    if not reply_error:
        try:
            rpc_result = admin_client.rpc('save_customer_inquiry_reply', {
                'p_inquiry_id': inquiry_id,
                'p_admin_id': g.admin_user['id'],
                'p_reply': reply_text,
                'p_expected_version': expected_version,
            }).execute()
            if not rpc_result.data:
                raise ValueError('답변 저장 결과를 반환하지 않았습니다.')
            flash('답변이 저장되어 고객에게 공개되었습니다.', 'success')
            return redirect(url_for('admin.inquiry_detail', inquiry_id=inquiry_id, **return_params))
        except Exception as exc:
            logger.error('[Admin Inquiries] 답변 저장 RPC에 실패했습니다.')
            try:
                latest_detail = _load_admin_inquiry_detail(admin_client, inquiry_id)
                if not latest_detail:
                    abort(404)
                if latest_detail['inquiry'].get('reply_text') == reply_text:
                    flash('답변이 저장되어 고객에게 공개되었습니다.', 'success')
                    return redirect(url_for('admin.inquiry_detail', inquiry_id=inquiry_id, **return_params))
                detail = latest_detail
            except HTTPException:
                raise
            except Exception:
                pass
            if 'inquiry_reply_version_conflict' in str(exc):
                reply_error = '다른 관리자가 답변을 먼저 수정했습니다. 최신 답변을 확인하고 다시 등록해주세요.'
                response_status = 409
            else:
                reply_error = '답변 저장에 실패했습니다. 입력한 내용은 유지했습니다. 잠시 후 다시 시도해주세요.'
                response_status = 503

    detail['inquiry']['form_expected_version'] = detail['inquiry'].get('reply_version') or 0
    return _render_admin_inquiry_detail(
        detail,
        return_params,
        reply_draft=reply_text,
        reply_error=reply_error,
        status=response_status,
    )


# ======================================================================
# 회원 조회 (GET /admin/members, GET /admin/members/<member_id>)
# ======================================================================
MEMBER_DIRECTORY_COLUMNS = (
    'member_id, member_id_text, profile_exists, auth_user_exists, display_name, '
    'nickname, email, phone, account_role, created_at, last_sign_in_at, login_providers'
)
MEMBER_DIRECTORY_LIST_COLUMNS = (
    'member_id, member_id_text, profile_exists, auth_user_exists, display_name, '
    'nickname, email, created_at, login_providers'
)
MEMBER_LOGIN_PROVIDERS = ('email', 'kakao', 'naver')
MEMBER_PAGE_SIZE = 20


def _member_search_pattern(value):
    escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
    escaped = escaped.replace('%', r'\%').replace('_', r'\_')
    return f'%{escaped}%'


def _member_return_params(args):
    try:
        page = max(1, int(args.get('return_page', 1)))
    except (ValueError, TypeError):
        page = 1
    provider = args.get('return_provider', '')
    return {
        'q': args.get('return_q', '')[:100],
        'joined_from': args.get('return_joined_from', ''),
        'joined_to': args.get('return_joined_to', ''),
        'provider': provider if provider in MEMBER_LOGIN_PROVIDERS else '',
        'page': page,
    }


def _validated_member_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return ''


@admin_bp.route('/members', methods=['GET'])
@admin_required
def member_list():
    """프로필 및 연결된 Auth 정보의 관리자 전용 서버 검색·페이지 조회."""
    admin_client = get_supabase_admin_client()
    query_text = request.args.get('q', '').strip()[:100]
    joined_from = request.args.get('joined_from', '').strip()
    joined_to = request.args.get('joined_to', '').strip()
    provider_filter = request.args.get('provider', '').strip().lower()
    if provider_filter not in MEMBER_LOGIN_PROVIDERS:
        provider_filter = ''
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    members = []
    total_count = None
    total_pages = 1
    displayed_count = None
    list_error = None
    date_error = None

    try:
        start_utc = None
        end_exclusive_utc = None
        if joined_from:
            start_utc = datetime.strptime(joined_from, '%Y-%m-%d').replace(
                tzinfo=SEOUL_TIMEZONE
            ).astimezone(timezone.utc).isoformat()
        if joined_to:
            end_exclusive_utc = (
                datetime.strptime(joined_to, '%Y-%m-%d').replace(tzinfo=SEOUL_TIMEZONE)
                + timedelta(days=1)
            ).astimezone(timezone.utc).isoformat()
        if joined_from and joined_to and joined_from > joined_to:
            raise ValueError('가입 기간의 시작일은 종료일보다 늦을 수 없습니다.')
    except ValueError as exc:
        date_error = (
            '가입 기간의 시작일은 종료일보다 늦을 수 없습니다.'
            if str(exc) == '가입 기간의 시작일은 종료일보다 늦을 수 없습니다.'
            else '가입 기간을 확인해주세요.'
        )

    if not date_error:
        try:
            def build_member_query():
                query = admin_client.table('admin_member_directory').select(
                    MEMBER_DIRECTORY_LIST_COLUMNS,
                    count='exact'
                )
                if query_text:
                    pattern = _member_search_pattern(query_text)
                    query = query.or_(
                        f'display_name.ilike."{pattern}",'
                        f'nickname.ilike."{pattern}",'
                        f'email.ilike."{pattern}",'
                        f'member_id_text.ilike."{pattern}"'
                    )
                if start_utc:
                    query = query.gte('created_at', start_utc)
                if end_exclusive_utc:
                    query = query.lt('created_at', end_exclusive_utc)
                if provider_filter:
                    query = query.contains('login_providers', [provider_filter])
                return query.order('created_at', desc=True).order('member_id', desc=True)

            result = build_member_query().range(
                (page - 1) * MEMBER_PAGE_SIZE,
                page * MEMBER_PAGE_SIZE - 1
            ).execute()
            total_count = result.count
            if total_count is None:
                raise ValueError('정확한 회원 검색 건수를 반환하지 않았습니다.')
            total_pages = max(1, math.ceil(total_count / MEMBER_PAGE_SIZE))
            if page > total_pages:
                page = total_pages
                result = build_member_query().range(
                    (page - 1) * MEMBER_PAGE_SIZE,
                    page * MEMBER_PAGE_SIZE - 1
                ).execute()
            members = [format_member_directory_row(row) for row in (result.data or [])]
            displayed_count = len(members)
        except Exception:
            logger.error('[Admin Members] 회원 목록 조회에 실패했습니다.')
            list_error = '회원 목록을 불러오지 못했습니다.'
            total_count = None

    return render_template(
        'admin/members.html',
        active_menu='members',
        members=members,
        query_text=query_text,
        joined_from=joined_from,
        joined_to=joined_to,
        provider_filter=provider_filter,
        provider_options=MEMBER_LOGIN_PROVIDERS,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        displayed_count=displayed_count,
        list_error=list_error,
        date_error=date_error,
    )


@admin_bp.route('/members/<member_id>', methods=['GET'])
@admin_required
def member_detail(member_id):
    """기존 Auth/Profile 연결과 해당 ID의 주문만 읽습니다."""
    member_id = _validated_member_id(member_id)
    if not member_id:
        abort(404)

    admin_client = get_supabase_admin_client()
    return_params = _member_return_params(request.args)
    member = None
    member_error = None
    order_state = 'ready'
    order_error = None
    order_count = None
    order_count_display = None
    recent_orders = []
    order_items_error = False
    member_inquiries = []
    member_inquiry_count = None
    member_inquiries_state = 'ready'
    member_inquiries_error = None

    try:
        member_result = (
            admin_client.table('admin_member_directory')
            .select(MEMBER_DIRECTORY_COLUMNS)
            .eq('member_id', member_id)
            .limit(1)
            .execute()
        )
        if not member_result.data:
            return render_template(
                'admin/member_detail.html',
                active_menu='members', member=None, member_error=None,
                order_state='unavailable', order_error=None, order_count=None,
                order_count_display=None, recent_orders=[], order_items_error=False,
                member_list_url=url_for('admin.member_list', **return_params),
            ), 404
        member = format_member_directory_row(member_result.data[0])
    except Exception:
        logger.error('[Admin Members] 회원 기본정보 조회에 실패했습니다.')
        member_error = '회원 기본정보를 불러오지 못했습니다.'

    if member:
        try:
            orders_result = (
                admin_client.table('orders')
                .select('id, order_number, status, created_at, total_amount', count='exact')
                .eq('user_id', member_id)
                .order('created_at', desc=True)
                .order('id', desc=True)
                .limit(5)
                .execute()
            )
            order_count = orders_result.count
            if order_count is None:
                raise ValueError('정확한 주문 건수를 반환하지 않았습니다.')
            order_count_display = order_count
            recent_orders = orders_result.data or []

            if recent_orders:
                order_ids = [order['id'] for order in recent_orders]
                try:
                    order_items_result = (
                        admin_client.table('order_items')
                        .select('order_id, product_name')
                        .in_('order_id', order_ids)
                        .order('id')
                        .execute()
                    )
                    items_by_order = {}
                    for item in order_items_result.data or []:
                        items_by_order.setdefault(item['order_id'], []).append(item.get('product_name') or '상품명 미등록')
                except Exception:
                    logger.error('[Admin Members] 회원 주문 상품 요약 조회에 실패했습니다.')
                    items_by_order = {}
                    order_items_error = True

                payment_labels = {
                    'PAID': '결제 완료', 'PREPARING': '결제 완료', 'SHIPPING': '결제 완료',
                    'DELIVERED': '결제 완료', 'CANCELLED': '결제 취소',
                    'PENDING': '입금 대기', 'PENDING_PAYMENT': '입금 대기',
                }
                delivery_labels = {
                    'PAID': '미발송', 'PREPARING': '배송 준비 중', 'SHIPPING': '배송 중',
                    'DELIVERED': '배송 완료', 'CANCELLED': '배송 중단',
                    'PENDING': '결제 대기', 'PENDING_PAYMENT': '결제 대기',
                }
                for order in recent_orders:
                    status = str(order.get('status') or '').upper()
                    names = items_by_order.get(order['id'], [])
                    if order_items_error:
                        order['summary_title'] = '상품 정보 조회 실패'
                    elif names:
                        order['summary_title'] = f'{names[0]} 외 {len(names) - 1}건' if len(names) > 1 else names[0]
                    else:
                        order['summary_title'] = '상품 정보 없음'
                    order['created_at_display'] = format_seoul_datetime(order.get('created_at'))
                    order['payment_status_display'] = payment_labels.get(status, '확인 가능한 상태 없음')
                    order['delivery_status_display'] = delivery_labels.get(status, '확인 가능한 상태 없음')
        except Exception:
            logger.error('[Admin Members] 회원 주문 내역 조회에 실패했습니다.')
            order_state = 'error'
            order_error = '주문 내역을 불러오지 못했습니다.'
            order_count = None
            order_count_display = None

        try:
            inquiries_result = (
                admin_client.table('customer_inquiries')
                .select(
                    'id, inquiry_number, inquiry_type, title, status, created_at',
                    count='exact'
                )
                .eq('user_id', member_id)
                .order('created_at', desc=True)
                .limit(5)
                .execute()
            )
            member_inquiry_count = inquiries_result.count
            if member_inquiry_count is None:
                raise ValueError('정확한 회원 문의 건수를 반환하지 않았습니다.')
            member_inquiries = [
                _format_admin_inquiry(row) for row in (inquiries_result.data or [])
            ]
        except Exception:
            logger.error('[Admin Members] 회원 문의 내역 조회에 실패했습니다.')
            member_inquiries_state = 'error'
            member_inquiries_error = '회원 문의 내역을 불러오지 못했습니다.'
            member_inquiry_count = None

    return render_template(
        'admin/member_detail.html',
        active_menu='members',
        member=member,
        member_error=member_error,
        order_state=order_state,
        order_error=order_error,
        order_count=order_count,
        order_count_display=order_count_display,
        recent_orders=recent_orders,
        order_items_error=order_items_error,
        member_list_url=url_for('admin.member_list', **return_params),
        member_order_url=url_for('admin.order_list', member_id=member_id),
        member_inquiries=member_inquiries,
        member_inquiry_count=member_inquiry_count,
        member_inquiries_state=member_inquiries_state,
        member_inquiries_error=member_inquiries_error,
        member_inquiry_list_url=url_for('admin.inquiry_list', member_id=member_id),
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
# [6] 주문·배송 관리: 목록 및 검색/필터 (GET /admin/orders)
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
    'PAID': '미처리 (결제 완료)',
    'PREPARING': '배송 준비 중',
    'SHIPPING': '발송 완료 (배송 중)',
    'DELIVERED': '배송 완료',
    'CANCELLED': '주문 취소'
}

# 검증된 국내 주요 택배사 목록 및 배송조회 공식 템플릿
SUPPORTED_CARRIERS = {
    'CJ대한통운': {
        'name': 'CJ대한통운',
        'tracking_url': 'https://www.doortodoor.co.kr/parcel/doortodoor.do?fsp_action=PARC_ACT_002&fsp_cmd=retrieveInvNoACT&invc_no={tracking_number}'
    },
    '우체국택배': {
        'name': '우체국택배',
        'tracking_url': 'https://service.epost.go.kr/trace.RetrieveDomRcvTraceList.comm?sid1={tracking_number}'
    },
    '한진택배': {
        'name': '한진택배',
        'tracking_url': 'https://www.hanjin.com/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038&wblnum={tracking_number}&schLang=KR'
    },
    '롯데택배': {
        'name': '롯데택배',
        'tracking_url': 'https://www.lotteglogis.com/home/reservation/tracking/linkView?InvNo={tracking_number}'
    },
    '로젠택배': {
        'name': '로젠택배',
        'tracking_url': 'https://www.ilogen.com/web/personal/trace/{tracking_number}'
    }
}


@admin_bp.route('/orders', methods=['GET'])
@admin_required
def order_list():
    """
    주문·배송 관리 목록:
    - 상단 요약 카드: 미처리(PAID), 배송 준비 중(PREPARING), 발송 후 배송 완료 전(SHIPPING), 취소(CANCELLED)
    - 검색: 주문번호, 주문자(수령인), 상품명
    - 기간 필터: 전체/오늘/7일/30일
    - 상태 필터: 전체/미처리/배송준비/발송완료(배송중)/배송완료/취소
    - 페이지네이션 (10건) 및 조건 유지
    """
    admin_client = get_supabase_admin_client()

    query_text = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '').strip().upper()
    period_filter = request.args.get('period', '').strip().lower()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 10

    work_task = request.args.get('task', '').strip().lower()
    if work_task in ('unshipped', 'refunds'):
        view_name = 'admin_unshipped_orders' if work_task == 'unshipped' else 'admin_pending_refund_orders'
        view_columns = 'id, order_number, status, created_at' if work_task == 'unshipped' else 'id, order_number, order_status, requested_at, refund_status'
        time_column = 'created_at' if work_task == 'unshipped' else 'requested_at'

        try:
            task_result = (
                admin_client.table(view_name)
                .select(view_columns, count='exact')
                .order(time_column)
                .range((page - 1) * per_page, page * per_page - 1)
                .execute()
            )
            total_count = task_result.count
            if total_count is None:
                raise ValueError('정확한 업무 건수를 반환하지 않았습니다.')
            task_rows = task_result.data or []
            order_ids = [row['id'] for row in task_rows]

            orders_by_id = {}
            items_by_order = {}
            if order_ids:
                orders_result = (
                    admin_client.table('orders')
                    .select('id, order_number, status, created_at, payment_amount, total_amount')
                    .in_('id', order_ids)
                    .execute()
                )
                orders_by_id = {row['id']: row for row in (orders_result.data or [])}
                items_result = (
                    admin_client.table('order_items')
                    .select('order_id, product_name, quantity')
                    .in_('order_id', order_ids)
                    .execute()
                )
                for item in items_result.data or []:
                    items_by_order.setdefault(item['order_id'], []).append(item)

            orders = []
            for task_row in task_rows:
                order = orders_by_id.get(task_row['id'])
                if not order:
                    raise ValueError('업무 view와 주문 데이터가 일치하지 않습니다.')
                order = {**order, 'status': order.get('status') or task_row.get('status') or task_row.get('order_status')}
                if work_task == 'refunds':
                    order['refund_status'] = task_row.get('refund_status')
                order_items_for_order = items_by_order.get(order['id'], [])
                if order_items_for_order:
                    first_name = order_items_for_order[0].get('product_name') or '주문 상품'
                    extra = len(order_items_for_order) - 1
                    order['summary_title'] = f"{first_name} 외 {extra}건" if extra > 0 else first_name
                    order['total_item_count'] = sum(item.get('quantity') or 1 for item in order_items_for_order)
                else:
                    order['summary_title'] = '주문 상품 1건'
                    order['total_item_count'] = 1
                orders.append(order)

            total_pages = max(1, math.ceil(total_count / per_page))
            db_error = None
        except Exception:
            logger.error('[Admin Order Task List] 업무 주문 목록 조회에 실패했습니다.')
            orders = []
            total_count = None
            total_pages = 1
            db_error = '업무 목록을 불러오지 못했습니다. 새로고침 후 다시 시도해주세요.'

        return render_template(
            'admin/orders.html',
            active_menu='orders',
            orders=orders,
            metrics={'unprocessed': 0, 'preparing': 0, 'in_transit': 0, 'cancelled': 0, 'total': 0},
            query_text='',
            status_filter='',
            period_filter='',
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            status_labels=STATUS_LABELS,
            db_error=db_error,
            work_task=work_task
        )

    member_filter_id = request.args.get('member_id', '').strip()
    if member_filter_id:
        try:
            member_filter_id = str(uuid.UUID(member_filter_id))
        except (ValueError, TypeError, AttributeError):
            abort(404)

        try:
            member_lookup = (
                admin_client.table('admin_member_directory')
                .select('member_id, display_name')
                .eq('member_id', member_filter_id)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.error('[Admin Orders] 회원 주문 필터의 회원 확인에 실패했습니다.')
            return render_template(
                'admin/orders.html', active_menu='orders', orders=[],
                metrics={}, query_text='', status_filter='', period_filter='',
                page=page, total_pages=1, total_count=None, status_labels=STATUS_LABELS,
                db_error='회원 주문을 확인하지 못했습니다. 다시 시도해주세요.',
                member_filter_id=member_filter_id, member_filter_name=''
            ), 503
        if not member_lookup.data:
            abort(404)

        member_filter_name = member_lookup.data[0].get('display_name') or f'이름 미등록 · {member_filter_id[:8]}'
        try:
            member_orders_result = (
                admin_client.table('orders')
                .select(
                    'id, order_number, user_id, status, created_at, total_amount, recipient_name',
                    count='exact'
                )
                .eq('user_id', member_filter_id)
                .order('created_at', desc=True)
                .order('id', desc=True)
                .range((page - 1) * per_page, page * per_page - 1)
                .execute()
            )
            total_count = member_orders_result.count
            if total_count is None:
                raise ValueError('정확한 회원 주문 건수를 반환하지 않았습니다.')
            total_pages = max(1, math.ceil(total_count / per_page))
            orders = member_orders_result.data or []
            if orders:
                order_ids = [order['id'] for order in orders]
                try:
                    items_result = (
                        admin_client.table('order_items')
                        .select('order_id, product_name, quantity')
                        .in_('order_id', order_ids)
                        .execute()
                    )
                    items_by_order = {}
                    for item in items_result.data or []:
                        items_by_order.setdefault(item['order_id'], []).append(item)
                except Exception:
                    logger.error('[Admin Orders] 회원 주문 상품 조회에 실패했습니다.')
                    items_by_order = {}

                for order in orders:
                    order_items_for_order = items_by_order.get(order['id'], [])
                    if order_items_for_order:
                        first_name = order_items_for_order[0].get('product_name') or '상품명 미등록'
                        extra = len(order_items_for_order) - 1
                        order['summary_title'] = f'{first_name} 외 {extra}건' if extra else first_name
                        order['total_item_count'] = sum(item.get('quantity') or 1 for item in order_items_for_order)
                    else:
                        order['summary_title'] = '상품 정보 없음'
                        order['total_item_count'] = 0
            db_error = None
        except Exception:
            logger.error('[Admin Orders] 회원 주문 목록 조회에 실패했습니다.')
            orders = []
            total_count = None
            total_pages = 1
            db_error = '회원 주문 내역을 불러오지 못했습니다.'

        return render_template(
            'admin/orders.html', active_menu='orders', orders=orders,
            metrics={}, query_text='', status_filter='', period_filter='',
            page=page, total_pages=total_pages, total_count=total_count,
            status_labels=STATUS_LABELS, db_error=db_error,
            member_filter_id=member_filter_id, member_filter_name=member_filter_name
        )

    orders = []
    total_count = 0
    total_pages = 1
    db_error = None

    metrics = {
        'unprocessed': 0,      # 미처리 (PAID)
        'preparing': 0,        # 배송 준비 중 (PREPARING)
        'in_transit': 0,       # 발송 후 배송 완료 전 (SHIPPING)
        'cancelled': 0,        # 취소 (CANCELLED)
        'total': 0
    }

    try:
        ord_res = admin_client.table('orders').select('*').order('created_at', desc=True).execute()
        all_orders = ord_res.data or []
        metrics['total'] = len(all_orders)

        # 상단 요약 카운트 집계 (전체 기간 실데이터 기준)
        for o in all_orders:
            st = str(o.get('status') or '').upper()
            if st == 'PAID':
                metrics['unprocessed'] += 1
            elif st == 'PREPARING':
                metrics['preparing'] += 1
            elif st == 'SHIPPING':
                metrics['in_transit'] += 1
            elif st == 'CANCELLED':
                metrics['cancelled'] += 1

        # 기간 필터링 기준 시간 계산
        period_cutoff = None
        now_ts = datetime.now(timezone.utc)
        if period_filter == 'today':
            period_cutoff = datetime(now_ts.year, now_ts.month, now_ts.day, tzinfo=timezone.utc)
        elif period_filter == 'week':
            period_cutoff = now_ts.timestamp() - (7 * 86400)
        elif period_filter == 'month':
            period_cutoff = now_ts.timestamp() - (30 * 86400)

        # 주문 상품 매핑을 위해 order_items 미리 수집
        all_order_ids = [o['id'] for o in all_orders]
        items_by_order = {}
        if all_order_ids:
            items_res = admin_client.table('order_items').select('order_id, product_name, quantity').in_('order_id', all_order_ids).execute()
            for it in (items_res.data or []):
                oid = it['order_id']
                items_by_order.setdefault(oid, []).append(it)

        filtered = []
        for o in all_orders:
            oid = o['id']
            its = items_by_order.get(oid, [])
            product_names = [it.get('product_name', '') for it in its]

            # 1. 기간 필터
            if period_cutoff:
                c_str = o.get('created_at') or ''
                try:
                    c_dt = datetime.fromisoformat(c_str.replace('Z', '+00:00'))
                    if isinstance(period_cutoff, datetime):
                        if c_dt < period_cutoff:
                            continue
                    else:
                        if c_dt.timestamp() < period_cutoff:
                            continue
                except Exception:
                    pass

            # 2. 검색어 필터 (주문번호, 수령인, 주문 상품명)
            if query_text:
                q_lower = query_text.lower()
                num_match = q_lower in (o.get('order_number') or '').lower()
                name_match = q_lower in (o.get('recipient_name') or '').lower()
                prod_match = any(q_lower in p.lower() for p in product_names)
                if not (num_match or name_match or prod_match):
                    continue

            # 3. 상태 필터
            if status_filter and status_filter != 'ALL':
                if str(o.get('status') or '').upper() != status_filter:
                    continue

            filtered.append(o)

        total_count = len(filtered)
        total_pages = max(1, math.ceil(total_count / per_page))
        start_idx = (page - 1) * per_page
        orders = filtered[start_idx:start_idx + per_page]

        # 각 주문별 대표 상품명 및 수량 정보 연결
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
        metrics=metrics,
        query_text=query_text,
        status_filter=status_filter,
        period_filter=period_filter,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        status_labels=STATUS_LABELS,
        db_error=db_error
    )


# ==============================================================================
# [7] 주문 상세 및 배송/상태 관리 (GET /admin/orders/<id>)
# ==============================================================================
@admin_bp.route('/orders/<order_id>', methods=['GET'])
@admin_required
def order_detail(order_id):
    """
    주문 상세 조회:
    - 주문 정보, 결제 금액, 배송지 정보, 주문 당시 상품 스냅샷(order_items)
    - 택배사, 송장번호, 배송추적 공식 링크
    - 주문 처리 이력(order_logs) 시간순 조회
    """
    admin_client = get_supabase_admin_client()

    try:
        ord_res = admin_client.table('orders').select('*').eq('id', order_id).execute()
        if not ord_res.data:
            flash('주문 정보를 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.order_list'))

        order = ord_res.data[0]
        cur_status = str(order.get('status') or '').upper()

        refunds_res = (
            admin_client.table('refunds')
            .select('id, refund_amount, reason, status, admin_note, created_at, updated_at')
            .eq('order_id', order_id)
            .order('created_at', desc=True)
            .execute()
        )
        refunds = refunds_res.data or []

        # 주문 상품 상세 조회 (주문 시점 스냅샷 그대로 노출)
        items_res = admin_client.table('order_items').select('*').eq('order_id', order_id).order('id').execute()
        order_items = items_res.data or []

        # 허용되는 전환 상태 목록
        allowed_next_statuses = ALLOWED_TRANSITIONS.get(cur_status, [])

        # 택배 배송추적 공식 URL 생성
        tracking_link = None
        raw_tracking = str(order.get('tracking_number') or '').strip()
        carrier_name = ''

        if raw_tracking:
            # "택배사 송장번호" 또는 송장번호 형태 분리
            parts = raw_tracking.split(maxsplit=1)
            if len(parts) == 2 and parts[0] in SUPPORTED_CARRIERS:
                carrier_name = parts[0]
                pure_no = parts[1]
            else:
                pure_no = raw_tracking

            if carrier_name and carrier_name in SUPPORTED_CARRIERS:
                tpl = SUPPORTED_CARRIERS[carrier_name]['tracking_url']
                tracking_link = tpl.replace('{tracking_number}', pure_no)

        # 주문 처리 이력(order_logs) 조회 (시간순)
        logs = []
        try:
            logs_res = admin_client.table('order_logs').select('*').eq('order_id', order_id).order('created_at', desc=True).execute()
            logs = logs_res.data or []
        except Exception as log_err:
            logger.warning(f"[Order Logs Fetch Warning] {log_err}")

        # 결제 상태 및 배송 상태 분리 표시
        # 결제 상태: PAID, PREPARING, SHIPPING, DELIVERED는 '결제 완료' / CANCELLED는 '결제 취소' / PENDING은 '입금 대기'
        if cur_status in ('PAID', 'PREPARING', 'SHIPPING', 'DELIVERED'):
            payment_status_label = '결제 완료'
            payment_badge_class = 'badge bg-success'
        elif cur_status == 'CANCELLED':
            payment_status_label = '결제 취소'
            payment_badge_class = 'badge bg-danger'
        else:
            payment_status_label = '입금 대기'
            payment_badge_class = 'badge bg-secondary'

        # 배송 상태 레이블
        delivery_status_map = {
            'PAID': ('미처리 (배송 대기)', 'badge bg-primary'),
            'PREPARING': ('배송 준비 중', 'badge bg-warning text-dark'),
            'SHIPPING': ('발송 완료 (배송 중)', 'badge bg-info text-dark'),
            'DELIVERED': ('배송 완료', 'badge bg-success'),
            'CANCELLED': ('주문 취소 (배송 중단)', 'badge bg-secondary'),
            'PENDING_PAYMENT': ('입금 확인 대기', 'badge bg-light text-dark border')
        }
        delivery_label, delivery_badge_class = delivery_status_map.get(cur_status, (cur_status, 'badge bg-secondary'))

        return render_template(
            'admin/order_detail.html',
            active_menu='orders',
            order=order,
            order_items=order_items,
            cur_status=cur_status,
            allowed_next_statuses=allowed_next_statuses,
            status_labels=STATUS_LABELS,
            supported_carriers=SUPPORTED_CARRIERS,
            carrier_name=carrier_name,
            pure_tracking_number=pure_no if raw_tracking else '',
            tracking_link=tracking_link,
            payment_status_label=payment_status_label,
            payment_badge_class=payment_badge_class,
            delivery_label=delivery_label,
            delivery_badge_class=delivery_badge_class,
            order_logs=logs,
            refunds=refunds,
            from_task=request.args.get('from_task', ''),
            from_member_id=_validated_member_id(request.args.get('from_member_id', '')),
            inquiry_return_url=(
                url_for(
                    'admin.inquiry_detail',
                    inquiry_id=_validated_member_id(request.args.get('from_inquiry_id', '')),
                    **{
                        key: request.args.get(f'inquiry_{key}', '')
                        for key in ('q', 'author', 'inquiry_type', 'status', 'from_date', 'to_date', 'member_id', 'page')
                    }
                )
                if _validated_member_id(request.args.get('from_inquiry_id', '')) else None
            )
        )

    except Exception as e:
        logger.error(f"[Admin Order Detail Error] {e}", exc_info=True)
        flash('주문 상세 정보를 불러오는 중 오류가 발생했습니다.', 'danger')
        return redirect(url_for('admin.order_list'))


@admin_bp.route('/orders/<order_id>/refunds/<refund_id>/review', methods=['POST'])
@admin_required
def order_refund_review(order_id, refund_id):
    """기존 환불 요청의 관리자 검토 상태를 승인 또는 거절로 기록합니다."""
    new_status = request.form.get('status', '').strip().lower()
    if new_status not in {'approved', 'rejected'}:
        abort(400, description='지원하지 않는 환불 검토 상태입니다.')

    admin_client = get_supabase_admin_client()
    try:
        result = (
            admin_client.table('refunds')
            .update({'status': new_status, 'updated_at': datetime.now(timezone.utc).isoformat()})
            .eq('id', refund_id)
            .eq('order_id', order_id)
            .eq('status', 'requested')
            .select('id')
            .execute()
        )
        if not result.data:
            flash('요청이 이미 처리되었거나 찾을 수 없습니다. 최신 상태를 확인해주세요.', 'warning')
        elif new_status == 'approved':
            flash('환불 요청을 승인 상태로 기록했습니다. 실제 환불 금액 처리는 결제사에서 별도로 진행해야 합니다.', 'success')
        else:
            flash('환불 요청을 거절 상태로 기록했습니다.', 'success')
    except Exception:
        logger.error('[Admin Refund Review] 환불 요청 상태 변경에 실패했습니다.')
        flash('환불 검토 상태를 저장하지 못했습니다.', 'danger')

    return redirect(url_for('admin.order_detail', order_id=order_id, from_task=request.form.get('from_task', '')))


@admin_bp.route('/orders/<order_id>/status', methods=['POST'])
@admin_required
def order_update_status(order_id):
    """
    주문·배송 상태 변경 및 송장번호 등록/수정 (POST 전용, CSRF 검증)
    - 발송 처리(SHIPPING) 시 택배사와 송장번호 필수 입력
    - 송장번호는 문자열(text)로 저장하여 앞자리 0 보존
    - 취소 처리(CANCELLED) 시 기차감된 재고 복원 (중복 복원 방지)
    - 상태 변경 및 배송 변경 이력을 order_logs에 기록
    """
    admin_client = get_supabase_admin_client()

    new_status = request.form.get('status', '').strip().upper()
    carrier = request.form.get('carrier', '').strip()
    tracking_number = request.form.get('tracking_number', '').strip()
    reason = request.form.get('reason', '').strip()

    try:
        ord_res = admin_client.table('orders').select('*').eq('id', order_id).execute()
        if not ord_res.data:
            flash('주문 정보를 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.order_list'))

        order = ord_res.data[0]
        cur_status = str(order.get('status') or '').upper()

        # 1. 전환 가능 여부 검증
        allowed = ALLOWED_TRANSITIONS.get(cur_status, [])
        if new_status and new_status != cur_status and new_status not in allowed:
            flash(f"현재 상태({STATUS_LABELS.get(cur_status, cur_status)})에서는 선택하신 상태({STATUS_LABELS.get(new_status, new_status)})로 전환할 수 없습니다.", 'danger')
            return redirect(url_for('admin.order_detail', order_id=order_id))

        target_status = new_status if new_status else cur_status

        # 2. 발송 처리(SHIPPING) 시 필수값 검증 (택배사 및 송장번호 필수)
        if target_status == 'SHIPPING':
            if not carrier:
                flash('발송 처리(배송 중) 시 택배사를 반드시 선택해주세요.', 'danger')
                return redirect(url_for('admin.order_detail', order_id=order_id))
            if not tracking_number:
                flash('발송 처리(배송 중) 시 송장번호를 반드시 입력해주세요.', 'danger')
                return redirect(url_for('admin.order_detail', order_id=order_id))

        # 송장번호 포맷팅 (앞자리 0 보존 문자열)
        formatted_tracking = order.get('tracking_number') or ''
        action_type = 'STATUS_CHANGE'
        if carrier and tracking_number:
            formatted_tracking = f"{carrier} {tracking_number}"
            if target_status == 'SHIPPING' and cur_status != 'SHIPPING':
                action_type = 'SHIPPING_START'
            elif cur_status == 'SHIPPING':
                action_type = 'TRACKING_UPDATE'

        if target_status == 'DELIVERED':
            action_type = 'MANUAL_DELIVERY'

        if target_status == 'CANCELLED':
            action_type = 'CANCEL'
            if not reason:
                flash('주문 취소 시 취소 사유를 반드시 입력해주세요.', 'danger')
                return redirect(url_for('admin.order_detail', order_id=order_id))

        # 3. 취소(CANCELLED) 처리 시 재고 복원 (이미 취소된 주문이 아닐 때 1회만 복원)
        if target_status == 'CANCELLED' and cur_status != 'CANCELLED':
            # 주문 상품 목록 조회
            items_res = admin_client.table('order_items').select('product_id, option_id, quantity').eq('order_id', order_id).execute()
            for it in (items_res.data or []):
                qty = int(it.get('quantity') or 0)
                oid = it.get('option_id')
                pid = it.get('product_id')

                if oid and qty > 0:
                    try:
                        admin_client.rpc('restore_product_option_stock', {'p_option_id': oid, 'p_quantity': qty}).execute()
                    except Exception:
                        try:
                            # 폴백: option 직접 증액
                            cur_opt = admin_client.table('product_options').select('stock').eq('id', oid).execute()
                            if cur_opt.data:
                                cur_stk = int(cur_opt.data[0].get('stock') or 0)
                                admin_client.table('product_options').update({'stock': cur_stk + qty}).eq('id', oid).execute()
                        except Exception as e_opt:
                            logger.error(f"[Cancel Option Stock Restore Error] {e_opt}")
                elif pid and qty > 0:
                    try:
                        admin_client.rpc('restore_product_stock', {'p_product_id': pid, 'p_quantity': qty}).execute()
                    except Exception:
                        try:
                            cur_prod = admin_client.table('products').select('stock').eq('id', pid).execute()
                            if cur_prod.data:
                                cur_stk = int(cur_prod.data[0].get('stock') or 0)
                                admin_client.table('products').update({'stock': cur_stk + qty}).eq('id', pid).execute()
                        except Exception as e_prod:
                            logger.error(f"[Cancel Product Stock Restore Error] {e_prod}")

        # 4. orders 테이블 업데이트
        update_payload = {
            'status': target_status,
            'tracking_number': formatted_tracking,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        admin_client.table('orders').update(update_payload).eq('id', order_id).execute()

        # 5. order_logs 이력 테이블 기록
        current_admin = getattr(g, 'admin_user', {})
        log_payload = {
            'order_id': order_id,
            'previous_status': cur_status,
            'new_status': target_status,
            'carrier': carrier or None,
            'tracking_number': tracking_number or None,
            'action_type': action_type,
            'reason': reason or ('배송 정보 등록 및 발송 처리' if action_type == 'SHIPPING_START' else '관리자 상태 변경'),
            'actor_id': current_admin.get('id'),
            'actor_email': current_admin.get('email'),
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        try:
            admin_client.table('order_logs').insert(log_payload).execute()
        except Exception as log_err:
            logger.warning(f"[Order Log Insert Warning] {log_err}")

        flash(f"주문({order.get('order_number')}) 처리가 정상 반영되었습니다. (상태: {STATUS_LABELS.get(target_status, target_status)})", 'success')

    except Exception as e:
        logger.error(f"[Admin Order Status Update Error] {e}", exc_info=True)
        flash(f"주문 처리 중 오류가 발생했습니다: {e}", 'danger')

    return redirect(url_for('admin.order_detail', order_id=order_id))


# ==============================================================================
# [8] 재고 관리: 목록 및 요약 현황 (GET /admin/inventory)
# ==============================================================================
@admin_bp.route('/inventory', methods=['GET'])
@admin_required
def inventory_list():
    """
    실제 데이터 기반 재고 관리 목록:
    - 옵션 보유 상품: 각 색상·사이즈 옵션 단위로 재고 관리
    - 단일 상품: 상품 단위로 재고 관리
    - 요약 카드: 총 관리 항목 수, 재고 부족 항목 수(5개 이하), 품절 항목 수(0개)
    - 검색: 상품명, 슬러그(상품코드)
    - 필터: 카테고리, 상태(전체/정상/부족/품절)
    - 페이지네이션 (페이지당 15개)
    """
    admin_client = get_supabase_admin_client()

    query_text = request.args.get('q', '').strip()
    category_id = request.args.get('category', '').strip()
    status_filter = request.args.get('status', '').strip().lower()

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 15

    work_task = request.args.get('task', '').strip().lower()
    if work_task in ('out_of_stock', 'low_stock'):
        task_query = (
            admin_client.table('admin_active_inventory_items')
            .select(
                'target_type, target_id, product_id, product_name, slug, thumbnail_url, '
                'category_id, category_name, option_id, option_info, stock',
                count='exact'
            )
        )
        if work_task == 'out_of_stock':
            task_query = task_query.eq('stock', 0).order('product_name')
            status_filter = 'out_of_stock'
        else:
            task_query = task_query.gte('stock', 1).lte('stock', LOW_STOCK_THRESHOLD).order('stock').order('product_name')
            status_filter = 'low'

        try:
            result = task_query.range((page - 1) * per_page, page * per_page - 1).execute()
            total_count = result.count
            if total_count is None:
                raise ValueError('정확한 재고 건수를 반환하지 않았습니다.')
            items = result.data or []
            total_pages = max(1, math.ceil(total_count / per_page))
            db_error = None
        except Exception:
            logger.error('[Admin Inventory Task List] 업무 재고 목록 조회에 실패했습니다.')
            total_count = None
            total_pages = 1
            items = []
            db_error = '업무 목록을 불러오지 못했습니다. 새로고침 후 다시 시도해주세요.'

        return render_template(
            'admin/inventory.html',
            active_menu='inventory',
            items=items,
            categories=[],
            metrics={
                'total_items': 0,
                'low_stock_items': 0,
                'out_of_stock_items': 0,
                'threshold': LOW_STOCK_THRESHOLD
            },
            query_text='',
            category_id='',
            status_filter=status_filter,
            page=page,
            total_pages=total_pages,
            total_count=total_count,
            db_error=db_error,
            work_task=work_task
        )

    categories = []
    items = []
    total_count = 0
    total_pages = 1
    db_error = None

    metrics = {
        'total_items': 0,
        'low_stock_items': 0,
        'out_of_stock_items': 0,
        'threshold': LOW_STOCK_THRESHOLD
    }

    try:
        # 카테고리 목록 조회
        cat_res = admin_client.table('categories').select('id, name, slug').order('sort_order').execute()
        categories = cat_res.data or []
        cat_map = {c.get('id'): (c.get('name') or '미지정') for c in categories if isinstance(c, dict)}

        # 전체 상품 조회
        prods_res = admin_client.table('products').select(
            'id, category_id, name, slug, price, sale_price, stock, is_active, thumbnail_url, created_at'
        ).order('created_at', desc=True).execute()
        all_prods = prods_res.data or []

        # 전체 옵션 조회
        opts_res = admin_client.table('product_options').select(
            'id, product_id, color, size, stock, additional_price, option_name, option_value'
        ).order('id').execute()
        all_opts = opts_res.data or []

        # 상품별 옵션 그룹화
        opts_by_product = {}
        for opt in all_opts:
            if isinstance(opt, dict) and opt.get('product_id'):
                pid = opt['product_id']
                opts_by_product.setdefault(pid, []).append(opt)

        # 전체 재고 항목 구성 (옵션 우선, 없으면 상품 단일 단위)
        all_inventory_items = []
        for prod in all_prods:
            if not isinstance(prod, dict) or not prod.get('id'):
                continue
            pid = prod['id']
            p_opts = opts_by_product.get(pid, [])
            c_name = cat_map.get(prod.get('category_id'), '미지정')

            if p_opts:
                for opt in p_opts:
                    c = opt.get('color') or ''
                    s = opt.get('size') or ''
                    if c and s:
                        opt_label = f"{c} / {s}"
                    elif c or s:
                        opt_label = c or s
                    else:
                        opt_label = opt.get('option_value') or '옵션'

                    cur_stock = int(opt.get('stock') if opt.get('stock') is not None else 0)

                    all_inventory_items.append({
                        'target_type': 'option',
                        'target_id': opt.get('id'),
                        'product_id': pid,
                        'product_name': prod.get('name') or '상품',
                        'slug': prod.get('slug') or '',
                        'thumbnail_url': prod.get('thumbnail_url'),
                        'category_id': prod.get('category_id'),
                        'category_name': c_name,
                        'option_id': opt.get('id'),
                        'option_info': opt_label,
                        'color': c,
                        'size': s,
                        'stock': cur_stock,
                        'is_active': prod.get('is_active', True)
                    })
            else:
                cur_stock = int(prod.get('stock') if prod.get('stock') is not None else 0)
                all_inventory_items.append({
                    'target_type': 'product',
                    'target_id': pid,
                    'product_id': pid,
                    'product_name': prod.get('name') or '상품',
                    'slug': prod.get('slug') or '',
                    'thumbnail_url': prod.get('thumbnail_url'),
                    'category_id': prod.get('category_id'),
                    'category_name': c_name,
                    'option_id': None,
                    'option_info': '단일 상품 (옵션 없음)',
                    'color': '',
                    'size': '',
                    'stock': cur_stock,
                    'is_active': prod.get('is_active', True)
                })

        # 요약 카드 수치 집계 (전체 항목 대상)
        metrics['total_items'] = len(all_inventory_items)
        for it in all_inventory_items:
            stk = it['stock']
            if stk <= 0:
                metrics['out_of_stock_items'] += 1
            elif stk <= LOW_STOCK_THRESHOLD:
                metrics['low_stock_items'] += 1

        # 검색 및 필터링 적용
        filtered = []
        for it in all_inventory_items:
            # 검색어 필터 (상품명 또는 슬러그)
            if query_text:
                q_lower = query_text.lower()
                name_match = q_lower in it['product_name'].lower()
                slug_match = q_lower in it['slug'].lower()
                opt_match = q_lower in it['option_info'].lower()
                if not (name_match or slug_match or opt_match):
                    continue

            # 카테고리 필터
            if category_id:
                if str(it.get('category_id')) != str(category_id):
                    continue

            # 상태 필터
            stk = it['stock']
            if status_filter == 'normal' and (stk <= LOW_STOCK_THRESHOLD):
                continue
            elif status_filter == 'low' and (stk <= 0 or stk > LOW_STOCK_THRESHOLD):
                continue
            elif status_filter == 'out_of_stock' and (stk > 0):
                continue

            filtered.append(it)

        total_count = len(filtered)
        total_pages = max(1, math.ceil(total_count / per_page))
        start_idx = (page - 1) * per_page
        items = filtered[start_idx:start_idx + per_page]

    except Exception as e:
        logger.error(f"[Admin Inventory List Error] {e}", exc_info=True)
        db_error = "재고 목록을 불러오는 중 오류가 발생했습니다."

    return render_template(
        'admin/inventory.html',
        active_menu='inventory',
        items=items,
        categories=categories,
        metrics=metrics,
        query_text=query_text,
        category_id=category_id,
        status_filter=status_filter,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        db_error=db_error
    )


# ==============================================================================
# [9] 재고 조정 처리 (POST /admin/inventory/adjust)
# ==============================================================================
@admin_bp.route('/inventory/adjust', methods=['POST'])
@admin_required
def inventory_adjust():
    """
    재고 조정 기능:
    - 입고(IN): 수량 증가 (1 이상)
    - 출고(OUT): 수량 감소 (1 이상, 음수 방지)
    - 실사 조정(ADJUST): 최종 수량 지정 (0 이상)
    - 사유 필수 검증
    - 낙관적 락(expected_stock 검증): 동시 수정 시 충돌 감지 및 알림
    - inventory_logs 이력 기록 (트랜잭션 일관성 유지)
    """
    admin_client = get_supabase_admin_client()

    target_type = request.form.get('target_type', '').strip().lower()
    target_id = request.form.get('target_id', '').strip()
    adjust_type = request.form.get('adjust_type', '').strip().upper()
    quantity_raw = request.form.get('quantity', '').strip()
    expected_stock_raw = request.form.get('expected_stock', '').strip()
    reason = request.form.get('reason', '').strip()

    if target_type not in ('option', 'product') or not target_id:
        flash('조정할 상품 또는 옵션 정보가 올바르지 않습니다.', 'danger')
        return redirect(url_for('admin.inventory_list'))

    if adjust_type not in ('IN', 'OUT', 'ADJUST'):
        flash('올바른 재고 조정 유형(입고, 출고, 실사조정)을 선택해주세요.', 'danger')
        return redirect(url_for('admin.inventory_list'))

    if not reason:
        flash('재고 변경 사유를 반드시 입력해주세요.', 'danger')
        return redirect(url_for('admin.inventory_list'))

    try:
        qty = int(quantity_raw)
    except (ValueError, TypeError):
        flash('수량은 정수로 입력해주세요.', 'danger')
        return redirect(url_for('admin.inventory_list'))

    if adjust_type in ('IN', 'OUT') and qty <= 0:
        flash('입고 및 출고 수량은 1개 이상이어야 합니다.', 'danger')
        return redirect(url_for('admin.inventory_list'))

    if adjust_type == 'ADJUST' and qty < 0:
        flash('실사 조정 수량은 0개 이상이어야 합니다.', 'danger')
        return redirect(url_for('admin.inventory_list'))

    # 현재 DB 최신 재고 조회
    try:
        if target_type == 'option':
            cur_res = admin_client.table('product_options').select('id, product_id, stock, color, size, option_value, products(name)').eq('id', target_id).execute()
            if not cur_res.data:
                flash('존재하지 않는 상품 옵션입니다.', 'warning')
                return redirect(url_for('admin.inventory_list'))
            record = cur_res.data[0]
            current_stock = int(record.get('stock') if record.get('stock') is not None else 0)
            product_id = record['product_id']
            option_id = record['id']
            p_name = (record.get('products') or {}).get('name') or '상품'
            c = record.get('color') or ''
            s = record.get('size') or ''
            option_info = f"{c} / {s}" if c and s else (c or s or record.get('option_value') or '')
        else:
            cur_res = admin_client.table('products').select('id, name, stock').eq('id', target_id).execute()
            if not cur_res.data:
                flash('존재하지 않는 상품입니다.', 'warning')
                return redirect(url_for('admin.inventory_list'))
            record = cur_res.data[0]
            current_stock = int(record.get('stock') if record.get('stock') is not None else 0)
            product_id = record['id']
            option_id = None
            p_name = record.get('name') or '상품'
            option_info = '단일 상품'

        # 낙관적 락 검증: 사용자가 조정 모달을 띄웠을 때의 expected_stock과 현재 DB 재고 비교
        if expected_stock_raw != '':
            try:
                expected_stock = int(expected_stock_raw)
                if expected_stock != current_stock:
                    flash(
                        f"다른 관리자에 의해 해당 재고가 이미 변경되었습니다. (화면 기준: {expected_stock}개 &rarr; 현재 실제 재고: {current_stock}개) "
                        "최신 재고 수량을 확인하신 후 다시 조정해주세요.",
                        'danger'
                    )
                    return redirect(url_for('admin.inventory_list'))
            except (ValueError, TypeError):
                pass

        # 신규 재고 및 증감량 계산
        if adjust_type == 'IN':
            new_stock = current_stock + qty
            qty_change = qty
        elif adjust_type == 'OUT':
            new_stock = current_stock - qty
            qty_change = -qty
            if new_stock < 0:
                flash(f"출고 수량({qty}개)이 현재 재고({current_stock}개)보다 많아 재고가 음수가 될 수 없습니다.", 'danger')
                return redirect(url_for('admin.inventory_list'))
        else:  # ADJUST
            new_stock = qty
            qty_change = new_stock - current_stock

        # 안전한 조건부 UPDATE (동시 수정 시 충돌 방지)
        if target_type == 'option':
            up_res = (
                admin_client.table('product_options')
                .update({'stock': new_stock})
                .eq('id', target_id)
                .eq('stock', current_stock)
                .execute()
            )
        else:
            up_res = (
                admin_client.table('products')
                .update({'stock': new_stock, 'updated_at': datetime.now(timezone.utc).isoformat()})
                .eq('id', target_id)
                .eq('stock', current_stock)
                .execute()
            )

        if not up_res.data or len(up_res.data) == 0:
            flash("동시에 다른 재고 수정이 발생하여 반영되지 않았습니다. 페이지를 새로고침 후 다시 시도해주세요.", 'danger')
            return redirect(url_for('admin.inventory_list'))

        # 재고 변경 이력(inventory_logs) 기록
        current_admin = getattr(g, 'admin_user', {})
        admin_id = current_admin.get('id')
        admin_email = current_admin.get('email')

        log_data = {
            'product_id': product_id,
            'option_id': option_id,
            'product_name': p_name,
            'option_info': option_info,
            'change_type': adjust_type,
            'before_stock': current_stock,
            'quantity_change': qty_change,
            'after_stock': new_stock,
            'reason': reason,
            'admin_id': admin_id,
            'admin_email': admin_email,
            'created_at': datetime.now(timezone.utc).isoformat()
        }

        try:
            admin_client.table('inventory_logs').insert(log_data).execute()
        except Exception as log_err:
            logger.warning(f"[Inventory Log Insert Warning] {log_err}")
            # 테이블 미생성 시 안내
            flash(
                f"재고가 정상적으로 변경되었습니다 ({current_stock}개 &rarr; {new_stock}개). "
                "단, Supabase에 inventory_logs 테이블이 아직 생성되지 않아 이력 기록이 누락되었습니다. 제공된 SQL 마이그레이션을 실행해주세요.",
                'warning'
            )
            return redirect(url_for('admin.inventory_list'))

        type_korean = {'IN': '입고', 'OUT': '출고', 'ADJUST': '실사 조정'}.get(adjust_type, adjust_type)
        flash(f"[{type_korean}] 재고가 성공적으로 조정되었습니다. ({p_name} {option_info}: {current_stock}개 &rarr; {new_stock}개)", 'success')

    except Exception as e:
        logger.error(f"[Admin Inventory Adjust Error] {e}", exc_info=True)
        flash(f"재고 조정 처리 중 오류가 발생했습니다: {e}", 'danger')

    return redirect(url_for('admin.inventory_list'))


# ==============================================================================
# [10] 재고 변경 이력 조회 API (GET /admin/inventory/logs)
# ==============================================================================
@admin_bp.route('/inventory/logs', methods=['GET'])
@admin_required
def inventory_logs():
    """
    특정 상품 또는 옵션의 재고 변경 이력 JSON 조회:
    - 쿼리: product_id, option_id (선택)
    - 최신순 최대 30건 조회
    """
    admin_client = get_supabase_admin_client()

    product_id = request.args.get('product_id', '').strip()
    option_id = request.args.get('option_id', '').strip()

    try:
        query = admin_client.table('inventory_logs').select('*')
        if option_id:
            query = query.eq('option_id', option_id)
        elif product_id:
            query = query.eq('product_id', product_id)

        res = query.order('created_at', desc=True).limit(30).execute()
        logs = res.data or []

        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs)
        }), 200

    except Exception as e:
        logger.error(f"[Admin Inventory Logs Error] {e}")
        return jsonify({
            'success': False,
            'error': '재고 변경 이력을 조회할 수 없습니다. inventory_logs 테이블이 생성되었는지 확인해주세요.',
            'logs': []
        }), 200


# ==============================================================================
# [11] 메인 배너 및 상단 공지 관리 (GET /admin/banners)
# ==============================================================================
def is_safe_link_url(url: str) -> bool:
    """내부 경로(/...) 또는 안전한 HTTPS URL만 허용 (javascript:, data: 등 차단)"""
    if not url:
        return True
    url = url.strip()
    if url.startswith('/') or url.startswith('#'):
        return True
    try:
        parsed = urlparse(url)
        return parsed.scheme == 'https' and bool(parsed.netloc)
    except Exception:
        return False


def swap_sort_order(table_name: str, item_id: str, direction: str):
    """지정한 테이블 내 항목의 노출 순서(sort_order)를 인접 항목과 안전하게 교환합니다."""
    admin_client = get_supabase_admin_client()
    items = admin_client.table(table_name).select('id, sort_order').order('sort_order', desc=False).order('created_at', desc=False).execute().data or []
    idx = next((i for i, it in enumerate(items) if str(it['id']) == str(item_id)), None)
    if idx is None:
        return
    target_idx = idx - 1 if direction == 'up' else idx + 1
    if 0 <= target_idx < len(items):
        curr_item = items[idx]
        target_item = items[target_idx]
        curr_order = curr_item.get('sort_order') if curr_item.get('sort_order') is not None else idx
        target_order = target_item.get('sort_order') if target_item.get('sort_order') is not None else target_idx
        if curr_order == target_order:
            curr_order, target_order = idx, target_idx

        admin_client.table(table_name).update({
            'sort_order': target_order,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', curr_item['id']).execute()

        admin_client.table(table_name).update({
            'sort_order': curr_order,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', target_item['id']).execute()


@admin_bp.route('/banners', methods=['GET'])
@admin_required
def banner_list():
    """
    배너 및 공지 관리 메인 화면:
    - 탭 1: 메인 배너 목록 (정렬, 공개/숨김, 수정, 삭제)
    - 탭 2: 상단 공지 목록 (정렬, 공개/숨김, 수정, 삭제)
    - active_tab 쿼리 파라미터로 선택 탭 유지
    """
    admin_client = get_supabase_admin_client()
    active_tab = request.args.get('tab', 'banners').strip().lower()
    if active_tab not in ('banners', 'announcements'):
        active_tab = 'banners'

    banners = []
    announcements = []
    db_notice = None

    try:
        b_res = admin_client.table('banners').select('*').order('sort_order', desc=False).order('created_at', desc=True).execute()
        banners = b_res.data or []
    except Exception as e:
        logger.warning(f"[Banners Table Fetch Notice] {e}")
        db_notice = "Supabase DB에 banners 및 announcements 테이블이 아직 생성되지 않았습니다. 제공된 마이그레이션 SQL을 실행해주세요."

    try:
        a_res = admin_client.table('announcements').select('*').order('sort_order', desc=False).order('created_at', desc=True).execute()
        announcements = a_res.data or []
    except Exception as e:
        logger.warning(f"[Announcements Table Fetch Notice] {e}")
        if not db_notice:
            db_notice = "Supabase DB에 announcements 테이블이 아직 생성되지 않았습니다. 제공된 마이그레이션 SQL을 실행해주세요."

    return render_template(
        'admin/banners.html',
        active_menu='banners',
        active_tab=active_tab,
        banners=banners,
        announcements=announcements,
        db_notice=db_notice
    )


# --- [메인 배너 등록/수정/삭제/순서/토글] ---

@admin_bp.route('/banners/new', methods=['GET', 'POST'])
@admin_required
def banner_new():
    """메인 배너 신규 등록 (기본 숨김 상태로 등록)"""
    admin_client = get_supabase_admin_client()

    if request.method == 'GET':
        return render_template(
            'admin/banner_form.html',
            active_menu='banners',
            is_edit=False,
            banner={}
        )

    # POST 처리
    name = request.form.get('name', '').strip()
    image_url = request.form.get('image_url', '').strip()
    image_alt = request.form.get('image_alt', '').strip()
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    button_text = request.form.get('button_text', '').strip()
    link_url = request.form.get('link_url', '').strip()
    # 새 배너는 기본적으로 숨김 (체크되어 있으면 공개)
    is_active = request.form.get('is_active') == 'true'

    if not name:
        flash('관리용 배너 이름은 필수 입력 항목입니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=False, banner=request.form)

    if not image_url:
        flash('배너 이미지 URL은 필수 입력 항목입니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=False, banner=request.form)

    # 이미지 URL 검증
    parsed_img = urlparse(image_url)
    if parsed_img.scheme not in ('http', 'https') or not parsed_img.netloc:
        flash('올바른 이미지 URL(http:// 또는 https://)을 입력해주세요.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=False, banner=request.form)

    # 버튼 문구와 연결 주소는 둘 다 있거나 둘 다 없어야 함
    if (button_text and not link_url) or (link_url and not button_text):
        flash('버튼 문구와 연결 주소는 함께 입력하거나 둘 다 비워두어야 합니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=False, banner=request.form)

    if link_url and not is_safe_link_url(link_url):
        flash('연결 주소는 내부 경로(/...) 또는 안전한 https:// URL만 입력할 수 있습니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=False, banner=request.form)

    try:
        # 노출 순서 자동 계산 (현재 등록된 마지막 순서 + 1)
        cur_banners = admin_client.table('banners').select('sort_order').order('sort_order', desc=True).limit(1).execute().data or []
        next_order = (cur_banners[0].get('sort_order', 0) + 1) if cur_banners else 1

        payload = {
            'name': name,
            'image_url': image_url,
            'image_alt': image_alt or None,
            'title': title or None,
            'description': description or None,
            'button_text': button_text or None,
            'link_url': link_url or None,
            'is_active': is_active,
            'sort_order': next_order,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        admin_client.table('banners').insert(payload).execute()
        flash(f"배너 '{name}'이(가) 등록되었습니다. (상태: {'공개' if is_active else '숨김'})", 'success')
        return redirect(url_for('admin.banner_list', tab='banners'))

    except Exception as e:
        logger.error(f"[Banner Create Error] {e}", exc_info=True)
        flash(f"배너 등록 중 오류가 발생했습니다: {e}", 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=False, banner=request.form)


@admin_bp.route('/banners/<banner_id>/edit', methods=['GET', 'POST'])
@admin_required
def banner_edit(banner_id):
    """메인 배너 수정"""
    admin_client = get_supabase_admin_client()

    try:
        b_res = admin_client.table('banners').select('*').eq('id', banner_id).execute()
        if not b_res.data:
            flash('수정할 배너를 찾을 수 없습니다.', 'warning')
            return redirect(url_for('admin.banner_list', tab='banners'))
        banner = b_res.data[0]
    except Exception as e:
        logger.error(f"[Banner Fetch Error] {e}")
        flash('배너 정보를 불러오지 못했습니다.', 'danger')
        return redirect(url_for('admin.banner_list', tab='banners'))

    if request.method == 'GET':
        return render_template(
            'admin/banner_form.html',
            active_menu='banners',
            is_edit=True,
            banner=banner
        )

    # POST 처리
    name = request.form.get('name', '').strip()
    image_url = request.form.get('image_url', '').strip()
    image_alt = request.form.get('image_alt', '').strip()
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    button_text = request.form.get('button_text', '').strip()
    link_url = request.form.get('link_url', '').strip()
    is_active = request.form.get('is_active') == 'true'

    if not name or not image_url:
        flash('관리용 배너 이름과 배너 이미지 URL은 필수입니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=True, banner=request.form)

    parsed_img = urlparse(image_url)
    if parsed_img.scheme not in ('http', 'https') or not parsed_img.netloc:
        flash('올바른 이미지 URL을 입력해주세요.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=True, banner=request.form)

    if (button_text and not link_url) or (link_url and not button_text):
        flash('버튼 문구와 연결 주소는 함께 입력하거나 둘 다 비워두어야 합니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=True, banner=request.form)

    if link_url and not is_safe_link_url(link_url):
        flash('연결 주소는 내부 경로(/...) 또는 안전한 https:// URL만 입력할 수 있습니다.', 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=True, banner=request.form)

    try:
        update_payload = {
            'name': name,
            'image_url': image_url,
            'image_alt': image_alt or None,
            'title': title or None,
            'description': description or None,
            'button_text': button_text or None,
            'link_url': link_url or None,
            'is_active': is_active,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        admin_client.table('banners').update(update_payload).eq('id', banner_id).execute()
        flash(f"배너 '{name}' 정보가 성공적으로 수정되었습니다.", 'success')
        return redirect(url_for('admin.banner_list', tab='banners'))

    except Exception as e:
        logger.error(f"[Banner Update Error] {e}", exc_info=True)
        flash(f"배너 수정 중 오류가 발생했습니다: {e}", 'danger')
        return render_template('admin/banner_form.html', active_menu='banners', is_edit=True, banner=request.form)


@admin_bp.route('/banners/<banner_id>/delete', methods=['POST'])
@admin_required
def banner_delete(banner_id):
    """배너 삭제"""
    admin_client = get_supabase_admin_client()
    try:
        cur = admin_client.table('banners').select('id, name').eq('id', banner_id).execute()
        name = cur.data[0]['name'] if cur.data else '선택한 배너'
        admin_client.table('banners').delete().eq('id', banner_id).execute()
        flash(f"배너 '{name}'이(가) 삭제되었습니다.", 'success')
    except Exception as e:
        logger.error(f"[Banner Delete Error] {e}", exc_info=True)
        flash('배너 삭제 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('admin.banner_list', tab='banners'))


@admin_bp.route('/banners/<banner_id>/toggle-status', methods=['POST'])
@admin_required
def banner_toggle_status(banner_id):
    """배너 공개 <-> 숨김 상태 토글"""
    admin_client = get_supabase_admin_client()
    try:
        cur = admin_client.table('banners').select('id, name, is_active').eq('id', banner_id).execute()
        if cur.data:
            b = cur.data[0]
            new_status = not b.get('is_active')
            admin_client.table('banners').update({
                'is_active': new_status,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', banner_id).execute()
            flash(f"배너 '{b.get('name')}' 상태가 [{'공개' if new_status else '숨김'}]으로 변경되었습니다.", 'success')
    except Exception as e:
        logger.error(f"[Banner Toggle Error] {e}", exc_info=True)
        flash('배너 상태 변경 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('admin.banner_list', tab='banners'))


@admin_bp.route('/banners/<banner_id>/reorder', methods=['POST'])
@admin_required
def banner_reorder(banner_id):
    """배너 노출 순서 변경 (up / down)"""
    direction = request.form.get('direction', 'up').strip().lower()
    if direction not in ('up', 'down'):
        direction = 'up'
    try:
        swap_sort_order('banners', banner_id, direction)
        flash('배너 노출 순서가 변경되었습니다.', 'success')
    except Exception as e:
        logger.error(f"[Banner Reorder Error] {e}", exc_info=True)
        flash('순서 변경 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('admin.banner_list', tab='banners'))


# --- [상단 공지 등록/수정/삭제/순서/토글] ---

@admin_bp.route('/announcements/new', methods=['POST'])
@admin_required
def announcement_new():
    """상단 공지 신규 등록"""
    admin_client = get_supabase_admin_client()

    name = request.form.get('name', '').strip()
    content = request.form.get('content', '').strip()
    link_url = request.form.get('link_url', '').strip()
    is_active = request.form.get('is_active') == 'true'

    if not name:
        flash('관리용 공지 이름은 필수입니다.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))

    if not content:
        flash('고객에게 표시할 공지 문구는 필수입니다.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))

    if len(content) > 100:
        flash('공지 문구는 최대 100자 이하로 작성해주세요.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))

    if link_url and not is_safe_link_url(link_url):
        flash('연결 주소는 내부 경로(/...) 또는 안전한 https:// URL만 입력 가능합니다.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))

    try:
        cur_ann = admin_client.table('announcements').select('sort_order').order('sort_order', desc=True).limit(1).execute().data or []
        next_order = (cur_ann[0].get('sort_order', 0) + 1) if cur_ann else 1

        payload = {
            'name': name,
            'content': content,
            'link_url': link_url or None,
            'is_active': is_active,
            'sort_order': next_order,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        admin_client.table('announcements').insert(payload).execute()
        flash(f"상단 공지 '{name}'이(가) 등록되었습니다. (상태: {'공개' if is_active else '숨김'})", 'success')
    except Exception as e:
        logger.error(f"[Announcement Create Error] {e}", exc_info=True)
        flash(f"공지 등록 중 오류가 발생했습니다: {e}", 'danger')

    return redirect(url_for('admin.banner_list', tab='announcements'))

@admin_bp.route('/announcements/<announcement_id>/edit', methods=['POST'])
@admin_required
def announcement_edit(announcement_id):
    """상단 공지 수정"""
    admin_client = get_supabase_admin_client()

    name = request.form.get('name', '').strip()
    content = request.form.get('content', '').strip()
    link_url = request.form.get('link_url', '').strip()
    is_active = request.form.get('is_active') == 'true'

    if not name or not content:
        flash('공지 이름과 고객 표시 문구는 필수 입력 항목입니다.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))
    if len(content) > 100:
        flash('공지 문구는 최대 100자 이하로 작성해주세요.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))

    if link_url and not is_safe_link_url(link_url):
        flash('연결 주소는 내부 경로(/...) 또는 안전한 https:// URL만 입력 가능합니다.', 'danger')
        return redirect(url_for('admin.banner_list', tab='announcements'))

    try:
        update_payload = {
            'name': name,
            'content': content,
            'link_url': link_url or None,
            'is_active': is_active,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        admin_client.table('announcements').update(update_payload).eq('id', announcement_id).execute()
        flash(f"상단 공지 '{name}'이(가) 수정되었습니다.", 'success')
    except Exception as e:
        logger.error(f"[Announcement Update Error] {e}", exc_info=True)
        flash(f"공지 수정 중 오류가 발생했습니다: {e}", 'danger')

    return redirect(url_for('admin.banner_list', tab='announcements'))

@admin_bp.route('/announcements/<announcement_id>/delete', methods=['POST'])
@admin_required
def announcement_delete(announcement_id):
    """상단 공지 삭제"""
    admin_client = get_supabase_admin_client()
    try:
        cur = admin_client.table('announcements').select('id, name').eq('id', announcement_id).execute()
        name = cur.data[0]['name'] if cur.data else '선택한 공지'
        admin_client.table('announcements').delete().eq('id', announcement_id).execute()
        flash(f"상단 공지 '{name}'이(가) 삭제되었습니다.", 'success')
    except Exception as e:
        logger.error(f"[Announcement Delete Error] {e}", exc_info=True)
        flash('공지 삭제 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('admin.banner_list', tab='announcements'))


@admin_bp.route('/announcements/<announcement_id>/toggle-status', methods=['POST'])
@admin_required
def announcement_toggle_status(announcement_id):
    """상단 공지 공개 <-> 숨김 상태 토글"""
    admin_client = get_supabase_admin_client()
    try:
        cur = admin_client.table('announcements').select('id, name, is_active').eq('id', announcement_id).execute()
        if cur.data:
            a = cur.data[0]
            new_status = not a.get('is_active')
            admin_client.table('announcements').update({
                'is_active': new_status,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', announcement_id).execute()
            flash(f"공지 '{a.get('name')}' 상태가 [{'공개' if new_status else '숨김'}]으로 변경되었습니다.", 'success')
    except Exception as e:
        logger.error(f"[Announcement Toggle Error] {e}", exc_info=True)
        flash('공지 상태 변경 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('admin.banner_list', tab='announcements'))


@admin_bp.route('/announcements/<announcement_id>/reorder', methods=['POST'])
@admin_required
def announcement_reorder(announcement_id):
    """상단 공지 우선순위 순서 변경 (up / down)"""
    direction = request.form.get('direction', 'up').strip().lower()
    if direction not in ('up', 'down'):
        direction = 'up'
    try:
        swap_sort_order('announcements', announcement_id, direction)
        flash('공지 우선순위 순서가 변경되었습니다.', 'success')
    except Exception as e:
        logger.error(f"[Announcement Reorder Error] {e}", exc_info=True)
        flash('순서 변경 중 오류가 발생했습니다.', 'danger')
    return redirect(url_for('admin.banner_list', tab='announcements'))

