"""관리자 대시보드 업무 알림 조회 helper."""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

try:
    SEOUL_TIMEZONE = ZoneInfo('Asia/Seoul')
except ZoneInfoNotFoundError:
    SEOUL_TIMEZONE = timezone(timedelta(hours=9))

ALERT_LIMIT = 5
LOW_STOCK_THRESHOLD = 5

INVENTORY_COLUMNS = (
    'target_type, target_id, product_id, product_name, slug, thumbnail_url, '
    'category_name, option_id, option_info, stock'
)
ORDER_COLUMNS = 'id, order_number, status, created_at'
REFUND_COLUMNS = 'id, order_number, order_status, requested_at, refund_status'


def format_seoul_datetime(value):
    """UTC/ISO 시각을 관리자 화면용 한국 시각으로 변환합니다."""
    if not value:
        return '-'
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(SEOUL_TIMEZONE).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return '-'


def _ready_alert(response, time_field=None):
    count = getattr(response, 'count', None)
    if count is None:
        raise ValueError('정확한 업무 건수를 반환하지 않았습니다.')

    items = response.data or []
    if time_field:
        items = [
            {**item, 'display_time': format_seoul_datetime(item.get(time_field))}
            for item in items
        ]
    return {'state': 'ready', 'count': count, 'items': items}


def _query_alert(alert_key, query, time_field=None):
    try:
        return _ready_alert(query.execute(), time_field=time_field)
    except Exception:
        logger.error('[Admin Work Alert] %s 조회에 실패했습니다.', alert_key)
        return {'state': 'error', 'count': None, 'items': []}


def load_work_alerts(admin_client):
    """DB view의 exact count와 최대 5개 미리보기를 업무별로 조회합니다."""
    alerts = {}

    out_of_stock_query = (
        admin_client.table('admin_active_inventory_items')
        .select(INVENTORY_COLUMNS, count='exact')
        .eq('stock', 0)
        .order('product_name')
        .limit(ALERT_LIMIT)
    )
    alerts['out_of_stock'] = _query_alert('out_of_stock', out_of_stock_query)

    low_stock_query = (
        admin_client.table('admin_active_inventory_items')
        .select(INVENTORY_COLUMNS, count='exact')
        .gte('stock', 1)
        .lte('stock', LOW_STOCK_THRESHOLD)
        .order('stock')
        .order('product_name')
        .limit(ALERT_LIMIT)
    )
    alerts['low_stock'] = _query_alert('low_stock', low_stock_query)

    unshipped_query = (
        admin_client.table('admin_unshipped_orders')
        .select(ORDER_COLUMNS, count='exact')
        .order('created_at')
        .limit(ALERT_LIMIT)
    )
    alerts['unshipped'] = _query_alert('unshipped', unshipped_query, 'created_at')

    refunds_query = (
        admin_client.table('admin_pending_refund_orders')
        .select(REFUND_COLUMNS, count='exact')
        .order('requested_at')
        .limit(ALERT_LIMIT)
    )
    alerts['refunds'] = _query_alert('refunds', refunds_query, 'requested_at')

    inquiries_query = (
        admin_client.table('admin_customer_inquiries')
        .select('id, inquiry_number, inquiry_type, title, author_name, created_at', count='exact')
        .eq('status', 'pending')
        .order('created_at')
        .order('id')
        .limit(ALERT_LIMIT)
    )
    alerts['inquiries'] = _query_alert('inquiries', inquiries_query, 'created_at')
    return alerts