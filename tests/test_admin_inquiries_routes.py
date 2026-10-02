import unittest
from unittest.mock import patch

from app import create_app


INQUIRY_ID = '11111111-1111-4111-8111-111111111111'
MEMBER_ID = '22222222-2222-4222-8222-222222222222'
ORDER_ID = '33333333-3333-4333-8333-333333333333'


class FakeResponse:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.calls = []
        self.select_options = {}

    def select(self, *args, **kwargs):
        self.calls.append(('select', args, kwargs))
        self.select_options = kwargs
        self.client.queries.setdefault(self.table, []).append(self)
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

    def or_(self, *args):
        self.calls.append(('or', *args))
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

    def execute(self):
        if self.table == 'profiles':
            return FakeResponse([{
                'id': 'admin-user', 'email': 'admin@example.invalid',
                'full_name': '관리자', 'role': self.client.role,
            }])
        if self.table == 'admin_customer_inquiries':
            wanted_id = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'id'), None)
            rows = [self.client.inquiry] if wanted_id == self.client.inquiry['id'] else ([] if wanted_id else self.client.rows)
            return FakeResponse(rows, len(rows) if self.select_options.get('count') == 'exact' else None)
        if self.table == 'customer_inquiry_reply_history':
            return FakeResponse(self.client.history)
        return FakeResponse([])


class FakeRpc:
    def __init__(self, client, name, params):
        self.client = client
        self.name = name
        self.params = params

    def execute(self):
        self.client.rpc_calls.append((self.name, self.params))
        if self.client.rpc_error:
            raise self.client.rpc_error
        return FakeResponse([{'inquiry_id': self.params['p_inquiry_id'], 'reply_version': self.params['p_expected_version'] + 1}])


class FakeSupabaseClient:
    def __init__(self):
        self.role = 'admin'
        self.inquiry = {
            'id': INQUIRY_ID, 'inquiry_number': 12, 'user_id': MEMBER_ID,
            'user_id_text': MEMBER_ID, 'author_name': '회원 · 22222222',
            'order_id': ORDER_ID, 'order_number': 'VF-1001', 'inquiry_type': 'delivery',
            'title': '배송 확인', 'content': '언제 도착하나요?', 'status': 'pending',
            'reply_text': None, 'answered_by': None, 'answered_at': None,
            'reply_updated_by': None, 'reply_updated_at': None, 'reply_version': 0,
            'created_at': '2026-09-01T00:00:00Z', 'updated_at': '2026-09-01T00:00:00Z',
        }
        self.rows = [self.inquiry]
        self.history = []
        self.queries = {}
        self.rpc_calls = []
        self.rpc_error = None

    def table(self, table):
        return FakeQuery(self, table)

    def rpc(self, name, params):
        return FakeRpc(self, name, params)


class AdminInquiryRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='admin-inquiry-test')
        self.client = self.app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 'admin-user'

    def csrf_token(self):
        with self.client.session_transaction() as session:
            return session['admin_csrf_token']

    def test_admin_role_required_for_list_and_reply(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.role = 'customer'
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            listing = self.client.get('/admin/inquiries')
            detail = self.client.get(f'/admin/inquiries/{INQUIRY_ID}')
            reply = self.client.post(f'/admin/inquiries/{INQUIRY_ID}/reply', data={
                'reply_text': '권한 없는 답변', 'expected_version': '0',
            })
        self.assertEqual(listing.status_code, 403)
        self.assertEqual(detail.status_code, 403)
        self.assertEqual(reply.status_code, 403)
        self.assertEqual(db.rpc_calls, [])

    def test_list_filters_count_and_oldest_pending_order(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.rows = [db.inquiry]
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(
                '/admin/inquiries?q=배송&author=회원&inquiry_type=delivery&status=pending'
                '&from_date=2026-09-01&to_date=2026-09-30&member_id=' + MEMBER_ID
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('검색 결과', response.get_data(as_text=True))
        query = db.queries['admin_customer_inquiries'][0]
        self.assertEqual(query.select_options.get('count'), 'exact')
        self.assertIn(('eq', 'status', 'pending'), query.calls)
        self.assertIn(('eq', 'user_id', MEMBER_ID), query.calls)
        self.assertTrue(any(call[0] == 'or' and 'content.ilike' in call[1] for call in query.calls))
        self.assertTrue(any(call[0] == 'or' and 'author_name.ilike' in call[1] for call in query.calls))
        self.assertTrue(any(call[0] == 'or' and 'author_nickname.ilike' in call[1] for call in query.calls))
        self.assertTrue(any(call[0] == 'gte' and call[1] == 'created_at' for call in query.calls))
        self.assertTrue(any(call[0] == 'lt' and call[1] == 'created_at' for call in query.calls))
        created_order = next(call for call in query.calls if call[0] == 'order' and call[1][0] == 'created_at')
        self.assertFalse(created_order[2].get('desc', True))

    def test_detail_links_to_member_and_order_and_shows_admin_history_only(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.history = [{
            'reply_version': 2, 'action': 'edited', 'previous_reply': '이전 안내',
            'new_reply': '최신 안내', 'changed_by': 'admin-user', 'changed_at': '2026-09-02T00:00:00Z',
        }]
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/admin/inquiries/{INQUIRY_ID}?status=pending&q=배송&page=2')

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/admin/members/{MEMBER_ID}', body)
        self.assertIn(f'/admin/orders/{ORDER_ID}', body)
        self.assertIn('이전 안내', body)
        self.assertIn('답변 수정', body)
        self.assertIn('status=pending', body)

    def test_reply_uses_admin_identity_csrf_and_atomic_rpc(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            self.client.get(f'/admin/inquiries/{INQUIRY_ID}')
            csrf = self.csrf_token()
            response = self.client.post(
                f'/admin/inquiries/{INQUIRY_ID}/reply?status=pending&page=3',
                data={'csrf_token': csrf, 'reply_text': '배송은 내일 도착할 예정입니다.', 'expected_version': '0'},
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn('status=pending', response.location)
        self.assertEqual(len(db.rpc_calls), 1)
        name, params = db.rpc_calls[0]
        self.assertEqual(name, 'save_customer_inquiry_reply')
        self.assertEqual(params['p_admin_id'], 'admin-user')
        self.assertEqual(params['p_expected_version'], 0)
        self.assertEqual(params['p_reply'], '배송은 내일 도착할 예정입니다.')

    def test_reply_requires_csrf_and_preserves_draft_when_save_fails(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.rpc_error = RuntimeError('database unavailable')
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            self.client.get(f'/admin/inquiries/{INQUIRY_ID}')
            csrf = self.csrf_token()
            missing_csrf = self.client.post(f'/admin/inquiries/{INQUIRY_ID}/reply', data={'reply_text': '답변', 'expected_version': '0'})
            response = self.client.post(
                f'/admin/inquiries/{INQUIRY_ID}/reply',
                data={'csrf_token': csrf, 'reply_text': '입력한 답변 유지', 'expected_version': '0'},
            )

        self.assertEqual(missing_csrf.status_code, 400)
        self.assertEqual(response.status_code, 503)
        body = response.get_data(as_text=True)
        self.assertIn('입력한 답변 유지', body)
        self.assertIn('답변 대기', body)
        self.assertNotIn('답변 완료', body)

    def test_stale_reply_version_does_not_silently_overwrite(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.inquiry.update({
            'status': 'answered', 'reply_text': '다른 관리자가 저장한 최신 답변',
            'reply_version': 1, 'answered_by': 'admin-2',
            'answered_at': '2026-09-02T00:00:00Z', 'reply_updated_by': 'admin-2',
            'reply_updated_at': '2026-09-02T00:00:00Z',
        })
        db.rpc_error = RuntimeError('inquiry_reply_version_conflict')
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            self.client.get(f'/admin/inquiries/{INQUIRY_ID}')
            csrf = self.csrf_token()
            response = self.client.post(
                f'/admin/inquiries/{INQUIRY_ID}/reply',
                data={'csrf_token': csrf, 'reply_text': '내가 작성한 새 답변', 'expected_version': '0'},
            )

        self.assertEqual(response.status_code, 409)
        body = response.get_data(as_text=True)
        self.assertIn('다른 관리자가 답변을 먼저 수정했습니다.', body)
        self.assertIn('내가 작성한 새 답변', body)
        self.assertIn('다른 관리자가 저장한 최신 답변', body)

    def test_blank_or_oversized_reply_never_calls_rpc(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            self.client.get(f'/admin/inquiries/{INQUIRY_ID}')
            csrf = self.csrf_token()
            blank = self.client.post(f'/admin/inquiries/{INQUIRY_ID}/reply', data={
                'csrf_token': csrf, 'reply_text': ' \n ', 'expected_version': '0',
            })
            oversized = self.client.post(f'/admin/inquiries/{INQUIRY_ID}/reply', data={
                'csrf_token': csrf, 'reply_text': '답' * 5001, 'expected_version': '0',
            })
        self.assertEqual(blank.status_code, 400)
        self.assertEqual(oversized.status_code, 400)
        self.assertEqual(db.rpc_calls, [])


if __name__ == '__main__':
    unittest.main()