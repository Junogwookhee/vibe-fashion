import unittest

from app.utils.admin_members import format_member_directory_row


class AdminMemberDirectoryTests(unittest.TestCase):
    def make_row(self, **overrides):
        row = {
            'member_id': 'member-12345678',
            'display_name': None,
            'nickname': None,
            'email': None,
            'phone': None,
            'login_providers': [],
            'created_at': '2024-01-01T00:00:00Z',
            'last_sign_in_at': None,
            'account_role': 'customer',
            'profile_exists': True,
            'auth_user_exists': True,
        }
        row.update(overrides)
        return row

    def test_kakao_member_without_email_uses_uuid_and_korean_time(self):
        result = format_member_directory_row(self.make_row(
            nickname='Fashion Fan',
            login_providers=['kakao'],
            last_sign_in_at='2024-02-01T00:00:00Z',
        ))

        self.assertEqual(result['name'], 'Fashion Fan')
        self.assertEqual(result['email'], '이메일 미제공')
        self.assertEqual(result['providers'], '카카오')
        self.assertEqual(result['last_sign_in_at'], '2024-02-01 09:00')
        self.assertEqual(result['created_at'], '2024-01-01 09:00')

    def test_linked_providers_are_combined_and_synthetic_email_is_hidden(self):
        result = format_member_directory_row(self.make_row(
            email='naver_abc@naver.auth',
            login_providers=['email', 'kakao'],
        ))

        self.assertEqual(result['email'], '이메일 미제공')
        self.assertEqual(result['providers'], '이메일 · 카카오')
        self.assertEqual(result['last_sign_in_at'], '확인 가능한 기록 없음')

    def test_name_and_phone_fallbacks_are_distinguishable(self):
        result = format_member_directory_row(self.make_row())

        self.assertEqual(result['name'], '이름 미등록')
        self.assertEqual(result['id'], 'member-12345678')
        self.assertFalse(result['has_name'])
        self.assertEqual(result['phone'], '미등록')
        self.assertEqual(result['created_at'], '2024-01-01 09:00')
        self.assertEqual(result['account_role'], '일반 회원')

    def test_missing_name_does_not_infer_email_local_part(self):
        result = format_member_directory_row(self.make_row(email='member-name@example.com'))

        self.assertEqual(result['name'], '이름 미등록')
        self.assertEqual(result['email'], 'member-name@example.com')

    def test_missing_profile_and_auth_links_are_reportable(self):
        result = format_member_directory_row(self.make_row(
            profile_exists=False,
            auth_user_exists=True,
        ))

        self.assertFalse(result['profile_exists'])
        self.assertTrue(result['auth_user_exists'])


if __name__ == '__main__':
    unittest.main()