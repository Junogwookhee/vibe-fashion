-- ==============================================================================
-- 마이그레이션: 메인 배너(banners) 및 상단 공지(announcements) 테이블 생성
-- ==============================================================================

-- 1. 메인 배너 (banners)
CREATE TABLE IF NOT EXISTS public.banners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,                         -- 관리용 배너 이름 (내부 관리용)
    image_url TEXT NOT NULL,                    -- 배너 이미지 URL
    image_alt TEXT,                             -- 이미지 대체 텍스트
    title TEXT,                                 -- 고객 표시 제목 (선택)
    description TEXT,                           -- 고객 표시 설명 문구 (선택)
    button_text TEXT,                           -- 버튼 문구 (선택)
    link_url TEXT,                              -- 연결 주소 (선택)
    is_active BOOLEAN NOT NULL DEFAULT false,   -- 공개/숨김 상태 (기본 숨김)
    sort_order INT NOT NULL DEFAULT 0,          -- 노출 순서 (낮을수록 먼저 노출)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_banners_is_active_sort ON public.banners(is_active, sort_order ASC);

-- 2. 상단 공지 (announcements)
CREATE TABLE IF NOT EXISTS public.announcements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,                         -- 관리용 공지 이름 (내부 관리용)
    content VARCHAR(100) NOT NULL,              -- 고객 표시 공지 문구 (최대 100자)
    link_url TEXT,                              -- 연결 주소 (선택)
    is_active BOOLEAN NOT NULL DEFAULT false,   -- 공개/숨김 상태 (기본 숨김)
    sort_order INT NOT NULL DEFAULT 0,          -- 노출 순서 (낮을수록 우선순위 높음)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_announcements_is_active_sort ON public.announcements(is_active, sort_order ASC);

-- 3. Row Level Security (RLS) 정책
-- 공개 조회(SELECT)는 누구나 가능, 변경(INSERT/UPDATE/DELETE)은 관리자만 가능

ALTER TABLE public.banners ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.announcements ENABLE ROW LEVEL SECURITY;

-- banners RLS
DROP POLICY IF EXISTS "공개 배너 조회: 누구나 가능" ON public.banners;
CREATE POLICY "공개 배너 조회: 누구나 가능"
    ON public.banners FOR SELECT
    USING (is_active = true OR public.is_admin());

DROP POLICY IF EXISTS "배너 관리: 관리자 전용" ON public.banners;
CREATE POLICY "배너 관리: 관리자 전용"
    ON public.banners FOR ALL
    TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());

-- announcements RLS
DROP POLICY IF EXISTS "공개 공지 조회: 누구나 가능" ON public.announcements;
CREATE POLICY "공개 공지 조회: 누구나 가능"
    ON public.announcements FOR SELECT
    USING (is_active = true OR public.is_admin());

DROP POLICY IF EXISTS "공지 관리: 관리자 전용" ON public.announcements;
CREATE POLICY "공지 관리: 관리자 전용"
    ON public.announcements FOR ALL
    TO authenticated
    USING (public.is_admin())
    WITH CHECK (public.is_admin());
