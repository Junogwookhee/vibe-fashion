"""Naver OAuth 2.0 login integration for Flask auth blueprint.
"""

import json
import logging
import os
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from flask import current_app, redirect, request, session, url_for
from app.utils.supabase_client import get_supabase_admin_client

logger = logging.getLogger(__name__)


def register_naver_routes(auth_bp):
    load_dotenv()

    def get_naver_settings():
        client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
        client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()
        callback = os.getenv("NAVER_REDIRECT_URI", "").strip()

        req_host = request.headers.get("X-Forwarded-Host", request.host)
        req_scheme = request.headers.get("X-Forwarded-Proto", request.scheme)

        # 로컬 개발 환경(localhost / 127.0.0.1)에서는 로컬 콜백 우선 적용
        if req_host and any(local in req_host for local in ("localhost", "127.0.0.1")):
            callback = f"{req_scheme}://{req_host}/auth/naver/callback"
        elif not callback:
            callback = f"{req_scheme}://{req_host}/auth/naver/callback"

        return client_id, client_secret, callback

    def fail(message):
        return redirect(url_for("auth.login", error=message))

    @auth_bp.route("/naver", methods=["GET"])
    def naver_login():
        if session.get("user_id"):
            return redirect(url_for("main.index"))

        client_id, _, callback = get_naver_settings()
        if not client_id:
            return fail("네이버 로그인 설정(NAVER_CLIENT_ID)이 필요합니다. 관리자에게 문의하세요.")

        # CSRF 방지용 state 토큰 생성
        state = secrets.token_urlsafe(32)
        session["naver_oauth_state"] = {
            "state": state,
            "created_at": time.time()
        }

        params = urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": callback,
            "state": state,
        })
        return redirect(f"https://nid.naver.com/oauth2.0/authorize?{params}")

    @auth_bp.route("/naver/callback", methods=["GET"])
    def naver_callback():
        flow = session.pop("naver_oauth_state", None)

        error = request.args.get("error")
        if error:
            error_description = request.args.get("error_description", "")
            logger.warning(f"Naver login auth error: {error} - {error_description}")
            return fail("네이버 로그인이 취소되었거나 인증에 실패했습니다.")

        code = request.args.get("code", "")
        received_state = request.args.get("state", "")

        # state 검증 및 만료 시간(10분) 확인
        if (not code or not isinstance(flow, dict)
                or not flow.get("state")
                or flow.get("state") != received_state
                or not 0 <= time.time() - flow.get("created_at", 0) <= 600):
            return fail("로그인 요청이 만료되었거나 비정상적인 접근입니다. 다시 시도해주세요.")

        client_id, client_secret, callback = get_naver_settings()
        if not client_id or not client_secret:
            return fail("네이버 로그인 키 설정(NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)이 필요합니다.")

        # 1. 접근 토큰(Access Token) 발급 요청
        try:
            token_params = urlencode({
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "state": received_state,
            })
            token_req = Request(
                f"https://nid.naver.com/oauth2.0/token?{token_params}",
                headers={"User-Agent": "Mozilla/5.0"},
                method="GET"
            )
            with urlopen(token_req, timeout=15) as token_res:
                token_data = json.load(token_res)

            access_token = token_data.get("access_token")
            if not access_token:
                logger.error(f"Naver token response missing access_token: {token_data}")
                return fail("네이버 접근 토큰 발급에 실패했습니다.")

            # 2. 사용자 프로필 정보 조회
            profile_req = Request(
                "https://openapi.naver.com/v1/nid/me",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": "Mozilla/5.0"
                },
                method="GET"
            )
            with urlopen(profile_req, timeout=15) as profile_res:
                profile_data = json.load(profile_res)

            if profile_data.get("resultcode") != "00":
                logger.error(f"Naver profile error: {profile_data}")
                return fail("네이버 프로필 조회에 실패했습니다.")

            naver_account = profile_data.get("response", {})
            naver_id = naver_account.get("id")
            email = naver_account.get("email") or ""
            name = (naver_account.get("name")
                    or naver_account.get("nickname")
                    or (email.split("@")[0] if email else "네이버 회원"))
            profile_image = naver_account.get("profile_image", "")

            # 이메일이 없는 경우 네이버 고유 ID 기반 고유 이메일 생성
            if not email:
                email = f"naver_{naver_id[:12]}@naver.auth"

            # 3. Supabase Admin API로 회원 연동 및 세션 생성
            admin_client = get_supabase_admin_client()

            # 기존 사용자 조회
            user = None
            try:
                users_list = admin_client.auth.admin.list_users()
                user_items = getattr(users_list, 'users', users_list) if users_list else []
                for u in user_items:
                    if getattr(u, 'email', None) == email:
                        user = u
                        break
            except Exception as e:
                logger.warning(f"Error checking existing Supabase user: {e}")

            # 신규 사용자일 경우 Supabase 계정 자동 생성
            if not user:
                random_pwd = secrets.token_urlsafe(24)
                create_res = admin_client.auth.admin.create_user({
                    "email": email,
                    "password": random_pwd,
                    "email_confirm": True,
                    "user_metadata": {
                        "full_name": name,
                        "avatar_url": profile_image,
                        "provider": "naver",
                        "naver_id": naver_id
                    }
                })
                user = getattr(create_res, 'user', create_res)

            user_id = getattr(user, 'id', None)
            if not user_id:
                return fail("회원 정보를 연동하지 못했습니다.")

            # profiles 테이블 확인 및 업데이트/생성 보장
            try:
                existing_profile = admin_client.table("profiles").select("id").eq("id", user_id).execute()
                if not existing_profile.data:
                    admin_client.table("profiles").insert({
                        "id": user_id,
                        "email": email,
                        "full_name": name,
                        "avatar_url": profile_image,
                        "role": "customer",
                        "grade": "BRONZE"
                    }).execute()
            except Exception as pe:
                logger.warning(f"Profiles upsert warning: {pe}")

            # Flask 로그인 세션 설정 (장바구니 세션 보존)
            session["user_id"] = user_id
            session["user"] = {
                "id": user_id,
                "email": email,
                "full_name": str(name)[:100]
            }

            return redirect(url_for("main.index"))

        except HTTPError as exc:
            current_app.logger.warning("Naver HTTP error: %s", exc.code)
            return fail("네이버 인증 서버와의 통신에 실패했습니다.")
        except (URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            current_app.logger.warning("Naver connection error: %s", exc)
            return fail("네이버 로그인 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
