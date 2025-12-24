from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file
from functools import wraps
from datetime import datetime, date, timedelta
from calendar import monthrange
import gzip
import io

from models import db, Usuario, RolUsuario
from models_prepaga import (PlanPrepaga, SuscripcionPrepaga, PagoMensualPrepaga, 
                            HistorialConsultasPrepaga, TipoPlan, EstadoSuscripcion, 
                            EstadoPagoMensual)

prepaga_bp = Blueprint('prepaga', __name__, url_prefix='/prepaga')

# ==================== DECORADORES ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debe iniciar sesión para acceder a esta página', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debe iniciar sesión', 'warning')
            return redirect(url_for('login'))
        
        usuario = Usuario.query.get(session['user_id'])
        if not usuario or usuario.rol not in [RolUsuario.ADMIN, RolUsuario.RECEPCION]:
            flash('No tiene permisos para acceder a esta página', 'danger')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

# ==================== UTILIDADES ====================

def comprimir_archivo(archivo_bytes):
    """Comprime un archivo usando gzip"""
    return gzip.compress(archivo_bytes)

def descomprimir_archivo(archivo_comprimido):
    """Descomprime un archivo gzip"""
    return gzip.decompress(archivo_comprimido)

def allowed_file(filename):
    """Verifica si el archivo tiene una extensión permitida"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== RUTAS USUARIO ====================

@prepaga_bp.route('/planes')
@login_required
def ver_planes():
    """Muestra los planes disponibles"""
    planes = PlanPrepaga.query.filter_by(activo=True).all()
    
    # Verificar si el usuario ya tiene una suscripción
    suscripcion_activa = SuscripcionPrepaga.query.filter_by(
        usuario_id=session['user_id']
    ).filter(
        SuscripcionPrepaga.estado.in_([EstadoSuscripcion.ACTIVA, EstadoSuscripcion.PENDIENTE])
    ).first()
    
    return render_template('prepaga/planes.html', 
                         planes=planes,
                         suscripcion_activa=suscripcion_activa)

@prepaga_bp.route('/solicitar/<int:plan_id>', methods=['GET', 'POST'])
@login_required
def solicitar_plan(plan_id):
    """Solicitar suscripción a un plan"""
    plan = PlanPrepaga.query.get_or_404(plan_id)
    
    # Verificar si ya tiene una suscripción activa o pendiente
    suscripcion_existente = SuscripcionPrepaga.query.filter_by(
        usuario_id=session['user_id']
    ).filter(
        SuscripcionPrepaga.estado.in_([EstadoSuscripcion.ACTIVA, EstadoSuscripcion.PENDIENTE])
    ).first()
    
    if suscripcion_existente:
        flash('Ya tiene una suscripción activa o pendiente de aprobación', 'warning')
        return redirect(url_for('prepaga.mi_suscripcion'))
    
    if request.method == 'POST':
        try:
            # Verificar comprobante
            if 'comprobante' not in request.files:
                flash('Debe subir el comprobante de pago', 'danger')
                return redirect(request.url)
            
            archivo = request.files['comprobante']
            
            if archivo.filename == '':
                flash('No se seleccionó ningún archivo', 'danger')
                return redirect(request.url)
            
            if not allowed_file(archivo.filename):
                flash('Formato de archivo no permitido. Use JPG, PNG o PDF', 'danger')
                return redirect(request.url)
            
            # Leer y comprimir archivo
            archivo_bytes = archivo.read()
            
            if len(archivo_bytes) > 5 * 1024 * 1024:  # 5MB
                flash('El archivo es demasiado grande (máximo 5MB)', 'danger')
                return redirect(request.url)
            
            archivo_comprimido = comprimir_archivo(archivo_bytes)
            
            # Crear suscripción
            suscripcion = SuscripcionPrepaga(
                usuario_id=session['user_id'],
                plan_id=plan_id,
                estado=EstadoSuscripcion.PENDIENTE,
                observaciones=request.form.get('observaciones'),
                comprobante_inicial=archivo_comprimido,
                comprobante_inicial_nombre=archivo.filename,
                comprobante_inicial_tipo=archivo.content_type,
                fecha_subida_inicial=datetime.utcnow()
            )
            
            db.session.add(suscripcion)
            db.session.commit()
            
            flash('Solicitud enviada correctamente. En breve será revisada por un administrador.', 'success')
            return redirect(url_for('prepaga.mi_suscripcion'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al enviar solicitud: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('prepaga/solicitar_plan.html', plan=plan)

@prepaga_bp.route('/mi-suscripcion')
@login_required
def mi_suscripcion():
    """Panel del usuario con su suscripción"""
    # Buscamos una suscripción que no esté cancelada
    suscripcion = SuscripcionPrepaga.query.filter_by(
        usuario_id=session['user_id']
    ).filter(
        SuscripcionPrepaga.estado != EstadoSuscripcion.CANCELADA
    ).first()
    
    # Si no tiene suscripción, mostramos la invitación en lugar de redirigir
    if not suscripcion:
        return render_template('prepaga/mi_suscripcion_vacia.html')
    
    # Obtener historial de pagos mensuales
    pagos_mensuales = PagoMensualPrepaga.query.filter_by(
        suscripcion_id=suscripcion.id
    ).order_by(PagoMensualPrepaga.anio.desc(), PagoMensualPrepaga.mes.desc()).all()
    
    # Verificar pago del mes actual
    hoy = date.today()
    pago_mes_actual = PagoMensualPrepaga.query.filter_by(
        suscripcion_id=suscripcion.id,
        mes=hoy.month,
        anio=hoy.year
    ).first()
    
    return render_template('prepaga/mi_suscripcion.html',
                         suscripcion=suscripcion,
                         pagos_mensuales=pagos_mensuales,
                         pago_mes_actual=pago_mes_actual)

@prepaga_bp.route('/pagar-mes/<int:pago_id>', methods=['GET', 'POST'])
@login_required
def pagar_mes(pago_id):
    """Subir comprobante de pago mensual"""
    pago = PagoMensualPrepaga.query.get_or_404(pago_id)
    
    # Verificar permisos
    if pago.suscripcion.usuario_id != session['user_id']:
        flash('No tiene permisos para este pago', 'danger')
        return redirect(url_for('prepaga.mi_suscripcion'))
    
    if pago.estado == EstadoPagoMensual.APROBADO:
        flash('Este pago ya fue aprobado', 'info')
        return redirect(url_for('prepaga.mi_suscripcion'))
    
    if request.method == 'POST':
        try:
            if 'comprobante' not in request.files:
                flash('Debe subir el comprobante de pago', 'danger')
                return redirect(request.url)
            
            archivo = request.files['comprobante']
            
            if archivo.filename == '':
                flash('No se seleccionó ningún archivo', 'danger')
                return redirect(request.url)
            
            if not allowed_file(archivo.filename):
                flash('Formato de archivo no permitido. Use JPG, PNG o PDF', 'danger')
                return redirect(request.url)
            
            # Leer y comprimir archivo
            archivo_bytes = archivo.read()
            
            if len(archivo_bytes) > 5 * 1024 * 1024:
                flash('El archivo es demasiado grande (máximo 5MB)', 'danger')
                return redirect(request.url)
            
            archivo_comprimido = comprimir_archivo(archivo_bytes)
            
            # Actualizar pago
            pago.comprobante = archivo_comprimido
            pago.comprobante_nombre = archivo.filename
            pago.comprobante_tipo = archivo.content_type
            pago.fecha_subida = datetime.utcnow()
            pago.estado = EstadoPagoMensual.PENDIENTE
            pago.observaciones = request.form.get('observaciones')
            
            db.session.commit()
            
            flash('Comprobante subido correctamente. Será revisado en breve.', 'success')
            return redirect(url_for('prepaga.mi_suscripcion'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al subir comprobante: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('prepaga/pagar_mes.html', pago=pago)

@prepaga_bp.route('/cancelar-suscripcion', methods=['POST'])
@login_required
def cancelar_suscripcion():
    """Cancelar suscripción"""
    suscripcion = SuscripcionPrepaga.query.filter_by(
        usuario_id=session['user_id'],
        estado=EstadoSuscripcion.ACTIVA
    ).first()
    
    if not suscripcion:
        flash('No tiene una suscripción activa para cancelar', 'warning')
        return redirect(url_for('prepaga.mi_suscripcion'))
    
    suscripcion.estado = EstadoSuscripcion.CANCELADA
    suscripcion.cancelado_por = session['user_id']
    suscripcion.fecha_cancelacion = datetime.utcnow()
    
    db.session.commit()
    
    flash('Suscripción cancelada correctamente', 'info')
    return redirect(url_for('prepaga.ver_planes'))

# ==================== RUTAS ADMIN ====================

@prepaga_bp.route('/admin/solicitudes')
@admin_required
def admin_solicitudes():
    """Lista de solicitudes pendientes"""
    solicitudes = SuscripcionPrepaga.query.filter_by(
        estado=EstadoSuscripcion.PENDIENTE
    ).order_by(SuscripcionPrepaga.fecha_solicitud.desc()).all()
    
    return render_template('prepaga/admin_solicitudes.html', solicitudes=solicitudes)

@prepaga_bp.route('/admin/aprobar-solicitud/<int:suscripcion_id>', methods=['POST'])
@admin_required
def aprobar_solicitud(suscripcion_id):
    """Aprobar solicitud de suscripción"""
    suscripcion = SuscripcionPrepaga.query.get_or_404(suscripcion_id)
    
    if suscripcion.estado != EstadoSuscripcion.PENDIENTE:
        flash('Esta solicitud ya fue procesada', 'warning')
        return redirect(url_for('prepaga.admin_solicitudes'))
    
    try:
        # Actualizar suscripción
        suscripcion.estado = EstadoSuscripcion.ACTIVA
        suscripcion.fecha_aprobacion = datetime.utcnow()
        suscripcion.fecha_inicio = date.today()
        suscripcion.aprobado_por = session['user_id']
        
        # Calcular consultas disponibles
        plan = suscripcion.plan
        suscripcion.consultas_disponibles = plan.consultas_incluidas * plan.personas_maximas
        suscripcion.consultas_consumidas = 0
        
        # Crear primer pago mensual para el próximo mes
        hoy = date.today()
        if hoy.month == 12:
            proximo_mes = 1
            proximo_anio = hoy.year + 1
        else:
            proximo_mes = hoy.month + 1
            proximo_anio = hoy.year
        
        # Fecha de vencimiento: día 10 del próximo mes
        ultimo_dia = monthrange(proximo_anio, proximo_mes)[1]
        fecha_venc = date(proximo_anio, proximo_mes, min(10, ultimo_dia))
        
        pago_mensual = PagoMensualPrepaga(
            suscripcion_id=suscripcion.id,
            mes=proximo_mes,
            anio=proximo_anio,
            monto=plan.precio_mensual,
            fecha_vencimiento=fecha_venc,
            estado=EstadoPagoMensual.PENDIENTE
        )
        
        db.session.add(pago_mensual)
        db.session.commit()
        
        flash('Solicitud aprobada correctamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al aprobar solicitud: {str(e)}', 'danger')
    
    return redirect(url_for('prepaga.admin_solicitudes'))

@prepaga_bp.route('/admin/rechazar-solicitud/<int:suscripcion_id>', methods=['POST'])
@admin_required
def rechazar_solicitud(suscripcion_id):
    """Rechazar solicitud de suscripción"""
    suscripcion = SuscripcionPrepaga.query.get_or_404(suscripcion_id)
    
    if suscripcion.estado != EstadoSuscripcion.PENDIENTE:
        flash('Esta solicitud ya fue procesada', 'warning')
        return redirect(url_for('prepaga.admin_solicitudes'))
    
    motivo = request.form.get('motivo_rechazo', 'No especificado')
    
    suscripcion.estado = EstadoSuscripcion.CANCELADA
    suscripcion.motivo_rechazo = motivo
    suscripcion.aprobado_por = session['user_id']
    
    db.session.commit()
    
    flash('Solicitud rechazada', 'info')
    return redirect(url_for('prepaga.admin_solicitudes'))

@prepaga_bp.route('/admin/pagos-mensuales')
@admin_required
def admin_pagos_mensuales():
    """Lista de pagos mensuales pendientes"""
    pagos_pendientes = PagoMensualPrepaga.query.filter_by(
        estado=EstadoPagoMensual.PENDIENTE
    ).filter(
        PagoMensualPrepaga.comprobante.isnot(None)
    ).order_by(PagoMensualPrepaga.fecha_subida.desc()).all()
    
    return render_template('prepaga/admin_pagos_mensuales.html', pagos=pagos_pendientes)

@prepaga_bp.route('/admin/aprobar-pago-mensual/<int:pago_id>', methods=['POST'])
@admin_required
def aprobar_pago_mensual(pago_id):
    """Aprobar pago mensual"""
    pago = PagoMensualPrepaga.query.get_or_404(pago_id)
    
    if pago.estado == EstadoPagoMensual.APROBADO:
        flash('Este pago ya fue aprobado', 'info')
        return redirect(url_for('prepaga.admin_pagos_mensuales'))
    
    try:
        pago.estado = EstadoPagoMensual.APROBADO
        pago.fecha_aprobacion = datetime.utcnow()
        pago.aprobado_por = session['user_id']
        
        # Reactivar suscripción si estaba suspendida
        if pago.suscripcion.estado == EstadoSuscripcion.SUSPENDIDA:
            pago.suscripcion.estado = EstadoSuscripcion.ACTIVA
        
        # Crear pago para el próximo mes
        if pago.mes == 12:
            proximo_mes = 1
            proximo_anio = pago.anio + 1
        else:
            proximo_mes = pago.mes + 1
            proximo_anio = pago.anio
        
        # Verificar si ya existe pago para el próximo mes
        pago_existente = PagoMensualPrepaga.query.filter_by(
            suscripcion_id=pago.suscripcion_id,
            mes=proximo_mes,
            anio=proximo_anio
        ).first()
        
        if not pago_existente:
            ultimo_dia = monthrange(proximo_anio, proximo_mes)[1]
            fecha_venc = date(proximo_anio, proximo_mes, min(10, ultimo_dia))
            
            nuevo_pago = PagoMensualPrepaga(
                suscripcion_id=pago.suscripcion_id,
                mes=proximo_mes,
                anio=proximo_anio,
                monto=pago.suscripcion.plan.precio_mensual,
                fecha_vencimiento=fecha_venc,
                estado=EstadoPagoMensual.PENDIENTE
            )
            db.session.add(nuevo_pago)
        
        db.session.commit()
        flash('Pago aprobado correctamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al aprobar pago: {str(e)}', 'danger')
    
    return redirect(url_for('prepaga.admin_pagos_mensuales'))

@prepaga_bp.route('/admin/rechazar-pago-mensual/<int:pago_id>', methods=['POST'])
@admin_required
def rechazar_pago_mensual(pago_id):
    """Rechazar pago mensual"""
    pago = PagoMensualPrepaga.query.get_or_404(pago_id)
    
    motivo = request.form.get('motivo_rechazo', 'Comprobante inválido')
    
    pago.estado = EstadoPagoMensual.RECHAZADO
    pago.motivo_rechazo = motivo
    pago.aprobado_por = session['user_id']
    
    db.session.commit()
    
    flash('Pago rechazado', 'info')
    return redirect(url_for('prepaga.admin_pagos_mensuales'))

@prepaga_bp.route('/admin/suscripciones')
@admin_required
def admin_suscripciones():
    """Lista todas las suscripciones"""
    estado_filtro = request.args.get('estado')
    
    query = SuscripcionPrepaga.query
    
    if estado_filtro:
        try:
            estado = EstadoSuscripcion[estado_filtro.upper()]
            query = query.filter_by(estado=estado)
        except KeyError:
            pass
    
    suscripciones = query.order_by(SuscripcionPrepaga.fecha_solicitud.desc()).all()
    
    return render_template('prepaga/admin_suscripciones.html', suscripciones=suscripciones)

@prepaga_bp.route('/ver-comprobante/<tipo>/<int:id>')
@login_required
def ver_comprobante(tipo, id):
    """Ver comprobante (inicial o mensual)"""
    try:
        if tipo == 'inicial':
            suscripcion = SuscripcionPrepaga.query.get_or_404(id)
            
            # Verificar permisos
            usuario = Usuario.query.get(session['user_id'])
            es_propietario = suscripcion.usuario_id == session['user_id']
            es_admin = usuario.rol in [RolUsuario.ADMIN, RolUsuario.RECEPCION]
            
            if not (es_propietario or es_admin):
                flash('No tiene permisos', 'danger')
                return redirect(url_for('index'))
            
            if not suscripcion.comprobante_inicial:
                flash('No hay comprobante', 'warning')
                return redirect(url_for('prepaga.mi_suscripcion'))
            
            archivo_descomprimido = descomprimir_archivo(suscripcion.comprobante_inicial)
            nombre = suscripcion.comprobante_inicial_nombre
            mime = suscripcion.comprobante_inicial_tipo
            
        elif tipo == 'mensual':
            pago = PagoMensualPrepaga.query.get_or_404(id)
            
            # Verificar permisos
            usuario = Usuario.query.get(session['user_id'])
            es_propietario = pago.suscripcion.usuario_id == session['user_id']
            es_admin = usuario.rol in [RolUsuario.ADMIN, RolUsuario.RECEPCION]
            
            if not (es_propietario or es_admin):
                flash('No tiene permisos', 'danger')
                return redirect(url_for('index'))
            
            if not pago.comprobante:
                flash('No hay comprobante', 'warning')
                return redirect(url_for('prepaga.mi_suscripcion'))
            
            archivo_descomprimido = descomprimir_archivo(pago.comprobante)
            nombre = pago.comprobante_nombre
            mime = pago.comprobante_tipo
        else:
            flash('Tipo de comprobante inválido', 'danger')
            return redirect(url_for('index'))
        
        return send_file(
            io.BytesIO(archivo_descomprimido),
            mimetype=mime or 'application/octet-stream',
            as_attachment=False,
            download_name=nombre
        )
        
    except Exception as e:
        flash(f'Error al recuperar comprobante: {str(e)}', 'danger')
        return redirect(url_for('prepaga.mi_suscripcion'))