from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from models import db, Usuario, Especialidad, RolUsuario
from models_admin import (
    ConfiguracionEspecialista,
    EspecialistaEspecialidad,
    HorarioAtencion,
    BloqueoHorario,
    AuditoriaAdmin
)
from permissions import admin_only, permission_required, log_admin_action
from turno_generator import GeneradorTurnos
from datetime import datetime, date, time, timedelta
from sqlalchemy import func

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ==================== GESTIÓN DE ESPECIALIDADES ====================

@admin_bp.route('/especialidades')
@permission_required('especialidades:ver')
def listar_especialidades():
    """Lista todas las especialidades"""
    especialidades = Especialidad.query.order_by(Especialidad.nombre).all()
    return render_template('admin/especialidades_lista.html', especialidades=especialidades)


@admin_bp.route('/especialidades/crear', methods=['GET', 'POST'])
@permission_required('especialidades:crear')
def crear_especialidad():
    """Crear nueva especialidad"""
    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre')
            descripcion = request.form.get('descripcion')
            costo_consulta = float(request.form.get('costo_consulta'))
            duracion_turno = int(request.form.get('duracion_turno', 30))
            activo = request.form.get('activo') == 'on'
            
            # Validar que no exista
            if Especialidad.query.filter_by(nombre=nombre).first():
                flash('Ya existe una especialidad con ese nombre', 'danger')
                return redirect(request.url)
            
            especialidad = Especialidad(
                nombre=nombre,
                descripcion=descripcion,
                costo_consulta=costo_consulta,
                duracion_turno=duracion_turno,
                activo=activo
            )
            
            db.session.add(especialidad)
            db.session.commit()
            
            # Log de auditoría
            log_admin_action(
                accion='CREAR_ESPECIALIDAD',
                tabla='especialidades',
                registro_id=especialidad.id,
                datos_nuevos={'nombre': nombre, 'costo': costo_consulta}
            )
            
            flash(f'Especialidad "{nombre}" creada exitosamente', 'success')
            return redirect(url_for('admin.listar_especialidades'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear especialidad: {str(e)}', 'danger')
    
    return render_template('admin/especialidad_form.html', especialidad=None)


@admin_bp.route('/especialidades/editar/<int:id>', methods=['GET', 'POST'])
@permission_required('especialidades:editar')
def editar_especialidad(id):
    """Editar especialidad existente"""
    especialidad = Especialidad.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Guardar datos anteriores para auditoría
            datos_anteriores = {
                'nombre': especialidad.nombre,
                'costo_consulta': float(especialidad.costo_consulta),
                'activo': especialidad.activo
            }
            
            especialidad.nombre = request.form.get('nombre')
            especialidad.descripcion = request.form.get('descripcion')
            especialidad.costo_consulta = float(request.form.get('costo_consulta'))
            especialidad.duracion_turno = int(request.form.get('duracion_turno', 30))
            especialidad.activo = request.form.get('activo') == 'on'
            
            db.session.commit()
            
            # Log de auditoría
            log_admin_action(
                accion='MODIFICAR_ESPECIALIDAD',
                tabla='especialidades',
                registro_id=especialidad.id,
                datos_anteriores=datos_anteriores,
                datos_nuevos={
                    'nombre': especialidad.nombre,
                    'costo_consulta': float(especialidad.costo_consulta),
                    'activo': especialidad.activo
                }
            )
            
            flash('Especialidad actualizada correctamente', 'success')
            return redirect(url_for('admin.listar_especialidades'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')
    
    return render_template('admin/especialidad_form.html', especialidad=especialidad)


@admin_bp.route('/especialidades/eliminar/<int:id>', methods=['POST'])
@permission_required('especialidades:eliminar')
def eliminar_especialidad(id):
    """Eliminar (desactivar) especialidad"""
    especialidad = Especialidad.query.get_or_404(id)
    
    try:
        # No eliminar físicamente, solo desactivar
        especialidad.activo = False
        db.session.commit()
        
        log_admin_action(
            accion='ELIMINAR_ESPECIALIDAD',
            tabla='especialidades',
            registro_id=especialidad.id,
            datos_anteriores={'nombre': especialidad.nombre, 'activo': True}
        )
        
        flash(f'Especialidad "{especialidad.nombre}" desactivada', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect(url_for('admin.listar_especialidades'))


# ==================== GESTIÓN DE ESPECIALISTAS ====================

@admin_bp.route('/especialistas')
@permission_required('especialistas:ver')
def listar_especialistas():
    """Lista todos los especialistas"""
    especialistas = Usuario.query.filter_by(rol=RolUsuario.ESPECIALISTA).all()
    return render_template('admin/especialistas_lista.html', especialistas=especialistas)


@admin_bp.route('/especialistas/crear', methods=['GET', 'POST'])
@permission_required('especialistas:crear')
def crear_especialista():
    """Crear nuevo especialista"""
    if request.method == 'POST':
        try:
            # Datos del usuario
            nombre = request.form.get('nombre')
            apellido = request.form.get('apellido')
            dni = request.form.get('dni')
            email = request.form.get('email')
            telefono = request.form.get('telefono')
            password = request.form.get('password')
            
            # Validaciones
            if Usuario.query.filter_by(dni=dni).first():
                flash('Ya existe un usuario con ese DNI', 'danger')
                return redirect(request.url)
            
            if Usuario.query.filter_by(email=email).first():
                flash('Ya existe un usuario con ese email', 'danger')
                return redirect(request.url)
            
            # Crear usuario especialista
            especialista = Usuario(
                nombre=nombre,
                apellido=apellido,
                dni=dni,
                email=email,
                telefono=telefono,
                rol=RolUsuario.ESPECIALISTA
            )
            especialista.set_password(password)
            
            db.session.add(especialista)
            db.session.flush()  # Para obtener el ID
            
            # Configuración del especialista
            duracion_turno = int(request.form.get('duracion_turno', 30))
            pacientes_max = int(request.form.get('pacientes_maximos_dia', 20))
            tiempo_buffer = int(request.form.get('tiempo_buffer', 0))
            permite_sobreturnos = request.form.get('permite_sobreturnos') == 'on'
            sobreturnos_max = int(request.form.get('sobreturnos_maximos', 0)) if permite_sobreturnos else 0
            
            config = ConfiguracionEspecialista(
                especialista_id=especialista.id,
                duracion_turno_minutos=duracion_turno,
                pacientes_maximos_dia=pacientes_max,
                tiempo_buffer_minutos=tiempo_buffer,
                permite_sobreturnos=permite_sobreturnos,
                sobreturnos_maximos=sobreturnos_max
            )
            
            db.session.add(config)
            
            # Asignar especialidades
            especialidades_ids = request.form.getlist('especialidades[]')
            for esp_id in especialidades_ids:
                asignacion = EspecialistaEspecialidad(
                    especialista_id=especialista.id,
                    especialidad_id=int(esp_id)
                )
                db.session.add(asignacion)
            
            db.session.commit()
            
            log_admin_action(
                accion='CREAR_ESPECIALISTA',
                tabla='usuarios',
                registro_id=especialista.id,
                datos_nuevos={'nombre': f"{nombre} {apellido}", 'dni': dni}
            )
            
            flash(f'Especialista Dr/a. {nombre} {apellido} creado exitosamente', 'success')
            return redirect(url_for('admin.configurar_horarios', especialista_id=especialista.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear especialista: {str(e)}', 'danger')
    
    especialidades = Especialidad.query.filter_by(activo=True).all()
    return render_template('admin/especialista_form.html', 
                         especialista=None, 
                         especialidades=especialidades)


@admin_bp.route('/especialistas/editar/<int:id>', methods=['GET', 'POST'])
@permission_required('especialistas:editar')
def editar_especialista(id):
    """Editar especialista existente"""
    especialista = Usuario.query.get_or_404(id)
    
    if especialista.rol != RolUsuario.ESPECIALISTA:
        flash('El usuario no es un especialista', 'danger')
        return redirect(url_for('admin.listar_especialistas'))
    
    if request.method == 'POST':
        try:
            especialista.nombre = request.form.get('nombre')
            especialista.apellido = request.form.get('apellido')
            especialista.email = request.form.get('email')
            especialista.telefono = request.form.get('telefono')
            
            # Actualizar configuración
            config = ConfiguracionEspecialista.query.filter_by(
                especialista_id=especialista.id
            ).first()
            
            if not config:
                config = ConfiguracionEspecialista(especialista_id=especialista.id)
                db.session.add(config)
            
            config.duracion_turno_minutos = int(request.form.get('duracion_turno', 30))
            config.pacientes_maximos_dia = int(request.form.get('pacientes_maximos_dia', 20))
            config.tiempo_buffer_minutos = int(request.form.get('tiempo_buffer', 0))
            config.permite_sobreturnos = request.form.get('permite_sobreturnos') == 'on'
            config.sobreturnos_maximos = int(request.form.get('sobreturnos_maximos', 0)) if config.permite_sobreturnos else 0
            
            # Actualizar especialidades
            # Eliminar asignaciones anteriores
            EspecialistaEspecialidad.query.filter_by(
                especialista_id=especialista.id
            ).delete()
            
            # Crear nuevas asignaciones
            especialidades_ids = request.form.getlist('especialidades[]')
            for esp_id in especialidades_ids:
                asignacion = EspecialistaEspecialidad(
                    especialista_id=especialista.id,
                    especialidad_id=int(esp_id)
                )
                db.session.add(asignacion)
            
            db.session.commit()
            
            log_admin_action(
                accion='MODIFICAR_ESPECIALISTA',
                tabla='usuarios',
                registro_id=especialista.id
            )
            
            flash('Especialista actualizado correctamente', 'success')
            return redirect(url_for('admin.listar_especialistas'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')
    
    especialidades = Especialidad.query.filter_by(activo=True).all()
    especialidades_asignadas = [e.especialidad_id for e in especialista.especialidades_asignadas]
    
    return render_template('admin/especialista_form.html',
                         especialista=especialista,
                         especialidades=especialidades,
                         especialidades_asignadas=especialidades_asignadas)


# ==================== CONFIGURACIÓN DE HORARIOS ====================

@admin_bp.route('/especialistas/<int:especialista_id>/horarios')
@permission_required('especialistas:horarios')
def configurar_horarios(especialista_id):
    """Página de configuración de horarios"""
    especialista = Usuario.query.get_or_404(especialista_id)
    
    # Obtener horarios existentes agrupados por día
    horarios = HorarioAtencion.query.filter_by(
        especialista_id=especialista_id,
        activo=True
    ).order_by(HorarioAtencion.dia_semana, HorarioAtencion.hora_inicio).all()
    
    # Agrupar por día
    horarios_por_dia = {}
    for horario in horarios:
        dia = horario.dia_semana
        if dia not in horarios_por_dia:
            horarios_por_dia[dia] = []
        horarios_por_dia[dia].append(horario)
    
    # Obtener bloqueos
    bloqueos = BloqueoHorario.query.filter(
        BloqueoHorario.especialista_id == especialista_id,
        BloqueoHorario.fecha_fin >= date.today(),
        BloqueoHorario.activo == True
    ).order_by(BloqueoHorario.fecha_inicio).all()
    
    especialidades = especialista.especialidades_asignadas
    
    return render_template('admin/horarios_config.html',
                         especialista=especialista,
                         horarios_por_dia=horarios_por_dia,
                         bloqueos=bloqueos,
                         especialidades=especialidades)


@admin_bp.route('/horarios/agregar', methods=['POST'])
@permission_required('especialistas:horarios')
def agregar_horario():
    """Agregar nuevo horario de atención"""
    try:
        especialista_id = int(request.form.get('especialista_id'))
        especialidad_id = int(request.form.get('especialidad_id'))
        dia_semana = int(request.form.get('dia_semana'))
        hora_inicio_str = request.form.get('hora_inicio')
        hora_fin_str = request.form.get('hora_fin')
        duracion_custom = request.form.get('duracion_turno_custom')
        
        # Convertir horas
        hora_inicio = datetime.strptime(hora_inicio_str, '%H:%M').time()
        hora_fin = datetime.strptime(hora_fin_str, '%H:%M').time()
        
        # Validar que hora_fin > hora_inicio
        if hora_fin <= hora_inicio:
            flash('La hora de fin debe ser posterior a la hora de inicio', 'danger')
            return redirect(url_for('admin.configurar_horarios', especialista_id=especialista_id))
        
        # Verificar solapamiento
        horarios_existentes = HorarioAtencion.query.filter(
            HorarioAtencion.especialista_id == especialista_id,
            HorarioAtencion.especialidad_id == especialidad_id,
            HorarioAtencion.dia_semana == dia_semana,
            HorarioAtencion.activo == True
        ).all()
        
        for h in horarios_existentes:
            # Verificar si hay solapamiento
            if not (hora_fin <= h.hora_inicio or hora_inicio >= h.hora_fin):
                flash('El horario se solapa con otro existente', 'danger')
                return redirect(url_for('admin.configurar_horarios', especialista_id=especialista_id))
        
        # Crear horario
        horario = HorarioAtencion(
            especialista_id=especialista_id,
            especialidad_id=especialidad_id,
            dia_semana=dia_semana,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            duracion_turno_custom=int(duracion_custom) if duracion_custom else None
        )
        
        db.session.add(horario)
        db.session.commit()
        
        log_admin_action(
            accion='AGREGAR_HORARIO',
            tabla='horarios_atencion',
            registro_id=horario.id
        )
        
        flash('Horario agregado correctamente', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al agregar horario: {str(e)}', 'danger')
    
    return redirect(url_for('admin.configurar_horarios', especialista_id=especialista_id))


@admin_bp.route('/horarios/eliminar/<int:id>', methods=['POST'])
@permission_required('especialistas:horarios')
def eliminar_horario(id):
    """Eliminar horario de atención"""
    horario = HorarioAtencion.query.get_or_404(id)
    especialista_id = horario.especialista_id
    
    try:
        horario.activo = False
        db.session.commit()
        
        log_admin_action(
            accion='ELIMINAR_HORARIO',
            tabla='horarios_atencion',
            registro_id=horario.id
        )
        
        flash('Horario eliminado correctamente', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    
    return redirect(url_for('admin.configurar_horarios', especialista_id=especialista_id))


@admin_bp.route('/bloqueos/crear', methods=['POST'])
@permission_required('especialistas:horarios')
def crear_bloqueo():
    """Crear bloqueo de horario (vacaciones, ausencias)"""
    try:
        especialista_id = int(request.form.get('especialista_id'))
        fecha_inicio_str = request.form.get('fecha_inicio')
        fecha_fin_str = request.form.get('fecha_fin')
        motivo = request.form.get('motivo')
        observaciones = request.form.get('observaciones')
        
        # Horario específico (opcional)
        hora_inicio_str = request.form.get('hora_inicio')
        hora_fin_str = request.form.get('hora_fin')
        
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        
        hora_inicio = datetime.strptime(hora_inicio_str, '%H:%M').time() if hora_inicio_str else None
        hora_fin = datetime.strptime(hora_fin_str, '%H:%M').time() if hora_fin_str else None
        
        bloqueo = BloqueoHorario(
            especialista_id=especialista_id,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            motivo=motivo,
            observaciones=observaciones,
            creado_por=request.form.get('user_id')  # De session
        )
        
        db.session.add(bloqueo)
        db.session.commit()
        
        log_admin_action(
            accion='CREAR_BLOQUEO',
            tabla='bloqueos_horario',
            registro_id=bloqueo.id
        )
        
        flash(f'Bloqueo creado: {motivo}', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al crear bloqueo: {str(e)}', 'danger')
    
    return redirect(url_for('admin.configurar_horarios', especialista_id=especialista_id))


# ==================== USUARIOS ADMINISTRATIVOS ====================

@admin_bp.route('/usuarios')
@admin_only
def listar_usuarios_admin():
    """Lista usuarios administrativos y de recepción"""
    usuarios = Usuario.query.filter(
        Usuario.rol.in_([RolUsuario.ADMIN, RolUsuario.RECEPCION])
    ).all()
    
    return render_template('admin/usuarios_lista.html', usuarios=usuarios)


@admin_bp.route('/usuarios/crear', methods=['GET', 'POST'])
@admin_only
def crear_usuario_admin():
    """Crear usuario administrativo o recepción"""
    if request.method == 'POST':
        try:
            nombre = request.form.get('nombre')
            apellido = request.form.get('apellido')
            dni = request.form.get('dni')
            email = request.form.get('email')
            telefono = request.form.get('telefono')
            password = request.form.get('password')
            rol_str = request.form.get('rol')
            
            # Validar rol
            if rol_str not in ['admin', 'recepcion']:
                flash('Rol inválido', 'danger')
                return redirect(request.url)
            
            rol = RolUsuario.ADMIN if rol_str == 'admin' else RolUsuario.RECEPCION
            
            # Validaciones
            if Usuario.query.filter_by(dni=dni).first():
                flash('Ya existe un usuario con ese DNI', 'danger')
                return redirect(request.url)
            
            usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                dni=dni,
                email=email,
                telefono=telefono,
                rol=rol
            )
            usuario.set_password(password)
            
            db.session.add(usuario)
            db.session.commit()
            
            log_admin_action(
                accion='CREAR_USUARIO_ADMIN',
                tabla='usuarios',
                registro_id=usuario.id,
                datos_nuevos={'nombre': f"{nombre} {apellido}", 'rol': rol_str}
            )
            
            flash(f'Usuario {nombre} {apellido} creado exitosamente', 'success')
            return redirect(url_for('admin.listar_usuarios_admin'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    
    return render_template('admin/usuario_admin_form.html', usuario=None)


# ==================== API ENDPOINTS ====================

@admin_bp.route('/api/slots-disponibles')
@permission_required('turnos:ver')
def api_slots_disponibles():
    """API para obtener slots disponibles"""
    especialista_id = request.args.get('especialista_id', type=int)
    especialidad_id = request.args.get('especialidad_id', type=int)
    fecha_str = request.args.get('fecha')
    
    if not all([especialista_id, especialidad_id, fecha_str]):
        return jsonify({'error': 'Faltan parámetros'}), 400
    
    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        slots = GeneradorTurnos.obtener_slots_disponibles(
            especialista_id,
            especialidad_id,
            fecha
        )
        
        # Convertir a formato JSON
        slots_json = []
        for slot in slots:
            slots_json.append({
                'hora_inicio': slot['hora_inicio'].strftime('%H:%M'),
                'hora_fin': slot['hora_fin'].strftime('%H:%M'),
                'disponible': slot['disponible'],
                'turno_id': slot['turno_id']
            })
        
        return jsonify({'slots': slots_json})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/fechas-disponibles')
@permission_required('turnos:ver')
def api_fechas_disponibles():
    """API para obtener próximas fechas con disponibilidad"""
    especialista_id = request.args.get('especialista_id', type=int)
    especialidad_id = request.args.get('especialidad_id', type=int)
    dias = request.args.get('dias', type=int, default=30)
    
    if not all([especialista_id, especialidad_id]):
        return jsonify({'error': 'Faltan parámetros'}), 400
    
    try:
        fechas = GeneradorTurnos.obtener_proximas_fechas_disponibles(
            especialista_id,
            especialidad_id,
            dias
        )
        
        # Convertir a JSON
        fechas_json = []
        for f in fechas:
            fechas_json.append({
                'fecha': f['fecha'].strftime('%Y-%m-%d'),
                'dia_semana': f['dia_semana'],
                'slots_disponibles': f['slots_disponibles'],
                'slots_totales': f['slots_totales']
            })
        
        return jsonify({'fechas': fechas_json})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500