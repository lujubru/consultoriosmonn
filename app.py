from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from functools import wraps
from datetime import datetime, date, time, timedelta
from sqlalchemy import func, and_, or_
import gzip
import io
import os


from config import Config
from models import (db, Usuario, GrupoFamiliar, Especialidad, Turno, Pago, 
                   Movimiento, HorarioDisponible, RolUsuario, EstadoTurno, 
                   EstadoPago, TipoMovimiento)
from admin_routes import admin_bp
from models_admin import EspecialistaEspecialidad
from turno_generator import GeneradorTurnos
from prepaga_routes import prepaga_bp
from models_prepaga import (SuscripcionPrepaga, EstadoSuscripcion, 
                            HistorialConsultasPrepaga, PagoMensualPrepaga, EstadoPagoMensual)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# Registrar Blueprint de administración
app.register_blueprint(admin_bp)
app.register_blueprint(prepaga_bp)

# ==================== DECORADORES ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debe iniciar sesión para acceder a esta página', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Debe iniciar sesión', 'warning')
                return redirect(url_for('login'))
            
            usuario = Usuario.query.get(session['user_id'])
            if not usuario or usuario.rol not in roles:
                flash('No tiene permisos para acceder a esta página', 'danger')
                return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ==================== UTILIDADES ====================

def comprimir_archivo(archivo_bytes):
    """Comprime un archivo usando gzip"""
    return gzip.compress(archivo_bytes)

def descomprimir_archivo(archivo_comprimido):
    """Descomprime un archivo gzip"""
    return gzip.decompress(archivo_comprimido)

def allowed_file(filename):
    """Verifica si el archivo tiene una extensión permitida"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def calcular_costo_grupo_familiar(usuario_id):
    """Calcula el costo con descuento por grupo familiar"""
    cant_familiares = GrupoFamiliar.query.filter_by(
        usuario_id=usuario_id, 
        activo=True
    ).count()
    
    costo_base = app.config['COSTO_BASE_CONSULTA']
    descuento = app.config['DESCUENTO_GRUPO_FAMILIAR']
    
    if cant_familiares == 0:
        return costo_base
    
    descuento_total = descuento * cant_familiares
    if descuento_total > 0.5:  # Máximo 50% descuento
        descuento_total = 0.5
    
    return costo_base * (1 - descuento_total)

# ==================== RUTAS PÚBLICAS ====================

@app.route('/')
def index():
    especialidades = Especialidad.query.filter_by(activo=True).all()
    
    # Calcular costo simulado para vista previa
    costo_base = app.config['COSTO_BASE_CONSULTA']
    
    return render_template('index.html', 
                         especialidades=especialidades,
                         costo_base=costo_base)

@app.route('/simular-costo', methods=['POST'])
def simular_costo():
    """Simula el costo según cantidad de familiares"""
    cant_familiares = int(request.form.get('cant_familiares', 0))
    
    costo_base = app.config['COSTO_BASE_CONSULTA']
    descuento = app.config['DESCUENTO_GRUPO_FAMILIAR']
    
    descuento_total = descuento * cant_familiares
    if descuento_total > 0.5:
        descuento_total = 0.5
    
    costo_final = costo_base * (1 - descuento_total)
    ahorro = costo_base - costo_final
    
    return render_template('simulador_result.html',
                         costo_base=costo_base,
                         cant_familiares=cant_familiares,
                         descuento_pct=descuento_total * 100,
                         costo_final=costo_final,
                         ahorro=ahorro)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            # Datos del usuario
            nombre = request.form.get('nombre')
            apellido = request.form.get('apellido')
            dni = request.form.get('dni')
            email = request.form.get('email')
            telefono = request.form.get('telefono')
            password = request.form.get('password')
            password_confirm = request.form.get('password_confirm')
            
            # Validaciones
            if password != password_confirm:
                flash('Las contraseñas no coinciden', 'danger')
                return redirect(url_for('register'))
            
            if Usuario.query.filter_by(dni=dni).first():
                flash('El DNI ya está registrado', 'danger')
                return redirect(url_for('register'))
            
            if Usuario.query.filter_by(email=email).first():
                flash('El email ya está registrado', 'danger')
                return redirect(url_for('register'))
            
            # Crear usuario
            usuario = Usuario(
                nombre=nombre,
                apellido=apellido,
                dni=dni,
                email=email,
                telefono=telefono,
                rol=RolUsuario.PACIENTE
            )
            usuario.set_password(password)
            
            db.session.add(usuario)
            db.session.flush()  # Para obtener el ID
            
            # Grupo familiar (opcional)
            familiares_nombres = request.form.getlist('familiar_nombre[]')
            familiares_apellidos = request.form.getlist('familiar_apellido[]')
            familiares_dnis = request.form.getlist('familiar_dni[]')
            familiares_parentescos = request.form.getlist('familiar_parentesco[]')
            
            for i in range(len(familiares_nombres)):
                if familiares_nombres[i] and familiares_dnis[i]:
                    familiar = GrupoFamiliar(
                        usuario_id=usuario.id,
                        nombre=familiares_nombres[i],
                        apellido=familiares_apellidos[i],
                        dni=familiares_dnis[i],
                        parentesco=familiares_parentescos[i]
                    )
                    db.session.add(familiar)
            
            db.session.commit()
            
            flash('Registro exitoso. Ya puede iniciar sesión', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar: {str(e)}', 'danger')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        dni = request.form.get('dni')
        password = request.form.get('password')
        
        usuario = Usuario.query.filter_by(dni=dni, activo=True).first()
        
        if usuario and usuario.check_password(password):
            session.permanent = True
            session['user_id'] = usuario.id
            session['user_rol'] = usuario.rol.value
            session['user_nombre'] = f"{usuario.nombre} {usuario.apellido}"
            
            flash(f'Bienvenido/a {usuario.nombre}', 'success')
            
            # Redireccionar según rol
            if usuario.rol == RolUsuario.ADMIN or usuario.rol == RolUsuario.RECEPCION:
                return redirect(url_for('dashboard_admin'))
            elif usuario.rol == RolUsuario.ESPECIALISTA:
                return redirect(url_for('dashboard_especialista'))
            else:
                return redirect(url_for('dashboard_user'))
        else:
            flash('DNI o contraseña incorrectos', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('index'))

# ==================== RUTAS USUARIO ====================

# @app.route('/dashboard')
# @login_required
# def dashboard_user():
#     usuario = Usuario.query.get(session['user_id'])
    
#     # Turnos próximos
#     turnos_proximos = Turno.query.filter(
#         Turno.paciente_id == usuario.id,
#         Turno.fecha >= date.today(),
#         Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
#     ).order_by(Turno.fecha, Turno.hora).limit(5).all()
    
#     # Pagos pendientes
#     pagos_pendientes = Pago.query.join(Turno).filter(
#         Turno.paciente_id == usuario.id,
#         Pago.estado == EstadoPago.PENDIENTE
#     ).all()
    
#     # Grupo familiar
#     grupo_familiar = GrupoFamiliar.query.filter_by(
#         usuario_id=usuario.id,
#         activo=True
#     ).all()
    
#     return render_template('dashboard_user.html',
#                          usuario=usuario,
#                          turnos_proximos=turnos_proximos,
#                          pagos_pendientes=pagos_pendientes,
#                          grupo_familiar=grupo_familiar)

# ==================== TURNOS ====================
# @app.route('/turnos/nuevo', methods=['GET', 'POST'])
# @login_required
# def nuevo_turno():
#     if request.method == 'POST':
#         # 1. Capturamos los datos del formulario (incluyendo el nuevo especialista_id)
#         especialidad_id = request.form.get('especialidad_id')
#         especialista_id = request.form.get('especialista_id')  # <--- AGREGAR ESTA LÍNEA
#         familiar_id = request.form.get('familiar_id')
#         fecha_str = request.form.get('fecha')
#         hora = request.form.get('hora')
#         motivo_consulta = request.form.get('motivo_consulta')

#         try:
#             # 2. Creamos la instancia del Turno
#             nuevo_turno = Turno(
#                 paciente_id=session['user_id'],
#                 especialista_id=int(especialista_id), # <--- ASIGNAR EL ID AQUÍ
#                 especialidad_id=int(especialidad_id),
#                 familiar_id=int(familiar_id) if familiar_id else None,
#                 fecha=datetime.strptime(fecha_str, '%Y-%m-%d').date(),
#                 hora=hora,
#                 motivo_consulta=motivo_consulta,
#                 estado=EstadoTurno.PENDIENTE # O el estado inicial que uses
#             )

#             db.session.add(nuevo_turno)
#             db.session.commit()
            
#             flash('¡Turno agendado con éxito!', 'success')
#             return redirect(url_for('mis_turnos'))

#         except Exception as e:
#             db.session.rollback()
#             flash(f'Error al agendar el turno: {str(e)}', 'danger')
#             return redirect(url_for('nuevo_turno'))

#     # Si es GET, cargamos las especialidades y familiares normalmente
#     especialidades = Especialidad.query.all()
#     grupo_familiar = GrupoFamiliar.query.filter_by(usuario_id=session['user_id']).all()
#     return render_template('turnos_nuevo.html', 
#                            especialidades=especialidades, 
#                            grupo_familiar=grupo_familiar,
#                            today=date.today().isoformat())

# @app.route('/turnos/nuevo', methods=['GET', 'POST'])ESTE ES EL ULTIMO QUE FUNCIONA
# @login_required
# def nuevo_turno():
#     if request.method == 'POST':
#         try:
#             # 1. Capturar todos los datos del formulario
#             paciente_id = session['user_id']
#             especialidad_id = request.form.get('especialidad_id')
#             especialista_id = request.form.get('especialista_id')  # ID del especialista seleccionado
#             familiar_id = request.form.get('familiar_id')  # Opcional
#             fecha_str = request.form.get('fecha')
#             hora_str = request.form.get('hora')
#             motivo_consulta = request.form.get('motivo_consulta')
            
#             # 2. Validaciones básicas
#             if not all([especialidad_id, especialista_id, fecha_str, hora_str]):
#                 flash('Por favor complete todos los campos obligatorios', 'danger')
#                 return redirect(url_for('nuevo_turno'))
            
#             # 3. Convertir fecha y hora
#             fecha_turno = datetime.strptime(fecha_str, '%Y-%m-%d').date()
#             hora_turno = datetime.strptime(hora_str, '%H:%M').time()
            
#             # 4. Validar que no exista turno en ese horario para ese especialista
#             turno_existente = Turno.query.filter_by(
#                 especialista_id=int(especialista_id),
#                 fecha=fecha_turno,
#                 hora=hora_turno,
#                 estado=EstadoTurno.PENDIENTE
#             ).first()
            
#             if turno_existente:
#                 flash('Ese horario ya está ocupado para este especialista', 'danger')
#                 return redirect(url_for('nuevo_turno'))
            
#             # 5. Crear el turno
#             nuevo_turno = Turno(
#                 paciente_id=paciente_id,
#                 especialista_id=int(especialista_id),
#                 especialidad_id=int(especialidad_id),
#                 familiar_id=int(familiar_id) if familiar_id else None,
#                 fecha=fecha_turno,
#                 hora=hora_turno,
#                 motivo_consulta=motivo_consulta,
#                 estado=EstadoTurno.PENDIENTE
#             )
            
#             db.session.add(nuevo_turno)
#             db.session.flush()  # Obtener el ID del turno sin hacer commit
            
#             # 6. Calcular costo con descuento por grupo familiar
#             costo = calcular_costo_grupo_familiar(paciente_id)
            
#             # 7. Crear pago asociado automáticamente
#             nuevo_pago = Pago(
#                 turno_id=nuevo_turno.id,
#                 monto=costo,
#                 estado=EstadoPago.PENDIENTE
#             )
            
#             db.session.add(nuevo_pago)
#             db.session.commit()
            
#             flash('¡Turno agendado con éxito! Debe subir el comprobante de pago para confirmar.', 'success')
#             return redirect(url_for('mis_turnos'))
            
#         except ValueError as ve:
#             db.session.rollback()
#             flash(f'Error en el formato de fecha u hora: {str(ve)}', 'danger')
#             return redirect(url_for('nuevo_turno'))
#         except Exception as e:
#             db.session.rollback()
#             flash(f'Error al crear turno: {str(e)}', 'danger')
#             return redirect(url_for('nuevo_turno'))
    
#     # GET - Cargar datos para el formulario
#     especialidades = Especialidad.query.filter_by(activo=True).all()
#     grupo_familiar = GrupoFamiliar.query.filter_by(
#         usuario_id=session['user_id'],
#         activo=True
#     ).all()
    
#     return render_template('turnos_nuevo.html',
#                          especialidades=especialidades,
#                          grupo_familiar=grupo_familiar,
#                          today=date.today().isoformat())

# @app.route('/turnos/nuevo', methods=['GET', 'POST'])
# @login_required
# def nuevo_turno():
#     if request.method == 'POST':
#         try:
#             paciente_id = session['user_id']
#             especialidad_id = request.form.get('especialidad_id')
#             fecha_str = request.form.get('fecha')
#             hora_str = request.form.get('hora')
#             familiar_id = request.form.get('familiar_id')  # Opcional
#             motivo = request.form.get('motivo_consulta')
            
#             # Convertir fecha y hora
#             fecha_turno = datetime.strptime(fecha_str, '%Y-%m-%d').date()
#             hora_turno = datetime.strptime(hora_str, '%H:%M').time()
            
#             # Validar que no exista turno en ese horario
#             turno_existente = Turno.query.filter_by(
#                 especialidad_id=especialidad_id,
#                 fecha=fecha_turno,
#                 hora=hora_turno,
#                 estado=EstadoTurno.PENDIENTE
#             ).first()
            
#             if turno_existente:
#                 flash('Ese horario ya está ocupado', 'danger')
#                 return redirect(url_for('nuevo_turno'))
            
#             # Crear turno
#             turno = Turno(
#                 paciente_id=paciente_id,
#                 especialidad_id=especialidad_id,
#                 fecha=fecha_turno,
#                 hora=hora_turno,
#                 familiar_id=familiar_id if familiar_id else None,
#                 motivo_consulta=motivo,
#                 estado=EstadoTurno.PENDIENTE
#             )
            
#             db.session.add(turno)
#             db.session.flush()
            
#             # Crear pago asociado
#             especialidad = Especialidad.query.get(especialidad_id)
#             usuario = Usuario.query.get(paciente_id)
            
#             # Calcular costo con descuento por grupo familiar
#             costo = calcular_costo_grupo_familiar(paciente_id)
            
#             pago = Pago(
#                 turno_id=turno.id,
#                 monto=costo,
#                 estado=EstadoPago.PENDIENTE
#             )
            
#             db.session.add(pago)
#             db.session.commit()
            
#             flash('Turno solicitado correctamente. Debe abonar para confirmar.', 'success')
#             return redirect(url_for('mis_turnos'))
            
#         except Exception as e:
#             db.session.rollback()
#             flash(f'Error al crear turno: {str(e)}', 'danger')
#             return redirect(url_for('nuevo_turno'))
    
#     # GET
#     especialidades = Especialidad.query.filter_by(activo=True).all()
#     grupo_familiar = GrupoFamiliar.query.filter_by(
#         usuario_id=session['user_id'],
#         activo=True
#     ).all()
    
#     return render_template('turnos_nuevo.html',
#                          especialidades=especialidades,
#                          grupo_familiar=grupo_familiar)

# @app.route('/api/turnos/horarios-disponibles')
# @login_required
# def horarios_disponibles():
#     """API para obtener horarios disponibles según especialidad y fecha"""
#     especialidad_id = request.args.get('especialidad_id')
#     fecha_str = request.args.get('fecha')
    
#     if not especialidad_id or not fecha_str:
#         return {'error': 'Faltan parámetros'}, 400
    
#     fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
#     dia_semana = fecha.weekday()
    
#     # Obtener horarios configurados para ese día
#     especialidad = Especialidad.query.get(especialidad_id)
#     duracion = especialidad.duracion_turno
    
#     # Horarios genéricos (8:00 a 18:00, cada 30 min por defecto)
#     horarios = []
#     hora_inicio = time(8, 0)
#     hora_fin = time(18, 0)
    
#     hora_actual = datetime.combine(date.today(), hora_inicio)
#     hora_final = datetime.combine(date.today(), hora_fin)
    
#     while hora_actual < hora_final:
#         horarios.append(hora_actual.time().strftime('%H:%M'))
#         hora_actual += timedelta(minutes=duracion)
    
#     # Filtrar horarios ocupados
#     turnos_ocupados = Turno.query.filter(
#         Turno.especialidad_id == especialidad_id,
#         Turno.fecha == fecha,
#         Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
#     ).all()
    
#     horarios_ocupados = [t.hora.strftime('%H:%M') for t in turnos_ocupados]
#     horarios_disponibles = [h for h in horarios if h not in horarios_ocupados]
    
#     return {'horarios': horarios_disponibles}

@app.route('/turnos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_turno():
    if request.method == 'POST':
        try:
            # 1. Capturar todos los datos del formulario
            paciente_id = session['user_id']
            especialidad_id = request.form.get('especialidad_id')
            especialista_id = request.form.get('especialista_id')
            familiar_id = request.form.get('familiar_id')
            fecha_str = request.form.get('fecha')
            hora_str = request.form.get('hora')
            motivo_consulta = request.form.get('motivo_consulta')
            
            # 2. Validaciones básicas
            if not all([especialidad_id, especialista_id, fecha_str, hora_str]):
                flash('Por favor complete todos los campos obligatorios', 'danger')
                return redirect(url_for('nuevo_turno'))
            
            # 3. Convertir fecha y hora
            fecha_turno = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            hora_turno = datetime.strptime(hora_str, '%H:%M').time()
            
            # 4. Validar que no exista turno en ese horario para ese especialista
            turno_existente = Turno.query.filter_by(
                especialista_id=int(especialista_id),
                fecha=fecha_turno,
                hora=hora_turno,
                estado=EstadoTurno.PENDIENTE
            ).first()
            
            if turno_existente:
                flash('Ese horario ya está ocupado para este especialista', 'danger')
                return redirect(url_for('nuevo_turno'))
            
            # 5. Verificar si el usuario tiene suscripción de prepaga activa
            suscripcion = SuscripcionPrepaga.query.filter_by(
                usuario_id=paciente_id,
                estado=EstadoSuscripcion.ACTIVA
            ).first()
            
            # 6. Crear el turno
            nuevo_turno = Turno(
                paciente_id=paciente_id,
                especialista_id=int(especialista_id),
                especialidad_id=int(especialidad_id),
                familiar_id=int(familiar_id) if familiar_id else None,
                fecha=fecha_turno,
                hora=hora_turno,
                motivo_consulta=motivo_consulta,
                estado=EstadoTurno.PENDIENTE
            )
            
            db.session.add(nuevo_turno)
            db.session.flush()  # Obtener el ID del turno
            
            # 7. Procesar según tenga o no prepaga
            if suscripcion and suscripcion.tiene_consultas_disponibles():
                # ✅ TIENE PREPAGA CON CONSULTAS DISPONIBLES
                
                # Consumir consulta
                consultas_antes = suscripcion.consultas_restantes()
                suscripcion.consumir_consulta()
                consultas_despues = suscripcion.consultas_restantes()
                
                # Registrar en historial
                historial = HistorialConsultasPrepaga(
                    suscripcion_id=suscripcion.id,
                    turno_id=nuevo_turno.id,
                    consultas_antes=consultas_antes,
                    consultas_despues=consultas_despues
                )
                db.session.add(historial)
                
                # El turno se confirma automáticamente (sin necesidad de pago)
                nuevo_turno.estado = EstadoTurno.CONFIRMADO
                
                db.session.commit()
                
                flash(f'¡Turno agendado con éxito! Consultas restantes: {consultas_despues}', 'success')
                
            else:
                # ❌ NO TIENE PREPAGA O SE QUEDÓ SIN CONSULTAS
                
                # Calcular costo con descuento por grupo familiar
                costo = calcular_costo_grupo_familiar(paciente_id)
                
                # Crear pago asociado
                nuevo_pago = Pago(
                    turno_id=nuevo_turno.id,
                    monto=costo,
                    estado=EstadoPago.PENDIENTE
                )
                
                db.session.add(nuevo_pago)
                db.session.commit()
                
                if suscripcion and not suscripcion.tiene_consultas_disponibles():
                    flash('Se agotaron sus consultas de prepaga. Debe abonar esta consulta.', 'warning')
                else:
                    flash('Turno agendado. Debe subir el comprobante de pago para confirmar.', 'success')
            
            return redirect(url_for('mis_turnos'))
            
        except ValueError as ve:
            db.session.rollback()
            flash(f'Error en el formato de fecha u hora: {str(ve)}', 'danger')
            return redirect(url_for('nuevo_turno'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear turno: {str(e)}', 'danger')
            return redirect(url_for('nuevo_turno'))
    
    # GET - Cargar datos para el formulario
    especialidades = Especialidad.query.filter_by(activo=True).all()
    grupo_familiar = GrupoFamiliar.query.filter_by(
        usuario_id=session['user_id'],
        activo=True
    ).all()
    
    # Obtener suscripción si existe
    suscripcion = SuscripcionPrepaga.query.filter_by(
        usuario_id=session['user_id'],
        estado=EstadoSuscripcion.ACTIVA
    ).first()
    
    return render_template('turnos_nuevo.html',
                         especialidades=especialidades,
                         grupo_familiar=grupo_familiar,
                         suscripcion=suscripcion,
                         today=date.today().isoformat())

# AGREGAR ESTA NUEVA RUTA PARA EL DASHBOARD:

@app.route('/dashboard')
@login_required
def dashboard_user():
    usuario = Usuario.query.get(session['user_id'])
    
    # Turnos próximos
    turnos_proximos = Turno.query.filter(
        Turno.paciente_id == usuario.id,
        Turno.fecha >= date.today(),
        Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
    ).order_by(Turno.fecha, Turno.hora).limit(5).all()
    
    # Pagos pendientes (solo si no tiene prepaga)
    pagos_pendientes = Pago.query.join(Turno).filter(
        Turno.paciente_id == usuario.id,
        Pago.estado == EstadoPago.PENDIENTE
    ).all()
    
    # Grupo familiar
    grupo_familiar = GrupoFamiliar.query.filter_by(
        usuario_id=usuario.id,
        activo=True
    ).all()
    
    # Suscripción de prepaga
    suscripcion = SuscripcionPrepaga.query.filter_by(
        usuario_id=usuario.id
    ).filter(
        SuscripcionPrepaga.estado.in_([EstadoSuscripcion.ACTIVA, EstadoSuscripcion.PENDIENTE])
    ).first()
    
    # Pago mensual pendiente (si tiene prepaga)
    pago_mensual_pendiente = None
    if suscripcion and suscripcion.estado == EstadoSuscripcion.ACTIVA:
        hoy = date.today()
        pago_mensual_pendiente = PagoMensualPrepaga.query.filter_by(
            suscripcion_id=suscripcion.id,
            mes=hoy.month,
            anio=hoy.year
        ).filter(
            PagoMensualPrepaga.estado.in_([EstadoPagoMensual.PENDIENTE, EstadoPagoMensual.RECHAZADO])
        ).first()
    
    return render_template('dashboard_user.html',
                         usuario=usuario,
                         turnos_proximos=turnos_proximos,
                         pagos_pendientes=pagos_pendientes,
                         grupo_familiar=grupo_familiar,
                         suscripcion=suscripcion,
                         pago_mensual_pendiente=pago_mensual_pendiente)

# ACTUALIZAR EL COMANDO seed_db() PARA INCLUIR PLANES:

@app.cli.command()
def seed_db():
    """Carga datos de ejemplo incluyendo planes de prepaga"""
    
    # Admin
    admin = Usuario(
        nombre="Admin",
        apellido="Sistema",
        dni="00000000",
        email="admin@consultorio.com",
        telefono="1234567890",
        rol=RolUsuario.ADMIN
    )
    admin.set_password("admin123")
    db.session.add(admin)
    
    # Especialidades
    especialidades = [
        Especialidad(nombre="Clínica Médica", costo_consulta=15000, duracion_turno=30),
        Especialidad(nombre="Pediatría", costo_consulta=15000, duracion_turno=30),
        Especialidad(nombre="Cardiología", costo_consulta=20000, duracion_turno=45),
        Especialidad(nombre="Dermatología", costo_consulta=18000, duracion_turno=30),
    ]
    
    for esp in especialidades:
        db.session.add(esp)
    
    # Planes de Prepaga
    planes = [
        PlanPrepaga(
            tipo=TipoPlan.INDIVIDUAL,
            nombre="Plan Individual",
            descripcion="Ideal para una persona",
            precio_mensual=8000,
            consultas_incluidas=10,
            personas_maximas=1,
            incluye_medico_online=False
        ),
        PlanPrepaga(
            tipo=TipoPlan.PAREJA,
            nombre="Plan Pareja",
            descripcion="Para dos personas",
            precio_mensual=14000,
            consultas_incluidas=10,
            personas_maximas=2,
            incluye_medico_online=False
        ),
        PlanPrepaga(
            tipo=TipoPlan.FAMILIAR,
            nombre="Plan Familiar",
            descripcion="Hasta 4 personas",
            precio_mensual=24000,
            consultas_incluidas=10,
            personas_maximas=4,
            incluye_medico_online=True
        ),
        PlanPrepaga(
            tipo=TipoPlan.FAMILIAR_MAXI,
            nombre="Plan Familiar Maxi",
            descripcion="Más de 4 personas",
            precio_mensual=32000,
            consultas_incluidas=10,
            personas_maximas=6,
            incluye_medico_online=True
        ),
    ]
    
    for plan in planes:
        db.session.add(plan)
    
    db.session.commit()
    print("✅ Datos de ejemplo cargados (incluyendo planes de prepaga)")

@app.route('/turnos/mis-turnos')
@login_required
def mis_turnos():
    usuario_id = session['user_id']
    
    # Turnos pendientes
    turnos_pendientes = Turno.query.filter(
        Turno.paciente_id == usuario_id,
        Turno.fecha >= date.today(),
        Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
    ).order_by(Turno.fecha, Turno.hora).all()
    
    # Turnos realizados
    turnos_realizados = Turno.query.filter(
        Turno.paciente_id == usuario_id,
        or_(
            Turno.estado == EstadoTurno.REALIZADO,
            and_(Turno.fecha < date.today(), Turno.estado != EstadoTurno.CANCELADO)
        )
    ).order_by(Turno.fecha.desc(), Turno.hora.desc()).limit(10).all()
    
    return render_template('turnos.html',
                         turnos_pendientes=turnos_pendientes,
                         turnos_realizados=turnos_realizados)

@app.route('/turnos/cancelar/<int:turno_id>', methods=['POST'])
@login_required
def cancelar_turno(turno_id):
    turno = Turno.query.get_or_404(turno_id)
    
    # Verificar que el turno pertenece al usuario
    if turno.paciente_id != session['user_id']:
        flash('No tiene permisos para cancelar este turno', 'danger')
        return redirect(url_for('mis_turnos'))
    
    # No se puede cancelar si ya está realizado
    if turno.estado == EstadoTurno.REALIZADO:
        flash('No se puede cancelar un turno ya realizado', 'danger')
        return redirect(url_for('mis_turnos'))
    
    turno.estado = EstadoTurno.CANCELADO
    
    # Si había pago asociado, cambiar estado
    if turno.pago:
        turno.pago.observaciones = "Turno cancelado por el paciente"
    
    db.session.commit()
    flash('Turno cancelado correctamente', 'info')
    return redirect(url_for('mis_turnos'))

# ==================== PAGOS ====================

@app.route('/pagos/subir-comprobante/<int:turno_id>', methods=['GET', 'POST'])
@login_required
def subir_comprobante(turno_id):
    turno = Turno.query.get_or_404(turno_id)
    
    # Verificar que el turno pertenece al usuario
    if turno.paciente_id != session['user_id']:
        flash('No tiene permisos para este turno', 'danger')
        return redirect(url_for('mis_turnos'))
    
    if not turno.pago:
        flash('Este turno no tiene pago asociado', 'danger')
        return redirect(url_for('mis_turnos'))
    
    if request.method == 'POST':
        try:
            if 'comprobante' not in request.files:
                flash('No se seleccionó ningún archivo', 'danger')
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
            
            if len(archivo_bytes) > app.config['MAX_CONTENT_LENGTH']:
                flash('El archivo es demasiado grande (máximo 5MB)', 'danger')
                return redirect(request.url)
            
            archivo_comprimido = comprimir_archivo(archivo_bytes)
            
            # Guardar en base de datos
            pago = turno.pago
            pago.comprobante = archivo_comprimido
            pago.comprobante_nombre = archivo.filename
            pago.comprobante_tipo = archivo.content_type
            pago.fecha_subida = datetime.utcnow()
            pago.estado = EstadoPago.PENDIENTE  # Cambiar a pendiente de aprobación
            
            db.session.commit()
            
            flash('Comprobante subido correctamente. En breve será revisado.', 'success')
            return redirect(url_for('mis_turnos'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al subir comprobante: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('subir_comprobante.html', turno=turno)

@app.route('/pagos/ver-comprobante/<int:pago_id>')
@login_required
def ver_comprobante(pago_id):
    pago = Pago.query.get_or_404(pago_id)
    
    # Verificar permisos
    usuario = Usuario.query.get(session['user_id'])
    es_propietario = pago.turno.paciente_id == session['user_id']
    es_admin = usuario.rol in [RolUsuario.ADMIN, RolUsuario.RECEPCION]
    
    if not (es_propietario or es_admin):
        flash('No tiene permisos para ver este comprobante', 'danger')
        return redirect(url_for('index'))
    
    if not pago.comprobante:
        flash('No hay comprobante asociado a este pago', 'warning')
        return redirect(url_for('mis_turnos'))
    
    try:
        # Descomprimir archivo
        archivo_descomprimido = descomprimir_archivo(pago.comprobante)
        
        # Determinar tipo MIME
        if pago.comprobante_tipo:
            mime_type = pago.comprobante_tipo
        else:
            # Inferir por extensión
            ext = pago.comprobante_nombre.rsplit('.', 1)[1].lower()
            mime_types = {
                'pdf': 'application/pdf',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'png': 'image/png'
            }
            mime_type = mime_types.get(ext, 'application/octet-stream')
        
        return send_file(
            io.BytesIO(archivo_descomprimido),
            mimetype=mime_type,
            as_attachment=False,
            download_name=pago.comprobante_nombre
        )
        
    except Exception as e:
        flash(f'Error al recuperar comprobante: {str(e)}', 'danger')
        return redirect(url_for('mis_turnos'))

@app.route('/pagos/mis-pagos')
@login_required
def mis_pagos():
    usuario_id = session['user_id']
    
    pagos = Pago.query.join(Turno).filter(
        Turno.paciente_id == usuario_id
    ).order_by(Pago.fecha_creacion.desc()).all()
    
    return render_template('pagos.html', pagos=pagos)

# ==================== HISTORIAL ====================

@app.route('/historial')
@login_required
def historial():
    usuario_id = session['user_id']
    
    # Turnos del titular
    turnos_titular = Turno.query.filter(
        Turno.paciente_id == usuario_id,
        Turno.familiar_id.is_(None),
        Turno.estado == EstadoTurno.REALIZADO
    ).order_by(Turno.fecha.desc()).all()
    
    # Turnos del grupo familiar
    grupo_familiar = GrupoFamiliar.query.filter_by(
        usuario_id=usuario_id,
        activo=True
    ).all()
    
    historial_familiar = {}
    for familiar in grupo_familiar:
        turnos = Turno.query.filter(
            Turno.paciente_id == usuario_id,
            Turno.familiar_id == familiar.id,
            Turno.estado == EstadoTurno.REALIZADO
        ).order_by(Turno.fecha.desc()).all()
        
        if turnos:
            historial_familiar[familiar] = turnos
    
    return render_template('historial.html',
                         turnos_titular=turnos_titular,
                         historial_familiar=historial_familiar)

@app.route('/historial/descargar-pdf/<int:persona_id>')
@login_required
def descargar_historial_pdf(persona_id):
    """Genera PDF del historial (simplificado - requiere librería adicional)"""
    # Aquí iría la lógica con reportlab o weasyprint
    flash('Funcionalidad de PDF en desarrollo', 'info')
    return redirect(url_for('historial'))


# ==================== DASHBOARD ADMIN ====================

@app.route('/admin/dashboard')
@role_required(RolUsuario.ADMIN, RolUsuario.RECEPCION)
def dashboard_admin():
    # Turnos del día
    turnos_hoy = Turno.query.filter(
        Turno.fecha == date.today()
    ).order_by(Turno.hora).all()
    
    # Pagos pendientes de aprobación
    pagos_pendientes = Pago.query.filter(
        Pago.estado == EstadoPago.PENDIENTE,
        Pago.comprobante.isnot(None)
    ).count()
    
    # Balance del mes
    mes_actual = date.today().replace(day=1)
    ingresos_mes = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.tipo == TipoMovimiento.INGRESO,
        Movimiento.fecha >= mes_actual
    ).scalar() or 0
    
    egresos_mes = db.session.query(func.sum(Movimiento.monto)).filter(
        Movimiento.tipo == TipoMovimiento.EGRESO,
        Movimiento.fecha >= mes_actual
    ).scalar() or 0
    
    balance = ingresos_mes - egresos_mes
    
    return render_template('dashboard_admin.html',
                         turnos_hoy=turnos_hoy,
                         pagos_pendientes=pagos_pendientes,
                         ingresos_mes=ingresos_mes,
                         egresos_mes=egresos_mes,
                         balance=balance)
    solicitudes_prepaga_count = SuscripcionPrepaga.query.filter_by(
        estado=EstadoSuscripcion.PENDIENTE
    ).count()
    
    pagos_mensuales_count = PagoMensualPrepaga.query.filter_by(
        estado=EstadoPagoMensual.PENDIENTE
    ).filter(PagoMensualPrepaga.comprobante.isnot(None)).count()
    
    return render_template('dashboard_admin.html',
                         # ... variables existentes ...
                         solicitudes_prepaga_count=solicitudes_prepaga_count,
                         pagos_mensuales_count=pagos_mensuales_count)

@app.route('/admin/buscar-paciente', methods=['GET', 'POST'])
@role_required(RolUsuario.ADMIN, RolUsuario.RECEPCION)
def buscar_paciente():
    if request.method == 'POST':
        dni = request.form.get('dni')
        
        usuario = Usuario.query.filter_by(dni=dni).first()
        
        if not usuario:
            flash('No se encontró paciente con ese DNI', 'warning')
            return render_template('buscar_paciente.html', usuario=None)
        
        # Turnos del paciente
        turnos = Turno.query.filter_by(paciente_id=usuario.id).order_by(
            Turno.fecha.desc(), Turno.hora.desc()
        ).limit(10).all()
        
        return render_template('buscar_paciente.html',
                             usuario=usuario,
                             turnos=turnos)
    
    return render_template('buscar_paciente.html', usuario=None)

@app.route('/admin/marcar-abonado/<int:pago_id>', methods=['POST'])
@role_required(RolUsuario.ADMIN, RolUsuario.RECEPCION)
def marcar_abonado(pago_id):
    pago = Pago.query.get_or_404(pago_id)
    
    if pago.estado == EstadoPago.ABONADO_EFECTIVO:
        flash('Este pago ya fue marcado como abonado', 'info')
        return redirect(request.referrer or url_for('dashboard_admin'))
    
    pago.estado = EstadoPago.ABONADO_EFECTIVO
    pago.fecha_aprobacion = datetime.utcnow()
    pago.aprobado_por = session['user_id']
    
    # Confirmar turno
    pago.turno.estado = EstadoTurno.CONFIRMADO
    
    # Registrar ingreso
    movimiento = Movimiento(
        tipo=TipoMovimiento.INGRESO,
        monto=pago.monto,
        concepto=f"Pago en efectivo - Turno {pago.turno_id}",
        pago_id=pago.id,
        usuario_registro=session['user_id']
    )
    
    db.session.add(movimiento)
    db.session.commit()
    
    flash('Pago registrado como abonado en efectivo', 'success')
    return redirect(request.referrer or url_for('dashboard_admin'))

@app.route('/admin/aprobar-pago/<int:pago_id>', methods=['POST'])
@role_required(RolUsuario.ADMIN, RolUsuario.RECEPCION)
def aprobar_pago(pago_id):
    pago = Pago.query.get_or_404(pago_id)
    
    pago.estado = EstadoPago.APROBADO
    pago.fecha_aprobacion = datetime.utcnow()
    pago.aprobado_por = session['user_id']
    
    # Confirmar turno
    pago.turno.estado = EstadoTurno.CONFIRMADO
    
    # Registrar ingreso
    movimiento = Movimiento(
        tipo=TipoMovimiento.INGRESO,
        monto=pago.monto,
        concepto=f"Pago transferencia - Turno {pago.turno_id}",
        pago_id=pago.id,
        usuario_registro=session['user_id']
    )
    
    db.session.add(movimiento)
    db.session.commit()
    
    flash('Pago aprobado correctamente', 'success')
    return redirect(url_for('revisar_pagos'))

@app.route('/admin/rechazar-pago/<int:pago_id>', methods=['POST'])
@role_required(RolUsuario.ADMIN, RolUsuario.RECEPCION)
def rechazar_pago(pago_id):
    pago = Pago.query.get_or_404(pago_id)
    
    observaciones = request.form.get('observaciones', 'Comprobante inválido')
    
    pago.estado = EstadoPago.RECHAZADO
    pago.observaciones = observaciones
    pago.aprobado_por = session['user_id']
    
    db.session.commit()
    
    flash('Pago rechazado', 'info')
    return redirect(url_for('revisar_pagos'))

@app.route('/admin/pagos')
@role_required(RolUsuario.ADMIN, RolUsuario.RECEPCION)
def revisar_pagos():
    # Pagos pendientes
    pagos_pendientes = Pago.query.filter(
        Pago.estado == EstadoPago.PENDIENTE,
        Pago.comprobante.isnot(None)
    ).order_by(Pago.fecha_subida.desc()).all()
    
    # Pagos recientes
    pagos_recientes = Pago.query.filter(
        Pago.estado.in_([EstadoPago.APROBADO, EstadoPago.RECHAZADO, EstadoPago.ABONADO_EFECTIVO])
    ).order_by(Pago.fecha_aprobacion.desc()).limit(20).all()
    
    return render_template('admin_pagos.html',
                         pagos_pendientes=pagos_pendientes,
                         pagos_recientes=pagos_recientes)

# ==================== MOVIMIENTOS ====================

@app.route('/admin/movimientos')
@role_required(RolUsuario.ADMIN)
def ver_movimientos():
    # Filtros
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    tipo = request.args.get('tipo')
    
    query = Movimiento.query
    
    if fecha_desde:
        query = query.filter(Movimiento.fecha >= datetime.strptime(fecha_desde, '%Y-%m-%d'))
    if fecha_hasta:
        query = query.filter(Movimiento.fecha <= datetime.strptime(fecha_hasta, '%Y-%m-%d'))
    if tipo:
        query = query.filter(Movimiento.tipo == TipoMovimiento[tipo.upper()])
    
    movimientos = query.order_by(Movimiento.fecha.desc()).all()
    
    # Calcular totales
    total_ingresos = sum(m.monto for m in movimientos if m.tipo == TipoMovimiento.INGRESO)
    total_egresos = sum(m.monto for m in movimientos if m.tipo == TipoMovimiento.EGRESO)
    balance = total_ingresos - total_egresos
    
    return render_template('movimientos.html',
                         movimientos=movimientos,
                         total_ingresos=total_ingresos,
                         total_egresos=total_egresos,
                         balance=balance)

@app.route('/admin/movimientos/nuevo', methods=['GET', 'POST'])
@role_required(RolUsuario.ADMIN)
def nuevo_movimiento():
    if request.method == 'POST':
        try:
            tipo = TipoMovimiento[request.form.get('tipo').upper()]
            monto = float(request.form.get('monto'))
            concepto = request.form.get('concepto')
            descripcion = request.form.get('descripcion')
            
            movimiento = Movimiento(
                tipo=tipo,
                monto=monto,
                concepto=concepto,
                descripcion=descripcion,
                usuario_registro=session['user_id']
            )
            
            db.session.add(movimiento)
            db.session.commit()
            
            flash('Movimiento registrado correctamente', 'success')
            return redirect(url_for('ver_movimientos'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar movimiento: {str(e)}', 'danger')
    
    return render_template('movimiento_nuevo.html')

# ==================== DASHBOARD ESPECIALISTA ====================

@app.route('/especialista/dashboard')
@role_required(RolUsuario.ESPECIALISTA)
def dashboard_especialista():
    especialista_id = session['user_id']
    
    # Turnos de hoy
    turnos_hoy = Turno.query.filter(
        Turno.especialista_id == especialista_id,
        Turno.fecha == date.today()
    ).order_by(Turno.hora).all()
    
    # Próximos turnos
    turnos_proximos = Turno.query.filter(
        Turno.especialista_id == especialista_id,
        Turno.fecha > date.today(),
        Turno.estado.in_([EstadoTurno.PENDIENTE, EstadoTurno.CONFIRMADO])
    ).order_by(Turno.fecha, Turno.hora).limit(10).all()
    
    return render_template('dashboard_especialista.html',
                         turnos_hoy=turnos_hoy,
                         turnos_proximos=turnos_proximos)


@app.route('/api/especialistas-por-especialidad')
@login_required
def especialistas_por_especialidad():
    especialidad_id = request.args.get('especialidad_id')
    if not especialidad_id:
        return {'error': 'Faltan parámetros'}, 400
    
    # Buscamos especialistas vinculados a esa especialidad
    # Unimos con la tabla Usuario para obtener los nombres
    especialistas = db.session.query(Usuario).join(
        EspecialistaEspecialidad, 
        EspecialistaEspecialidad.especialista_id == Usuario.id
    ).filter(
        EspecialistaEspecialidad.especialidad_id == especialidad_id,
        EspecialistaEspecialidad.activo == True
    ).all()
    
    return {
        'especialistas': [
            {
                'id': esp.id, 
                'nombre': f"{esp.nombre} {esp.apellido}"
            } for esp in especialistas
        ]
    }

@app.route('/api/turnos/horarios-disponibles')
@login_required
def horarios_disponibles():
    especialista_id = request.args.get('especialista_id')
    especialidad_id = request.args.get('especialidad_id')
    fecha_str = request.args.get('fecha')
    
    if not all([especialista_id, especialidad_id, fecha_str]):
        return {'error': 'Faltan parámetros'}, 400
    
    fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    
    # USAMOS TU GENERADOR DE TURNOS (Lógica del archivo turno_generator.py)
    slots = GeneradorTurnos.obtener_slots_disponibles(
        int(especialista_id), 
        int(especialidad_id), 
        fecha
    )
    
    # Filtramos solo los que están disponibles para la API
    horarios_finales = [s['hora_inicio'].strftime('%H:%M') for s in slots if s['disponible']]
    
    return {'horarios': horarios_finales}

@app.route('/especialista/atender-turno/<int:turno_id>', methods=['GET', 'POST'])
@role_required(RolUsuario.ESPECIALISTA)
def atender_turno(turno_id):
    turno = Turno.query.get_or_404(turno_id)
    
    # Verificar que el turno es del especialista
    if turno.especialista_id != session['user_id']:
        flash('No tiene permisos para este turno', 'danger')
        return redirect(url_for('dashboard_especialista'))
    
    if request.method == 'POST':
        observaciones = request.form.get('observaciones')
        
        turno.observaciones = observaciones
        turno.estado = EstadoTurno.REALIZADO
        
        db.session.commit()
        
        flash('Turno marcado como realizado', 'success')
        return redirect(url_for('dashboard_especialista'))
    
    return render_template('atender_turno.html', turno=turno)

# ==================== INICIALIZACIÓN ====================

@app.cli.command()
def init_db():
    """Crea todas las tablas en la base de datos"""
    db.create_all()
    print("✅ Base de datos inicializada")

# @app.cli.command()
# def seed_db():
#     """Carga datos de ejemplo"""
    
#     # Admin
#     admin = Usuario(
#         nombre="Admin",
#         apellido="Sistema",
#         dni="00000000",
#         email="admin@consultorio.com",
#         telefono="1234567890",
#         rol=RolUsuario.ADMIN
#     )
#     admin.set_password("admin123")
#     db.session.add(admin)
    
#     # Especialidades
#     especialidades = [
#         Especialidad(nombre="Clínica Médica", costo_consulta=15000, duracion_turno=30),
#         Especialidad(nombre="Pediatría", costo_consulta=15000, duracion_turno=30),
#         Especialidad(nombre="Cardiología", costo_consulta=20000, duracion_turno=45),
#         Especialidad(nombre="Dermatología", costo_consulta=18000, duracion_turno=30),
#     ]
    
#     for esp in especialidades:
#         db.session.add(esp)
    
#     db.session.commit()
#     print("✅ Datos de ejemplo cargados")

if __name__ == '__main__':
    app.run(debug=True)