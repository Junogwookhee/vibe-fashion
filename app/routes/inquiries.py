"""로그인 회원의 비공개 1:1 문의 route."""

import logging
import math
import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from app.routes.admin import get_or_create_csrf_token, validate_csrf
from app.routes.auth import login_required
from app.utils.admin_work_alerts import format_seoul_datetime
from app.utils.supabase_client import get_supabase_admin_client

logger = logging.getLogger(__name__)

inquiries_bp = Blueprint('inquiries', __name__)

INQUIRY_TYPES = (
    ('product_size', '상품·사이즈'),
    ('delivery', '배송'),
    ('order_payment', '주문·결제'),
    ('cancel_exchange_return', '취소·교환·반품'),
    ('other', '기타'),
)
INQUIRY_TYPE_LABELS = dict(INQUIRY_TYPES)
INQUIRY_STATUS_LABELS = {'pending': '답변 대기', 'answered': '답변 완료'}
CUSTOMER_PAGE_SIZE = 10
TITLE_MAX_LENGTH = 100
CONTENT_MAX_LENGTH = 5000


def _session_user_id():
    try:
        return str(uuid.UUID(str(session.get('user_id'))))
    except (ValueError, TypeError, AttributeError):
        return None


def _page_number(value):
    try:
        return max(1, int(value))
    except (ValueError, TypeError):
        return 1


def _display_row(row):
    item = dict(row)
    item['inquiry_type_label'] = INQUIRY_TYPE_LABELS.get(item.get('inquiry_type'), '기타')
    item['status_label'] = INQUIRY_STATUS_LABELS.get(item.get('status'), '확인 필요')
    item['created_at_display'] = format_seoul_datetime(item.get('created_at'))
    item['answered_at_display'] = format_seoul_datetime(item.get('answered_at'))
    item['reply_updated_at_display'] = format_seoul_datetime(item.get('reply_updated_at'))
    item['reply_was_edited'] = (item.get('reply_version') or 0) > 1
    return item


def _render_form(values=None, errors=None, status=200):
    values = values or {}
    errors = errors or {}
    orders = []
    orders_error = None
    client = get_supabase_admin_client()

    try:
        result = (
            client.table('orders')
            .select('id, order_number, created_at, total_amount')
            .eq('user_id', _session_user_id())
            .order('created_at', desc=True)
            .limit(100)
            .execute()
        )
        orders = result.data or []
    except Exception:
        logger.error('[Customer Inquiries] 회원 주문 선택 목록 조회에 실패했습니다.')
        orders_error = '주문 목록을 불러오지 못했습니다. 주문을 연결하지 않고 문의를 등록할 수 있습니다.'

    return render_template(
        'customer_inquiry_form.html',
        inquiry_types=INQUIRY_TYPES,
        orders=orders,
        orders_error=orders_error,
        errors=errors,
        values=values,
        csrf_token=get_or_create_csrf_token(),
        submission_token=values.get('submission_token') or str(uuid.uuid4()),
    ), status


@inquiries_bp.route('/mypage/inquiries', methods=['GET'])
@login_required
def customer_list():
    user_id = _session_user_id()
    if not user_id:
        abort(401)

    page = _page_number(request.args.get('page', 1))
    inquiries = []
    total_count = None
    total_pages = 1
    list_error = None
    client = get_supabase_admin_client()

    def build_query():
        return (
            client.table('customer_inquiries')
            .select(
                'id, inquiry_number, inquiry_type, title, status, created_at, '
                'answered_at, reply_updated_at, reply_version',
                count='exact'
            )
            .eq('user_id', user_id)
            .order('created_at', desc=True)
            .order('id', desc=True)
        )

    try:
        result = build_query().range(
            (page - 1) * CUSTOMER_PAGE_SIZE,
            page * CUSTOMER_PAGE_SIZE - 1
        ).execute()
        total_count = result.count
        if total_count is None:
            raise ValueError('정확한 문의 건수를 반환하지 않았습니다.')
        total_pages = max(1, math.ceil(total_count / CUSTOMER_PAGE_SIZE))
        if page > total_pages:
            page = total_pages
            result = build_query().range(
                (page - 1) * CUSTOMER_PAGE_SIZE,
                page * CUSTOMER_PAGE_SIZE - 1
            ).execute()
        inquiries = [_display_row(row) for row in (result.data or [])]
    except Exception:
        logger.error('[Customer Inquiries] 회원 문의 목록 조회에 실패했습니다.')
        list_error = '문의 내역을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.'
        total_count = None

    return render_template(
        'customer_inquiries.html',
        inquiries=inquiries,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        list_error=list_error,
    ), 503 if list_error else 200


@inquiries_bp.route('/mypage/inquiries/new', methods=['GET', 'POST'])
@login_required
def customer_new():
    user_id = _session_user_id()
    if not user_id:
        abort(401)

    if request.method == 'GET':
        return _render_form()

    validate_csrf()
    values = {
        'inquiry_type': request.form.get('inquiry_type', '').strip(),
        'title': request.form.get('title', '').strip(),
        'content': request.form.get('content', '').strip(),
        'order_id': request.form.get('order_id', '').strip(),
        'submission_token': request.form.get('submission_token', '').strip(),
    }
    errors = {}

    if values['inquiry_type'] not in INQUIRY_TYPE_LABELS:
        errors['inquiry_type'] = '문의 유형을 선택해주세요.'
    if not values['title']:
        errors['title'] = '제목을 입력해주세요.'
    elif len(values['title']) > TITLE_MAX_LENGTH:
        errors['title'] = f'제목은 {TITLE_MAX_LENGTH}자 이내로 입력해주세요.'
    if not values['content']:
        errors['content'] = '문의 내용을 입력해주세요.'
    elif len(values['content']) > CONTENT_MAX_LENGTH:
        errors['content'] = f'문의 내용은 {CONTENT_MAX_LENGTH}자 이내로 입력해주세요.'
    try:
        submission_token = str(uuid.UUID(values['submission_token']))
    except (ValueError, TypeError, AttributeError):
        submission_token = ''
        errors['form'] = '문의 등록 화면을 새로고침한 뒤 다시 시도해주세요.'

    client = get_supabase_admin_client()
    if not errors and submission_token:
        try:
            existing = (
                client.table('customer_inquiries')
                .select('id')
                .eq('user_id', user_id)
                .eq('submission_token', submission_token)
                .limit(1)
                .execute()
            )
            if existing.data:
                flash('이미 등록된 문의입니다.', 'info')
                return redirect(url_for('inquiries.customer_detail', inquiry_id=existing.data[0]['id']))
        except Exception:
            logger.error('[Customer Inquiries] 중복 등록 확인에 실패했습니다.')
            errors['form'] = '문의 등록을 확인하지 못했습니다. 입력 내용은 유지됩니다.'

    order_id = None
    if not errors and values['order_id']:
        try:
            order_result = (
                client.table('orders')
                .select('id')
                .eq('id', values['order_id'])
                .eq('user_id', user_id)
                .limit(1)
                .execute()
            )
            if not order_result.data:
                errors['order_id'] = '본인 주문만 문의에 연결할 수 있습니다.'
            else:
                order_id = order_result.data[0]['id']
        except Exception:
            logger.error('[Customer Inquiries] 문의 연결 주문 소유권 확인에 실패했습니다.')
            errors['order_id'] = '주문 소유권을 확인하지 못했습니다. 잠시 후 다시 시도해주세요.'

    if errors:
        return _render_form(values, errors, 400 if 'form' not in errors else 503)

    try:
        result = (
            client.table('customer_inquiries')
            .insert({
                'user_id': user_id,
                'order_id': order_id,
                'inquiry_type': values['inquiry_type'],
                'title': values['title'],
                'content': values['content'],
                'submission_token': submission_token,
            })
            .select('id')
            .execute()
        )
        if not result.data:
            raise ValueError('문의 번호를 반환하지 않았습니다.')
        inquiry_id = result.data[0]['id']
        flash('문의가 등록되었습니다. 답변이 등록되면 이 화면에서 확인할 수 있습니다.', 'success')
        return redirect(url_for('inquiries.customer_detail', inquiry_id=inquiry_id))
    except Exception:
        logger.error('[Customer Inquiries] 문의 등록에 실패했습니다.')
        values['submission_token'] = submission_token
        return _render_form(values, {'form': '문의 등록에 실패했습니다. 입력 내용을 확인하고 다시 시도해주세요.'}, 503)


@inquiries_bp.route('/mypage/inquiries/<inquiry_id>', methods=['GET'])
@login_required
def customer_detail(inquiry_id):
    user_id = _session_user_id()
    if not user_id:
        abort(401)
    try:
        inquiry_id = str(uuid.UUID(str(inquiry_id)))
    except (ValueError, TypeError, AttributeError):
        abort(404)

    try:
        result = (
            get_supabase_admin_client().table('customer_inquiries')
            .select(
                'id, inquiry_number, inquiry_type, title, content, order_id, status, '
                'created_at, reply_text, answered_at, reply_updated_at, reply_version'
            )
            .eq('id', inquiry_id)
            .eq('user_id', user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            abort(404)
        inquiry = _display_row(result.data[0])
        order = None
        order_error = None
        if inquiry.get('order_id'):
            try:
                order_result = (
                    get_supabase_admin_client().table('orders')
                    .select('id, order_number')
                    .eq('id', inquiry['order_id'])
                    .eq('user_id', user_id)
                    .limit(1)
                    .execute()
                )
                order = (order_result.data or [None])[0]
            except Exception:
                logger.error('[Customer Inquiries] 문의 연결 주문 조회에 실패했습니다.')
                order_error = '연결된 주문 정보를 불러오지 못했습니다.'
    except HTTPException:
        raise
    except Exception:
        logger.error('[Customer Inquiries] 회원 문의 상세 조회에 실패했습니다.')
        return render_template('customer_inquiry_detail.html', inquiry=None, load_error=True), 503

    return render_template(
        'customer_inquiry_detail.html',
        inquiry=inquiry,
        order=order,
        order_error=order_error,
        load_error=False,
    )