-- ==============================================================================
-- 마이그레이션: 재고 변경 이력(inventory_logs) 테이블 생성
-- ==============================================================================
-- 관리자의 입고, 출고, 실사 조정 내역을 안전하게 추적 및 기록합니다.

CREATE TABLE IF NOT EXISTS public.inventory_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    option_id BIGINT REFERENCES public.product_options(id) ON DELETE SET NULL,
    product_name TEXT NOT NULL,
    option_info TEXT,
    change_type TEXT NOT NULL CHECK (change_type IN ('IN', 'OUT', 'ADJUST')),
    before_stock INT NOT NULL,
    quantity_change INT NOT NULL,
    after_stock INT NOT NULL,
    reason TEXT NOT NULL,
    admin_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    admin_email TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 검색 및 조회 성능을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_inventory_logs_product_id ON public.inventory_logs(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_logs_option_id ON public.inventory_logs(option_id);
CREATE INDEX IF NOT EXISTS idx_inventory_logs_created_at ON public.inventory_logs(created_at DESC);

-- RLS 정책 설정 (관리자 및 service_role 권한)
ALTER TABLE public.inventory_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "재고 이력 조회: 관리자 전용" ON public.inventory_logs;
CREATE POLICY "재고 이력 조회: 관리자 전용"
    ON public.inventory_logs FOR SELECT
    TO authenticated
    USING (public.is_admin());

DROP POLICY IF EXISTS "재고 이력 등록: 관리자 전용" ON public.inventory_logs;
CREATE POLICY "재고 이력 등록: 관리자 전용"
    ON public.inventory_logs FOR INSERT
    TO authenticated
    WITH CHECK (public.is_admin());

-- 일반 사용자의 임의 수정/삭제 차단 (이력 무결성 보장)
REVOKE UPDATE, DELETE ON public.inventory_logs FROM PUBLIC, anon, authenticated;
