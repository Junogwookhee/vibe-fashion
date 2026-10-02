-- 비공개 1:1 고객 문의, 관리자 답변 및 답변 변경 이력
-- 이 migration은 작성되지 않은 운영 문의 데이터를 생성하거나 수정하지 않습니다.

CREATE TABLE IF NOT EXISTS public.customer_inquiries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inquiry_number BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    order_id UUID REFERENCES public.orders(id) ON DELETE SET NULL,
    inquiry_type TEXT NOT NULL CHECK (
        inquiry_type IN ('product_size', 'delivery', 'order_payment', 'cancel_exchange_return', 'other')
    ),
    title TEXT NOT NULL CHECK (char_length(title) <= 100 AND title !~ '^[[:space:]]*$'),
    content TEXT NOT NULL CHECK (char_length(content) <= 5000 AND content !~ '^[[:space:]]*$'),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'answered')),
    reply_text TEXT,
    answered_by UUID,
    answered_at TIMESTAMPTZ,
    reply_updated_by UUID,
    reply_updated_at TIMESTAMPTZ,
    reply_version INTEGER NOT NULL DEFAULT 0 CHECK (reply_version >= 0),
    submission_token UUID NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT customer_inquiries_reply_length_check CHECK (
        reply_text IS NULL OR (char_length(reply_text) <= 5000 AND reply_text !~ '^[[:space:]]*$')
    ),
    CONSTRAINT customer_inquiries_reply_state_check CHECK (
        (status = 'pending' AND reply_text IS NULL AND reply_version = 0 AND answered_by IS NULL AND answered_at IS NULL)
        OR
        (status = 'answered' AND reply_text IS NOT NULL AND reply_version > 0 AND answered_by IS NOT NULL AND answered_at IS NOT NULL AND reply_updated_by IS NOT NULL AND reply_updated_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_customer_inquiries_user_created
    ON public.customer_inquiries (user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_customer_inquiries_status_created
    ON public.customer_inquiries (status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_customer_inquiries_order
    ON public.customer_inquiries (order_id) WHERE order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.customer_inquiry_reply_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inquiry_id UUID NOT NULL REFERENCES public.customer_inquiries(id) ON DELETE CASCADE,
    reply_version INTEGER NOT NULL CHECK (reply_version > 0),
    action TEXT NOT NULL CHECK (action IN ('answered', 'edited')),
    previous_reply TEXT,
    new_reply TEXT NOT NULL CHECK (char_length(new_reply) <= 5000 AND new_reply !~ '^[[:space:]]*$'),
    changed_by UUID NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT customer_inquiry_reply_history_version_unique UNIQUE (inquiry_id, reply_version)
);

ALTER TABLE public.customer_inquiries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.customer_inquiry_reply_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "회원은 본인 문의와 관리자는 전체 문의 조회" ON public.customer_inquiries;
CREATE POLICY "회원은 본인 문의와 관리자는 전체 문의 조회"
    ON public.customer_inquiries FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());

DROP POLICY IF EXISTS "회원은 본인 문의만 등록" ON public.customer_inquiries;
CREATE POLICY "회원은 본인 문의만 등록"
    ON public.customer_inquiries FOR INSERT
    WITH CHECK (
        auth.uid() = user_id
        AND status = 'pending'
        AND reply_text IS NULL
        AND reply_version = 0
        AND answered_by IS NULL
        AND answered_at IS NULL
        AND (
            order_id IS NULL
            OR EXISTS (
                SELECT 1 FROM public.orders AS own_order
                WHERE own_order.id = order_id AND own_order.user_id = auth.uid()
            )
        )
    );

DROP POLICY IF EXISTS "관리자만 문의 답변 이력 조회" ON public.customer_inquiry_reply_history;
CREATE POLICY "관리자만 문의 답변 이력 조회"
    ON public.customer_inquiry_reply_history FOR SELECT
    USING (public.is_admin());

REVOKE ALL ON public.customer_inquiries FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.customer_inquiry_reply_history FROM PUBLIC, anon, authenticated;
GRANT SELECT (id, inquiry_number, user_id, order_id, inquiry_type, title, content, status, reply_text, answered_at, reply_updated_at, reply_version, created_at, updated_at)
    ON public.customer_inquiries TO authenticated;
GRANT INSERT (user_id, order_id, inquiry_type, title, content, submission_token)
    ON public.customer_inquiries TO authenticated;
GRANT SELECT, INSERT ON public.customer_inquiries TO service_role;
GRANT SELECT ON public.customer_inquiry_reply_history TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.customer_inquiries_inquiry_number_seq TO authenticated, service_role;

CREATE OR REPLACE VIEW public.admin_customer_inquiries AS
SELECT
    i.id,
    i.inquiry_number,
    i.user_id,
    i.user_id::TEXT AS user_id_text,
    CASE
        WHEN u.id IS NOT NULL
          AND NULLIF(p.full_name, '') IS NOT NULL
          AND LOWER(p.full_name) = LOWER(SPLIT_PART(COALESCE(u.email, p.email, ''), '@', 1))
          AND NULLIF(u.raw_user_meta_data ->> 'full_name', '') IS NULL
          AND NULLIF(u.raw_user_meta_data ->> 'name', '') IS NULL
        THEN COALESCE(
            NULLIF(u.raw_user_meta_data ->> 'nickname', ''),
            '회원 · ' || LEFT(i.user_id::TEXT, 8)
        )
        ELSE COALESCE(
            NULLIF(p.full_name, ''),
            NULLIF(u.raw_user_meta_data ->> 'nickname', ''),
            NULLIF(u.raw_user_meta_data ->> 'name', ''),
            '회원 · ' || LEFT(i.user_id::TEXT, 8)
        )
    END AS author_name,
    NULLIF(u.raw_user_meta_data ->> 'nickname', '') AS author_nickname,
    i.order_id,
    o.order_number,
    i.inquiry_type,
    i.title,
    i.content,
    i.status,
    i.reply_text,
    i.answered_by,
    i.answered_at,
    i.reply_updated_by,
    i.reply_updated_at,
    i.reply_version,
    i.created_at,
    i.updated_at
FROM public.customer_inquiries AS i
LEFT JOIN public.profiles AS p ON p.id = i.user_id
LEFT JOIN auth.users AS u ON u.id = i.user_id
LEFT JOIN public.orders AS o ON o.id = i.order_id;

REVOKE ALL ON public.admin_customer_inquiries FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.admin_customer_inquiries TO service_role;

CREATE OR REPLACE FUNCTION public.save_customer_inquiry_reply(
    p_inquiry_id UUID,
    p_admin_id UUID,
    p_reply TEXT,
    p_expected_version INTEGER
)
RETURNS TABLE (
    inquiry_id UUID,
    reply_version INTEGER,
    answered_at TIMESTAMPTZ,
    reply_updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    target public.customer_inquiries%ROWTYPE;
    changed_at TIMESTAMPTZ := clock_timestamp();
    next_version INTEGER;
BEGIN
    IF p_reply IS NULL OR char_length(p_reply) > 5000 OR p_reply !~ '[^[:space:]]' THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid_inquiry_reply';
    END IF;
    IF p_expected_version IS NULL OR p_expected_version < 0 THEN
        RAISE EXCEPTION USING ERRCODE = '22023', MESSAGE = 'invalid_inquiry_reply_version';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.profiles WHERE id = p_admin_id AND role = 'admin') THEN
        RAISE EXCEPTION USING ERRCODE = '42501', MESSAGE = 'inquiry_admin_required';
    END IF;

    SELECT * INTO target
    FROM public.customer_inquiries AS inquiry
    WHERE inquiry.id = p_inquiry_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE = 'P0002', MESSAGE = 'inquiry_not_found';
    END IF;
    IF target.reply_version <> p_expected_version THEN
        RAISE EXCEPTION USING ERRCODE = '40001', MESSAGE = 'inquiry_reply_version_conflict';
    END IF;
    IF target.reply_text IS NOT DISTINCT FROM p_reply THEN
        RETURN QUERY SELECT p_inquiry_id, target.reply_version, target.answered_at, target.reply_updated_at;
        RETURN;
    END IF;

    next_version := target.reply_version + 1;
    UPDATE public.customer_inquiries AS inquiry
    SET reply_text = p_reply,
        status = 'answered',
        answered_by = COALESCE(target.answered_by, p_admin_id),
        answered_at = COALESCE(target.answered_at, changed_at),
        reply_updated_by = p_admin_id,
        reply_updated_at = changed_at,
        reply_version = next_version,
        updated_at = changed_at
    WHERE inquiry.id = p_inquiry_id;

    INSERT INTO public.customer_inquiry_reply_history (
        inquiry_id, reply_version, action, previous_reply, new_reply, changed_by, changed_at
    ) VALUES (
        p_inquiry_id,
        next_version,
        CASE WHEN target.reply_text IS NULL THEN 'answered' ELSE 'edited' END,
        target.reply_text,
        p_reply,
        p_admin_id,
        changed_at
    );

    RETURN QUERY SELECT p_inquiry_id, next_version, COALESCE(target.answered_at, changed_at), changed_at;
END;
$$;

REVOKE ALL ON FUNCTION public.save_customer_inquiry_reply(UUID, UUID, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.save_customer_inquiry_reply(UUID, UUID, TEXT, INTEGER) TO service_role;