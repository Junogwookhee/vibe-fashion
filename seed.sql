-- ==============================================================================
-- VIBE-FASHION 쇼핑몰 초기 데이터(Seed) (Supabase SQL Editor 실행용)
-- ==============================================================================

-- 0. 기존 테이블에 컬럼이 누락되어 있을 경우를 대비한 컬럼 추가 보장
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE public.categories ADD COLUMN IF NOT EXISTS slug TEXT;

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

ALTER TABLE public.products ADD COLUMN IF NOT EXISTS category_id UUID REFERENCES public.categories(id) ON DELETE SET NULL;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS price NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS sale_price NUMERIC(12, 2);
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS stock INT NOT NULL DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT true;
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

-- product_options 및 product_images 테이블 구조도 확인/보장
CREATE TABLE IF NOT EXISTS public.product_options (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    option_name TEXT NOT NULL,
    option_value TEXT NOT NULL,
    additional_price NUMERIC(12, 2) NOT NULL DEFAULT 0,
    stock INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.product_options ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES public.products(id) ON DELETE CASCADE;
ALTER TABLE public.product_options ADD COLUMN IF NOT EXISTS option_name TEXT;
ALTER TABLE public.product_options ADD COLUMN IF NOT EXISTS option_value TEXT;
ALTER TABLE public.product_options ADD COLUMN IF NOT EXISTS additional_price NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE public.product_options ADD COLUMN IF NOT EXISTS stock INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS public.product_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id UUID NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.product_images ADD COLUMN IF NOT EXISTS product_id UUID REFERENCES public.products(id) ON DELETE CASCADE;
ALTER TABLE public.product_images ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE public.product_images ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 0;
ALTER TABLE public.product_images ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT false;

-- 1. 카테고리 7개 등록 (상의, 하의, 아우터, 원피스/세트, 액세서리, 가방, 신발)
INSERT INTO public.categories (name, slug, sort_order, is_active)
VALUES
    ('상의', 'top', 1, true),
    ('하의', 'bottom', 2, true),
    ('아우터', 'outer', 3, true),
    ('원피스/세트', 'dress', 4, true),
    ('액세서리', 'acc', 5, true),
    ('가방', 'bag', 6, true),
    ('신발', 'shoes', 7, true)
ON CONFLICT (slug) DO UPDATE
SET
    name = EXCLUDED.name,
    sort_order = EXCLUDED.sort_order,
    is_active = EXCLUDED.is_active;

-- 2. 기존 샘플 상품 및 연관 데이터 초기화 후 지정된 순서대로 재등록
-- 연관된 기존 옵션 및 이미지 삭제
DELETE FROM public.product_options
WHERE product_id IN (
    SELECT id FROM public.products
    WHERE slug IN ('basic-crop-tshirt', 'wide-denim-pants', 'overfit-cotton-jacket', 'floral-midi-dress')
       OR name IN ('베이직 크롭 티셔츠', '와이드 데님 팬츠', '오버핏 코튼 자켓', '플로럴 미디 원피스')
);

DELETE FROM public.product_images
WHERE product_id IN (
    SELECT id FROM public.products
    WHERE slug IN ('basic-crop-tshirt', 'wide-denim-pants', 'overfit-cotton-jacket', 'floral-midi-dress')
       OR name IN ('베이직 크롭 티셔츠', '와이드 데님 팬츠', '오버핏 코튼 자켓', '플로럴 미디 원피스')
);

-- 기존 4개 샘플 상품 삭제 (새 순서 반영을 위해 재생성)
DELETE FROM public.products
WHERE slug IN ('basic-crop-tshirt', 'wide-denim-pants', 'overfit-cotton-jacket', 'floral-midi-dress')
   OR name IN ('베이직 크롭 티셔츠', '와이드 데님 팬츠', '오버핏 코튼 자켓', '플로럴 미디 원피스');

-- 샘플 상품 4개 등록 순서:
-- 1) 와이드 데님 팬츠 (하의, 39,900원) - sort_order: 1
-- 2) 베이직 크롭 티셔츠 (상의, 정상가 29,900원 / 할인가 19,900원) - sort_order: 2 (와이드 데님 팬츠 뒤)
-- 3) 오버핏 코튼 자켓 (아우터, 59,900원) - sort_order: 3
-- 4) 플로럴 미디 원피스 (원피스, 45,900원) - sort_order: 4
INSERT INTO public.products (category_id, name, slug, description, price, sale_price, stock, thumbnail_url, sort_order, is_featured, is_active)
VALUES
    (
        (SELECT id FROM public.categories WHERE slug = 'bottom' LIMIT 1),
        '와이드 데님 팬츠',
        'wide-denim-pants',
        '자연스러운 워싱과 편안하고 멋스러운 와이드 핏 데님 팬츠',
        39900,
        NULL,
        120,
        'https://images.unsplash.com/photo-1582552938357-32b906df40cb?auto=format&fit=crop&w=600&q=80',
        1,
        true,
        true
    ),
    (
        (SELECT id FROM public.categories WHERE slug = 'top' LIMIT 1),
        '베이직 크롭 티셔츠',
        'basic-crop-tshirt',
        '트렌디하고 슬림한 실루엣의 데일리 코튼 크롭 티셔츠',
        29900,
        19900,
        180,
        'https://images.unsplash.com/photo-1581655353564-df123a1eb820?auto=format&fit=crop&w=600&q=80',
        2,
        true,
        true
    ),
    (
        (SELECT id FROM public.categories WHERE slug = 'outer' LIMIT 1),
        '오버핏 코튼 자켓',
        'overfit-cotton-jacket',
        '탄탄한 코튼 소재로 간절기에 캐주얼하게 걸치기 좋은 오버핏 자켓',
        59900,
        NULL,
        80,
        'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?auto=format&fit=crop&w=600&q=80',
        3,
        true,
        true
    ),
    (
        (SELECT id FROM public.categories WHERE slug = 'dress' LIMIT 1),
        '플로럴 미디 원피스',
        'floral-midi-dress',
        '은은한 플라워 패턴과 살랑이는 미디 기장감으로 우아한 무드의 원피스',
        45900,
        NULL,
        90,
        'https://images.unsplash.com/photo-1572804013309-59a88b7e92f1?auto=format&fit=crop&w=600&q=80',
        4,
        true,
        true
    );

-- 3. 베이직 크롭 티셔츠 옵션 정확히 9개 등록
-- (블랙 / 화이트 / 베이지) × (S / M / L)
INSERT INTO public.product_options (product_id, option_name, option_value, additional_price, stock)
SELECT
    p.id,
    '색상/사이즈',
    opt.color || ' / ' || opt.size,
    0,
    20
FROM (
    SELECT id FROM public.products
    WHERE slug = 'basic-crop-tshirt' OR name = '베이직 크롭 티셔츠'
    ORDER BY created_at DESC
    LIMIT 1
) p
CROSS JOIN (
    VALUES
        ('블랙', 'S'),
        ('블랙', 'M'),
        ('블랙', 'L'),
        ('화이트', 'S'),
        ('화이트', 'M'),
        ('화이트', 'L'),
        ('베이지', 'S'),
        ('베이지', 'M'),
        ('베이지', 'L')
) AS opt(color, size);

-- 4. 상품 기본 이미지 등록 (product_images)
INSERT INTO public.product_images (product_id, image_url, sort_order, is_primary)
SELECT id, thumbnail_url, 0, true
FROM public.products
WHERE slug IN ('basic-crop-tshirt', 'wide-denim-pants', 'overfit-cotton-jacket', 'floral-midi-dress');