import os
import logging
from functools import wraps
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)
from app.utils.supabase_client import get_supabase_client, get_supabase_admin_client
from app.utils.email_sender import (
    send_email_via_gmail_smtp,
    build_signup_confirmation_email,
    build_password_reset_email
)

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# SITE_URL 설정 (환경변수 또는 기본값)
SITE_URL = os.getenv("SITE_URL", "http://localhost:5000").rstrip("/")


# ==============================================================================
# login_required 데코레이터 (Flask session에서 user_id 확인)
# ==============================================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('auth.login', error='login_required', next=request.path))
        return f(*args, **kwargs)
    return decorated_function


# ==============================================================================
# 에러 및 성공 메시지 한국어 매핑
# ==============================================================================
ERROR_MESSAGES = {
    'email_not_confirmed': '이메일 인증이 완료되지 않았습니다. 메일함에서 인증 링크를 클릭해주세요.',
    'invalid_credentials': '이메일 또는 비밀번호가 올바르지 않습니다.',
    'login_required': '로그인이 필요한 서비스입니다.',
    'email_already_registered': '이미 가입된 이메일 주소입니다. 로그인해주세요.',
    'password_mismatch': '비밀번호와 비밀번호 확인이 일치하지 않습니다.',
    'password_too_short': '비밀번호는 최소 6자리 이상이어야 합니다.',
    'missing_fields': '필수 입력 항목을 모두 작성해주세요.',
    'token_invalid': '인증 링크가 유효하지 않거나 만료되었습니다. 다시 시도해주세요.',
    'reset_failed': '비밀번호 재설정에 실패했습니다. 다시 시도해주세요.',
    'email_send_failed': '메일 발송에 실패했습니다. 잠시 후 다시 시도해주세요.',
    'unknown_error': '요청 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'
}

SUCCESS_MESSAGES = {
    'logged_out': '성공적으로 로그아웃되었습니다.',
    'email_sent': '비밀번호 재설정 인증 메일이 발송되었습니다. 메일함을 확인해주세요.',
    'password_reset_success': '비밀번호가 성공적으로 변경되었습니다. 새 비밀번호로 로그인해주세요.',
    'signup_success': '회원가입이 완료되었습니다.',
    'email_confirmed': '이메일 인증이 성공적으로 완료되었습니다.'
}

def resolve_message(code: str, message_dict: dict) -> str:
    if not code:
        return ""
    return message_dict.get(code, code)


# ==============================================================================
# [1] GET/POST /auth/login - 로그인 폼 + 처리
# ==============================================================================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if session.get('user_id'):
            return redirect(url_for('main.index'))
        
        error_code = request.args.get('error')
        success_code = request.args.get('success') or request.args.get('msg')
        error_msg = resolve_message(error_code, ERROR_MESSAGES)
        success_msg = resolve_message(success_code, SUCCESS_MESSAGES)
        
        return render_template(
            'auth/login.html',
            error_code=error_code,
            error_msg=error_msg,
            success_msg=success_msg,
            email=request.args.get('email', '')
        )

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        return redirect(url_for('auth.login', error='missing_fields'))

    try:
        supabase = get_supabase_client()
        auth_res = supabase.auth.sign_in_with_password({
            'email': email,
            'password': password
        })

        if auth_res and auth_res.user:
            user = auth_res.user
            session['user_id'] = user.id
            full_name = None
            role = 'customer'
            if user.user_metadata:
                full_name = user.user_metadata.get('full_name')

            try:
                prof = supabase.table('profiles').select('full_name, role').eq('id', user.id).execute().data
                if prof:
                    if prof[0].get('full_name'):
                        full_name = prof[0].get('full_name')
                    role = prof[0].get('role') or 'customer'
            except Exception:
                pass

            session['is_admin'] = (role == 'admin')
            session['user'] = {
                'id': user.id,
                'email': user.email,
                'full_name': full_name or user.email.split('@')[0],
                'role': role
            }

            if auth_res.session:
                session['access_token'] = auth_res.session.access_token
                session['refresh_token'] = auth_res.session.refresh_token

            next_url = request.args.get('next')
            return redirect(next_url or url_for('main.index'))
        else:
            return redirect(url_for('auth.login', error='invalid_credentials'))

    except Exception as e:
        err_str = str(e).lower()
        logger.error(f"[Login Error] {e}", exc_info=True)
        if 'email not confirmed' in err_str:
            return redirect(url_for('auth.login', error='email_not_confirmed', email=email))
        return redirect(url_for('auth.login', error='invalid_credentials'))


# ==============================================================================
# [2] GET/POST /auth/signup - 회원가입 폼 + 처리
# ==============================================================================
@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        if session.get('user_id'):
            return redirect(url_for('main.index'))

        error_code = request.args.get('error')
        error_msg = resolve_message(error_code, ERROR_MESSAGES)
        return render_template(
            'auth/signup.html',
            error_code=error_code,
            error_msg=error_msg
        )

    email = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()
    password_confirm = request.form.get('password_confirm', '').strip()
    full_name = request.form.get('full_name', '').strip() or '고객'

    if not email or not password or not password_confirm:
        return redirect(url_for('auth.signup', error='missing_fields'))

    if len(password) < 6:
        return redirect(url_for('auth.signup', error='password_too_short'))

    if password != password_confirm:
        return redirect(url_for('auth.signup', error='password_mismatch'))

    try:
        redirect_url = f"{SITE_URL}/auth/confirm"
        admin_client = get_supabase_admin_client()

        # 1. Supabase 크레딧 절약: admin.generate_link로 링크만 생성하고 Supabase 자체 메일러는 건너뜀
        link_res = admin_client.auth.admin.generate_link({
            'type': 'signup',
            'email': email,
            'password': password,
            'options': {
                'data': {'full_name': full_name},
                'redirect_to': redirect_url
            }
        })

        verification_link = None
        if link_res and link_res.properties:
            verification_link = link_res.properties.action_link
            logger.info(f"[VIBE Auth] 회원가입 인증 링크 생성: {verification_link}")
            print(f"\n========================================================")
            print(f"[VIBE Auth] 📩 '{email}' 님을 위한 이메일 인증 링크:")
            print(f"{verification_link}")
            print(f"========================================================\n")

            # 2. Gmail SMTP(일일 500통 무료)로 사용자 이메일에 직접 발송
            html_body = build_signup_confirmation_email(full_name, verification_link)
            sent = send_email_via_gmail_smtp(
                to_email=email,
                subject="[VIBE-FASHION] 회원가입 이메일 인증을 완료해주세요",
                html_content=html_body
            )
            if sent:
                print(f"[VIBE Auth] Gmail SMTP를 통해 '{email}'로 인증 메일이 발송되었습니다.")

        session['verification_link'] = verification_link
        return redirect(url_for('auth.signup_complete', email=email))

    except Exception as e:
        err_str = str(e).lower()
        err_code = getattr(e, 'code', '') or ''
        logger.error(f"[Signup Error] {e}", exc_info=True)
        if (
            'already been registered' in err_str
            or 'already registered' in err_str
            or 'already exists' in err_str
            or err_code == 'email_exists'
        ):
            return redirect(url_for('auth.signup', error='email_already_registered'))
        return redirect(url_for('auth.signup', error='unknown_error'))


# ==============================================================================
# [3] GET /auth/signup-complete - "인증 메일을 보냈습니다" 안내
# ==============================================================================
@auth_bp.route('/signup-complete', methods=['GET'])
def signup_complete():
    email = request.args.get('email', '')
    verification_link = session.pop('verification_link', None)
    return render_template('auth/signup_complete.html', email=email, verification_link=verification_link)


# ==============================================================================
# [4] GET /auth/confirm - 이메일 인증 링크 클릭 처리
# ==============================================================================
@auth_bp.route('/confirm', methods=['GET'])
def confirm():
    token_hash = request.args.get('token_hash')
    otp_type = request.args.get('type', 'signup')
    code = request.args.get('code')
    token = request.args.get('token')
    email = request.args.get('email')

    supabase = get_supabase_client()
    auth_response = None

    try:
        if token_hash:
            auth_response = supabase.auth.verify_otp({
                'token_hash': token_hash,
                'type': otp_type
            })
        elif code:
            auth_response = supabase.auth.exchange_code_for_session({
                'auth_code': code
            })
        elif token and email:
            auth_response = supabase.auth.verify_otp({
                'email': email,
                'token': token,
                'type': otp_type
            })
        else:
            return redirect(url_for('auth.login', error='token_invalid'))

        if auth_response and auth_response.user:
            user = auth_response.user
            session['user_id'] = user.id
            full_name = user.user_metadata.get('full_name') if user.user_metadata else None

            if not full_name:
                try:
                    prof = supabase.table('profiles').select('full_name').eq('id', user.id).execute().data
                    if prof and prof[0].get('full_name'):
                        full_name = prof[0].get('full_name')
                except Exception:
                    pass

            session['user'] = {
                'id': user.id,
                'email': user.email,
                'full_name': full_name or user.email.split('@')[0]
            }

            if auth_response.session:
                session['access_token'] = auth_response.session.access_token
                session['refresh_token'] = auth_response.session.refresh_token

            return redirect('/mypage')
        else:
            return redirect(url_for('auth.login', error='token_invalid'))

    except Exception as e:
        logger.error(f"[Auth Confirm Error] {e}", exc_info=True)
        return redirect(url_for('auth.login', error='token_invalid'))


# ==============================================================================
# [5] GET/POST /auth/forgot-password - 비밀번호 재설정 메일 발송
# ==============================================================================
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        error_code = request.args.get('error')
        success_code = request.args.get('success') or request.args.get('msg')
        error_msg = resolve_message(error_code, ERROR_MESSAGES)
        success_msg = resolve_message(success_code, SUCCESS_MESSAGES)

        return render_template(
            'auth/forgot_password.html',
            error_code=error_code,
            error_msg=error_msg,
            success_msg=success_msg,
            email=request.args.get('email', '')
        )

    email = request.form.get('email', '').strip()
    if not email:
        return redirect(url_for('auth.forgot_password', error='missing_fields'))

    try:
        redirect_url = f"{SITE_URL}/auth/reset-password"
        admin_client = get_supabase_admin_client()

        # Supabase 크레딧 절약: admin.generate_link로 링크 생성 후 Gmail SMTP로 직접 전송
        rec_res = admin_client.auth.admin.generate_link({
            'type': 'recovery',
            'email': email,
            'options': {'redirect_to': redirect_url}
        })

        if not rec_res or not rec_res.properties:
            logger.error("[Forgot Password Error] Supabase에서 재설정 링크를 생성하지 못했습니다.")
            return redirect(url_for('auth.forgot_password', error='unknown_error'))

        if rec_res and rec_res.properties:
            reset_link = rec_res.properties.action_link

            user_name = "고객"
            if rec_res.user and rec_res.user.user_metadata:
                user_name = rec_res.user.user_metadata.get('full_name', '고객')

            html_body = build_password_reset_email(user_name, reset_link)
            sent = send_email_via_gmail_smtp(
                to_email=email,
                subject="[VIBE-FASHION] 비밀번호 재설정 안내",
                html_content=html_body
            )
            if not sent:
                return redirect(url_for('auth.forgot_password', error='email_send_failed', email=email))

        return redirect(url_for('auth.forgot_password', success='email_sent', email=email))

    except Exception as e:
        logger.error(f"[Forgot Password Error] {e}", exc_info=True)
        return redirect(url_for('auth.forgot_password', error='unknown_error'))


# ==============================================================================
# [6] GET/POST /auth/reset-password - 새 비밀번호 설정
# ==============================================================================
@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    supabase = get_supabase_client()

    if request.method == 'GET':
        token_hash = request.args.get('token_hash')
        code = request.args.get('code')
        otp_type = request.args.get('type', 'recovery')

        if token_hash:
            try:
                res = supabase.auth.verify_otp({'token_hash': token_hash, 'type': otp_type})
                if res and res.user:
                    session['user_id'] = res.user.id
                    if res.session:
                        session['access_token'] = res.session.access_token
                        session['refresh_token'] = res.session.refresh_token
            except Exception as e:
                logger.error(f"[Reset Password Token Error] {e}")
        elif code:
            try:
                res = supabase.auth.exchange_code_for_session({'auth_code': code})
                if res and res.user:
                    session['user_id'] = res.user.id
                    if res.session:
                        session['access_token'] = res.session.access_token
                        session['refresh_token'] = res.session.refresh_token
            except Exception as e:
                logger.error(f"[Reset Password Code Error] {e}")

        error_code = request.args.get('error')
        error_msg = resolve_message(error_code, ERROR_MESSAGES)
        return render_template(
            'auth/reset_password.html',
            error_code=error_code,
            error_msg=error_msg
        )

    # POST 처리
    password = request.form.get('password', '').strip()
    password_confirm = request.form.get('password_confirm', '').strip()
    access_token = request.form.get('access_token', '').strip() or session.get('access_token')

    if not password or not password_confirm:
        return redirect(url_for('auth.reset_password', error='missing_fields'))

    if len(password) < 6:
        return redirect(url_for('auth.reset_password', error='password_too_short'))

    if password != password_confirm:
        return redirect(url_for('auth.reset_password', error='password_mismatch'))

    user_id = session.get('user_id')

    try:
        updated = False
        if user_id:
            admin_client = get_supabase_admin_client()
            admin_client.auth.admin.update_user_by_id(user_id, {'password': password})
            updated = True
        elif access_token:
            supabase.auth.set_session(access_token, session.get('refresh_token', ''))
            supabase.auth.update_user({'password': password})
            updated = True

        if updated:
            session.pop('user_id', None)
            session.pop('user', None)
            session.pop('access_token', None)
            session.pop('refresh_token', None)
            return redirect(url_for('auth.login', success='password_reset_success'))
        else:
            return redirect(url_for('auth.reset_password', error='reset_failed'))

    except Exception as e:
        logger.error(f"[Reset Password Update Error] {e}", exc_info=True)
        return redirect(url_for('auth.reset_password', error='reset_failed'))


# ==============================================================================
# 로그아웃 및 마이페이지 라우트
# ==============================================================================
@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user', None)
    session.pop('access_token', None)
    session.pop('refresh_token', None)
    return redirect(url_for('auth.login', success='logged_out'))


@auth_bp.route('/mypage')
@login_required
def auth_mypage():
    return redirect('/mypage')


# ==============================================================================
# [7] POST /auth/delete-account (또는 /delete_account) - 회원 탈퇴 처리
# ==============================================================================
@auth_bp.route('/delete-account', methods=['POST'])
def delete_account():
    """
    회원 탈퇴 처리:
    - 로그인 여부 확인 (session['user_id'])
    - Supabase Auth에서 사용자 계정 삭제 (admin.delete_user)
    - profiles 테이블은 ON DELETE CASCADE로 자동 연쇄 삭제
    - 세션 클리어 (session.clear())
    - JSON 또는 리다이렉트 응답 지원
    """
    if "user_id" not in session:
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                "success": False,
                "message": "로그인이 필요합니다."
            }), 401
        return redirect(url_for('auth.login', error='login_required'))

    user_id = session["user_id"]

    try:
        admin_client = get_supabase_admin_client()
        admin_client.auth.admin.delete_user(user_id)

        # 세션 초기화
        session.clear()

        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                "success": True,
                "message": "회원탈퇴 완료"
            })

        flash("회원 탈퇴가 정상적으로 완료되었습니다. 그동안 이용해 주셔서 감사합니다.", "info")
        return redirect(url_for('main.index'))

    except Exception as e:
        logger.error(f"[Delete Account Error] {e}", exc_info=True)
        if request.is_json or request.headers.get('Accept') == 'application/json':
            return jsonify({
                "success": False,
                "message": f"회원탈퇴 실패: {str(e)}"
            }), 500
        flash("회원 탈퇴 처리 중 오류가 발생했습니다.", "danger")
        return redirect('/mypage')
from .kakao import register_kakao_routes
from .naver import register_naver_routes

register_kakao_routes(auth_bp)
register_naver_routes(auth_bp)