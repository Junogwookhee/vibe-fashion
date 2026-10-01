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
WHERE slug IN ('basic-crop-tshirt', 'wide-denim-pants', 'overfit-cotton-jacket', 'floral-midi-dress', 'classic-leather-totebag', 'minimal-chelsea-leather-boots')
   OR name IN ('베이직 크롭 티셔츠', '와이드 데님 팬츠', '오버핏 코튼 자켓', '플로럴 미디 원피스', '클래식 레더 토트백', '미니멀 첼시 레더 부츠');

-- 샘플 상품 6개 등록 순서:
-- 1) 와이드 데님 팬츠 (하의, 39,900원) - sort_order: 1
-- 2) 베이직 크롭 티셔츠 (상의, 정상가 29,900원 / 할인가 19,900원) - sort_order: 2
-- 3) 오버핏 코튼 자켓 (아우터, 59,900원) - sort_order: 3
-- 4) 플로럴 미디 원피스 (원피스, 45,900원) - sort_order: 4
-- 5) 클래식 레더 토트백 (가방, 정상가 148,000원 / 할인가 119,000원) - sort_order: 5
-- 6) 미니멀 첼시 레더 부츠 (신발, 168,000원) - sort_order: 6
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
        'https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=800&q=80',
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
        'https://images.unsplash.com/photo-1581655353564-df123a1eb820?auto=format&fit=crop&w=800&q=80',
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
        'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?auto=format&fit=crop&w=800&q=80',
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
        'https://images.unsplash.com/photo-1595777457583-95e059d581b8?auto=format&fit=crop&w=800&q=80',
        4,
        true,
        true
    ),
    (
        (SELECT id FROM public.categories WHERE slug = 'bag' LIMIT 1),
        '클래식 레더 토트백',
        'classic-leather-totebag',
        '고급 천연 소가죽의 은은한 결이 살아있는 모던 스퀘어 실루엣의 데일리 토트백',
        148000,
        119000,
        45,
        'https://images.unsplash.com/photo-1584917865442-de89df76afd3?auto=format&fit=crop&w=800&q=80',
        5,
        true,
        true
    ),
    (
        (SELECT id FROM public.categories WHERE slug = 'shoes' LIMIT 1),
        '미니멀 첼시 레더 부츠',
        'minimal-chelsea-leather-boots',
        '탄탄한 쉐입과 견고한 아웃솔로 편안한 착화감을 선사하는 클래식 첼시 부츠',
        168000,
        NULL,
        60,
        'https://images.unsplash.com/photo-1608256246200-53e635b5b65f?auto=format&fit=crop&w=800&q=80',
        6,
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
WHERE slug IN (
    'basic-crop-tshirt',
    'wide-denim-pants',
    'overfit-cotton-jacket',
    'floral-midi-dress',
    'classic-leather-totebag',
    'minimal-chelsea-leather-boots'
);

-- 5. 고객 리뷰 초기 데이터 등록 (reviews)
INSERT INTO public.reviews (product_id, user_id, rating, content)
SELECT
    p.id,
    u.id,
    r.rating,
    r.content
FROM (
    VALUES
        ('wide-denim-pants', 5, '핏이 정말 예술입니다! 하체 라인을 자연스럽고 슬림하게 커버해주고 사계절 내내 데일리로 입기 딱 좋아요. 강력 추천합니다.'),
        ('basic-crop-tshirt', 5, '목 늘어남 전혀 없고 코튼 소재가 정말 탄탄합니다. 하이웨이스트 팬츠랑 매치했을 때 기장감이 완벽해요.'),
        ('overfit-cotton-jacket', 5, '요즘 날씨에 입기 최고의 아우터입니다. 어깨 라인이 과하지 않게 떨어져서 고급스럽고 주위에서 칭찬을 정말 많이 들었어요.'),
        ('classic-leather-totebag', 5, '가죽 텍스처가 너무 고급스럽고 13인치 노트북까지 깔끔하게 수납됩니다. 디자인, 실용성 둘 다 잡은 인생 가방이에요!'),
        ('minimal-chelsea-leather-boots', 5, '발볼이 넓은 편인데도 하루 종일 걸어도 발이 편안해요! 가죽 질감도 은은한 광택감이 돌아서 슬랙스나 데님 어디에나 잘 어울립니다.'),
        ('floral-midi-dress', 5, '데이트룩이나 모임룩으로 최고예요! 잔잔한 플로럴 패턴이 화사하고 허리 라인을 예쁘게 잡아줘서 인생 사진 건졌습니다.')
) AS r(slug, rating, content)
JOIN public.products p ON p.slug = r.slug
CROSS JOIN (
    SELECT id FROM public.profiles ORDER BY created_at ASC LIMIT 1
) u
WHERE NOT EXISTS (
    SELECT 1
    FROM public.reviews existing
    WHERE existing.product_id = p.id
      AND existing.content = r.content
);