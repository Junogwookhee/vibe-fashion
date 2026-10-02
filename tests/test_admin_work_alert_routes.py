import os
import unittest
from unittest.mock import patch

from app import create_app
from app.utils.supabase_client import get_supabase_admin_client


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
        self.client.queries.append((self.table, self))
        return self

    def update(self, payload):
        self.payload = payload
        self.calls.append(('update', payload))
        self.client.queries.append((self.table, self))
        return self

    def eq(self, *args):
        self.calls.append(('eq', *args))
        return self

    def gte(self, *args):
        self.calls.append(('gte', *args))
        return self

    def lte(self, *args):
        self.calls.append(('lte', *args))
        return self

    def order(self, *args, **kwargs):
        self.calls.append(('order', args, kwargs))
        return self

    def limit(self, *args):
        self.calls.append(('limit', *args))
        return self

    def range(self, *args):
        self.calls.append(('range', *args))
        return self

    def in_(self, *args):
        self.calls.append(('in', *args))
        return self

    def execute(self):
        if self.table == 'profiles':
            return FakeResponse([{
                'id': 'admin-user',
                'email': 'admin@example.invalid',
                'full_name': 'Admin',
                'role': self.client.role,
            }])
        if self.table == 'admin_active_inventory_items':
            return FakeResponse(self.client.inventory_rows, self.client.inventory_count)
        if self.table == 'admin_unshipped_orders':
            return FakeResponse(self.client.unshipped_rows, self.client.unshipped_count)
        if self.table == 'admin_pending_refund_orders':
            return FakeResponse(self.client.refund_rows, self.client.refund_count)
        if self.table == 'admin_customer_inquiries':
            return FakeResponse(self.client.inquiry_rows, self.client.inquiry_count)
        if self.table == 'orders':
            return FakeResponse(self.client.orders)
        if self.table == 'order_items':
            return FakeResponse(self.client.order_items)
        if self.table == 'refunds' and self.payload is not None:
            return FakeResponse([{'id': 'refund-1'}])
        if self.table == 'refunds':
            return FakeResponse(self.client.refund_details)
        return FakeResponse([])


class FakeSupabaseClient:
    def __init__(self, role='admin'):
        self.role = role
        self.queries = []
        self.inventory_rows = []
        self.inventory_count = 0
        self.unshipped_rows = []
        self.unshipped_count = 0
        self.refund_rows = []
        self.refund_count = 0
        self.orders = []
        self.order_items = []
        self.refund_details = []
        self.inquiry_rows = []
        self.inquiry_count = 0

    def table(self, table):
        return FakeQuery(self, table)


class AdminWorkAlertRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='test-secret')
        self.client = self.app.test_client()

    def sign_in(self, user_id='admin-user'):
        with self.client.session_transaction() as session:
            session['user_id'] = user_id

    def test_existing_admin_pages_render_without_task_context(self):
        self.sign_in()
        db = FakeSupabaseClient()

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            for path in ('/admin/dashboard', '/admin/inventory', '/admin/orders'):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)

    def test_work_alert_api_denies_non_admin(self):
        self.sign_in()
        with patch('app.routes.admin.get_supabase_admin_client', return_value=FakeSupabaseClient(role='customer')):
            response = self.client.get('/admin/api/work-alerts')
        self.assertEqual(response.status_code, 403)

    def test_work_alert_api_returns_zero_only_for_ready_queries(self):
        self.sign_in()
        db = FakeSupabaseClient()

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/api/work-alerts')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['alerts']['refunds']['count'], 0)
        self.assertEqual(response.json['alerts']['refunds']['state'], 'ready')
        self.assertEqual(response.json['alerts']['inquiries']['state'], 'ready')
        self.assertEqual(response.json['alerts']['inquiries']['count'], 0)
        self.assertNotIn('recipient_phone', str(response.json))
        self.assertNotIn('shipping_address', str(response.json))

    def test_inventory_work_task_uses_exact_count_and_disjoint_low_stock_filter(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.inventory_rows = [{
            'target_type': 'option', 'target_id': 'option-1', 'product_id': 'product-1',
            'product_name': 'Coat', 'slug': 'coat', 'thumbnail_url': None,
            'category_name': 'Outerwear', 'option_id': 'option-1', 'option_info': 'M', 'stock': 3,
        }]
        db.inventory_count = 8

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/inventory?task=low_stock')

        self.assertEqual(response.status_code, 200)
        self.assertIn('inventory-option-1', response.get_data(as_text=True))
        query = next(query for table, query in db.queries if table == 'admin_active_inventory_items')
        self.assertIn(('gte', 'stock', 1), query.calls)
        self.assertIn(('lte', 'stock', 5), query.calls)
        select_call = next(call for call in query.calls if call[0] == 'select')
        self.assertEqual(select_call[2].get('count'), 'exact')

    def test_refund_task_lists_each_view_order_once_without_period_filter(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.refund_rows = [{
            'id': 'order-1', 'order_number': 'ORD-1', 'order_status': 'PAID',
            'requested_at': '2024-01-01T00:00:00Z', 'refund_status': 'requested',
        }]
        db.refund_count = 6
        db.orders = [{
            'id': 'order-1', 'order_number': 'ORD-1', 'status': 'PAID',
            'created_at': '2024-01-01T00:00:00Z', 'payment_amount': 100, 'total_amount': 100,
        }]
        db.order_items = [
            {'order_id': 'order-1', 'product_name': 'Coat', 'quantity': 1},
            {'order_id': 'order-1', 'product_name': 'Shirt', 'quantity': 2},
        ]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            response = self.client.get('/admin/orders?task=refunds&period=month')

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertEqual(body.count('ORD-1'), 1)
        self.assertIn('6', body)
        view_query = next(query for table, query in db.queries if table == 'admin_pending_refund_orders')
        select_call = next(call for call in view_query.calls if call[0] == 'select')
        self.assertEqual(select_call[2].get('count'), 'exact')
        self.assertTrue(any(call[0] == 'range' for call in view_query.calls))
        orders_query = next(query for table, query in db.queries if table == 'orders')
        orders_select = next(call for call in orders_query.calls if call[0] == 'select')
        self.assertNotIn('recipient_name', orders_select[1][0])
        self.assertNotIn('recipient_phone', orders_select[1][0])

    def test_refund_review_records_only_requested_transition_with_csrf(self):
        self.sign_in()
        db = FakeSupabaseClient()
        db.orders = [{
            'id': 'order-1', 'order_number': 'ORD-1', 'status': 'PAID',
            'created_at': '2024-01-01T00:00:00Z', 'total_amount': 100, 'payment_amount': 100,
        }]
        db.refund_details = [{
            'id': 'refund-1', 'refund_amount': 100, 'reason': 'Damaged', 'status': 'requested',
            'admin_note': None, 'created_at': '2024-01-02T00:00:00Z', 'updated_at': '2024-01-02T00:00:00Z',
        }]

        with patch('app.routes.admin.get_supabase_admin_client', return_value=db):
            detail = self.client.get('/admin/orders/order-1?from_task=refunds')
            self.assertEqual(detail.status_code, 200)
            with self.client.session_transaction() as session:
                csrf_token = session['admin_csrf_token']
            response = self.client.post(
                '/admin/orders/order-1/refunds/refund-1/review',
                data={'csrf_token': csrf_token, 'status': 'approved', 'from_task': 'refunds'},
            )

        self.assertEqual(response.status_code, 302)
        refund_query = next(query for table, query in db.queries if table == 'refunds' and query.payload)
        self.assertEqual(refund_query.payload['status'], 'approved')
        self.assertIn(('eq', 'status', 'requested'), refund_query.calls)

    def test_service_role_key_is_required_from_environment(self):
        with patch.dict(os.environ, {'SUPABASE_SERVICE_KEY': ''}), patch('app.utils.supabase_client.create_client') as create_client:
            with self.assertRaises(ValueError):
                get_supabase_admin_client()
        create_client.assert_not_called()


if __name__ == '__main__':
    unittest.main()