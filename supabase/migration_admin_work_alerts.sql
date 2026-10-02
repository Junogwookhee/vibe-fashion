-- 관리자 업무 알림용 읽기 전용 view
-- 실행 전 schema.sql의 products, product_options, orders, order_items, refunds 테이블이 있어야 합니다.

CREATE OR REPLACE VIEW public.admin_active_inventory_items AS
SELECT
    'option'::TEXT AS target_type,
    po.id AS target_id,
    p.id AS product_id,
    p.name AS product_name,
    p.slug,
    p.thumbnail_url,
    p.category_id,
    c.name AS category_name,
    po.id AS option_id,
    COALESCE(
        NULLIF(CONCAT_WS(' / ', NULLIF(po.option_name, ''), NULLIF(po.option_value, '')), ''),
        '옵션'
    ) AS option_info,
    COALESCE(po.stock, 0)::INTEGER AS stock
FROM public.products AS p
JOIN public.product_options AS po ON po.product_id = p.id
LEFT JOIN public.categories AS c ON c.id = p.category_id
WHERE p.is_active IS TRUE

UNION ALL

SELECT
    'product'::TEXT AS target_type,
    p.id AS target_id,
    p.id AS product_id,
    p.name AS product_name,
    p.slug,
    p.thumbnail_url,
    p.category_id,
    c.name AS category_name,
    NULL::UUID AS option_id,
    '단일 상품 (옵션 없음)'::TEXT AS option_info,
    COALESCE(p.stock, 0)::INTEGER AS stock
FROM public.products AS p
LEFT JOIN public.categories AS c ON c.id = p.category_id
WHERE p.is_active IS TRUE
  AND NOT EXISTS (
      SELECT 1
      FROM public.product_options AS po
      WHERE po.product_id = p.id
  );

CREATE OR REPLACE VIEW public.admin_unshipped_orders AS
SELECT
    o.id,
    o.order_number,
    UPPER(o.status::TEXT) AS status,
    o.created_at
FROM public.orders AS o
WHERE UPPER(o.status::TEXT) IN ('PAID', 'PREPARING')
  AND NOT EXISTS (
      SELECT 1
      FROM public.refunds AS r
      WHERE r.order_id = o.id
        AND LOWER(r.status::TEXT) IN ('requested', 'approved')
  );

CREATE OR REPLACE VIEW public.admin_pending_refund_orders AS
SELECT
    o.id,
    o.order_number,
    UPPER(o.status::TEXT) AS order_status,
    MIN(r.created_at) AS requested_at,
    CASE
        WHEN BOOL_OR(LOWER(r.status::TEXT) = 'requested') THEN 'requested'
        ELSE 'approved'
    END AS refund_status
FROM public.refunds AS r
JOIN public.orders AS o ON o.id = r.order_id
WHERE LOWER(r.status::TEXT) IN ('requested', 'approved')
GROUP BY o.id, o.order_number, o.status;

-- These views contain operational data and are only queried server-side with service_role.
REVOKE ALL ON public.admin_active_inventory_items FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.admin_unshipped_orders FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.admin_pending_refund_orders FROM PUBLIC, anon, authenticated;

GRANT SELECT ON public.admin_active_inventory_items TO service_role;
GRANT SELECT ON public.admin_unshipped_orders TO service_role;
GRANT SELECT ON public.admin_pending_refund_orders TO service_role;