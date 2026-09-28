import os
from flask import Flask
from dotenv import load_dotenv

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()

def create_app():
    """
    애플리케이션 팩토리 함수:
    Flask 앱 인스턴스를 생성하고 환경 설정 및 블루프린트(라우트)를 등록합니다.
    """
    app = Flask(__name__)

    # 기본 시크릿 키 설정 (.env의 SECRET_KEY 또는 기본값)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'vibe-fashion-default-secret')

    # routes 폴더에서 메인 블루프린트 가져와 등록하기
    from .routes.main import main_bp
    app.register_blueprint(main_bp)

    return app
