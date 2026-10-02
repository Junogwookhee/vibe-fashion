import unittest
from unittest.mock import patch

from app import create_app


MEMBER_ID = '11111111-1111-4111-8111-111111111111'
OTHER_MEMBER_ID = '22222222-2222-4222-8222-222222222222'


class FakeResponse:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.calls = []
        self.select_args = None

    def select(self, *args, **kwargs):
        self.select_args = (args, kwargs)
        self.calls.append(('select', args, kwargs))
        self.client.queries.append((self.table, self))
        return self

    def eq(self, *args):
        self.calls.append(('eq', *args))
        return self

    def gte(self, *args):
        self.calls.append(('gte', *args))
        return self

    def lt(self, *args):
        self.calls.append(('lt', *args))
        return self

    def contains(self, *args):
        self.calls.append(('contains', *args))
        return self

    def or_(self, expression):
        self.calls.append(('or', expression))
        return self

    def order(self, *args, **kwargs):
        self.calls.append(('order', args, kwargs))
        return self

    def range(self, *args):
        self.calls.append(('range', *args))
        return self

    def limit(self, *args):
        self.calls.append(('limit', *args))
        return self

    def in_(self, *args):
        self.calls.append(('in', *args))
        return self

    def execute(self):
        if self.table in self.client.fail_tables:
            raise RuntimeError('private database detail must not be logged')
        if self.table == 'profiles':
            return FakeResponse([{
                'id': 'admin-user',
                'email': 'admin@example.invalid',
                'full_name': 'Admin',
                'role': self.client.admin_role,
            }])
        if self.table == 'admin_member_directory':
            member_filter = next((call[1] for call in self.calls if call[0] == 'eq' and call[1] == 'member_id'), None)
            if member_filter:
                wanted_id = next(call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'member_id')
                rows = [row for row in self.client.members if row['member_id'] == wanted_id]
                is_detail = self.select_args[0][0] != 'member_id, display_name'
                return FakeResponse(rows[:1] if is_detail else rows, len(rows))
            return FakeResponse(self.client.members, self.client.member_count)
        if self.table == 'orders':
            user_filter = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'user_id'), None)
            rows = [row for row in self.client.orders if not user_filter or row.get('user_id') == user_filter]
            count_requested = bool(self.select_args and self.select_args[1].get('count') == 'exact')
            count = self.client.order_count if count_requested else None
            return FakeResponse(rows, count)
        if self.table == 'order_items':
            order_ids = next((call[2] for call in self.calls if call[0] == 'in' and call[1] == 'order_id'), [])
            return FakeResponse([item for item in self.client.order_items if item['order_id'] in order_ids])
        if self.table == 'customer_inquiries':
            wanted_user = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'user_id'), None)
            rows = [row for row in self.client.inquiries if not wanted_user or row['user_id'] == wanted_user]
            count_requested = bool(self.select_args and self.select_args[1].get('count') == 'exact')
            return FakeResponse(rows, len(rows) if count_requested else None)
        return FakeResponse([])


class FakeSupabaseClient:
    def __init__(self):
        self.admin_role = 'admin'
        self.queries = []
        self.fail_tables = set()
        self.member_count = 0
        self.order_count = 0
        self.members = []
        self.orders = []
        self.order_items = []
        self.inquiries = []

    def table(self, table):
        return FakeQuery(self, table)


def member_row(member_id=MEMBER_ID, **overrides):
    row = {
        'member_id': member_id,
        'member_id_text': member_id,
        'profile_exists': True,
        'auth_user_exists': True,
        'display_name': '동명이인',
        'nickname': None,
        'email': None,
        'phone': None,
        'account_role': 'customer',
        'created_at': '2024-01-01T00:00:00Z',
        'last_sign_in_at': None,
        'login_providers': ['kakao'],
    }
    row.update(overrides)
    return row


def order_row(order_id, user_id, order_number):
    return {
        'id': order_id,
        'user_id': user_id,
        'order_number': order_number,
        'status': 'PAID',
        'created_at': '2024-02-01T00:00:00Z',
        'total_amount': 15000,
        'payment_amount': 15000,
        'recipient_name': '수령인',
    }


class AdminMemberRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='member-route-test')
        self.client = self.app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 'admin-user'

    def test_logged_out_member_route_redirects_to_login(self):
        with patch('app.routes.admin.get_supabase_admin_client') as get_client:
            response = self.client.get('/admin/members')

        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.location)
        get_client.assert_not_called()

    def test_member_list_and_detail_require_server_side_admin_role(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.admin_role = 'customer'

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            list_response = self.client.get('/admin/members')
            detail_response = self.client.get(f'/admin/members/{MEMBER_ID}')

        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(detail_response.status_code, 403)

    def test_member_search_filters_server_side_and_preserves_return_conditions(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.member_count = 21
        db.members = [member_row(nickname='Fashion Fan')]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(
                '/admin/members?q=Fashion+Fan&joined_from=2024-01-01&joined_to=2024-01-31&provider=kakao&page=2'
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('21', body)
        self.assertIn('현재 페이지', body)
        query = next(query for table, query in db.queries if table == 'admin_member_directory')
        filters = query.calls
        search_filter = next(call[1] for call in filters if call[0] == 'or')
        self.assertIn('display_name.ilike.', search_filter)
        self.assertIn('nickname.ilike.', search_filter)
        self.assertIn('email.ilike.', search_filter)
        self.assertIn('member_id_text.ilike.', search_filter)
        self.assertIn(('contains', 'login_providers', ['kakao']), filters)
        self.assertIn(('gte', 'created_at', '2023-12-31T15:00:00+00:00'), filters)
        self.assertIn(('lt', 'created_at', '2024-01-31T15:00:00+00:00'), filters)
        self.assertIn(('range', 20, 39), filters)
        select_call = next(call for call in filters if call[0] == 'select')
        self.assertEqual(select_call[2].get('count'), 'exact')
        self.assertNotIn('phone', select_call[1][0])
        self.assertNotIn('last_sign_in_at', select_call[1][0])
        self.assertNotIn('address', select_call[1][0])
        self.assertIn(f'return_q=Fashion+Fan', body)
        self.assertIn('return_provider=kakao', body)
        self.assertFalse(any(call[0] in ('insert', 'update', 'delete') for _, item_query in db.queries for call in item_query.calls))

    def test_page_beyond_results_is_requeried_at_last_valid_offset(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.member_count = 21
        db.members = [member_row()]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/members?page=99')

        self.assertEqual(response.status_code, 200)
        directory_queries = [query for table, query in db.queries if table == 'admin_member_directory']
        ranges = [call for query in directory_queries for call in query.calls if call[0] == 'range']
        self.assertEqual(ranges, [('range', 1960, 1979), ('range', 20, 39)])

    def test_invalid_join_date_is_not_presented_as_empty_members(self):
        self.sign_in()
        db = FakeSupabaseClient()

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/members?joined_from=not-a-date')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('가입 기간을 확인해주세요.', body)
        self.assertIn('검색 조건을 확인할 수 없습니다.', body)
        self.assertNotIn('등록된 회원이 없습니다.', body)
        self.assertFalse(any(table == 'admin_member_directory' for table, _ in db.queries))

    def test_kakao_without_email_is_rendered_and_user_content_is_escaped(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.member_count = 1
        db.members = [member_row(display_name='<script>alert(1)</script>', login_providers=['kakao'])]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/members')

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('이메일 미제공', body)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('<script>alert(1)</script>', body)

    def test_missing_profile_is_reported_without_creating_one(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.member_count = 1
        db.members = [member_row(profile_exists=False)]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/members')

        self.assertEqual(response.status_code, 200)
        self.assertIn('프로필 연결 누락', response.get_data(as_text=True))
        self.assertFalse(any(call[0] in ('insert', 'update', 'delete') for _, query in db.queries for call in query.calls))

    def test_member_detail_only_queries_same_member_orders_and_shows_recent_five(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.members = [member_row()]
        db.order_count = 6
        db.orders = [order_row('order-1', MEMBER_ID, 'ORDER-OWN'), order_row('order-2', OTHER_MEMBER_ID, 'ORDER-OTHER')]
        db.order_items = [{'order_id': 'order-1', 'product_name': 'Coat'}]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/admin/members/{MEMBER_ID}')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('ORDER-OWN', body)
        self.assertNotIn('ORDER-OTHER', body)
        self.assertIn('Coat', body)
        self.assertIn('총 주문', body)
        self.assertIn('6', body)
        self.assertIn('문의 내역', body)
        self.assertIn('이 회원이 등록한 문의가 없습니다.', body)
        order_query = next(query for table, query in db.queries if table == 'orders')
        self.assertIn(('eq', 'user_id', MEMBER_ID), order_query.calls)
        select_call = next(call for call in order_query.calls if call[0] == 'select')
        self.assertEqual(select_call[2].get('count'), 'exact')
        self.assertNotIn('shipping_address', select_call[1][0])
        self.assertNotIn('recipient_phone', select_call[1][0])
        self.assertIn(('limit', 5), order_query.calls)
        self.assertFalse(any(call[0] in ('insert', 'update', 'delete') for _, query in db.queries for call in query.calls))

    def test_member_orders_page_is_filtered_by_member_id(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.members = [member_row()]
        db.order_count = 1
        db.orders = [order_row('order-1', MEMBER_ID, 'ORDER-OWN'), order_row('order-2', OTHER_MEMBER_ID, 'ORDER-OTHER')]
        db.order_items = [{'order_id': 'order-1', 'product_name': 'Coat'}]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/admin/orders?member_id={MEMBER_ID}')

        self.assertEqual(response.status_code, 200)
        self.assertIn('ORDER-OWN', response.get_data(as_text=True))
        self.assertNotIn('ORDER-OTHER', response.get_data(as_text=True))
        order_query = next(query for table, query in db.queries if table == 'orders')
        self.assertIn(('eq', 'user_id', MEMBER_ID), order_query.calls)
        select_call = next(call for call in order_query.calls if call[0] == 'select')
        self.assertEqual(select_call[2].get('count'), 'exact')
        self.assertNotIn('shipping_address', select_call[1][0])
        self.assertNotIn('recipient_phone', select_call[1][0])

    def test_member_detail_shows_only_inquiries_for_that_uuid(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.members = [member_row()]
        db.inquiries = [{
            'id': '33333333-3333-4333-8333-333333333333', 'user_id': MEMBER_ID,
            'inquiry_number': 8, 'inquiry_type': 'delivery', 'title': '회원 배송 문의',
            'status': 'pending', 'created_at': '2026-09-01T00:00:00Z',
        }, {
            'id': '44444444-4444-4444-8444-444444444444', 'user_id': OTHER_MEMBER_ID,
            'inquiry_number': 9, 'inquiry_type': 'other', 'title': '다른 회원 문의',
            'status': 'pending', 'created_at': '2026-09-02T00:00:00Z',
        }]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/admin/members/{MEMBER_ID}')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('회원 배송 문의', body)
        self.assertNotIn('다른 회원 문의', body)
        inquiry_query = next(query for table, query in db.queries if table == 'customer_inquiries')
        self.assertIn(('eq', 'user_id', MEMBER_ID), inquiry_query.calls)

    def test_empty_member_orders_link_back_to_that_member(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.members = [member_row()]
        db.order_count = 0

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/admin/orders?member_id={MEMBER_ID}')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('이 회원의 주문 내역이 없습니다.', body)
        self.assertIn(f'/admin/members/{MEMBER_ID}', body)
        self.assertNotIn('필터 초기화', body)

    def test_order_failure_keeps_member_information_and_does_not_show_zero(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.members = [member_row(display_name='Member Name')]
        db.fail_tables.add('orders')

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/admin/members/{MEMBER_ID}')

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Member Name', body)
        self.assertIn('주문 내역을 불러오지 못했습니다.', body)
        self.assertNotIn('총 주문 <strong>0</strong>', body)

    def test_empty_list_and_directory_failure_are_distinct(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.member_count = 0
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            empty_response = self.client.get('/admin/members')

        db.fail_tables.add('admin_member_directory')
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            failed_response = self.client.get('/admin/members')

        self.assertEqual(empty_response.status_code, 200)
        self.assertIn('등록된 회원이 없습니다.', empty_response.get_data(as_text=True))
        self.assertEqual(failed_response.status_code, 200)
        self.assertIn('회원 목록을 불러오지 못했습니다.', failed_response.get_data(as_text=True))
        self.assertNotIn('검색 결과 0명', failed_response.get_data(as_text=True))

    def test_missing_member_and_member_query_failure_are_distinct(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            missing_response = self.client.get(f'/admin/members/{MEMBER_ID}')

        db.fail_tables.add('admin_member_directory')
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            failed_response = self.client.get(f'/admin/members/{MEMBER_ID}')

        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(failed_response.status_code, 200)
        self.assertIn('회원 기본정보를 불러오지 못했습니다.', failed_response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()