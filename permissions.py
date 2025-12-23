from functools import wraps
from flask import session, flash, redirect, url_for, request
from models import Usuario, RolUsuario
import json
from datetime import datetime

# ==================== DEFINICIÓN DE PERMISOS ====================

PERMISOS = {
    RolUsuario.ADMIN: {
        'especialidades': ['crear', 'editar', 'eliminar', 'ver'],
        'especialistas': ['crear', 'editar', 'eliminar', 'ver', 'horarios'],
        'usuarios': ['crear', 'editar', 'eliminar', 'ver'],
        'turnos': ['ver', 'modificar', 'cancelar', 'crear'],
        'pagos': ['ver', 'aprobar', 'rechazar', 'marcar_abonado'],
        'movimientos': ['ver', 'crear', 'modificar'],
        'reportes': ['ver', 'exportar'],
        'configuracion': ['ver', 'modificar'],
    },
    
    RolUsuario.RECEPCION: {
        'turnos': ['ver', 'crear'],
        'pagos': ['ver', 'marcar_abonado'],
        'pacientes': ['buscar', 'ver'],
    },
    
    RolUsuario.ESPECIALISTA: {
        'turnos': ['ver_propios', 'atender', 'observaciones'],
        'pacientes': ['ver_asignados'],
    },
    
    RolUsuario.PACIENTE: {
        'turnos': ['crear', 'ver_propios', 'cancelar_propios'],
        'pagos': ['ver_propios', 'subir_comprobante'],
        'historial': ['ver_propio'],
    }
}

# ==================== DECORADORES ====================

def permission_required(*permisos_requeridos):
    """
    Decorador para verificar permisos específicos
    
    Uso:
        @permission_required('especialidades:crear', 'especialidades:editar')
        def crear_especialidad():
            pass
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Debe iniciar sesión', 'warning')
                return redirect(url_for('login'))
            
            usuario = Usuario.query.get(session['user_id'])
            if not usuario:
                flash('Usuario no encontrado', 'danger')
                return redirect(url_for('login'))
            
            # Verificar cada permiso
            tiene_permiso = False
            permisos_usuario = PERMISOS.get(usuario.rol, {})
            
            for permiso in permisos_requeridos:
                if ':' in permiso:
                    recurso, accion = permiso.split(':')
                    if recurso in permisos_usuario and accion in permisos_usuario[recurso]:
                        tiene_permiso = True
                        break
            
            if not tiene_permiso:
                flash('No tiene permisos para realizar esta acción', 'danger')
                return redirect(url_for('dashboard_admin' if usuario.rol in [RolUsuario.ADMIN, RolUsuario.RECEPCION] else 'dashboard_user'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_only(f):
    """Decorador simplificado para acciones exclusivas de admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debe iniciar sesión', 'warning')
            return redirect(url_for('login'))
        
        usuario = Usuario.query.get(session['user_id'])
        if not usuario or usuario.rol != RolUsuario.ADMIN:
            flash('Acceso denegado. Solo administradores.', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function


def log_admin_action(accion, tabla=None, registro_id=None, datos_anteriores=None, datos_nuevos=None):
    """
    Registra una acción administrativa en la auditoría
    """
    from models_admin import AuditoriaAdmin
    from models import db
    
    if 'user_id' not in session:
        return
    
    auditoria = AuditoriaAdmin(
        usuario_id=session['user_id'],
        accion=accion,
        tabla_afectada=tabla,
        registro_id=registro_id,
        datos_anteriores=datos_anteriores,
        datos_nuevos=datos_nuevos,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:255]
    )
    
    db.session.add(auditoria)
    db.session.commit()