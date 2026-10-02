-- 관리자 회원 조회를 위한 읽기 전용 Auth/Profile 디렉터리
-- 기존 회원을 복제하거나 쓰기 경로/RLS 정책을 변경하지 않습니다.

CREATE OR REPLACE VIEW public.admin_member_directory AS
SELECT
    COALESCE(p.id, u.id) AS member_id,
    COALESCE(p.id, u.id)::TEXT AS member_id_text,
    p.id IS NOT NULL AS profile_exists,
    u.id IS NOT NULL AS auth_user_exists,
    CASE
        WHEN u.id IS NOT NULL
          AND NULLIF(p.full_name, '') IS NOT NULL
          AND LOWER(p.full_name) = LOWER(SPLIT_PART(COALESCE(u.email, p.email, ''), '@', 1))
          AND NULLIF(u.raw_user_meta_data ->> 'full_name', '') IS NULL
          AND NULLIF(u.raw_user_meta_data ->> 'name', '') IS NULL
        THEN COALESCE(
            NULLIF(u.raw_user_meta_data ->> 'full_name', ''),
            NULLIF(u.raw_user_meta_data ->> 'name', ''),
            NULLIF(u.raw_user_meta_data ->> 'nickname', '')
        )
        ELSE COALESCE(
            NULLIF(p.full_name, ''),
            NULLIF(u.raw_user_meta_data ->> 'full_name', ''),
            NULLIF(u.raw_user_meta_data ->> 'name', ''),
            NULLIF(u.raw_user_meta_data ->> 'nickname', '')
        )
    END AS display_name,
    NULLIF(u.raw_user_meta_data ->> 'nickname', '') AS nickname,
    CASE
        WHEN LOWER(COALESCE(u.email, p.email, '')) LIKE '%@naver.auth' THEN NULL
        ELSE NULLIF(COALESCE(u.email, p.email), '')
    END AS email,
    COALESCE(NULLIF(p.phone, ''), NULLIF(u.phone, '')) AS phone,
    p.role AS account_role,
    COALESCE(u.created_at, p.created_at) AS created_at,
    u.last_sign_in_at,
    ARRAY(
        SELECT DISTINCT LOWER(provider_entry.provider)
        FROM (
            SELECT 'naver'::TEXT AS provider
            WHERE LOWER(COALESCE(u.raw_user_meta_data ->> 'provider', '')) = 'naver'

            UNION ALL

            SELECT i.provider
            FROM auth.identities AS i
            WHERE i.user_id = COALESCE(p.id, u.id)
              AND LOWER(COALESCE(u.raw_user_meta_data ->> 'provider', '')) <> 'naver'

            UNION ALL

            SELECT jsonb_array_elements_text(
                CASE
                    WHEN jsonb_typeof(u.raw_app_meta_data -> 'providers') = 'array'
                    THEN u.raw_app_meta_data -> 'providers'
                    ELSE '[]'::JSONB
                END
            ) AS provider
            WHERE LOWER(COALESCE(u.raw_user_meta_data ->> 'provider', '')) <> 'naver'
        ) AS provider_entry
        WHERE COALESCE(provider_entry.provider, '') <> ''
        ORDER BY LOWER(provider_entry.provider)
    ) AS login_providers
FROM public.profiles AS p
FULL OUTER JOIN auth.users AS u ON u.id = p.id;

REVOKE ALL ON public.admin_member_directory FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.admin_member_directory TO service_role;