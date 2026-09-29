import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

def send_email_via_gmail_smtp(to_email: str, subject: str, html_content: str) -> bool:
    """
    Gmail SMTP(smtp.gmail.com:587)를 사용하여 인증 이메일을 직접 발송합니다.
    - Supabase 내장 이메일 발송 크레딧(시간당 3~4통)을 소모하지 않음
    - Gmail 무료 일일 500통 한도 활용
    """
    gmail_user = os.getenv("GMAIL_USER") or os.getenv("MAIL_USERNAME")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD") or os.getenv("MAIL_PASSWORD")

    if not gmail_user or not gmail_app_password:
        logger.warning(
            "[Gmail SMTP] GMAIL_USER 또는 GMAIL_APP_PASSWORD 환경변수가 설정되지 않았습니다. "
            "이메일 발송을 건너뜁니다."
        )
        return False

    try:
        # 공백 제거
        gmail_user = gmail_user.strip()
        gmail_app_password = gmail_app_password.replace(" ", "").strip()

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"VIBE-FASHION <{gmail_user}>"
        msg["To"] = to_email

        # HTML 본문 추가
        part = MIMEText(html_content, "html", "utf-8")
        msg.attach(part)

        # TLS 보안 연결 (587 포트)
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())

        logger.info(f"[Gmail SMTP] '{to_email}' 님에게 메일 전송 성공: {subject}")
        print(f"[Gmail SMTP] ✉️ '{to_email}' 님에게 인증 메일이 성공적으로 발송되었습니다!")
        return True

    except Exception as e:
        logger.error(f"[Gmail SMTP Error] 메일 전송 실패: {e}", exc_info=True)
        print(f"[Gmail SMTP Error] 메일 전송 실패: {e}")
        return False


def build_signup_confirmation_email(user_name: str, confirm_link: str) -> str:
    """회원가입 인증용 프리미엄 HTML 메일 템플릿"""
    return f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; }}
            .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
            .header {{ background: #0f172a; padding: 36px 30px; text-align: center; color: #ffffff; }}
            .brand {{ font-size: 22px; font-weight: 800; letter-spacing: 2px; color: #ffffff; margin-bottom: 6px; }}
            .sub-title {{ font-size: 13px; color: #94a3b8; letter-spacing: 1px; text-transform: uppercase; }}
            .content {{ padding: 36px 30px; color: #334155; line-height: 1.7; }}
            .greeting {{ font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 16px; }}
            .box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 24px 0; text-align: center; }}
            .btn {{ display: inline-block; background: #f43f5e; color: #ffffff !important; font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 50px; text-decoration: none; box-shadow: 0 4px 14px rgba(244,63,94,0.35); }}
            .link-text {{ word-break: break-all; font-size: 12px; color: #64748b; margin-top: 16px; line-height: 1.5; }}
            .footer {{ background: #f1f5f9; padding: 24px 30px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="brand">💎 VIBE FASHION</div>
                <div class="sub-title">Contemporary Lifestyle Select Shop</div>
            </div>
            <div class="content">
                <div class="greeting">{user_name}님, 환영합니다!</div>
                <p>VIBE-FASHION의 멤버가 되어주셔서 진심으로 감사드립니다.<br>
                아래 버튼을 클릭하시면 이메일 인증이 완료되며, 신규 회원 전용 <strong>10% 웰컴 쿠폰</strong>이 즉시 발급됩니다.</p>
                
                <div class="box">
                    <a href="{confirm_link}" class="btn" target="_blank">이메일 인증 완료하기</a>
                    <div class="link-text">
                        버튼이 클릭되지 않는 경우 아래 링크를 주소창에 붙여넣어 주세요:<br>
                        <a href="{confirm_link}" style="color: #f43f5e;">{confirm_link}</a>
                    </div>
                </div>

                <p style="font-size: 13px; color: #64748b; margin-top: 20px;">
                    * 본 메일은 회원가입 인증을 위해 발송되었습니다.<br>
                    * 본인이 요청하지 않은 경우 본 메일을 무시해주세요.
                </p>
            </div>
            <div class="footer">
                &copy; 2026 VIBE-FASHION. All rights reserved.<br>
                본 메일은 발신 전용 메일입니다.
            </div>
        </div>
    </body>
    </html>
    """


def build_password_reset_email(user_name: str, reset_link: str) -> str:
    """비밀번호 재설정용 프리미엄 HTML 메일 템플릿"""
    return f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; }}
            .container {{ max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
            .header {{ background: #0f172a; padding: 36px 30px; text-align: center; color: #ffffff; }}
            .brand {{ font-size: 22px; font-weight: 800; letter-spacing: 2px; color: #ffffff; margin-bottom: 6px; }}
            .content {{ padding: 36px 30px; color: #334155; line-height: 1.7; }}
            .greeting {{ font-size: 18px; font-weight: 700; color: #0f172a; margin-bottom: 16px; }}
            .box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 24px 0; text-align: center; }}
            .btn {{ display: inline-block; background: #0f172a; color: #ffffff !important; font-weight: 700; font-size: 15px; padding: 14px 32px; border-radius: 50px; text-decoration: none; }}
            .link-text {{ word-break: break-all; font-size: 12px; color: #64748b; margin-top: 16px; line-height: 1.5; }}
            .footer {{ background: #f1f5f9; padding: 24px 30px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="brand">🔒 VIBE FASHION</div>
                <div style="font-size: 13px; color: #94a3b8;">비밀번호 재설정 안내</div>
            </div>
            <div class="content">
                <div class="greeting">안녕하세요, {user_name}님.</div>
                <p>비밀번호 재설정을 요청하셨습니다.<br>
                아래 버튼을 클릭하여 새로운 비밀번호를 설정해주세요.</p>
                
                <div class="box">
                    <a href="{reset_link}" class="btn" target="_blank">새 비밀번호 설정하기</a>
                    <div class="link-text">
                        <a href="{reset_link}" style="color: #0f172a;">{reset_link}</a>
                    </div>
                </div>

                <p style="font-size: 13px; color: #e11d48;">
                    * 본인이 요청하지 않은 경우 계정 보안을 확인해주세요.
                </p>
            </div>
            <div class="footer">
                &copy; 2026 VIBE-FASHION. All rights reserved.
            </div>
        </div>
    </body>
    </html>
    """
