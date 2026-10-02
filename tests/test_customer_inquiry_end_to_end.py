import unittest
from unittest.mock import patch

from app import create_app
from app.utils.admin_work_alerts import load_work_alerts


MEMBER_A = '11111111-1111-4111-8111-111111111111'
MEMBER_B = '22222222-2222-4222-8222-222222222222'
ADMIN_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
ORDER_A = '33333333-3333-4333-8333-333333333333'
INQUIRY_ID = '55555555-5555-4555-8555-555555555555'


class FakeResponse:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class SharedQuery:
    def __init__(self, database, table):
        self.database = database
        self.table = table
        self.filters = []
        self.options = {}
        self.payload = None
        self.start = None
        self.end = None

    def select(self, *args, **kwargs):
        self.options = kwargs
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def gte(self, column, value):
        self.filters.append((column, value))
        return self

    def lt(self, column, value):
        self.filters.append((column, value))
        return self

    def lte(self, column, value):
        self.filters.append((column, value))
        return self

    def contains(self, column, value):
        self.filters.append((column, value))
        return self

    def or_(self, expression):
        self.filters.append(('or', expression))
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def limit(self, limit):
        self.end = limit - 1
        return self

    def execute(self):
        if self.table == 'profiles':
            return FakeResponse([{
                'id': ADMIN_ID, 'email': 'support@example.invalid',
                'full_name': '고객센터 관리자', 'role': self.database.admin_role,
            }])
        if self.table == 'orders':
            rows = [row for row in self.database.orders if self._matches(row)]
            return FakeResponse(rows[:100])
        if self.table == 'customer_inquiries' and self.payload is not None:
            duplicate = next((row for row in self.database.inquiries if
                              row['user_id'] == self.payload['user_id'] and
                              row['submission_token'] == self.payload['submission_token']), None)
            if duplicate:
                raise RuntimeError('duplicate submission token')
            row = {
                **self.payload, 'id': INQUIRY_ID, 'inquiry_number': 1,
                'status': 'pending', 'reply_text': None, 'answered_by': None,
                'answered_at': None, 'reply_updated_by': None,
                'reply_updated_at': None, 'reply_version': 0,
                'created_at': '2026-10-01T00:00:00Z', 'updated_at': '2026-10-01T00:00:00Z',
            }
            self.database.inquiries.append(row)
            return FakeResponse([{'id': INQUIRY_ID}])
        if self.table in ('customer_inquiries', 'admin_customer_inquiries'):
            rows = [row for row in self.database.inquiries if self._matches(row)]
            if self.table == 'admin_customer_inquiries':
                rows = [self.database.as_admin_view(row) for row in rows]
            count = len(rows) if self.options.get('count') == 'exact' else None
            if self.start is not None:
                rows = rows[self.start:self.end + 1]
            elif self.end is not None:
                rows = rows[:self.end + 1]
            return FakeResponse(rows, count)
        if self.table == 'customer_inquiry_reply_history':
            return FakeResponse([entry for entry in self.database.history if self._matches(entry)])
        return FakeResponse([], 0 if self.options.get('count') == 'exact' else None)

    def _matches(self, row):
        return all(row.get(column) == value for column, value in self.filters if column != 'or')


class SharedSupabase:
    def __init__(self):
        self.admin_role = 'admin'
        self.orders = [{
            'id': ORDER_A, 'user_id': MEMBER_A, 'order_number': 'VF-TEST-1',
            'created_at': '2026-09-30T00:00:00Z', 'total_amount': 12000,
        }]
        self.inquiries = []
        self.history = []

    def table(self, table):
        return SharedQuery(self, table)

    def as_admin_view(self, row):
        return {
            **row,
            'user_id_text': row['user_id'],
            'author_name': '카카오 회원 · ' + row['user_id'][:8],
            'author_nickname': None,
            'order_number': 'VF-TEST-1' if row.get('order_id') == ORDER_A else None,
        }

    def rpc(self, name, params):
        database = self

        class Rpc:
            def execute(self):
                if name != 'save_customer_inquiry_reply':
                    raise AssertionError('unexpected RPC')
                row = next(row for row in database.inquiries if row['id'] == params['p_inquiry_id'])
                if row['reply_version'] != params['p_expected_version']:
                    raise RuntimeError('inquiry_reply_version_conflict')
                if row['reply_text'] != params['p_reply']:
                    changed_at = '2026-10-02T00:00:00Z'
                    version = row['reply_version'] + 1
                    database.history.append({
                        'inquiry_id': row['id'], 'reply_version': version,
                        'action': 'answered' if row['reply_text'] is None else 'edited',
                        'previous_reply': row['reply_text'], 'new_reply': params['p_reply'],
                        'changed_by': params['p_admin_id'], 'changed_at': changed_at,
                    })
                    row.update({
                        'reply_text': params['p_reply'], 'status': 'answered',
                        'answered_by': row['answered_by'] or params['p_admin_id'],
                        'answered_at': row['answered_at'] or changed_at,
                        'reply_updated_by': params['p_admin_id'],
                        'reply_updated_at': changed_at, 'reply_version': version,
                    })
                return FakeResponse([{'inquiry_id': row['id']}])

        return Rpc()


class CustomerInquiryEndToEndTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY='inquiry-e2e-test')
        self.customer_a = app.test_client()
        self.customer_b = app.test_client()
        self.admin = app.test_client()
        self.db = SharedSupabase()
        with self.customer_a.session_transaction() as session:
            session['user_id'] = MEMBER_A
        with self.customer_b.session_transaction() as session:
            session['user_id'] = MEMBER_B
        with self.admin.session_transaction() as session:
            session['user_id'] = ADMIN_ID
        self.patches = (
            patch('app.routes.inquiries.get_supabase_admin_client', return_value=self.db),
            patch('app.routes.admin.get_supabase_admin_client', return_value=self.db),
        )
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def csrf(self, client):
        with client.session_transaction() as session:
            return session['admin_csrf_token']

    def test_member_to_admin_reply_to_private_customer_confirmation(self):
        form_page = self.customer_a.get('/mypage/inquiries/new')
        self.assertEqual(form_page.status_code, 200)
        create_response = self.customer_a.post('/mypage/inquiries/new', data={
            'csrf_token': self.csrf(self.customer_a),
            'submission_token': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            'inquiry_type': 'delivery', 'title': '도착 일정 문의',
            'content': '주문 상품의 배송 일정을 확인해주세요.', 'order_id': ORDER_A,
        })
        self.assertEqual(create_response.status_code, 302)
        self.assertEqual(len(self.db.inquiries), 1)
        self.assertEqual(self.db.inquiries[0]['user_id'], MEMBER_A)

        pending_alert = load_work_alerts(self.db)['inquiries']
        self.assertEqual(pending_alert['count'], 1)
        self.assertEqual(pending_alert['items'][0]['id'], INQUIRY_ID)
        admin_list = self.admin.get('/admin/inquiries?status=pending')
        self.assertEqual(admin_list.status_code, 200)
        self.assertIn('검색 결과', admin_list.get_data(as_text=True))
        self.assertIn('도착 일정 문의', admin_list.get_data(as_text=True))

        admin_detail = self.admin.get(f'/admin/inquiries/{INQUIRY_ID}?status=pending')
        self.assertEqual(admin_detail.status_code, 200)
        answer_response = self.admin.post(
            f'/admin/inquiries/{INQUIRY_ID}/reply?status=pending',
            data={
                'csrf_token': self.csrf(self.admin),
                'expected_version': '0',
                'reply_text': '배송은 내일 도착 예정입니다.',
            },
        )
        self.assertEqual(answer_response.status_code, 302)
        self.assertEqual(self.db.inquiries[0]['status'], 'answered')
        self.assertEqual(len(self.db.history), 1)
        self.assertEqual(load_work_alerts(self.db)['inquiries']['count'], 0)
        self.assertEqual(self.admin.get('/admin/inquiries?status=pending').status_code, 200)
        self.assertNotIn('도착 일정 문의', self.admin.get('/admin/inquiries?status=pending').get_data(as_text=True))

        customer_detail = self.customer_a.get(f'/mypage/inquiries/{INQUIRY_ID}')
        customer_body = customer_detail.get_data(as_text=True)
        self.assertEqual(customer_detail.status_code, 200)
        self.assertIn('배송은 내일 도착 예정입니다.', customer_body)
        self.assertIn('VIBE-FASHION 고객센터 답변', customer_body)
        self.assertNotIn(ADMIN_ID, customer_body)
        self.assertEqual(self.customer_b.get(f'/mypage/inquiries/{INQUIRY_ID}').status_code, 404)


if __name__ == '__main__':
    unittest.main()