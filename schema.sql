-- ==============================================================================
-- VIBE-FASHION 쇼핑몰 데이터베이스 스키마 (Supabase SQL Editor 실행용)
-- ==============================================================================

-- 1. 확장 기능 활성화
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- 2. 공통 함수 (updated_at 자동 갱신 트리거 함수)
-- ==============================================================================
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ==============================================================================
-- 3. 테이블 정의
-- ==============================================================================

-- 3.1 사용자 프로필 (profiles) - Supabase auth.users 연동
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    full_name TEXT,
    avatar_url TEXT,
    phone TEXT,
    role TEXT NOT NULL DEFAULT 'customer' CHECK (role IN ('customer', 'admin')),
    grade TEXT NOT NULL DEFAULT 'BRONZE' CHECK (grade IN ('BRONZE', 'SILVER', 'GOLD', 'VIP')),
    total_spent NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (total_spent >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 기존에 profiles 테이블이 이미 생성되어 있던 경우를 대비해 컬럼 추가 보장
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'customer';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS grade TEXT NOT NULL DEFAULT 'BRONZE';
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS total_spent NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- role 및 grade 체크 제약조건이 없는 경우 추가
DO $$
BEGIN
    UPDATE public.profiles SET role = 'customer' WHERE role IS NULL;
    UPDATE public.profiles SET grade = 'BRONZE' WHERE grade IS NULL;
    UPDATE public.profiles SET total_spent = 0 WHERE total_spent IS NULL;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'profiles_role_check'
    ) THEN
        ALTER TABLE public.profiles ADD CONSTRAINT profiles_role_check CHECK (role IN ('customer', 'admin'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'profiles_grade_check'
    ) THEN
        ALTER TABLE public.profiles ADD CONSTRAINT profiles_grade_check CHECK (grade IN ('BRONZE', 'SILVER', 'GOLD', 'VIP'));
    END IF;
EXCEPTION
    WHEN OTHERS THEN NULL;
END $$;

-- 3.2 카테고리 (categories)
CREATE TABLE IF NOT EXISTS public.categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id UUID REFERENCES public.categories(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 기존에 categories 테이블이 이미 존재할 경우 누락 컬럼 추가
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES public.categories(id) ON DELETE SET NULL;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- slug UNIQUE 제약조건 확인 및 추가
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'categories_slug_key'
    ) THEN
        ALTER TABLE public.categories ADD CONSTRAINT categories_slug_key UNIQUE (slug);
    END IF;
EXCEPTION
    WHEN OTHERS THEN NULL;
END $$;

-- 3.3 상품 (products)
CREATE TABLE IF NOT EXISTS public.products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID REFERENCES public.categories(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    sale_price NUMERIC(12, 2) CHECK (sale_price IS NULL OR sale_price >= 0),
    stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    thumbnail_url TEXT,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 기존에 products 테이블이 이미 존재할 경우 누락 컬럼 추가
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES public.categories(id) ON DELETE SET NULL;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS price NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS sale_price NUMERIC(12, 2);
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS stock INT NOT NULL DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'products_slug_key'
    ) THEN
        ALTER TABLE public.products ADD CONSTRAINT products_slug_key UNIQUE (slug);
    END IF;
EXCEPTION
    WHEN OTHERS THEN NULL;
END $$;

-- 3.4 상품 옵션 (product_options - 색상, 사이즈 등)
CREATE TABLE IF NOT EXISTS public.product_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    option_name TEXT NOT NULL,   -- 예: '사이즈', '컬러'
    option_value TEXT NOT NULL,  -- 예: 'L', '블랙'
    additional_price NUMERIC(12, 2) NOT NULL DEFAULT 0,
    stock INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.5 상품 이미지 (product_images)
CREATE TABLE IF NOT EXISTS public.product_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.6 장바구니 (carts)
CREATE TABLE IF NOT EXISTS public.carts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    option_id UUID REFERENCES public.product_options(id) ON DELETE SET NULL,
    quantity INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_product_option UNIQUE (user_id, product_id, option_id)
);

-- 3.7 주문 (orders)
CREATE TABLE IF NOT EXISTS public.orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number TEXT NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'preparing', 'shipping', 'delivered', 'cancelled')),
    total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0),
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    shipping_fee NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (shipping_fee >= 0),
    payment_method TEXT,
    payment_key TEXT,
    recipient_name TEXT,
    recipient_phone TEXT,
    shipping_address JSONB,
    order_memo TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.8 주문 상품 상세 (order_items)
CREATE TABLE IF NOT EXISTS public.order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE RESTRICT,
    option_id UUID REFERENCES public.product_options(id) ON DELETE SET NULL,
    product_name TEXT NOT NULL,
    option_info TEXT,
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    total_price NUMERIC(12, 2) NOT NULL CHECK (total_price >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.9 환불 / 취소 (refunds)
CREATE TABLE IF NOT EXISTS public.refunds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES public.orders(id) ON DELETE CASCADE,
    order_item_id UUID REFERENCES public.order_items(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    refund_amount NUMERIC(12, 2) NOT NULL CHECK (refund_amount >= 0),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'rejected', 'completed')),
    admin_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.10 알림 (notifications)
CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'order' CHECK (type IN ('order', 'delivery', 'refund', 'notice', 'event', 'review')),
    link_url TEXT,
    is_read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3.11 리뷰 (reviews)
CREATE TABLE IF NOT EXISTS public.reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    order_item_id UUID REFERENCES public.order_items(id) ON DELETE SET NULL,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    content TEXT NOT NULL,
    image_urls TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==============================================================================
-- 4. 인덱스 (성능 최적화)
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_products_category_id ON public.products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_is_active ON public.products(is_active);
CREATE INDEX IF NOT EXISTS idx_product_options_product_id ON public.product_options(product_id);
CREATE INDEX IF NOT EXISTS idx_product_images_product_id ON public.product_images(product_id);
CREATE INDEX IF NOT EXISTS idx_carts_user_id ON public.carts(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON public.orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON public.orders(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON public.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_order_id ON public.refunds(order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_user_id ON public.refunds(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_id_read ON public.notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_reviews_product_id ON public.reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user_id ON public.reviews(user_id);

-- ==============================================================================
-- 5. updated_at 자동 갱신 트리거 등록
-- ==============================================================================
DROP TRIGGER IF EXISTS tr_profiles_updated_at ON public.profiles;
CREATE TRIGGER tr_profiles_updated_at BEFORE UPDATE ON public.profiles FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_products_updated_at ON public.products;
CREATE TRIGGER tr_products_updated_at BEFORE UPDATE ON public.products FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_carts_updated_at ON public.carts;
CREATE TRIGGER tr_carts_updated_at BEFORE UPDATE ON public.carts FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_orders_updated_at ON public.orders;
CREATE TRIGGER tr_orders_updated_at BEFORE UPDATE ON public.orders FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_refunds_updated_at ON public.refunds;
CREATE TRIGGER tr_refunds_updated_at BEFORE UPDATE ON public.refunds FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS tr_reviews_updated_at ON public.reviews;
CREATE TRIGGER tr_reviews_updated_at BEFORE UPDATE ON public.reviews FOR EACH ROW EXECUTE FUNCTION public.handle_updated_at();

-- ==============================================================================
-- 6. 소셜 로그인 시 profiles 자동 생성 트리거 (handle_new_user)
-- ==============================================================================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
DECLARE
    v_full_name TEXT;
    v_avatar_url TEXT;
BEGIN
    -- 소셜 로그인(OAuth) 및 일반 로그인 메타데이터 추출
    v_full_name := COALESCE(
        NEW.raw_user_meta_data->>'full_name',
        NEW.raw_user_meta_data->>'name',
        NEW.raw_user_meta_data->>'user_name',
        split_part(NEW.email, '@', 1)
    );

    v_avatar_url := COALESCE(
        NEW.raw_user_meta_data->>'avatar_url',
        NEW.raw_user_meta_data->>'picture'
    );

    INSERT INTO public.profiles (
        id,
        email,
        full_name,
        avatar_url,
        role,
        grade,
        total_spent
    )
    VALUES (
        NEW.id,
        NEW.email,
        v_full_name,
        v_avatar_url,
        'customer',
        'BRONZE',
        0
    )
    ON CONFLICT (id) DO UPDATE
    SET
        email = EXCLUDED.email,
        full_name = COALESCE(public.profiles.full_name, EXCLUDED.full_name),
        avatar_url = COALESCE(public.profiles.avatar_url, EXCLUDED.avatar_url),
        updated_at = NOW();

    RETURN NEW;
END;
$$;

-- auth.users 테이블에 트리거 연결
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ==============================================================================
-- 7. 고객 등급 자동 업데이트 함수 및 트리거 (update_customer_grade)
--    등급 기준 (누적 실결제액 total_spent 기준):
--    - VIP: 1,000,000원 이상
--    - GOLD: 500,000원 이상
--    - SILVER: 200,000원 이상
--    - BRONZE: 200,000원 미만
-- ==============================================================================
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
    -- 결제 완료(PAID, paid) 또는 배송 완료(DELIVERED, delivered) 상태인 실구매 누적액 계산
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

-- 주문(orders) 상태 변경 시 고객 등급 자동 갱신 트리거 함수
CREATE OR REPLACE FUNCTION public.handle_order_grade_update()
RETURNS TRIGGER
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
BEGIN
    -- 주문 추가 시 대상 유저 등급 갱신
    IF TG_OP = 'INSERT' THEN
        PERFORM public.update_customer_grade(NEW.user_id);
    -- 상태나 결제금액이 변경된 경우
    ELSIF TG_OP = 'UPDATE' THEN
        IF (NEW.status IS DISTINCT FROM OLD.status) OR (NEW.total_amount IS DISTINCT FROM OLD.total_amount) THEN
            PERFORM public.update_customer_grade(NEW.user_id);
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tr_orders_update_grade ON public.orders;
CREATE TRIGGER tr_orders_update_grade
    AFTER INSERT OR UPDATE ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.handle_order_grade_update();

-- ==============================================================================
-- 8. 관리자 권한 확인 함수 및 Row Level Security (RLS) 정책 설정
-- ==============================================================================

-- 8.0 관리자 여부 확인 함수 (SECURITY DEFINER로 RLS 무한 재귀 및 권한 충돌 방지)
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
SECURITY DEFINER
SET search_path = public
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = auth.uid() AND role = 'admin'
    );
END;
$$;

-- 8.1 profiles
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "프로필 조회: 본인 프로필 조회 또는 관리자 전체 조회" ON public.profiles;
CREATE POLICY "프로필 조회: 본인 프로필 조회 또는 관리자 전체 조회"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id OR public.is_admin());

DROP POLICY IF EXISTS "프로필 수정: 본인 프로필만 수정 가능" ON public.profiles;
CREATE POLICY "프로필 수정: 본인 프로필만 수정 가능"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id);

-- 8.2 categories (공개 읽기, 관리자만 수정/등록)
ALTER TABLE public.categories ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "카테고리 조회: 누구나 조회 가능" ON public.categories;
CREATE POLICY "카테고리 조회: 누구나 조회 가능"
    ON public.categories FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "카테고리 관리: 관리자만 가능" ON public.categories;
CREATE POLICY "카테고리 관리: 관리자만 가능"
    ON public.categories FOR ALL
    USING (public.is_admin());

-- 8.3 products (공개 읽기, 관리자만 수정/등록)
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "상품 조회: 활성화된 상품 누구나 조회 가능" ON public.products;
CREATE POLICY "상품 조회: 활성화된 상품 누구나 조회 가능"
    ON public.products FOR SELECT
    USING (is_active = true OR public.is_admin());

DROP POLICY IF EXISTS "상품 관리: 관리자만 가능" ON public.products;
CREATE POLICY "상품 관리: 관리자만 가능"
    ON public.products FOR ALL
    USING (public.is_admin());

-- 8.4 product_options (공개 읽기)
ALTER TABLE public.product_options ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "상품 옵션 조회: 누구나 조회 가능" ON public.product_options;
CREATE POLICY "상품 옵션 조회: 누구나 조회 가능"
    ON public.product_options FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "상품 옵션 관리: 관리자만 가능" ON public.product_options;
CREATE POLICY "상품 옵션 관리: 관리자만 가능"
    ON public.product_options FOR ALL
    USING (public.is_admin());

-- 8.5 product_images (공개 읽기)
ALTER TABLE public.product_images ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "상품 이미지 조회: 누구나 조회 가능" ON public.product_images;
CREATE POLICY "상품 이미지 조회: 누구나 조회 가능"
    ON public.product_images FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "상품 이미지 관리: 관리자만 가능" ON public.product_images;
CREATE POLICY "상품 이미지 관리: 관리자만 가능"
    ON public.product_images FOR ALL
    USING (public.is_admin());

-- 8.6 carts (본인 장바구니만 접근)
ALTER TABLE public.carts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "장바구니 조회: 본인 것만 조회" ON public.carts;
CREATE POLICY "장바구니 조회: 본인 것만 조회"
    ON public.carts FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "장바구니 추가: 본인 계정으로만 추가" ON public.carts;
CREATE POLICY "장바구니 추가: 본인 계정으로만 추가"
    ON public.carts FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "장바구니 수정: 본인 장바구니만 수정" ON public.carts;
CREATE POLICY "장바구니 수정: 본인 장바구니만 수정"
    ON public.carts FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "장바구니 삭제: 본인 장바구니만 삭제" ON public.carts;
CREATE POLICY "장바구니 삭제: 본인 장바구니만 삭제"
    ON public.carts FOR DELETE
    USING (auth.uid() = user_id);

-- 8.7 orders (본인 주문 조회/생성, 관리자 전체 권한)
ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "주문 조회: 본인 주문 또는 관리자" ON public.orders;
CREATE POLICY "주문 조회: 본인 주문 또는 관리자"
    ON public.orders FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());

DROP POLICY IF EXISTS "주문 생성: 본인 주문만 생성 가능" ON public.orders;
CREATE POLICY "주문 생성: 본인 주문만 생성 가능"
    ON public.orders FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "주문 수정: 관리자 또는 본인(취소 등 제한적)" ON public.orders;
CREATE POLICY "주문 수정: 관리자 또는 본인(취소 등 제한적)"
    ON public.orders FOR UPDATE
    USING (auth.uid() = user_id OR public.is_admin());

-- 8.8 order_items
ALTER TABLE public.order_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "주문 상품 조회: 본인 주문 상품 또는 관리자" ON public.order_items;
CREATE POLICY "주문 상품 조회: 본인 주문 상품 또는 관리자"
    ON public.order_items FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.orders
            WHERE orders.id = order_items.order_id
              AND (orders.user_id = auth.uid() OR public.is_admin())
        )
    );

DROP POLICY IF EXISTS "주문 상품 생성: 본인 주문에만 추가 가능" ON public.order_items;
CREATE POLICY "주문 상품 생성: 본인 주문에만 추가 가능"
    ON public.order_items FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.orders
            WHERE orders.id = order_items.order_id
              AND orders.user_id = auth.uid()
        )
    );

-- 8.9 refunds (환불 요청 및 조회)
ALTER TABLE public.refunds ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "환불 내역 조회: 본인 신청 건 또는 관리자" ON public.refunds;
CREATE POLICY "환불 내역 조회: 본인 신청 건 또는 관리자"
    ON public.refunds FOR SELECT
    USING (auth.uid() = user_id OR public.is_admin());

DROP POLICY IF EXISTS "환불 요청 생성: 본인만 생성 가능" ON public.refunds;
CREATE POLICY "환불 요청 생성: 본인만 생성 가능"
    ON public.refunds FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "환불 관리: 관리자만 상태 변경 가능" ON public.refunds;
CREATE POLICY "환불 관리: 관리자만 상태 변경 가능"
    ON public.refunds FOR UPDATE
    USING (public.is_admin());

-- 8.10 notifications (알림)
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "알림 조회: 본인 알림만 조회" ON public.notifications;
CREATE POLICY "알림 조회: 본인 알림만 조회"
    ON public.notifications FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "알림 읽음 처리: 본인 알림만 수정 가능" ON public.notifications;
CREATE POLICY "알림 읽음 처리: 본인 알림만 수정 가능"
    ON public.notifications FOR UPDATE
    USING (auth.uid() = user_id);

-- 8.11 reviews (리뷰)
ALTER TABLE public.reviews ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "리뷰 조회: 누구나 조회 가능" ON public.reviews;
CREATE POLICY "리뷰 조회: 누구나 조회 가능"
    ON public.reviews FOR SELECT
    USING (true);

DROP POLICY IF EXISTS "리뷰 작성: 인증된 사용자가 본인 명의로 작성" ON public.reviews;
CREATE POLICY "리뷰 작성: 인증된 사용자가 본인 명의로 작성"
    ON public.reviews FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "리뷰 수정/삭제: 작성자 본인 또는 관리자" ON public.reviews;
CREATE POLICY "리뷰 수정/삭제: 작성자 본인 또는 관리자"
    ON public.reviews FOR ALL
    USING (auth.uid() = user_id OR public.is_admin());
