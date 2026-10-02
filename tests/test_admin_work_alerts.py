import unittest

from app.utils.admin_work_alerts import load_work_alerts


class FakeResponse:
    def __init__(self, data, count):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.calls = []

    def select(self, columns, **kwargs):
        self.calls.append(('select', columns, kwargs))
        self.client.queries.setdefault(self.table_name, []).append(self)
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
        self.calls.append(('order', *args, kwargs))
        return self

    def limit(self, value):
        self.calls.append(('limit', value))
        return self

    def execute(self):
        if self.table_name in self.client.fail_tables:
            raise RuntimeError('simulated query failure')
        return self.client.responses[self.table_name]


class FakeSupabaseClient:
    def __init__(self, responses, fail_tables=()):
        self.responses = responses
        self.fail_tables = set(fail_tables)
        self.queries = {}

    def table(self, table_name):
        return FakeQuery(self, table_name)


class AdminWorkAlertTests(unittest.TestCase):
    def test_exact_counts_and_preview_limits_are_kept_separate(self):
        responses = {
            'admin_active_inventory_items': FakeResponse([], 23),
            'admin_unshipped_orders': FakeResponse([], 11),
            'admin_pending_refund_orders': FakeResponse([], 4),
        }
        client = FakeSupabaseClient(responses)

        alerts = load_work_alerts(client)

        self.assertEqual(alerts['out_of_stock']['count'], 23)
        self.assertEqual(alerts['low_stock']['count'], 23)
        self.assertEqual(alerts['unshipped']['count'], 11)
        self.assertEqual(alerts['refunds']['count'], 4)
        self.assertEqual(alerts['inquiries']['state'], 'unavailable')
        self.assertIsNone(alerts['inquiries']['count'])
        for queries in client.queries.values():
            for query in queries:
                select_call = next(call for call in query.calls if call[0] == 'select')
                self.assertEqual(select_call[2].get('count'), 'exact')
                self.assertIn(('limit', 5), query.calls)
                self.assertNotIn('recipient_phone', select_call[1])
                self.assertNotIn('shipping_address', select_call[1])

    def test_zero_rows_are_ready_but_a_failed_query_is_not_zero(self):
        responses = {
            'admin_active_inventory_items': FakeResponse([], 0),
            'admin_unshipped_orders': FakeResponse([], 0),
            'admin_pending_refund_orders': FakeResponse([], 0),
        }
        client = FakeSupabaseClient(responses, fail_tables={'admin_unshipped_orders'})

        alerts = load_work_alerts(client)

        self.assertEqual(alerts['out_of_stock']['state'], 'ready')
        self.assertEqual(alerts['out_of_stock']['count'], 0)
        self.assertEqual(alerts['unshipped']['state'], 'error')
        self.assertIsNone(alerts['unshipped']['count'])
        self.assertEqual(alerts['refunds']['state'], 'ready')
        self.assertEqual(alerts['refunds']['count'], 0)

    def test_inventory_alert_filters_are_disjoint(self):
        responses = {
            'admin_active_inventory_items': FakeResponse([], 0),
            'admin_unshipped_orders': FakeResponse([], 0),
            'admin_pending_refund_orders': FakeResponse([], 0),
        }
        client = FakeSupabaseClient(responses)

        load_work_alerts(client)

        inventory_queries = client.queries['admin_active_inventory_items']
        out_filters = inventory_queries[0].calls
        low_filters = inventory_queries[1].calls
        self.assertIn(('eq', 'stock', 0), out_filters)
        self.assertIn(('gte', 'stock', 1), low_filters)
        self.assertIn(('lte', 'stock', 5), low_filters)


if __name__ == '__main__':
    unittest.main()