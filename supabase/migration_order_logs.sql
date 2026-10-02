-- ==============================================================================
-- 마이그레이션: 주문 처리 이력(order_logs) 테이블 생성 및 RLS 설정
-- ==============================================================================
-- 관리자의 주문·배송 상태 변경, 송장번호 등록/수정, 취소 승인 이력을 시간순으로 기록합니다.

CREATE TABLE IF NOT EXISTS public.order_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    carrier TEXT,
    tracking_number TEXT,
    action_type TEXT NOT NULL CHECK (action_type IN ('STATUS_CHANGE', 'SHIPPING_START', 'TRACKING_UPDATE', 'MANUAL_DELIVERY', 'CANCEL')),
    reason TEXT,
    actor_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    actor_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_order_logs_order_id ON public.order_logs(order_id);
CREATE INDEX IF NOT EXISTS idx_order_logs_created_at ON public.order_logs(created_at DESC);

-- RLS
ALTER TABLE public.order_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "주문 이력 조회: 관리자 또는 주문자 본인" ON public.order_logs;
CREATE POLICY "주문 이력 조회: 관리자 또는 주문자 본인"
    ON public.order_logs FOR SELECT
    TO authenticated
    USING (
        public.is_admin() OR
        EXISTS (
            SELECT 1 FROM public.orders
            WHERE orders.id = order_logs.order_id
              AND orders.user_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS "주문 이력 등록: 관리자 전용" ON public.order_logs;
CREATE POLICY "주문 이력 등록: 관리자 전용"
    ON public.order_logs FOR INSERT
    TO authenticated
    WITH CHECK (public.is_admin());

REVOKE UPDATE, DELETE ON public.order_logs FROM PUBLIC, anon, authenticated;
