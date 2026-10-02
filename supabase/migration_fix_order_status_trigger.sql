-- ==============================================================================
-- 마이그레이션: 주문 고객 등급 갱신 트리거 enum 캐스팅 오류 수정
-- ==============================================================================
-- orders.status는 'PAID', 'PENDING_PAYMENT' 등 대문자 enum(public.order_status)을 사용하므로,
-- 트리거 함수 내에서 status를 text로 안전하게 변환(status::text)하여 비교하도록 수정합니다.

CREATE OR REPLACE FUNCTION public.update_customer_grade(target_user_id UUID)
RETURNS VOID
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
    v_total_spent NUMERIC(12, 2);
    v_new_grade TEXT;
BEGIN
    -- 결제 완료 또는 배송 완료 상태인 실구매 누적액 계산
    SELECT COALESCE(SUM(total_amount), 0)
    INTO v_total_spent
    FROM public.orders
    WHERE user_id = target_user_id
      AND status::text IN ('PAID', 'DELIVERED', 'paid', 'delivered', 'preparing', 'shipping');

    -- 등급 산정 로직
    IF v_total_spent >= 1000000 THEN
        v_new_grade := 'VIP';
    ELSIF v_total_spent >= 500000 THEN
        v_new_grade := 'GOLD';
    ELSIF v_total_spent >= 200000 THEN
        v_new_grade := 'SILVER';
    ELSE
        v_new_grade := 'BRONZE';
    END IF;

    -- 프로필 테이블에 누적 구매금액 및 등급 반영
    UPDATE public.profiles
    SET
        total_spent = v_total_spent,
        grade = v_new_grade,
        updated_at = NOW()
    WHERE id = target_user_id;
END;
$$;

-- 재고 차감은 읽기 후 절대값을 쓰지 않고 단일 UPDATE로 원자 처리합니다.
CREATE OR REPLACE FUNCTION public.decrement_product_option_stock(
    p_option_id BIGINT,
    p_quantity INTEGER
)
RETURNS SETOF public.product_options
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE public.product_options
    SET stock = stock - p_quantity
    WHERE id = p_option_id
      AND p_quantity > 0
      AND stock >= p_quantity
    RETURNING *;
$$;

CREATE OR REPLACE FUNCTION public.restore_product_option_stock(
    p_option_id BIGINT,
    p_quantity INTEGER
)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE public.product_options
    SET stock = stock + p_quantity
    WHERE id = p_option_id
      AND p_quantity > 0;
$$;

CREATE OR REPLACE FUNCTION public.decrement_product_stock(
    p_product_id UUID,
    p_quantity INTEGER
)
RETURNS SETOF public.products
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE public.products
    SET stock = stock - p_quantity
    WHERE id = p_product_id
      AND p_quantity > 0
      AND stock >= p_quantity
    RETURNING *;
$$;

CREATE OR REPLACE FUNCTION public.restore_product_stock(
    p_product_id UUID,
    p_quantity INTEGER
)
RETURNS VOID
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE public.products
    SET stock = stock + p_quantity
    WHERE id = p_product_id
      AND p_quantity > 0;
$$;

REVOKE ALL ON FUNCTION public.decrement_product_option_stock(BIGINT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restore_product_option_stock(BIGINT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.decrement_product_stock(UUID, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restore_product_stock(UUID, INTEGER) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.decrement_product_option_stock(BIGINT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.restore_product_option_stock(BIGINT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.decrement_product_stock(UUID, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.restore_product_stock(UUID, INTEGER) TO service_role;
