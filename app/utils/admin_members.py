"""관리자 회원 디렉터리 view row의 화면 표시값을 정규화합니다."""

from app.utils.admin_work_alerts import format_seoul_datetime

PROVIDER_LABELS = {
    'email': '이메일',
    'kakao': '카카오',
    'naver': '네이버',
    'google': '구글',
}


def format_member_directory_row(row):
    """service-role 전용 디렉터리 row에서 화면에 필요한 값만 만듭니다."""
    member_id = str(row.get('member_id') or '')
    raw_name = row.get('display_name') or row.get('nickname')
    providers = row.get('login_providers') or []
    if isinstance(providers, str):
        providers = [provider.strip() for provider in providers.strip('{}').split(',') if provider.strip()]
    provider_labels = sorted(
        {
            PROVIDER_LABELS.get(str(provider).lower(), '기타')
            for provider in providers
            if provider
        },
        key=str.casefold,
    )
    email = row.get('email')
    if not email or str(email).lower().endswith('@naver.auth'):
        email = '이메일 미제공'

    return {
        'id': member_id,
        'name': raw_name or '이름 미등록',
        'has_name': bool(raw_name),
        'nickname': row.get('nickname') or '',
        'email': email,
        'phone': row.get('phone') or '미등록',
        'providers': ' · '.join(provider_labels) if provider_labels else '확인 가능한 인증 방식 없음',
        'provider_values': [str(provider).lower() for provider in providers if provider],
        'created_at': format_seoul_datetime(row.get('created_at')) if row.get('created_at') else '미등록',
        'last_sign_in_at': format_seoul_datetime(row.get('last_sign_in_at'))
        if row.get('last_sign_in_at')
        else '확인 가능한 기록 없음',
        'account_role': {'admin': '관리자', 'customer': '일반 회원'}.get(
            row.get('account_role'), '확인 가능한 권한 없음'
        ),
        'profile_exists': bool(row.get('profile_exists')),
        'auth_user_exists': bool(row.get('auth_user_exists')),
    }