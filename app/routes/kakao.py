"""Supabase Kakao login for the existing Flask auth blueprint.

Save as app/routes/kakao.py. At the bottom of auth.py add:
    from .kakao import register_kakao_routes
    register_kakao_routes(auth_bp)

Required server environment: SUPABASE_ANON_KEY (public/anon API key).
Optional: SUPABASE_URL, KAKAO_REDIRECT_URL.
Never put a Kakao Client Secret or Supabase service-role key in this file.
"""

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from flask import current_app, redirect, request, session, url_for


def register_kakao_routes(auth_bp):
    load_dotenv()

    def settings():
        base = os.getenv(
            "SUPABASE_URL", "https://rdkvvonoenyzskovspcc.supabase.co"
        ).rstrip("/")
        key = os.getenv("SUPABASE_ANON_KEY", "").strip()
        callback = os.getenv(
            "KAKAO_REDIRECT_URL", "http://localhost:5000/auth/kakao/callback"
        ).strip()
        parts = urlsplit(callback)
        if not key or urlsplit(base).scheme != "https":
            raise ValueError("SUPABASE_URL / SUPABASE_ANON_KEY 설정 필요")
        if (parts.scheme not in ("http", "https") or not parts.netloc
                or parts.query or parts.fragment
                or parts.path != "/auth/kakao/callback"):
            raise ValueError("KAKAO_REDIRECT_URL 설정 확인 필요")
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("배포 환경에서는 HTTPS 주소가 필요합니다")
        return base, key, callback

    def fail(message):
        return redirect(url_for("auth.login", error=message))

    @auth_bp.route("/kakao", methods=["GET"])
    def kakao_login():
        if session.get("user_id"):
            return redirect(url_for("main.index"))
        try:
            base, _, callback = settings()
        except ValueError as exc:
            return fail(str(exc))

        # Always start on the callback's origin so its browser session matches.
        parts = urlsplit(callback)
        origin = f"{parts.scheme}://{parts.netloc}"
        if request.host_url.rstrip("/") != origin:
            return redirect(origin + "/auth/kakao")

        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        session["kakao_pkce"] = {"verifier": verifier, "created": time.time()}
        params = urlencode({
            "provider": "kakao",
            "redirect_to": callback,
            "scope": "profile_nickname",
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        })
        return redirect(f"{base}/auth/v1/authorize?{params}")

    @auth_bp.route("/kakao/callback", methods=["GET"])
    def kakao_callback():
        flow = session.pop("kakao_pkce", None)
        if request.args.get("error"):
            return fail("카카오 인증이 완료되지 않았습니다. 다시 시도해주세요.")
        code = request.args.get("code", "")
        if (not code or not isinstance(flow, dict)
                or not flow.get("verifier")
                or not 0 <= time.time() - flow.get("created", 0) <= 600):
            return fail("로그인 요청이 만료되었습니다. 카카오 로그인 버튼을 다시 눌러주세요.")
        try:
            base, key, _ = settings()
            token_request = Request(
                f"{base}/auth/v1/token?grant_type=pkce",
                data=json.dumps({
                    "auth_code": code,
                    "code_verifier": flow["verifier"],
                }).encode("utf-8"),
                headers={"apikey": key, "Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(token_request, timeout=15) as response:
                result = json.load(response)
            user = result.get("user") or {}
            if not user.get("id") or not result.get("access_token"):
                return fail("카카오 사용자 정보를 확인하지 못했습니다.")

            metadata = user.get("user_metadata") or {}
            email = user.get("email") or ""
            name = (metadata.get("full_name") or metadata.get("name")
                    or metadata.get("nickname") or metadata.get("preferred_username")
                    or (email.split("@")[0] if email else "카카오 회원"))
            # Match the existing application's session fields; keep cart data.
            session["user_id"] = user["id"]
            session["user"] = {
                "id": user["id"], "email": email, "full_name": str(name)[:100]
            }
            session["access_token"] = result["access_token"]
            session["refresh_token"] = result.get("refresh_token", "")
            return redirect(url_for("main.index"))
        except HTTPError as exc:
            # Do not log response bodies, tokens, authorization codes or keys.
            current_app.logger.warning("Kakao token exchange HTTP %s", exc.code)
            return fail("카카오 로그인 처리에 실패했습니다. Supabase 인증 설정을 확인해주세요.")
        except (URLError, TimeoutError, ValueError, KeyError, TypeError):
            current_app.logger.warning("Kakao login connection or response error")
            return fail("카카오 로그인 연결에 실패했습니다. 잠시 후 다시 시도해주세요.")
