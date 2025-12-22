import os
from datetime import timedelta

class Config:
    # Base de datos
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://postgres:kEIIFmMcSnyrYwasaqtuYqqQbHkldTez@hopper.proxy.rlwy.net:57142/railway'
    
    # Fix para Railway (usa postgres:// en lugar de postgresql://)
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Seguridad
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SESSION_COOKIE_SECURE = True  # Solo HTTPS en producción
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    
    # Archivos
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB máximo por archivo
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
    
    # Costos
    COSTO_BASE_CONSULTA = 15000  # Pesos

    DESCUENTO_GRUPO_FAMILIAR = 0.15  # 15% descuento por integrante adicional
