import unittest
from unittest.mock import patch

from app import create_app


USER_ID = '11111111-1111-4111-8111-111111111111'
OTHER_USER_ID = '22222222-2222-4222-8222-222222222222'
ORDER_ID = '33333333-3333-4333-8333-333333333333'
OTHER_ORDER_ID = '44444444-4444-4444-8444-444444444444'
INQUIRY_ID = '55555555-5555-4555-8555-555555555555'
CREATED_INQUIRY_ID = '66666666-6666-4666-8666-666666666666'


class FakeResponse:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.calls = []
        self.payload = None

    def select(self, *args, **kwargs):
        self.calls.append(('select', args, kwargs))
        return self

    def insert(self, payload):
        self.payload = payload
        self.calls.append(('insert', payload))
        return self

    def eq(self, *args):
        self.calls.append(('eq', *args))
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
        if self.table == 'orders':
            wanted_id = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'id'), None)
            wanted_user = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'user_id'), None)
            rows = [row for row in self.client.orders if (not wanted_id or row['id'] == wanted_id) and (not wanted_user or row['user_id'] == wanted_user)]
            return FakeResponse(rows)
        if self.table == 'customer_inquiries' and self.payload is not None:
            self.client.inserted.append(self.payload)
            self.client.inquiries.append({
                **self.payload,
                'id': CREATED_INQUIRY_ID,
                'inquiry_number': 2,
                'status': 'pending',
                'created_at': '2026-09-03T00:00:00Z',
                'answered_at': None,
                'reply_updated_at': None,
                'reply_version': 0,
                'reply_text': None,
            })
            return FakeResponse([{'id': CREATED_INQUIRY_ID}])
        if self.table == 'customer_inquiries':
            wanted_id = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'id'), None)
            wanted_user = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'user_id'), None)
            wanted_token = next((call[2] for call in self.calls if call[0] == 'eq' and call[1] == 'submission_token'), None)
            rows = [row for row in self.client.inquiries if (not wanted_id or row['id'] == wanted_id) and (not wanted_user or row['user_id'] == wanted_user) and (not wanted_token or row['submission_token'] == wanted_token)]
            count_requested = bool(self.calls and self.calls[0][0] == 'select' and self.calls[0][2].get('count') == 'exact')
            return FakeResponse(rows, len(rows) if count_requested else None)
        return FakeResponse([])


class FakeSupabaseClient:
    def __init__(self):
        self.orders = [
            {'id': ORDER_ID, 'user_id': USER_ID, 'order_number': 'VF-1001', 'created_at': '2026-09-01T00:00:00Z', 'total_amount': 25000},
            {'id': OTHER_ORDER_ID, 'user_id': OTHER_USER_ID, 'order_number': 'VF-2002', 'created_at': '2026-09-02T00:00:00Z', 'total_amount': 45000},
        ]
        self.inquiries = [{
            'id': INQUIRY_ID, 'inquiry_number': 1, 'user_id': USER_ID,
            'inquiry_type': 'delivery', 'title': '배송 확인', 'content': '언제 도착하나요?',
            'status': 'pending', 'created_at': '2026-09-03T00:00:00Z',
            'answered_at': None, 'reply_updated_at': None, 'reply_version': 0,
            'reply_text': None, 'order_id': ORDER_ID, 'submission_token': 'token',
        }]
        self.inserted = []

    def table(self, table):
        return FakeQuery(self, table)


class CustomerInquiryRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='customer-inquiry-test')
        self.client = self.app.test_client()

    def sign_in(self, user_id=USER_ID):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id

    def csrf_token(self):
        with self.client.session_transaction() as session:
            return session['admin_csrf_token']

    def test_customer_routes_require_login(self):
        with patch('app.routes.inquiries.get_supabase_admin_client') as get_client:
            response = self.client.get('/mypage/inquiries')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.location)
        get_client.assert_not_called()

    def test_create_uses_session_uuid_and_checks_linked_order_owner(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            form = self.client.get('/mypage/inquiries/new')
            self.assertEqual(form.status_code, 200)
            token = self.csrf_token()
            response = self.client.post('/mypage/inquiries/new', data={
                'csrf_token': token,
                'submission_token': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                'user_id': OTHER_USER_ID,
                'status': 'answered',
                'reply_text': '고객이 위조한 답변',
                'answered_by': OTHER_USER_ID,
                'inquiry_type': 'delivery',
                'title': '배송 문의',
                'content': '확인 부탁드립니다.',
                'order_id': ORDER_ID,
            })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(db.inserted[0]['user_id'], USER_ID)
        self.assertEqual(db.inserted[0]['order_id'], ORDER_ID)
        self.assertEqual(db.inserted[0]['status'] if 'status' in db.inserted[0] else 'pending', 'pending')
        self.assertNotIn('reply_text', db.inserted[0])
        self.assertNotIn('answered_by', db.inserted[0])
        self.assertNotIn('user_id', str(form.get_data(as_text=True)))

        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            token = self.client.get('/mypage/inquiries/new')
            csrf = self.csrf_token()
            response = self.client.post('/mypage/inquiries/new', data={
                'csrf_token': csrf,
                'submission_token': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
                'inquiry_type': 'delivery', 'title': '주문 문의', 'content': '다른 회원 주문',
                'order_id': OTHER_ORDER_ID,
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn('본인 주문만 문의에 연결', response.get_data(as_text=True))
        self.assertEqual(len(db.inserted), 1)

    def test_kakao_without_email_can_read_only_uuid_owned_inquiries(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            listing = self.client.get('/mypage/inquiries')
            own_detail = self.client.get(f'/mypage/inquiries/{INQUIRY_ID}')

        self.assertEqual(listing.status_code, 200)
        self.assertIn('배송 확인', listing.get_data(as_text=True))
        self.assertEqual(own_detail.status_code, 200)
        self.assertIn('언제 도착하나요?', own_detail.get_data(as_text=True))
        self.assertIn('답변 대기', own_detail.get_data(as_text=True))
        self.assertNotIn('answered_by', own_detail.get_data(as_text=True))
        self.assertNotIn('changed_by', own_detail.get_data(as_text=True))

    def test_other_member_cannot_read_inquiry_by_changing_id(self):
        self.sign_in(OTHER_USER_ID)
        db = FakeSupabaseClient()
        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/mypage/inquiries/{INQUIRY_ID}')

        self.assertEqual(response.status_code, 404)

    def test_reposting_same_submission_token_does_not_duplicate_inquiry(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            self.client.get('/mypage/inquiries/new')
            csrf = self.csrf_token()
            form = {
                'csrf_token': csrf,
                'submission_token': 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
                'inquiry_type': 'other', 'title': '중복 방지', 'content': '같은 요청 재전송',
            }
            first = self.client.post('/mypage/inquiries/new', data=form)
            second = self.client.post('/mypage/inquiries/new', data=form)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertIn(CREATED_INQUIRY_ID, second.location)
        self.assertEqual(len(db.inserted), 1)

    def test_customer_sees_latest_edited_reply_without_admin_identity(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.inquiries[0].update({
            'status': 'answered',
            'content': '<script>alert(1)</script> 원문',
            'reply_text': '<b>최신 답변</b>\n배송 예정입니다.',
            'answered_at': '2026-09-04T00:00:00Z',
            'reply_updated_at': '2026-09-05T00:00:00Z',
            'reply_version': 2,
            'answered_by': 'internal-admin-id',
            'reply_updated_by': 'internal-admin-id',
        })
        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            response = self.client.get(f'/mypage/inquiries/{INQUIRY_ID}')

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('VIBE-FASHION 고객센터 답변', body)
        self.assertIn('답변이 수정되었습니다.', body)
        self.assertIn('&lt;b&gt;최신 답변&lt;/b&gt;', body)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', body)
        self.assertNotIn('internal-admin-id', body)

    def test_customer_write_requires_csrf_and_valid_lengths(self):
        self.sign_in()
        db = FakeSupabaseClient()
        with patch('app.routes.inquiries.get_supabase_admin_client', return_value=db):
            self.client.get('/mypage/inquiries/new')
            response = self.client.post('/mypage/inquiries/new', data={
                'submission_token': 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
                'inquiry_type': 'other', 'title': 'x' * 101, 'content': 'body',
            })
            self.assertEqual(response.status_code, 400)
            csrf = self.csrf_token()
            response = self.client.post('/mypage/inquiries/new', data={
                'csrf_token': csrf,
                'submission_token': 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
                'inquiry_type': 'other', 'title': '제목', 'content': '   ',
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn('문의 내용을 입력', response.get_data(as_text=True))
        self.assertEqual(db.inserted, [])


if __name__ == '__main__':
    unittest.main()